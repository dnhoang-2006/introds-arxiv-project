"""Orchestrator của Milestone 2 — ghép 4 module theo đúng thứ tự đã chốt.

    python src/parse_main.py --ids ids/24120053.txt --limit 20
    python src/parse_main.py --ids ids/24120053.txt --workers 2 --overwrite
"""

from __future__ import annotations

import argparse
from pathlib import Path

import config
from parser.bib import collect_bib  # noqa: F401  (dùng ở tuần 2)
from parser.bib_dedup import unify_publication  # noqa: F401
from parser.elements import build_store  # noqa: F401
from parser.gather import gather  # noqa: F401
from parser.hierarchy import build_tree  # noqa: F401
from parser.normalize import clean_latex, normalize_math  # noqa: F401


def parse_one(pub_key: str, out_root: Path, overwrite: bool = False) -> dict:
    """Xử lý trọn một publication theo đúng thứ tự ở schema_m2.md mục 5.

        1. gather()                       — đường biên dịch từng version
        2. clean_latex + normalize_math   — chuẩn hoá
        3-4. unify_publication()          — dựng rename_map rồi đổi \\cite
        5. build_tree + build_store       — dựng cây và BĂM (chỉ băm ở đây)

    Chạy lại được: bỏ qua publication đã có parsed/<pub_key>/elements.jsonl,
    trừ khi overwrite=True.
    """
    raise NotImplementedError


def already_done(pub_key: str, out_root: Path) -> bool:
    return (out_root / pub_key / "elements.jsonl").exists()


def main() -> None:
    p = argparse.ArgumentParser(description="Hierarchical parser cho Milestone 2")
    p.add_argument("--ids", required=True, help="File ID (1 ID/dòng) hoặc danh sách ngăn bởi dấu phẩy")
    p.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N publication đầu (để test)")
    p.add_argument("--workers", type=int, default=1, help="Số tiến trình song song (mặc định 1)")
    p.add_argument("--overwrite", action="store_true", help="Parse lại cả publication đã xong")
    p.add_argument("--out", type=Path, default=config.PROJECT_ROOT / "parsed")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()  # noqa: F841

    raise NotImplementedError


if __name__ == "__main__":
    main()
