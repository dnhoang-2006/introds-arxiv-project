"""Re-export các hàm chuẩn hóa văn bản và định danh dùng cho matcher M3.

Theo quyết định D1 trong docs/plan_tuan2_auto_label.md, toàn bộ bước làm sạch
đi qua module này. Khi nhóm trưởng cung cấp clean.py, chỉ cần đổi nguồn import
tại đây mà không sửa logic đối sánh ở các module khác.
"""

from __future__ import annotations

try:
    from parser.bib_dedup import (
        _clean_year as clean_year,
        _first_author_last_name as first_author_last_name,
        _norm_arxiv as norm_arxiv,
        _norm_doi as norm_doi,
        _norm_title as norm_title,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"parser", "parser.bib_dedup"}:
        raise
    from src.parser.bib_dedup import (
        _clean_year as clean_year,
        _first_author_last_name as first_author_last_name,
        _norm_arxiv as norm_arxiv,
        _norm_doi as norm_doi,
        _norm_title as norm_title,
    )

__all__ = [
    "clean_year",
    "first_author_last_name",
    "norm_arxiv",
    "norm_doi",
    "norm_title",
]
