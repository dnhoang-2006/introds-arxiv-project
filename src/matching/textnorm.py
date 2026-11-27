"""Re-export các hàm chuẩn hóa văn bản và định danh dùng cho matcher M3 (quyết định D1).

Tiêu đề lấy từ `clean.py` của nhóm. Họ tác giả, DOI, arXiv ID và năm vẫn lấy từ
`bib_dedup`: `clean.py` không có hàm cho DOI/arXiv/năm, còn `parse_author` làm mất
70 cặp đúng trên mẫu 500 pub (ngày 27/11). Lỗi gặp: `X et al.` thành họ `al`,
`Cr'epel` của S2 thành `cr epel`, `Blümlein` thành `bluemlein` trong khi S2 ghi `Blumlein`.
shortcut: đổi họ tác giả sang clean.py khi nhóm trưởng sửa ba lỗi trên.
"""

from __future__ import annotations

from typing import Any

from .clean import clean_title

try:
    from parser.bib_dedup import (
        _clean_year as clean_year,
        _first_author_last_name as first_author_last_name,
        _norm_arxiv as norm_arxiv,
        _norm_doi as norm_doi,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"parser", "parser.bib_dedup"}:
        raise
    from src.parser.bib_dedup import (
        _clean_year as clean_year,
        _first_author_last_name as first_author_last_name,
        _norm_arxiv as norm_arxiv,
        _norm_doi as norm_doi,
    )


def norm_title(title: Any) -> str | None:
    """Tiêu đề chuẩn hóa theo `clean.clean_title`; `None` nếu rỗng."""
    return clean_title(str(title) if title else None) or None


__all__ = [
    "clean_year",
    "first_author_last_name",
    "norm_arxiv",
    "norm_doi",
    "norm_title",
]
