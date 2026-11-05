"""Crawl references tuần tự cho danh sách arXiv ID được giao.

Chạy từ thư mục gốc project:
    python src/reference_builder.py --ids ids/<MSSV>.txt

Kết quả được ghi vào corpus/<pub_key>/references.json; mỗi HTTP attempt được
ghi thêm một dòng vào logs/references.csv để tìm các bài cần chạy lại.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import config
from semantic_scholar import (
    BATCH_MAX_IDS,
    ConnectionFailedError,
    RateLimitError,
    get_references_batch,
)

LOG_FIELDS = ["arxiv_id", "n_total", "n_with_arxiv", "seconds", "status", "error_type"]
DEFAULT_BATCH_SIZE = 100  # ~20KB/bài -> ~2MB mỗi response, dưới giới hạn 10MB của API


def load_ids(path: Path, limit: int | None = None) -> list[str]:
    """Đọc một arXiv ID mỗi dòng; bỏ dòng trống, comment, version và trùng lặp."""
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file ID: {path}")
    if limit is not None and limit < 1:
        raise ValueError("--limit phải là số nguyên dương")

    result: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        arxiv_id = line.strip()
        if not arxiv_id or arxiv_id.startswith("#"):
            continue
        if arxiv_id.lower().startswith("arxiv:"):
            arxiv_id = arxiv_id[6:].strip()
        arxiv_id = config.strip_version(arxiv_id)
        if arxiv_id and arxiv_id not in seen:
            result.append(arxiv_id)
            seen.add(arxiv_id)
    return result[:limit] if limit is not None else result


def normalize_reference(reference: dict[str, Any], arxiv_id: str) -> dict[str, Any]:
    """Chuẩn hóa một reference theo schema trong ``docs/schema.md``. """
    external_ids = reference.get("externalIds") or {}
    ref_arxiv_id = (
        external_ids.get("ArXiv")
        or external_ids.get("ArXivID")
        or external_ids.get("arXiv")
    )
    authors = [
        author["name"]
        for author in (reference.get("authors") or [])
        if isinstance(author, dict) and author.get("name")
    ]
    return {
        "arxiv_id": arxiv_id,
        "ref_s2_id": reference.get("paperId"),
        "ref_title": reference.get("title"),
        "ref_authors": authors,
        # API: publicationDate -> corpus schema: ref_submission_date.
        "ref_submission_date": reference.get("publicationDate"),
        "ref_arxiv_id": ref_arxiv_id,
        "has_arxiv_id": bool(ref_arxiv_id),
        "ref_venue": reference.get("venue"),
        "ref_year": reference.get("year"),
    }


def read_existing_result(arxiv_id: str) -> dict[str, Any] | None:
    path = config.pub_dir(arxiv_id) / "references.json"
    if not path.is_file():
        return None
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict):
        return None
    
    if result.get("status") != "ok" or result.get("arxiv_id") != arxiv_id:
        return None

    references = result.get("references")
    if not isinstance(references, list) or not isinstance(result.get("crawled_at"), str):
        return None
    if type(result.get("n_total")) is not int or result["n_total"] != len(references):
        return None
    if type(result.get("n_with_arxiv")) is not int:
        return None

    required_reference_fields = {
        "arxiv_id",
        "ref_s2_id",
        "ref_title",
        "ref_authors",
        "ref_submission_date",
        "ref_arxiv_id",
        "has_arxiv_id",
        "ref_venue",
        "ref_year",
    }
    for reference in references:
        if not isinstance(reference, dict):
            return None
        if reference.get("arxiv_id") != arxiv_id:
            return None
        if not required_reference_fields.issubset(reference):
            return None
        if not isinstance(reference["ref_authors"], list):
            return None
        if not isinstance(reference["has_arxiv_id"], bool):
            return None
        if reference["has_arxiv_id"] != bool(reference["ref_arxiv_id"]):
            return None

    actual_n_with_arxiv = sum(bool(reference["ref_arxiv_id"]) for reference in references)
    if result["n_with_arxiv"] != actual_n_with_arxiv:
        return None
    return result


def write_result(
    arxiv_id: str,
    status: str,
    references: list[dict[str, Any]],
) -> tuple[int, int]:
    # Chuẩn hóa toàn bộ danh sách; không lọc reference thiếu arXiv ID ở đây.
    normalized = [normalize_reference(reference, arxiv_id) for reference in references]
    n_with_arxiv = sum(reference["has_arxiv_id"] for reference in normalized)
    result = {
        "arxiv_id": arxiv_id,
        "crawled_at": config.now_iso(),
        "status": status,
        "n_total": len(normalized),
        "n_with_arxiv": n_with_arxiv,
        "references": normalized,
    }
    out_dir = config.pub_dir(arxiv_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "references.json"
    temporary_path = out_dir / "references.json.tmp"
    temporary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Thay file đích sau khi JSON đã được ghi đầy đủ, tránh file dở dang khi ngắt.
    temporary_path.replace(out_path)
    return len(normalized), n_with_arxiv


def log_row(
    writer: csv.DictWriter,
    log_file: Any,
    *,
    arxiv_id: str,
    n_total: int | None,
    n_with_arxiv: int | None,
    seconds: float,
    status: str,
    error_type: str = "",
) -> None:
    writer.writerow({
        "arxiv_id": arxiv_id,
        "n_total": "" if n_total is None else n_total,
        "n_with_arxiv": "" if n_with_arxiv is None else n_with_arxiv,
        "seconds": f"{seconds:.2f}",
        "status": status,
        "error_type": error_type,
    })
    log_file.flush()


def run(
    ids_path: Path,
    limit: int | None = None,
    overwrite: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    arxiv_ids = load_ids(ids_path, limit=limit)
    if not arxiv_ids:
        print(f"Không có arXiv ID nào trong {ids_path}")
        return
    run_ids(arxiv_ids, overwrite=overwrite, batch_size=batch_size)


def run_ids(
    arxiv_ids: list[str],
    overwrite: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Lấy references cho danh sách ID đã chuẩn hóa; trả số bài theo trạng thái."""
    if not 1 <= batch_size <= BATCH_MAX_IDS:
        raise ValueError(f"--batch-size phải nằm trong khoảng 1-{BATCH_MAX_IDS}")
    config.ensure_dirs()

    log_path = config.LOGS_ROOT / "references.csv"
    write_header = not log_path.exists() or log_path.stat().st_size == 0
    counts = {"ok": 0, "not_indexed": 0, "failed": 0, "skipped": 0}
    total = len(arxiv_ids)

    with log_path.open("a", encoding="utf-8", newline="") as log_file:
        writer = csv.DictWriter(log_file, fieldnames=LOG_FIELDS)
        if write_header:
            writer.writeheader()
            log_file.flush()

        def record_attempt(record: dict[str, Any]) -> None:
            log_row(
                writer, log_file,
                arxiv_id=record["arxiv_id"],
                n_total=record.get("n_total"),
                n_with_arxiv=record.get("n_with_arxiv"),
                seconds=record["seconds"],
                status=record["status"],
                error_type=record.get("error_type", ""),
            )

        def crawl(batch: list[tuple[int, str, dict[str, Any] | None]]) -> None:
            """Lấy một lô; lỗi HTTP khác 429 (vd. response quá lớn) thì chia đôi lô rồi thử lại."""
            print(f"[{batch[0][0]}-{batch[-1][0]}/{total}] Đang lấy references cho {len(batch)} bài")
            started = time.monotonic()
            try:
                results = get_references_batch(
                    [arxiv_id for _, arxiv_id, _ in batch], on_attempt=record_attempt,
                )
            except Exception as exc:
                if len(batch) > 1 and not isinstance(exc, (RateLimitError, ConnectionFailedError)):
                    print(f"  Lỗi lô ({exc}); chia đôi lô và thử lại", file=sys.stderr)
                    middle = len(batch) // 2
                    crawl(batch[:middle])
                    crawl(batch[middle:])
                    return
                elapsed = (time.monotonic() - started) / len(batch)
                error_type = getattr(exc, "error_type", type(exc).__name__.lower())
                result_status = "rate_limited" if isinstance(exc, RateLimitError) else "error"
                print(f"  Lỗi ({error_type}): {exc}", file=sys.stderr)
                for _, arxiv_id, existing in batch:
                    # Attempt của lô được log dưới nhãn lô; thêm một dòng mỗi bài
                    # để vẫn lọc được bài cần chạy lại từ references.csv.
                    log_row(
                        writer, log_file,
                        arxiv_id=arxiv_id,
                        n_total=None,
                        n_with_arxiv=None,
                        seconds=elapsed,
                        status="fail",
                        error_type=error_type,
                    )
                    if existing is None:
                        write_result(arxiv_id, result_status, [])
                    counts["failed"] += 1
                return

            for index, arxiv_id, existing in batch:
                references = results.get(arxiv_id)
                if references is None:
                    if existing is None:
                        write_result(arxiv_id, "not_indexed", [])
                    counts["not_indexed"] += 1
                    if existing is None:
                        print(f"  [{index}/{total}] {arxiv_id}: không có trên Semantic Scholar")
                    else:
                        print(f"  [{index}/{total}] {arxiv_id}: chưa được lập chỉ mục; giữ kết quả cũ")
                    continue
                n_total, n_with_arxiv = write_result(arxiv_id, "ok", references)
                counts["ok"] += 1
                print(f"  [{index}/{total}] {arxiv_id}: {n_total} references ({n_with_arxiv} có arXiv ID)")

        pending: list[tuple[int, str, dict[str, Any] | None]] = []
        for index, arxiv_id in enumerate(arxiv_ids, start=1):
            existing = read_existing_result(arxiv_id)
            if not overwrite and existing is not None:
                log_row(
                    writer, log_file,
                    arxiv_id=arxiv_id,
                    n_total=existing.get("n_total"),
                    n_with_arxiv=existing.get("n_with_arxiv"),
                    seconds=0.0,
                    status="skipped",
                )
                counts["skipped"] += 1
                continue
            pending.append((index, arxiv_id, existing))

        print(f"Bỏ qua {counts['skipped']} bài đã có kết quả; còn {len(pending)} bài, "
              f"lô {batch_size} -> {-(-len(pending) // batch_size)} request")
        for start in range(0, len(pending), batch_size):
            crawl(pending[start:start + batch_size])
    print(
        "Hoàn tất — "
        f"ok: {counts['ok']}, không được lập chỉ mục: {counts['not_indexed']}, "
        f"lỗi cần xem lại: {counts['failed']}, bỏ qua: {counts['skipped']}"
    )
    print(f"Log: {log_path}")
    return counts


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Lay references tu Semantic Scholar")
    parser.add_argument(
        "--ids",
        required=True,
        type=Path,
        help="File ID duoc giao, mot arXiv ID moi dong",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Chi xu ly N ID dau",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi de references.json da co",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"So ID moi request POST /paper/batch (1-{BATCH_MAX_IDS})",
    )
    args = parser.parse_args()
    try:
        run(args.ids, limit=args.limit, overwrite=args.overwrite, batch_size=args.batch_size)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
