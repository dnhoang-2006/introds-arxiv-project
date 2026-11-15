"""Orchestrator của Milestone 2 — ghép 4 module theo đúng thứ tự đã chốt.

    python src/parse_main.py --ids ids/24120053.txt --limit 20
    python src/parse_main.py --ids ids/24120053.txt --overwrite
    python src/parse_main.py --ids ids/24120053.txt --workers 2   # tuần 2, Minh Thư

Chạy lại được từ giữa chừng (docs/schema_m2.md mục 7): publication nào đã có
parsed/<pub_key>/elements.jsonl thì bỏ qua và ghi `skipped` vào logs/parse.csv,
trừ khi có --overwrite. Đứt giữa chừng thì chạy lại đúng lệnh cũ là đi tiếp.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import config
from parser.bib import collect_bib  # noqa: F401  (dùng ở tuần 2)
from parser.bib_dedup import unify_publication  # noqa: F401
from parser.elements import build_store  # noqa: F401
from parser.gather import gather  # noqa: F401
from parser.hierarchy import build_tree  # noqa: F401
from parser.normalize import clean_latex, normalize_math  # noqa: F401

# Định dạng ở docs/schema_m2.md mục 8 — đổi ở đây thì phải đổi cả ở đó.
PARSE_LOG_FIELDS = (
    "arxiv_id", "version", "n_elements", "n_sentences", "n_formulas",
    "n_figures", "max_depth", "seconds", "status", "error_type",
)

# File đánh dấu "publication này đã xong". Được ghi CUỐI CÙNG, xem write_outputs().
DONE_MARKER = "elements.jsonl"


# --------------------------------------------------------------------------- #
# Tuần 2
# --------------------------------------------------------------------------- #
def parse_one(arxiv_id: str, out_root: Path) -> list[dict[str, Any]]:
    """Xử lý trọn một publication theo đúng thứ tự ở schema_m2.md mục 5.

        1. gather()                       — đường biên dịch từng version
        2. clean_latex + normalize_math   — chuẩn hoá
        3-4. unify_publication()          — dựng rename_map rồi đổi \\cite
        5. build_tree + build_store       — dựng cây và BĂM (chỉ băm ở đây)
        6. write_outputs()                — ghi 3 bảng, elements.jsonl ghi sau cùng

    Việc bỏ qua bài đã xong do run() lo, hàm này không cần kiểm tra lại.

    Returns:
        Danh sách dòng log, MỘT dòng cho mỗi version, khoá theo PARSE_LOG_FIELDS
        (thiếu khoá nào thì run() điền 0 / rỗng; có `arxiv_id` cũng được, run() ghi
        đè bằng ID của chính nó). Version rỗng: status="empty".
    """
    raise NotImplementedError


# --------------------------------------------------------------------------- #
# Chạy lại được từ giữa chừng
# --------------------------------------------------------------------------- #
def already_done(pub_key: str, out_root: Path) -> bool:
    return (out_root / pub_key / DONE_MARKER).exists()


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Ghi ra file tạm rồi đổi tên — đứt giữa chừng thì file đích không tồn tại.

    os.replace là thao tác nguyên tử trên cùng một ổ đĩa (cả Windows lẫn POSIX).
    """
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write_outputs(
    pub_key: str,
    out_root: Path,
    elements: list[dict[str, Any]],
    hierarchy: list[dict[str, Any]],
    bibtex: list[dict[str, Any]],
) -> Path:
    """Ghi 3 bảng của một publication vào parsed/<pub_key>/.

    ⚠️ elements.jsonl là dấu "đã xong" mà already_done() kiểm tra, nên nó được ghi
    SAU CÙNG và ghi nguyên tử. Nếu ghi nó trước hoặc ghi thẳng, mất điện lúc đang
    ghi dở sẽ để lại một elements.jsonl cụt — lần chạy sau tưởng bài đã xong và bỏ
    qua, đúng kiểu lỗi "archive cụt đuôi" đã gặp ở M1.
    """
    pub_dir = out_root / pub_key
    pub_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(pub_dir / "hierarchy.jsonl", hierarchy)
    _write_jsonl_atomic(pub_dir / "bibtex.jsonl", bibtex)
    _write_jsonl_atomic(pub_dir / DONE_MARKER, elements)
    return pub_dir


def _log_row(arxiv_id: str, fields: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    """Dựng một dòng parse.csv đủ cột. Nhận dict (không bung **) để dòng do parse_one
    trả về có chứa `arxiv_id` cũng không đụng tham số — arxiv_id của run() luôn thắng.
    Khoá lạ bị bỏ qua thay vì làm DictWriter ném lỗi."""
    row: dict[str, Any] = {f: 0 for f in PARSE_LOG_FIELDS}
    row.update(version="", status="ok", error_type="")
    merged = {**(fields or {}), **kw}
    row.update({k: v for k, v in merged.items() if k in row})
    row["arxiv_id"] = arxiv_id
    if isinstance(row["seconds"], (int, float)):
        row["seconds"] = f"{row['seconds']:.2f}"
    return row


def run(
    ids: list[str],
    out_root: Path,
    overwrite: bool = False,
    verbose: bool = True,
    log_path: Path | None = None,
    parse_fn: Callable[[str, Path], list[dict[str, Any]]] | None = None,
    workers: int = 1,
) -> dict[str, int]:
    """Parse lần lượt từng publication, ghi logs/parse.csv, trả về số đếm theo status.

    - Đã có elements.jsonl và không --overwrite -> một dòng `skipped` (version để
      rỗng vì không mở lại bài đó), không đụng tới file cũ.
    - parse_fn ném lỗi -> một dòng `fail`, error_type = tên lớp lỗi, chạy tiếp bài sau.
      Riêng NotImplementedError được ném lại: đó là code chưa viết, không phải lỗi dữ liệu.
    - Log được flush sau mỗi bài để đứt giữa chừng vẫn còn.

    parse_fn mặc định là parse_one; tham số này để test thay bằng hàm giả.

    workers > 1 — CHỖ CẮM CHO MINH THƯ (điểm cộng tuần 2: so sánh --workers 1 vs 2).
    Gợi ý để không phá cơ chế chạy lại:
      - Lọc already_done() TRƯỚC khi đưa vào pool, như nhánh tuần tự bên dưới.
      - Chỉ chạy parse_fn trong tiến trình con (ProcessPoolExecutor). Mỗi bài ghi vào
        thư mục parsed/<pub_key>/ riêng nên các tiến trình không giẫm file nhau.
      - Ghi parse.csv ở TIẾN TRÌNH CHÍNH, khi từng future xong — không cho nhiều tiến
        trình cùng ghi một file CSV.
      - Giữ nguyên quy tắc: lỗi một bài -> dòng `fail`, không dừng cả mẻ.
    """
    if workers < 1:
        raise ValueError("workers phải >= 1")
    if workers > 1:
        raise NotImplementedError("Parse song song: Minh Thư viết ở tuần 2")
    parse_fn = parse_fn or parse_one
    log_path = log_path or (config.LOGS_ROOT / "parse.csv")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    counts = {"ok": 0, "empty": 0, "fail": 0, "skipped": 0}
    new_file = not log_path.exists() or log_path.stat().st_size == 0

    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PARSE_LOG_FIELDS)
        if new_file:
            writer.writeheader()

        for i, raw_id in enumerate(ids, 1):
            arxiv_id = config.strip_version(raw_id)
            key = config.pub_key(arxiv_id)

            if already_done(key, out_root) and not overwrite:
                writer.writerow(_log_row(arxiv_id, status="skipped"))
                counts["skipped"] += 1
                if verbose:
                    print(f"[{i}/{len(ids)}] {arxiv_id}  bỏ qua (đã có {DONE_MARKER})")
                fh.flush()
                continue

            t0 = time.perf_counter()
            try:
                # Dựng dòng log NGAY TRONG try: parse_one trả về sai dạng (None, thiếu
                # khoá, khoá thừa...) chỉ làm fail bài này, không giết cả mẻ.
                rows = [_log_row(arxiv_id, r) for r in parse_fn(arxiv_id, out_root)]
            except NotImplementedError:
                raise
            except Exception as exc:  # noqa: BLE001 — log mọi lỗi, không dừng cả mẻ
                writer.writerow(_log_row(arxiv_id, seconds=time.perf_counter() - t0,
                                         status="fail", error_type=type(exc).__name__))
                counts["fail"] += 1
                if verbose:
                    print(f"[{i}/{len(ids)}] {arxiv_id}  LỖI: {type(exc).__name__}: {exc}")
                fh.flush()
                continue

            for row in rows:
                writer.writerow(row)
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            if verbose:
                print(f"[{i}/{len(ids)}] {arxiv_id}  {len(rows)} version  "
                      f"{time.perf_counter() - t0:5.2f}s")
            fh.flush()

    return counts


def main() -> None:
    p = argparse.ArgumentParser(description="Hierarchical parser cho Milestone 2")
    p.add_argument("--ids", required=True, help="File ID (1 ID/dòng) hoặc danh sách ngăn bởi dấu phẩy")
    p.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N publication đầu (để test)")
    p.add_argument("--overwrite", action="store_true", help="Parse lại cả publication đã xong")
    p.add_argument("--workers", type=int, default=1,
                   help="Số tiến trình song song (mặc định 1; >1 do Minh Thư viết ở tuần 2)")
    p.add_argument("--out", type=Path, default=config.PROJECT_ROOT / "parsed")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    # Bỏ version và ID trùng giống src/main.py — một publication chỉ parse một lần.
    ids = list(dict.fromkeys(config.strip_version(i) for i in config.load_ids(args.ids)))
    ids = ids[:args.limit] if args.limit else ids
    if not ids:
        sys.exit("Không đọc được ID nào.")

    started = time.perf_counter()
    counts = run(ids, args.out, overwrite=args.overwrite, verbose=not args.quiet,
                 workers=args.workers)
    print(f"\n{'=' * 60}")
    print(f"Publication     : {len(ids)}")
    print("Version theo status: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Thời gian       : {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
