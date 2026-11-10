"""Trích xuất reference: đọc file .bib có sẵn và chuyển \\bibitem thành BibTeX.

Quy mô (từ duy2_prescan_summary.json, dải 2503, 8.129 version):
    bib_file_only       4.833 version (59,45%)  -> chỉ cần read_bib_file()
    inline_bibitem_only 1.277 version (15,71%)  -> cần parse_bibitem()
    both                  124 version ( 1,53%)  -> cả hai, và là BỘ ĐỐI CHỨNG
    none                1.895 version (23,31%)  -> bỏ qua

124 version có cả hai nguồn là bộ đối chứng miễn phí: file .bib là đáp án để chấm
độ chính xác của regex bóc \\bibitem, không tốn công gán tay.

Cần thêm vào src/requirements.txt:  bibtexparser>=1.4.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import logging
import bibtexparser
from bibtexparser.bparser import BibTexParser

logging.getLogger("bibtexparser").setLevel(logging.ERROR)

YEAR_PAT = re.compile(r"\b(19|20)\d{2}\b")

def _clean_bib_text(val:str|None)->str|None:
    if not val:
        return None
    # Xóa ngoặc nhọn trước BibTex và chuẩn hóa khoảng trắng

    cleaned = re.sub(r"[{}]","",val)
    cleaned=re.sub(r"\s+"," ", cleaned).strip()
    return cleaned or None


def read_bib_file(path: Path) -> list[dict[str, Any]]:
    """Đọc file .bib có sẵn thành danh sách entry theo schema mục 1.3."""
    path =Path(path)
    if not path.is_file():
        return []

    with open(path,encoding='utf-8', errors="replace") as f:
        # common_strings = True giúp giải quyết các macro tháng, tên tạp chí
        parser = BibTexParser(common_strings=True)
        db = bibtexparser.load(f, parser= parser)
    entries: list[dict[str,Any]] = []
    for e in db.entries:
        key = e.get("ID")
        if not key:
            continue
        # Title
        title= _clean_bib_text(e.get("title"))

        # Authors -> list[str]
        raw_authors = e.get("author")
        if raw_authors:
            cleaned_author_str = _clean_bib_text(raw_authors) or ""
            authors_list = [a.strip() for a in cleaned_author_str.split(" and ") if a.strip()]

            authors = authors_list if authors_list else None
        else:
            authors = None

        # Year -> int |None
        raw_year= str(e.get("year",""))
        m_year = YEAR_PAT.search(raw_year)
        year = int (m_year.group(0)) if m_year else None

        # DOI, Journal, URL
        doi = _clean_bib_text(e.get("doi"))
        journal = _clean_bib_text(e.get("journal") or e.get("booktitle"))
        url = _clean_bib_text(e.get("url"))

        entry_type = str(e.get("ENTRYTYPE", "misc")).lower().strip()

        entries.append(
            {
                "citation_key": key.strip(),
                "entry_type": entry_type,
                "title": title,
                "authors": authors,
                "year": year,
                "doi": doi,
                "journal": journal,
                "url": url
            }
        )
    return entries

        


def split_bibitems(tex: str) -> list[tuple[str, str]]:
    """Cắt phần thebibliography thành [(citation_key, văn bản thô của mục đó)].

    Mục cuối cùng chạy tới \\end{thebibliography} hoặc hết chuỗi — nhớ test ca này.
    """
    raise NotImplementedError


def parse_bibitem(key: str, raw: str) -> dict[str, Any]:
    """Bóc các trường ra khỏi văn bản tự do của một \\bibitem.

    \\bibitem KHÔNG có cấu trúc chuẩn, nên regex sẽ trượt một tỉ lệ nhất định.
    LUÔN GIỮ CỘT `raw` để tuần sau còn cứu được, và để báo cáo nêu được tỉ lệ
    bóc tách thành công từng trường — con số thật đáng giá hơn một câu chung chung.

    Giữ nguyên ID cũ dạng hep-th/9901001, không ép về dạng số.
    """
    raise NotImplementedError


def collect_bib(vdir: Path) -> list[dict[str, Any]]:
    """Gom toàn bộ reference của MỘT version từ cả hai nguồn (.bib và \\bibitem)."""
    raise NotImplementedError
