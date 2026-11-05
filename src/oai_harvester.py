"""
oai_harvester.py — A3: lấy metadata arXiv qua OAI-PMH bằng Sickle, phạm vi hẹp.

Đề ghi rõ harvest toàn arXiv KHÔNG thuộc milestone này, nên lệnh `list` bắt buộc
có cửa sổ ngày (tối đa MAX_WINDOW_DAYS) và dừng sau --max-pages trang.

Chạy:
    # ListRecords trên một cửa sổ ngày hẹp
    python src/oai_harvester.py list --from 2025-07-10 --until 2025-07-10 --set cs:cs:AI
    python src/oai_harvester.py list --from 2025-07-10 --until 2025-07-10 --resume
    python src/oai_harvester.py list --from 2025-07-10 --until 2025-07-10 --probe-token

    # GetRecord theo ID, để so sánh trên đúng tập ID được giao
    python src/oai_harvester.py get --ids ids/24120053.txt --sample 500

    # Chạy lại các token đã lưu, sau mốc 00:00 UTC, để kiểm chứng "hết hạn theo ngày"
    python src/oai_harvester.py recheck-tokens

Kết quả (thư mục được gitignore):
    data/oai_records.jsonl     một dòng mỗi record; đọc lại bằng load_records()
    logs/oai_requests.csv      mọi lần gọi HTTP, kể cả lần lỗi
    logs/oai_tokens.jsonl      token server cấp, kèm thuộc tính và thời điểm nhận
    logs/oai_token_checks.csv  kết quả các phép thử token
    logs/oai_checkpoint.json   token gần nhất của lệnh `list`, phục vụ --resume

Hành vi của endpoint sau đợt viết lại 3/2025 (https://info.arxiv.org/help/oa/index.html):
  - datestamp là lần SỬA record cuối, không phải ngày nộp: OAI-PMH không lọc được
    theo ngày nộp, nên một cửa sổ ngày không trả về một khoảng arXiv ID liền nhau.
  - Token không còn cursor/completeListSize, chỉ có expirationDate là 00:00 UTC hôm sau.
    Tài liệu nói token hết hạn theo ngày, nên gặp badResumptionToken thì harvest lại
    cửa sổ từ đầu. Bản thân token là truy vấn gốc + `skip`, tức phân trang theo offset.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, unquote

import requests
from lxml import etree

try:
    from sickle import Sickle, oaiexceptions
    from sickle.response import OAIResponse
except ImportError:
    sys.exit("Thiếu thư viện. Chạy: pip install -r src/requirements.txt")

import config
from discovery import load_ids
from http_utils import RETRY_STATUS, RateLimiter

OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"
RAW_NS = "{http://arxiv.org/OAI/arXivRaw/}"
METADATA_PREFIX = "arXivRaw"  # định dạng duy nhất có lịch sử version kèm ngày
IDENTIFIER_PREFIX = "oai:arXiv.org:"

# CDN của arXiv tự cắt request sau khoảng 183 giây (503 first byte timeout)
OAI_TIMEOUT = 200
MAX_WINDOW_DAYS = 7
DEFAULT_MAX_PAGES = 5
BACKOFF_BASE = 30.0
BACKOFF_MAX = 300.0
CRAFTED_SKIP_STEP = 7  # probe_token: token tự chế bỏ qua thêm 7 record so với token thật
RECHECK_SKIP_RANGE = 300  # recheck_tokens: `skip` lệch ngẫu nhiên trong khoảng này để né cache

RECORDS_PATH = config.DATA_ROOT / "oai_records.jsonl"
REQUEST_LOG = config.LOGS_ROOT / "oai_requests.csv"
TOKEN_LOG = config.LOGS_ROOT / "oai_tokens.jsonl"
TOKEN_CHECK_LOG = config.LOGS_ROOT / "oai_token_checks.csv"
CHECKPOINT = config.LOGS_ROOT / "oai_checkpoint.json"

REQUEST_COLUMNS = ["at_utc", "verb", "query", "attempt", "http_status", "seconds",
                   "bytes", "x_cache", "age", "retry_after", "status", "error_type"]
TOKEN_CHECK_COLUMNS = ["checked_at_utc", "probe", "token", "issued_at_utc", "age_hours",
                       "crossed_utc_midnight", "result", "first_identifier", "detail"]


# Các exception của Sickle kế thừa thẳng từ Exception, không có lớp cha chung
OAI_ERRORS = tuple(
    obj for obj in vars(oaiexceptions).values()
    if isinstance(obj, type) and issubclass(obj, Exception)
)


class OAIUnavailable(Exception):
    """Endpoint vẫn lỗi sau khi đã dùng hết số lần retry."""

    def __init__(self, message: str, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _append_csv(path: Path, columns: list[str], row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


# ----------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------
class PoliteSickle(Sickle):
    """Sickle có pacing >= 3 giây, 1 connection, User-Agent và retry riêng.

    Không dùng retry có sẵn của Sickle: endpoint trả `Retry-After: 0` kèm 503,
    Sickle sẽ gọi lại ngay trong khi server đang quá tải.
    """

    def __init__(self, timeout: float = OAI_TIMEOUT, max_retries: int = config.MAX_RETRIES) -> None:
        # Phản hồi là `text/xml` không khai charset. Không ép encoding thì requests
        # giải mã bằng ISO-8859-1 và mọi ký tự ngoài ASCII trong title bị hỏng.
        super().__init__(config.OAI_PMH_ENDPOINT, max_retries=0, encoding="utf-8")
        self.timeout = timeout
        self.retries = max_retries
        self._limiter = RateLimiter(config.REQUEST_DELAY)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = config.USER_AGENT

    def harvest(self, **kwargs: Any) -> OAIResponse:
        verb = kwargs.get("verb", "")
        query = {k: v for k, v in kwargs.items() if k != "verb"}
        error_type = "other"
        for attempt in range(1, self.retries + 2):
            self._limiter.wait()
            started = time.perf_counter()
            row: dict[str, Any] = {
                "at_utc": now_utc().isoformat(), "verb": verb,
                "query": json.dumps(query, sort_keys=True), "attempt": attempt,
                "status": "fail",
            }
            try:
                response = self._session.get(self.endpoint, params=kwargs, timeout=self.timeout)
            except requests.Timeout:
                error_type = "timeout"
            except requests.ConnectionError:
                error_type = "connection_error"
            else:
                row.update(
                    http_status=response.status_code, bytes=len(response.content),
                    x_cache=response.headers.get("X-Cache", ""),
                    age=response.headers.get("Age", ""),
                    retry_after=response.headers.get("Retry-After", ""),
                )
                if response.status_code == 200:
                    row.update(status="ok", seconds=f"{time.perf_counter() - started:.2f}")
                    _append_csv(REQUEST_LOG, REQUEST_COLUMNS, row)
                    response.encoding = self.encoding
                    return OAIResponse(response, params=kwargs)
                error_type = f"http_{response.status_code}"

            row.update(error_type=error_type, seconds=f"{time.perf_counter() - started:.2f}")
            _append_csv(REQUEST_LOG, REQUEST_COLUMNS, row)
            if row.get("http_status") and row["http_status"] not in RETRY_STATUS:
                break
            if attempt <= self.retries:
                time.sleep(min(BACKOFF_BASE * 2 ** (attempt - 1), BACKOFF_MAX))
        raise OAIUnavailable(f"{verb} {query}: {error_type}", error_type)

    def close(self) -> None:
        self._session.close()


def raise_oai_error(response: OAIResponse) -> None:
    """Đổi phần tử <error> trong XML thành exception của Sickle."""
    error = response.xml.find(f".//{OAI_NS}error")
    if error is None:
        return
    code = error.attrib.get("code", "UNKNOWN")
    exception = getattr(oaiexceptions, code[0].upper() + code[1:], oaiexceptions.OAIError)
    raise exception(error.text or code)


# ----------------------------------------------------------------------
# Parse
# ----------------------------------------------------------------------
def parse_record(element: etree._Element, via: str) -> dict[str, Any]:
    """Một phần tử <record> định dạng arXivRaw -> dict."""
    header = element.find(f"{OAI_NS}header")
    identifier = header.findtext(f"{OAI_NS}identifier", "")
    record: dict[str, Any] = {
        "id": identifier.removeprefix(IDENTIFIER_PREFIX),
        "datestamp": header.findtext(f"{OAI_NS}datestamp"),
        "sets": [s.text for s in header.findall(f"{OAI_NS}setSpec")],
        "deleted": header.attrib.get("status") == "deleted",
        "via": via,
        "harvested_at": config.now_iso(),
    }
    raw = element.find(f"{OAI_NS}metadata/{RAW_NS}arXivRaw")
    if raw is None:
        return record  # record đã xoá chỉ có header

    record.update(
        title=raw.findtext(f"{RAW_NS}title"),
        authors=raw.findtext(f"{RAW_NS}authors"),
        journal_ref=raw.findtext(f"{RAW_NS}journal-ref"),
        doi=raw.findtext(f"{RAW_NS}doi"),
        categories=raw.findtext(f"{RAW_NS}categories"),
        versions=[
            {
                "version": v.attrib.get("version"),
                "date": v.findtext(f"{RAW_NS}date"),
                "size": v.findtext(f"{RAW_NS}size"),
            }
            for v in raw.findall(f"{RAW_NS}version")
        ],
    )
    return record


def read_token(response: OAIResponse) -> dict[str, Any] | None:
    """Đọc <resumptionToken>. Thẻ rỗng nghĩa là trang cuối, trả None."""
    element = response.xml.find(f".//{OAI_NS}resumptionToken")
    if element is None or not (element.text or "").strip():
        return None
    return {"token": element.text.strip(), "attributes": dict(element.attrib)}


def decode_token(token: str) -> dict[str, str]:
    """Token của arXiv là truy vấn gốc đã URL-encode cộng thêm `skip`, đọc được trực tiếp."""
    return dict(parse_qsl(unquote(token)))


def load_records(path: Path = RECORDS_PATH) -> dict[str, dict]:
    """Đọc lại data/oai_records.jsonl. Một ID có nhiều dòng thì dòng sau thắng."""
    records: dict[str, dict] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                record = json.loads(line)
                records[record["id"]] = record
    return records


def _append_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------------
# ListRecords trên cửa sổ ngày
# ----------------------------------------------------------------------
def validate_window(from_date: str, until_date: str) -> None:
    start, end = date.fromisoformat(from_date), date.fromisoformat(until_date)
    if end < start:
        raise ValueError(f"--until {until_date} trước --from {from_date}")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise ValueError(
            f"Cửa sổ tối đa {MAX_WINDOW_DAYS} ngày: harvest diện rộng không thuộc milestone này"
        )


def window_params(from_date: str, until_date: str, set_spec: str | None) -> dict[str, str]:
    params = {"verb": "ListRecords", "metadataPrefix": METADATA_PREFIX,
              "from": from_date, "until": until_date}
    if set_spec:
        params["set"] = set_spec
    return params


def iter_pages(client: Sickle, params: dict[str, str]) -> Iterator[tuple[OAIResponse, dict | None]]:
    """Duyệt từng trang, tự nối bằng resumption token."""
    while True:
        response = client.harvest(**params)
        raise_oai_error(response)
        token = read_token(response)
        yield response, token
        if token is None:
            return
        params = {"verb": params["verb"], "resumptionToken": token["token"]}


def harvest_window(client: Sickle, params: dict[str, str], max_pages: int,
                   start_token: str | None = None,
                   out_path: Path = RECORDS_PATH) -> dict[str, Any]:
    """Harvest một cửa sổ, ghi record và token sau mỗi trang.

    Trả tóm tắt gồm `complete`: False nghĩa là dừng vì max_pages, còn token để --resume.
    """
    first = dict(params)
    if start_token:
        first = {"verb": params["verb"], "resumptionToken": start_token}

    summary: dict[str, Any] = {"pages": 0, "records": 0, "deleted": 0, "complete": True,
                               "first_token": None}
    for response, token in iter_pages(client, first):
        records = [parse_record(el, "ListRecords")
                   for el in response.xml.iterfind(f".//{OAI_NS}record")]
        _append_records(out_path, records)
        summary["pages"] += 1
        summary["records"] += len(records)
        summary["deleted"] += sum(r["deleted"] for r in records)
        if token:
            summary["first_token"] = summary["first_token"] or token["token"]
            issued = now_utc().isoformat()
            with TOKEN_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**token, "issued_at_utc": issued, "query": params,
                                     "decoded": decode_token(token["token"])},
                                    ensure_ascii=False) + "\n")
            CHECKPOINT.write_text(json.dumps(
                {"query": params, "token": token["token"], "issued_at_utc": issued},
                ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            CHECKPOINT.unlink(missing_ok=True)
        print(f"  trang {summary['pages']}: {len(records)} record, "
              f"{'còn token' if token else 'hết danh sách'}")
        if token and summary["pages"] >= max_pages:
            summary["complete"] = False
            break
    return summary


def resume_or_restart(client: Sickle, params: dict[str, str], max_pages: int) -> dict[str, Any]:
    """Tiếp tục từ checkpoint; token đã hết hạn thì harvest lại cửa sổ từ đầu.

    Ghi trùng record không sao vì load_records() giữ dòng sau cùng của mỗi ID.
    """
    state = json.loads(CHECKPOINT.read_text(encoding="utf-8")) if CHECKPOINT.exists() else None
    if state is None or state["query"] != params:
        print("Không có checkpoint cho cửa sổ này, harvest từ đầu.")
        return harvest_window(client, params, max_pages)
    try:
        return harvest_window(client, params, max_pages, start_token=state["token"])
    except oaiexceptions.BadResumptionToken as exc:
        record_token_check("resume", state["token"], state["issued_at_utc"],
                           "badResumptionToken", detail=str(exc))
        print(f"Token cấp lúc {state['issued_at_utc']} không còn dùng được, harvest lại từ đầu.")
        return harvest_window(client, params, max_pages)


# ----------------------------------------------------------------------
# Thử hành vi token
# ----------------------------------------------------------------------
def record_token_check(probe: str, token: str, issued_at: str | None, result: str,
                       first_identifier: str = "", detail: str = "") -> None:
    checked = now_utc()
    age = crossed = ""
    if issued_at:
        issued = datetime.fromisoformat(issued_at)
        age = f"{(checked - issued).total_seconds() / 3600:.2f}"
        crossed = checked.date() > issued.date()
    _append_csv(TOKEN_CHECK_LOG, TOKEN_CHECK_COLUMNS, {
        "checked_at_utc": checked.isoformat(), "probe": probe, "token": token,
        "issued_at_utc": issued_at or "", "age_hours": age, "crossed_utc_midnight": crossed,
        "result": result, "first_identifier": first_identifier, "detail": detail[:200],
    })
    print(f"  [{probe}] age={age or '-'}h -> {result} {first_identifier}")


def try_token(client: Sickle, probe: str, token: str, issued_at: str | None) -> str:
    """Gửi một token, ghi lại server trả gì. Trả identifier đầu tiên, rỗng nếu lỗi.

    Mỗi trang không trả theo thứ tự quét, nên muốn biết `skip` có tác dụng không thì
    xem số record trong `detail`, đừng so identifier đầu tiên.
    """
    try:
        response = client.harvest(verb="ListRecords", resumptionToken=token)
        raise_oai_error(response)
    except OAI_ERRORS as exc:
        record_token_check(probe, token, issued_at, type(exc).__name__, detail=str(exc))
        return ""
    except OAIUnavailable as exc:
        record_token_check(probe, token, issued_at, exc.error_type, detail=str(exc))
        return ""
    identifiers = response.xml.findall(f".//{OAI_NS}record/{OAI_NS}header/{OAI_NS}identifier")
    identifier = identifiers[0].text if identifiers else ""
    record_token_check(probe, token, issued_at, "ok", identifier,
                       detail=f"{len(identifiers)} records")
    return identifier


def probe_token(client: Sickle, token: str | None) -> None:
    """Thử dùng lại token thật, một token tự sửa `skip`, và một token giả.

    Hai lần replay có thể được CDN trả từ cache (xem cột x_cache). Token tự sửa chưa
    từng được cấp nên buộc server phải xử lý: chấp nhận nghĩa là server không lưu token.
    """
    if token:
        issued = now_utc().isoformat()
        try_token(client, "replay_1", token, issued)
        try_token(client, "replay_2", token, issued)
        crafted = shift_skip(token, CRAFTED_SKIP_STEP)
        if crafted != token:
            try_token(client, "handcrafted_skip", crafted, None)
    try_token(client, "forged", "introds-a3-forged-token", None)


def shift_skip(token: str, step: int) -> str:
    """Token mới từ token cũ, tăng `skip` thêm `step`.

    >>> shift_skip("verb%3DListRecords%26skip%3D1300", 7)
    'verb%3DListRecords%26skip%3D1307'
    """
    return re.sub(r"skip%3D(\d+)", lambda m: f"skip%3D{int(m.group(1)) + step}", token)


def recheck_tokens(client: Sickle) -> None:
    """Gửi lại token đã lưu. Chạy sau 00:00 UTC để kiểm chứng hết hạn.

    CDN có thể trả token cũ từ cache dù token đã hết hạn, nên với mỗi token còn gửi
    thêm một bản đổi `skip` theo thời gian hiện tại: chưa ai gọi nên buộc server xử lý.
    """
    if not TOKEN_LOG.exists():
        sys.exit(f"Chưa có token nào trong {TOKEN_LOG}")
    entries = [json.loads(line) for line in TOKEN_LOG.read_text(encoding="utf-8").splitlines()]
    latest = {entry["token"]: entry for entry in entries}  # cùng token thì lấy lần cấp sau cùng
    for entry in latest.values():
        try_token(client, "recheck", entry["token"], entry["issued_at_utc"])
        step = 1 + int(time.time()) % RECHECK_SKIP_RANGE
        try_token(client, "recheck_uncached", shift_skip(entry["token"], step),
                  entry["issued_at_utc"])


# ----------------------------------------------------------------------
# GetRecord theo ID
# ----------------------------------------------------------------------
def choose_sample(ids: list[str], n: int | None, seed: int) -> list[str]:
    """Mẫu ngẫu nhiên có seed, để chạy lại vẫn ra đúng tập ID."""
    if n is None or n >= len(ids):
        return ids
    return random.Random(seed).sample(ids, n)


def get_records(client: Sickle, ids: list[str], out_path: Path = RECORDS_PATH) -> dict[str, int]:
    """GetRecord từng ID, bỏ qua ID đã có. Lỗi ở một ID không dừng cả mẻ."""
    done = load_records(out_path)
    todo = [i for i in ids if i not in done]
    counts = {"ok": 0, "skipped": len(ids) - len(todo), "not_found": 0, "fail": 0}
    print(f"GetRecord {len(todo)} ID (đã có {counts['skipped']}), "
          f"ước tính {len(todo) * config.REQUEST_DELAY / 60:.0f} phút")
    for i, arxiv_id in enumerate(todo, 1):
        try:
            response = client.harvest(verb="GetRecord", metadataPrefix=METADATA_PREFIX,
                                      identifier=IDENTIFIER_PREFIX + arxiv_id)
            raise_oai_error(response)
        except oaiexceptions.IdDoesNotExist:
            counts["not_found"] += 1
            continue
        except (OAIUnavailable, *OAI_ERRORS) as exc:
            print(f"  {arxiv_id}: lỗi {exc}")
            counts["fail"] += 1
            continue
        element = response.xml.find(f".//{OAI_NS}record")
        _append_records(out_path, [parse_record(element, "GetRecord")])
        counts["ok"] += 1
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}")
    return counts


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Harvest arXiv qua OAI-PMH, phạm vi hẹp")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="ListRecords trên một cửa sổ ngày hẹp")
    list_cmd.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    list_cmd.add_argument("--until", dest="until_date", required=True, help="YYYY-MM-DD")
    list_cmd.add_argument("--set", dest="set_spec", default=None, help="vd cs:cs:AI")
    list_cmd.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    list_cmd.add_argument("--resume", action="store_true", help="Tiếp tục từ checkpoint")
    list_cmd.add_argument("--probe-token", action="store_true",
                          help="Sau khi harvest, thử dùng lại token và thử token giả")
    list_cmd.add_argument("--retries", type=int, default=config.MAX_RETRIES)

    get_cmd = sub.add_parser("get", help="GetRecord theo danh sách ID")
    get_cmd.add_argument("--ids", required=True)
    get_cmd.add_argument("--sample", type=int, default=None, help="Chỉ lấy N ID ngẫu nhiên")
    get_cmd.add_argument("--seed", type=int, default=42)

    sub.add_parser("recheck-tokens", help="Gửi lại token đã lưu để xem còn dùng được không")
    args = parser.parse_args()

    config.ensure_dirs()
    config.DATA_ROOT.mkdir(parents=True, exist_ok=True)

    if args.command == "list":
        try:
            validate_window(args.from_date, args.until_date)
        except ValueError as exc:
            parser.error(str(exc))
        params = window_params(args.from_date, args.until_date, args.set_spec)
        client = PoliteSickle(max_retries=args.retries)
        try:
            if args.resume:
                summary = resume_or_restart(client, params, args.max_pages)
            else:
                summary = harvest_window(client, params, args.max_pages)
            print(f"Xong: {summary}")
            if args.probe_token:
                probe_token(client, summary["first_token"])
        except oaiexceptions.NoRecordsMatch:
            print("Cửa sổ này không có record nào (noRecordsMatch).")
        except OAIUnavailable as exc:
            sys.exit(f"Endpoint không phản hồi sau khi retry: {exc}\nChi tiết: {REQUEST_LOG}")
        finally:
            client.close()
    elif args.command == "get":
        ids = list(dict.fromkeys(config.strip_version(i) for i in load_ids(args.ids)))
        if not ids:
            sys.exit("Không đọc được ID nào.")
        client = PoliteSickle()
        try:
            print(get_records(client, choose_sample(ids, args.sample, args.seed)))
        finally:
            client.close()
    else:
        client = PoliteSickle()
        try:
            recheck_tokens(client)
        finally:
            client.close()


if __name__ == "__main__":
    main()
