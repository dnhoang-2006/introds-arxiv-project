"""
discovery.py — Bước 1 của pipeline: giải các arXiv ID được giao thành metadata
và xác định SỐ VERSION của từng bài.

Vì sao module này quan trọng: số version mà nó trả ra chính là đầu vào của
`downloader.py` (Minh Thư). Đề yêu cầu "all available versions must be crawled",
nên nếu đếm sai version ở đây thì cả nhóm crawl thiếu dữ liệu.

Cách lấy số version (theo crawling.md):
    Một lookup `id_list` trên ID gốc trả về identifier của version MỚI NHẤT,
    ví dụ `2310.12345v4`. Đọc hậu tố đó là biết bài có 4 version.

Chạy:
    python src/discovery.py --ids ids/24120053.txt
    python src/discovery.py --ids 2310.12345,1706.03762 --limit 5
    python src/discovery.py --ids ids/24120053.txt --overwrite
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

try:
    import arxiv
except ImportError:
    sys.exit("Thiếu thư viện. Chạy: pip install -r src/requirements.txt")

import config


# ----------------------------------------------------------------------
# Kết quả cho một publication
# ----------------------------------------------------------------------
@dataclass
class PaperMeta:
    """Khớp đúng với `paper_meta.json` mô tả trong docs/schema.md."""

    # 6 trường của bảng `papers` theo Requirement của đề
    arxiv_id: str
    title: str
    authors: list[str]
    submission_date: str | None
    revised_dates: list[str]
    venue: str | None

    # Trường nội bộ, phục vụ các bước sau
    n_versions: int
    latest_versioned_id: str
    discovered_at: str = field(default_factory=config.now_iso)
    revised_dates_complete: bool = True

    def write(self, overwrite: bool = False) -> Path:
        """Ghi ra corpus/<pub_key>/paper_meta.json."""
        out_dir = config.pub_dir(self.arxiv_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "paper_meta.json"
        if path.exists() and not overwrite:
            return path
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


# ----------------------------------------------------------------------
# Client dùng chung
# ----------------------------------------------------------------------
def build_client() -> arxiv.Client:
    """Client của arxiv.py 4.x.

    `delay_seconds` được thư viện tự áp giữa các lần gọi API, đúng yêu cầu
    "wait at least 3 seconds" của arXiv. `num_retries` lo phần lỗi mạng tạm thời.
    """
    return arxiv.Client(
        page_size=100,
        delay_seconds=config.REQUEST_DELAY,
        num_retries=config.MAX_RETRIES,
    )


def _clean_title(raw: str) -> str:
    """arXiv trả title có xuống dòng và thụt lề — gộp lại thành 1 dòng."""
    return " ".join(raw.split())


# ----------------------------------------------------------------------
# Lõi: một ID -> PaperMeta
# ----------------------------------------------------------------------
def resolve_one(arxiv_id: str, client: arxiv.Client) -> PaperMeta:
    """Giải một arXiv ID thành metadata đầy đủ.

    Ném `StopIteration` nếu API không tìm thấy bài — caller bắt và ghi log `not_found`.
    """
    query_id = config.strip_version(arxiv_id)

    # arxiv.py 4.x: CHỈ có client.results(search).
    # search.results() và Result.download_source() đã bị xoá ở 4.0.0 (tháng 5/2026).
    search = arxiv.Search(id_list=[query_id])
    result = next(client.results(search))

    # entry_id dạng http://arxiv.org/abs/2310.12345v4
    #           hoặc http://arxiv.org/abs/hep-th/9901001v2  (ID cũ có dấu /)
    tail = result.entry_id.split("/abs/", 1)[-1]
    n_versions = config.parse_version(tail) or 1

    # ID chuẩn lấy từ CHÍNH phản hồi của API, không lấy từ input.
    # Nhờ vậy file ID của nhóm có lẫn hậu tố "v2", thừa khoảng trắng hay sai
    # hoa/thường thì corpus vẫn mang đúng ID gốc mà arXiv công nhận.
    base_id = config.strip_version(tail)
    latest = tail

    # ---- revised_dates: xem cảnh báo trong docs/schema.md -------------
    # Atom API chỉ trả `published` (v1) và `updated` (bản mới nhất).
    # Ngày của các version trung gian KHÔNG có trong response.
    submission_date = config.to_iso(result.published)
    updated = config.to_iso(result.updated)

    revised: list[str] = []
    if n_versions > 1 and updated and updated != submission_date:
        revised = [updated]

    # n_versions >= 3 nghĩa là còn version trung gian mà ta không biết ngày
    complete = n_versions <= 2

    return PaperMeta(
        arxiv_id=base_id,
        title=_clean_title(result.title),
        authors=[a.name for a in result.authors],
        submission_date=submission_date,
        revised_dates=revised,
        venue=result.journal_ref or None,
        n_versions=n_versions,
        latest_versioned_id=latest,
        revised_dates_complete=complete,
    )


# ----------------------------------------------------------------------
# Chạy hàng loạt + ghi log
# ----------------------------------------------------------------------
def run(ids: list[str], overwrite: bool = False, verbose: bool = True) -> list[PaperMeta]:
    config.ensure_dirs()
    client = build_client()
    metas: list[PaperMeta] = []

    log_path = config.LOGS_ROOT / "discovery.csv"
    new_file = not log_path.exists()

    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["arxiv_id", "n_versions", "status", "seconds", "error_type"])

        for i, raw_id in enumerate(ids, 1):
            started = time.perf_counter()
            try:
                meta = resolve_one(raw_id, client)
                meta.write(overwrite=overwrite)
                metas.append(meta)
                elapsed = time.perf_counter() - started
                writer.writerow([meta.arxiv_id, meta.n_versions, "ok", f"{elapsed:.2f}", ""])
                if verbose:
                    flag = "" if meta.revised_dates_complete else "  [revised_dates thiếu]"
                    print(f"[{i}/{len(ids)}] {meta.arxiv_id}  "
                          f"{meta.n_versions} version  {elapsed:5.2f}s  "
                          f"{meta.title[:50]}{flag}")

            except StopIteration:
                elapsed = time.perf_counter() - started
                writer.writerow([config.strip_version(raw_id), 0, "fail",
                                 f"{elapsed:.2f}", "not_found"])
                if verbose:
                    print(f"[{i}/{len(ids)}] {raw_id}  KHÔNG TÌM THẤY")

            except Exception as exc:  # noqa: BLE001 — log mọi lỗi, không dừng cả mẻ
                elapsed = time.perf_counter() - started
                writer.writerow([config.strip_version(raw_id), 0, "fail",
                                 f"{elapsed:.2f}", type(exc).__name__])
                if verbose:
                    print(f"[{i}/{len(ids)}] {raw_id}  LỖI: {type(exc).__name__}: {exc}")

            fh.flush()  # ghi ngay, mất điện giữa chừng vẫn còn log

    return metas


def load_ids(source: str, limit: int | None = None) -> list[str]:
    """Nhận đường dẫn file (một ID mỗi dòng) hoặc danh sách ID ngăn bởi dấu phẩy."""
    path = Path(source)
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        ids = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    else:
        ids = [s.strip() for s in source.split(",") if s.strip()]
    return ids[:limit] if limit else ids


def main() -> None:
    p = argparse.ArgumentParser(description="Entry Discovery cho Milestone 1")
    p.add_argument("--ids", required=True,
                   help="Đường dẫn file ID (1 ID/dòng) hoặc danh sách ngăn bởi dấu phẩy")
    p.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N ID đầu (để test)")
    p.add_argument("--overwrite", action="store_true",
                   help="Ghi đè paper_meta.json đã có")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    ids = load_ids(args.ids, args.limit)
    if not ids:
        sys.exit("Không đọc được ID nào.")

    print(f"Giải {len(ids)} ID — pacing {config.REQUEST_DELAY}s/request, "
          f"ước tính {len(ids) * config.REQUEST_DELAY / 60:.1f} phút\n")

    metas = run(ids, overwrite=args.overwrite, verbose=not args.quiet)

    total_versions = sum(m.n_versions for m in metas)
    incomplete = sum(1 for m in metas if not m.revised_dates_complete)
    print(f"\n{'=' * 60}")
    print(f"Thành công      : {len(metas)}/{len(ids)} bài")
    print(f"Tổng số version : {total_versions}  (Minh Thư sẽ tải từng cái qua /src/)")
    print(f"Thiếu revised   : {incomplete} bài có >2 version nên thiếu ngày trung gian")
    print(f"Corpus          : {config.CORPUS_ROOT}")
    print(f"Log             : {config.LOGS_ROOT / 'discovery.csv'}")


if __name__ == "__main__":
    main()
