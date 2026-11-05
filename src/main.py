"""main.py — chạy cả pipeline Milestone 1 cho một danh sách arXiv ID.

    discovery -> downloader -> corpus_builder -> reference_builder

Chạy từ thư mục gốc project:
    python src/main.py --ids ids/<MSSV>.txt
    python src/main.py --ids ids/<MSSV>.txt --limit 5
    python src/main.py --ids 2507.06659,2507.06660 --out runs/test

Mỗi bước tự bỏ qua phần đã xong (paper_meta.json, archive đã tải, version đã
dựng, references.json hợp lệ), nên bị ngắt giữa chừng chỉ cần chạy lại đúng lệnh.

--out là thư mục gốc chứa corpus/, raw/, logs/, reports/ (mặc định: gốc project).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Biến môi trường mà config.py / downloader.py / corpus_builder.py đọc lúc import
OUTPUT_DIRS = {
    "CORPUS_ROOT": "corpus",
    "RAW_ROOT": "raw",
    "LOGS_ROOT": "logs",
    "REPORTS_ROOT": "reports",
}


def set_output_root(out: Path) -> None:
    """Trỏ mọi thư mục output vào out/.

    Phải gọi TRƯỚC khi import config và các bước: đường dẫn được đọc từ biến
    môi trường ngay lúc import module.
    """
    if "config" in sys.modules:
        raise RuntimeError("set_output_root() phải được gọi trước khi import config")
    out = out.resolve()
    for env, name in OUTPUT_DIRS.items():
        os.environ[env] = str(out / name)


def read_ids(source: str, limit: int | None = None) -> list[str]:
    """Đọc file ID hoặc danh sách ngăn bởi dấu phẩy; bỏ version và ID trùng."""
    import config
    from discovery import load_ids

    ids = list(dict.fromkeys(config.strip_version(i) for i in load_ids(source)))
    return ids[:limit] if limit else ids


def run_pipeline(ids: list[str]) -> list[tuple[str, float, Any]]:
    """Chạy lần lượt 4 bước; trả về (tên bước, số giây, tóm tắt) cho từng bước."""
    import config
    import corpus_builder
    import discovery
    import reference_builder
    from downloader import SourceDownloader

    steps: list[tuple[str, float, Any]] = []

    def step(name: str, fn: Callable[[], Any]) -> None:
        print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
        started = time.perf_counter()
        summary = fn()
        steps.append((name, time.perf_counter() - started, summary))

    # 1. Chỉ hỏi arXiv cho bài chưa có paper_meta.json
    todo = [i for i in ids if not (config.pub_dir(i) / "paper_meta.json").exists()]

    def run_discovery() -> str:
        if not todo:
            return f"đã có đủ paper_meta.json ({len(ids)} bài)"
        metas = discovery.run(todo)
        return f"thêm {len(metas)}/{len(todo)} bài, {len(ids) - len(todo)} bài đã có"

    step("1/4 Discovery", run_discovery)
    if todo:
        # Discovery và downloader dùng hai bộ đếm 3 giây riêng cho export.arxiv.org
        time.sleep(config.REQUEST_DELAY)

    def run_downloader() -> dict[str, int]:
        downloader = SourceDownloader()
        downloader.run(ids)
        return dict(downloader.summary)

    step("2/4 Tải source mọi version", run_downloader)
    step("3/4 Giải nén + dựng corpus",
         lambda: dict(corpus_builder.build_ids(",".join(ids))))
    step("4/4 Crawl reference", lambda: reference_builder.run_ids(ids))
    return steps


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Chạy cả pipeline: discovery -> downloader -> corpus_builder -> reference_builder"
    )
    parser.add_argument("--ids", required=True,
                        help="File ID (1 ID/dòng) hoặc danh sách ID ngăn bởi dấu phẩy")
    parser.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N ID đầu")
    parser.add_argument("--out", type=Path, default=None,
                        help="Thư mục gốc chứa corpus/, raw/, logs/, reports/ "
                             "(mặc định: gốc project)")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit phải là số nguyên dương")
    if args.out is not None:
        set_output_root(args.out)

    import config

    ids = read_ids(args.ids, args.limit)
    if not ids:
        parser.error(f"Không đọc được ID nào từ {args.ids}")
    if not os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        print("Chú ý: chưa có SEMANTIC_SCHOLAR_API_KEY, bước reference sẽ chậm hơn nhiều")

    print(f"Pipeline cho {len(ids)} bài")
    print(f"Corpus : {config.CORPUS_ROOT}")
    print(f"Log    : {config.LOGS_ROOT}")

    started = time.perf_counter()
    try:
        steps = run_pipeline(ids)
    except KeyboardInterrupt:
        sys.exit("\nĐã dừng. Chạy lại đúng lệnh để tiếp tục, phần đã xong sẽ được bỏ qua.")

    print(f"\n{'=' * 60}\nTỔNG KẾT\n{'=' * 60}")
    for name, seconds, summary in steps:
        print(f"{name:<30} {seconds:8.1f}s  {summary}")
    print(f"{'Tổng thời gian':<30} {time.perf_counter() - started:8.1f}s")


if __name__ == "__main__":
    main()
