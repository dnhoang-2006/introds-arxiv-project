"""
kaggle_loader.py — A3: đọc Cornell arXiv snapshot trên Kaggle, lọc đúng ID được giao.

Snapshot (khoảng 5,7 GB JSON Lines, nén zip khoảng 1,9 GB) tải một lần vào data/:
    curl -L -o data/kaggle_snapshot/arxiv.zip \
        https://www.kaggle.com/api/v1/datasets/download/Cornell-University/arxiv

Chạy:
    python src/kaggle_loader.py --ids ids/24120053.txt
    python src/kaggle_loader.py --ids ids/24120053.txt --snapshot path/to/snapshot.json

Kết quả:
    data/kaggle_records.jsonl   một dòng mỗi bài tìm thấy, đã bỏ abstract
    logs/kaggle_loader.json     ngày snapshot, số dòng đã đọc, ID không tìm thấy

Vì sao đọc với dtype=False: mặc định `pandas.read_json` đoán kiểu và biến cột `id`
thành số, nên 2507.10000 thành 2507.1 và không còn khớp với ID nào.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from discovery import load_ids

DEFAULT_SNAPSHOT = config.DATA_ROOT / "kaggle_snapshot" / "arxiv.zip"
DEFAULT_OUTPUT = config.DATA_ROOT / "kaggle_records.jsonl"
CHUNK_ROWS = 100_000  # đọc từng khúc để không nạp cả 5,7 GB vào RAM

KEEP_COLUMNS = [
    "id", "title", "authors", "authors_parsed", "journal-ref", "doi",
    "categories", "versions", "update_date",
]


def snapshot_date(path: Path) -> str | None:
    """Ngày tạo snapshot, đọc từ file JSON bên trong zip (mtime của file zip là ngày tải)."""
    if path.suffix.lower() != ".zip":
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()
    with zipfile.ZipFile(path) as archive:
        year, month, day, *_ = archive.infolist()[0].date_time
    return f"{year:04d}-{month:02d}-{day:02d}"


def filter_snapshot(snapshot: Path, ids: list[str],
                    chunk_rows: int = CHUNK_ROWS) -> tuple[pd.DataFrame, int]:
    """Quét snapshot, trả (các dòng có ID nằm trong `ids`, tổng số dòng đã đọc)."""
    wanted = {config.strip_version(i) for i in ids}
    found: list[pd.DataFrame] = []
    n_rows = 0
    reader = pd.read_json(
        snapshot, lines=True, chunksize=chunk_rows,
        dtype=False, convert_dates=False,
    )
    with reader:
        for chunk in reader:
            n_rows += len(chunk)
            hit = chunk.loc[chunk["id"].isin(wanted), KEEP_COLUMNS]
            if not hit.empty:
                found.append(hit)
    if not found:
        return pd.DataFrame(columns=KEEP_COLUMNS), n_rows
    records = pd.concat(found, ignore_index=True).drop_duplicates(subset="id")
    return records.reset_index(drop=True), n_rows


def load_records(path: Path = DEFAULT_OUTPUT) -> dict[str, dict]:
    """Đọc lại file đã lọc thành {arxiv_id: record}."""
    records: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            records[record["id"]] = record
    return records


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Lọc Cornell Kaggle snapshot theo ID được giao")
    parser.add_argument("--ids", required=True, help="File ID (1 ID/dòng) hoặc danh sách ngăn bởi dấu phẩy")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT,
                        help="File .zip hoặc .json của snapshot")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.snapshot.exists():
        sys.exit(f"Không thấy snapshot: {args.snapshot}\nXem lệnh tải ở đầu file kaggle_loader.py.")
    ids = list(dict.fromkeys(config.strip_version(i) for i in load_ids(args.ids)))
    if not ids:
        sys.exit("Không đọc được ID nào.")

    config.ensure_dirs()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    records, n_rows = filter_snapshot(args.snapshot, ids)
    seconds = time.perf_counter() - started
    records.to_json(args.out, orient="records", lines=True, force_ascii=False)

    missing = sorted(set(ids) - set(records["id"]))
    summary = {
        "snapshot": args.snapshot.name,
        "snapshot_date": snapshot_date(args.snapshot),
        "rows_scanned": n_rows,
        "ids_requested": len(ids),
        "ids_found": len(records),
        "ids_missing": missing,
        "seconds": round(seconds, 2),
        "loaded_at": config.now_iso(),
    }
    (config.LOGS_ROOT / "kaggle_loader.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"Snapshot {summary['snapshot_date']}: đọc {n_rows:,} dòng trong {seconds:.0f}s")
    print(f"Tìm thấy {len(records)}/{len(ids)} ID, thiếu {len(missing)}")
    print(f"Ghi: {args.out}")


if __name__ == "__main__":
    main()
