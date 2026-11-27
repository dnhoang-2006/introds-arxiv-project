"""Re-export các hàm chuẩn hóa văn bản và định danh dùng cho matcher M3 (quyết định D1).

Tiêu đề và họ tác giả lấy từ `clean.py` của nhóm. DOI, arXiv ID và năm lấy từ `bib_dedup`
vì `clean.py` không có hàm cho ba trường này (chuẩn hóa định danh, không phải làm sạch văn bản).
"""

from __future__ import annotations

from typing import Any

from .clean import Author, clean_title, parse_authors

try:
    from parser.bib_dedup import (
        _clean_year as clean_year,
        _norm_arxiv as norm_arxiv,
        _norm_doi as norm_doi,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"parser", "parser.bib_dedup"}:
        raise
    from src.parser.bib_dedup import (
        _clean_year as clean_year,
        _norm_arxiv as norm_arxiv,
        _norm_doi as norm_doi,
    )


def norm_title(title: Any) -> str | None:
    """Tiêu đề chuẩn hóa theo `clean.clean_title`; `None` nếu rỗng."""
    return clean_title(str(title) if title else None) or None


def first_author(authors: Any) -> Author | None:
    """Tác giả đầu theo `clean.parse_authors` (đã cắt `et al.`, xử lý nháy, tên tổ chức)."""
    if isinstance(authors, list):
        authors = [a for a in authors if isinstance(a, str)]
    parsed = parse_authors(authors) if authors else []
    return parsed[0] if parsed else None


def same_first_author(a: Author, b: Author) -> bool:
    """Bộ lọc ứng viên: cùng họ theo `Author.matches` của clean.py.

    `matches` lo khoá phụ umlaut (`Böttcher`/`Bottcher`), tiền tố tách lệch
    (`Di Giulio`/`Giulio`) và tên tổ chức (`ATLAS Collaboration`/`A. Collaboration`).
    Bỏ chữ đầu tên vì họ chỉ dùng để lọc (schema_m3 mục 5): `Tong, Peter` với
    `Shengbang Tong` là cùng bài, so cả chữ đầu thì trượt.
    """
    return a.matches(b) or a._replace(initials="").matches(b._replace(initials=""))


__all__ = [
    "clean_year",
    "first_author",
    "norm_arxiv",
    "norm_doi",
    "norm_title",
    "same_first_author",
]
