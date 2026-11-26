"""Trích xuất reference: đọc file .bib có sẵn và chuyển \\bibitem thành BibTeX.

Quy mô (từ duy2_prescan_summary.json, dải 2503, 8.129 version):
    bib_file_only       4.833 version (59,45%)  -> chỉ cần read_bib_file()
    inline_bibitem_only 1.277 version (15,71%)  -> cần parse_bibitem()
    both                  124 version ( 1,53%)  -> cả hai, và là BỘ ĐỐI CHỨNG
    none                1.895 version (23,31%)  -> bỏ qua

124 version có cả hai nguồn là bộ đối chứng miễn phí: file .bib là đáp án để chấm
độ chính xác của regex bóc \\bibitem, không tốn công gán tay.

Cần thêm vào src/requirements.txt:  bibtexparser>=2.0,<3
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import bibtexparser

logging.getLogger("bibtexparser").setLevel(logging.ERROR)

COMMENT_PAT = re.compile(r"(?<!\\)%.*")
THEBIB_BLOCK_PAT = re.compile(
    r"\\begin\{thebibliography\}[^}]*\}([\s\S]*?)\\end\{thebibliography\}",
    re.IGNORECASE,
)
BIBITEM_PAT = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
YEAR_PAT = re.compile(r"\b(19|20)\d{2}\b")
DOI_PAT = re.compile(r"10\.\d{4,9}/[-._;()/:\w]+", re.IGNORECASE)
ARXIV_PAT = re.compile(r"arXiv[:\s]*(\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?", re.IGNORECASE)
ARXIV_REF_PAT = re.compile(r"(?:arXiv[:.]|abs/)\s*(\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?", re.IGNORECASE)
URL_PAT = re.compile(r"https?://[^\s,}]+")

# Các regex trích xuất tiêu đề fallback theo ngoặc kép ``...'' và "...",
# cuối cùng là \emph/\textit/\textbf vì \emph{} thường dùng cho tên hội nghị/tạp chí
TITLE_PATS = [
    re.compile(r"``(.+?)''"),
    re.compile(r'"([^"]+)"'),
    re.compile(r"\\(?:emph|textit|textbf)\{([^}]+)\}"),
]


def _extract_bibinfo_title_span(raw: str) -> tuple[str, int, int] | None:
    """Trích xuất tiêu đề từ \\bibinfo{title}{...} bằng cách cân bằng ngoặc nhọn (arbitrary nesting).

    Hỗ trợ độ lồng ngoặc không giới hạn (như {\\textendash}, {\\ensuremath{\\alpha}}, v.v.),
    tránh giới hạn của regex tĩnh khi gặp macro lồng sâu bên trong tiêu đề.
    Trả về (nội dung tiêu đề thô, vị trí bắt đầu, vị trí kết thúc) hoặc None.
    """
    m = re.search(r"\\bibinfo\s*\{title\}\s*\{", raw, re.IGNORECASE)
    if not m:
        return None
    start_content = m.end()
    depth = 1
    i = start_content
    n = len(raw)
    while i < n and depth > 0:
        c = raw[i]
        if c == "\\":
            i += 2
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                content = raw[start_content:i]
                return content, m.start(), i
        i += 1
    return None


# Lệnh định dạng chỉ bọc nội dung, phải GỠ trước khi xoá ngoặc nhọn.
# Nếu xoá ngoặc trước thì \\text{Hermitian} thành \\textHermitian, rồi
# bib_dedup.py (dòng 110, 123, 348) xoá nguyên cụm \\[a-zA-Z]+ -> mất chữ.
# Đo 26/11: 1.637/1.692.998 title dính lỗi này (0,097%), chủ yếu \\mathrm trong công thức.
_UNWRAP_CMD = (
    "text|textrm|textbf|textit|texttt|textsc|textsf|textnormal|textup|"
    "emph|mathrm|mathbf|mathit|mathsf|mathtt|mathcal|mbox|hbox|"
    "ensuremath|boldsymbol|bm|uppercase|lowercase"
)
_UNWRAP_PAT = re.compile(r"\\(?:" + _UNWRAP_CMD + r")\s*\{([^{}]*)\}")


def _clean_bib_text(val: str | None) -> str | None:
    if not val:
        return None
    cleaned = val
    for _ in range(4):                      # lệnh có thể lồng vài lớp
        new = _UNWRAP_PAT.sub(r"\1", cleaned)
        if new == cleaned:
            break
        cleaned = new
    cleaned = re.sub(r"[{}]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _find_arxiv(e: Any) -> str | None:
    """Tìm arXiv ID rải rác trong các trường của entry BibTeX (M3 matching pool)."""
    # 1. Ưu tiên trường eprint (có thể có hoặc không có tiền tố arXiv:)
    fld_eprint = e.fields_dict.get("eprint")
    if fld_eprint:
        val = str(fld_eprint.value).strip()
        m_eprint = re.search(r"(?:arXiv[:\s]*)?(\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?", val, re.IGNORECASE)
        if m_eprint:
            return m_eprint.group(1)

    # 2. Tìm trong các trường khác (cần có tiền tố arXiv: hoặc abs/)
    for name in ("doi", "url", "journal", "note", "volume"):
        fld = e.fields_dict.get(name)
        if fld and (m := ARXIV_REF_PAT.search(str(fld.value))):
            return m.group(1)
    return None


def read_bib_file(
    path: Path | str,
    lenient: bool = False,
    failed_blocks_out: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Đọc file .bib có sẵn thành danh sách entry theo schema mục 1.3.

    Args:
        path: Đường dẫn file .bib
        lenient: Nếu True, vẫn trích xuất các entry hợp lệ khi có block lỗi cú pháp;
                 nếu False (mặc định), ném ValueError khi có bất kỳ block lỗi nào.
        failed_blocks_out: Nếu truyền list, các block lỗi cú pháp (nếu có) sẽ được nạp vào đây.
    """
    path = Path(path)
    if not path.is_file():
        return []

    lib = bibtexparser.parse_file(str(path))
    if lib.failed_blocks:
        if failed_blocks_out is not None:
            failed_blocks_out.extend(lib.failed_blocks)
        if not lenient:
            raise ValueError(f"File BibTeX chứa {len(lib.failed_blocks)} block lỗi cú pháp: {path}")

    entries: list[dict[str, Any]] = []
    for e in lib.entries:
        if not e.key:
            continue

        def f(name: str) -> str | None:
            fld = e.fields_dict.get(name)
            return _clean_bib_text(str(fld.value)) if fld and fld.value is not None else None

        # Title
        title = f("title")

        # Authors -> list[str]
        auth = f("author")
        auth_list = [a.strip() for a in auth.split(" and ") if a.strip()] if auth else None
        authors = auth_list if auth_list else None

        # Year -> int |None
        yr = YEAR_PAT.search(f("year") or "")
        year = int(yr.group(0)) if yr else None

        # DOI, Journal, URL
        doi = f("doi")
        journal = f("journal") or f("booktitle")
        url = f("url")

        # arXiv ID
        arxiv_id = _find_arxiv(e)

        entry_type = (e.entry_type or "misc").lower().strip()

        entries.append(
            {
                "citation_key": e.key.strip(),
                "entry_type": entry_type,
                "title": title,
                "authors": authors,
                "year": year,
                "doi": doi,
                "journal": journal,
                "url": url,
                "arxiv_id": arxiv_id,
            }
        )
    return entries


def split_bibitems(tex: str) -> list[tuple[str, str]]:
    """Cắt phần thebibliography thành [(citation_key, văn bản thô của mục đó)].

    Mục cuối cùng chạy tới \\end{thebibliography} hoặc hết chuỗi — nhớ test ca này.
    """
    # 1. Loại bỏ comment TeX nhưng giữ ký tự thoát \%
    clean_tex = COMMENT_PAT.sub("", tex)

    # 2. Tìm tất cả các khối thebibliography
    blocks = list(THEBIB_BLOCK_PAT.finditer(clean_tex))
    out: list[tuple[str, str]] = []

    if blocks:
        for block_match in blocks:
            block_content = block_match.group(1)
            hits = list(BIBITEM_PAT.finditer(block_content))
            if not hits:
                continue
            for i, m in enumerate(hits):
                key = m.group(1).strip()
                start_pos = m.end()
                end_pos = hits[i + 1].start() if (i + 1 < len(hits)) else len(block_content)
                raw = block_content[start_pos:end_pos].strip()
                out.append((key, raw))
    else:
        hits = list(BIBITEM_PAT.finditer(clean_tex))
        if hits:
            end_env = clean_tex.find(r"\end{thebibliography}")
            max_len = end_env if end_env != -1 else len(clean_tex)
            for i, m in enumerate(hits):
                key = m.group(1).strip()
                start_pos = m.end()
                end_pos = hits[i + 1].start() if (i + 1 < len(hits)) else max_len
                raw = clean_tex[start_pos:end_pos].strip()
                out.append((key, raw))

    return out


def _split_author_chunk(chunk: str) -> list[str]:
    """Tách một chuỗi tác giả (không chứa 'and') thành danh sách các tác giả."""
    chunk = chunk.strip().rstrip(",")
    if not chunk:
        return []

    if ";" in chunk:
        return [p.strip() for p in chunk.split(";") if p.strip()]

    if "," not in chunk:
        return [chunk]

    parts = [p.strip() for p in chunk.split(",") if p.strip()]
    if len(parts) <= 1:
        return parts

    # Kiểm tra xem có phải dạng "Last, First"
    # hay là danh sách nhiều tác giả
    authors = []
    i = 0
    while i < len(parts):
        curr = parts[i]
        if re.match(r"^et\s+al\.?$", curr, re.IGNORECASE):
            authors.append(curr)
            i += 1
            continue

        if i + 1 < len(parts):
            next_p = parts[i + 1]
            if re.match(r"^et\s+al\.?$", next_p, re.IGNORECASE):
                authors.append(curr)
                i += 1
                continue

            curr_words = curr.split()
            next_words = next_p.split()
            is_initial = bool(re.match(r"^[A-Z](\.[A-Z])*\.?$", next_p))
            curr_has_leading_initial = bool(re.match(r"^[A-Z]\.", curr_words[0])) if curr_words else False

            if not curr_has_leading_initial and (is_initial or (len(curr_words) == 1 and len(next_words) <= 2)):
                authors.append(f"{curr}, {next_p}")
                i += 2
                continue

        authors.append(curr)
        i += 1

    return authors


def _extract_authors(clean_raw: str, title_match: re.Match | None) -> list[str] | None:
    """Trích xuất danh sách đầy đủ tác giả từ văn bản bibitem trước tiêu đề/năm."""
    if title_match and title_match.start() > 0:
        prefix = clean_raw[:title_match.start()].strip().rstrip(".")
    else:
        m_yr = YEAR_PAT.search(clean_raw)
        if m_yr and m_yr.start() > 0:
            prefix = clean_raw[:m_yr.start()].strip().rstrip(".")
        else:
            prefix = clean_raw.split(".")[0].strip()

    if not prefix:
        return None

    # Làm sạch các macro LaTeX thường gặp trong \\bibitem như \\bibinfo{author}, \\newblock
    prefix = re.sub(r"\\newblock\s*", " ", prefix)
    prefix = re.sub(r"\\bibinfo\s*\{author\}\s*", " ", prefix)

    # Tách theo 'and' hoặc '&' (kể cả dạng LaTeX '\&') trước nếu có
    if re.search(r"\band\b|\\?&", prefix, re.IGNORECASE):
        chunks = [c.strip() for c in re.split(r",?\s*(?:\band\b|\\?&)\s*", prefix, flags=re.IGNORECASE) if c.strip()]
    else:
        chunks = [prefix]

    raw_authors: list[str] = []
    for chunk in chunks:
        raw_authors.extend(_split_author_chunk(chunk))

    authors = []
    for p in raw_authors:
        cleaned = _clean_bib_text(p)
        if cleaned and cleaned.lower() not in ("in", "by"):
            authors.append(cleaned)

    return authors if authors else None


def parse_bibitem(key: str, raw: str) -> dict[str, Any]:
    """Bóc các trường ra khỏi văn bản tự do của một \\bibitem.

    \\bibitem KHÔNG có cấu trúc chuẩn, nên regex sẽ trượt một tỉ lệ nhất định.
    LUÔN GIỮ CỘT `raw` để tuần sau còn cứu được, và để báo cáo nêu được tỉ lệ
    bóc tách thành công từng trường — con số thật đáng giá hơn một câu chung chung.

    Giữ nguyên ID cũ dạng hep-th/9901001, không ép về dạng số.
    """
    clean_raw = re.sub(r"\s+", " ", raw).strip()
    clean_raw = re.sub(r"^\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^}]*\}\s*", "", clean_raw)

    # Title
    title = None
    title_match = None

    # 1. Ưu tiên bóc tách cân bằng ngoặc cho \bibinfo{title}{...} (REVTeX/APS), hỗ trợ lồng ngoặc sâu
    res_bibinfo = _extract_bibinfo_title_span(clean_raw)
    if res_bibinfo:
        raw_title, t_start, _ = res_bibinfo
        title = _clean_bib_text(raw_title)
        if title:
            title = title.rstrip(" ,.")

        class _SpanMatch:
            def __init__(self, start_pos: int):
                self._start = start_pos

            def start(self) -> int:
                return self._start

        title_match = _SpanMatch(t_start)  # type: ignore[assignment]
    else:
        # 2. Thử các pattern regex fallback
        for pat in TITLE_PATS:
            m = pat.search(clean_raw)
            if m:
                title = _clean_bib_text(m.group(1))
                if title:
                    title = title.rstrip(" ,.")
                title_match = m
                break

    # Year
    m_year = YEAR_PAT.search(clean_raw)
    year = int(m_year.group(0)) if m_year else None

    # DOI
    m_doi = DOI_PAT.search(clean_raw)
    doi = m_doi.group(0).rstrip(".") if m_doi else None

    # arXiv ID
    m_arxiv = ARXIV_PAT.search(clean_raw)
    arxiv_id = m_arxiv.group(1) if m_arxiv else None

    # URL
    m_url = URL_PAT.search(clean_raw)
    url = m_url.group(0).rstrip(".") if m_url else None

    # Authors -> list[str]
    authors = _extract_authors(clean_raw, title_match)

    return {
        "citation_key": key,
        "entry_type": "article",
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "journal": None,
        "url": url,
        "arxiv_id": arxiv_id,
        "raw": raw,
    }



_CITE_PAT = re.compile(
    r"\\[a-zA-Z]*[Cc]ite[a-zA-Z]*\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}"
)
_NOCITE_ALL = re.compile(r"\\nocite\s*\{\s*\*\s*\}")


def _collect_cited_keys(vdir: Path) -> set[str] | None:
    """Khoá xuất hiện trong lệnh trích dẫn của các file .tex trong version.

    Trả về None khi KHÔNG được lọc:
      - gặp \\nocite{*}: bài cố ý in toàn bộ thư mục
      - không tìm thấy lệnh trích dẫn nào: có thể do định dạng lạ, lọc sẽ xoá nhầm
    """
    keys: set[str] = set()
    for p in sorted(vdir.rglob("*.tex")):
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            tex = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        tex = re.sub(r"(?<!\\)%.*", "", tex)        # bỏ comment
        if _NOCITE_ALL.search(tex):
            return None
        for group in _CITE_PAT.findall(tex):
            for k in group.split(","):
                k = k.strip()
                if k:
                    keys.add(k)
    return keys or None


def collect_bib(
    vdir: Path | str,
    failed_blocks_out: list[Any] | None = None,
    errors_out: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Gom toàn bộ reference của MỘT version từ cả hai nguồn (.bib và \\bibitem).

    Quy tắc ưu tiên: khi cùng citation_key ở cả hai nguồn, bản từ .bib ghi đè
    bản từ \\bibitem vì .bib có cấu trúc chuẩn và trường chính xác hơn.

    Args:
        vdir: Thư mục version (ví dụ corpus/2503-12000/v1)
        failed_blocks_out: Nếu truyền list, các block lỗi cú pháp .bib sẽ được thêm vào đây.
        errors_out: Nếu truyền list, thông báo ngoại lệ khi đọc file .bib sẽ được thêm vào đây.
    """
    vdir = Path(vdir)
    if not vdir.is_dir():
        return []

    collected: dict[str, dict[str, Any]] = {}
    logger = logging.getLogger("parser.bib")

    # 1. Bóc từ \bibitem trong các file .tex (đưa vào trước)
    tex_files = sorted(
        p for p in vdir.rglob("*.tex")
        if p.is_file() and not p.name.startswith(".")
    )
    for p in tex_files:
        try:
            tex = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if r"\begin{thebibliography}" not in tex:
            continue
        for key, raw in split_bibitems(tex):
            if key not in collected:
                collected[key] = parse_bibitem(key, raw)

    # 1b. Bóc \bibitem trong các file .bbl — bản đã dàn trang, sinh khi compile
    # từ .bib. Đặt SAU .tex và TRƯỚC .bib để hai nguồn chuẩn hơn vẫn ghi đè được.
    # Trường bóc ra kém chính xác hơn .bib vì .bbl không còn cấu trúc trường.
    bbl_files = sorted(
        p for p in vdir.rglob("*.bbl")
        if p.is_file() and not p.name.startswith(".")
    )
    for p in bbl_files:
        try:
            bbl = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for key, raw in split_bibitems(bbl):
            if key not in collected:
                collected[key] = parse_bibitem(key, raw)

    # 2. Đọc từ các file .bib (đưa vào sau để ghi đè khi trùng key)
    bib_files = sorted(
        p for p in vdir.rglob("*.bib")
        if p.is_file() and not p.name.startswith(".")
    )
    for p in bib_files:
        cur_failed: list[tuple[str, str]] = []
        try:
            # Dùng lenient=True để vớt các entries hợp lệ, ghi nhận failed_blocks
            entries = read_bib_file(p, lenient=True, failed_blocks_out=cur_failed)
        except Exception as exc:
            msg = f"Lỗi đọc file BibTeX {p}: {type(exc).__name__}: {exc}"
            logger.warning(msg)
            if errors_out is not None:
                errors_out.append(msg)
            continue

        if cur_failed:
            logger.warning(
                "File BibTeX %s chứa %d block lỗi cú pháp bị bỏ qua (lenient mode)",
                p,
                len(cur_failed),
            )
            if failed_blocks_out is not None:
                failed_blocks_out.extend(cur_failed)

        for entry in entries:
            key = entry.get("citation_key")
            if key:
                collected[key] = entry

    # 3. Chỉ giữ entry THỰC SỰ được trích dẫn.
    # Nhiều bài đóng gói nguyên một cơ sở dữ liệu bibliography vào source
    # (ví dụ anthology.bib của ACL, ~105.000 entry) rồi chỉ trích vài mục.
    # Đo 26/11 trên dải 2507: 20 bài kiểu này chiếm 74,1% toàn bảng bibtex.
    # Entry không được trích dẫn không phải tham khảo của bài, và ở M3 không
    # bao giờ khớp được với reference nào.
    cited = _collect_cited_keys(vdir)
    if cited is not None:
        kept = {k: v for k, v in collected.items() if k in cited}
        if kept:                            # chốt chặn: không bao giờ trả về rỗng
            n_drop = len(collected) - len(kept)
            if n_drop:
                logger.info("%s: bỏ %d entry không được trích dẫn, giữ %d",
                            vdir, n_drop, len(kept))
            collected = kept

    return list(collected.values())

