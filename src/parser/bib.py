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

from .bib_dedup import _tex_to_unicode

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
# cuối cùng là \emph/\textit vì \emph{} thường dùng cho tên hội nghị/tạp chí.
# KHÔNG dùng \textbf: style vật lý in đậm số volume (`Nucl. Phys. B \textbf{277}`),
# đo 27/11 trên 500 pub dải 24120177 thì tiêu đề bắt từ \textbf hầu hết là số volume.
TITLE_PATS = [
    re.compile(r"``(.+?)''"),
    # `\"` là dấu umlaut, không phải ngoặc kép: `Extremal K\"ahler` từng ra tiêu đề `K\"a`.
    re.compile(r'(?<!\\)"([^"]+?)(?<!\\)"'),
    re.compile(r"\\(?:emph|textit)\{([^}]+)\}"),
]

# REVTeX dùng \bibinfo{title}, ACM (ACM-Reference-Format) dùng \showarticletitle.
_STRUCT_TITLE_PAT = re.compile(r"\\bibinfo\s*\{\s*title\s*\}\s*\{|\\showarticletitle\s*\{", re.IGNORECASE)
# REVTeX ghi từng tác giả trong \bibinfo{author}{...}, ACM trong \bibinfo{person}{...}.
_STRUCT_AUTHOR_PAT = re.compile(r"\\bibinfo\s*\{\s*(?:author|person)\s*\}\s*\{", re.IGNORECASE)
_NEWBLOCK_PAT = re.compile(r"\\newblock\b")
# LNCS: phần tác giả kết thúc bằng chữ cái đầu viết tắt ("Farhood, M.:" / "Garoche, P.L.:").
_LNCS_PAT = re.compile(
    r"(?P<authors>[^:]{2,400}?\b[A-Z](?:\.-?[A-Z])*\.)\s*:\s+(?P<title>[^:]+?)\.\s+(?=In:|[A-Z(]|\d|$)"
)


def _balanced_close(raw: str, start: int) -> int:
    """Vị trí `}` đóng ngoặc mở ngay trước `start`, bỏ qua ký tự sau `\\`; -1 nếu không có."""
    depth, i, n = 1, start, len(raw)
    while i < n:
        c = raw[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_bibinfo_title_span(raw: str) -> tuple[str, int, int] | None:
    """Trích xuất tiêu đề từ \\bibinfo{title}{...} hoặc \\showarticletitle{...}, cân bằng ngoặc nhọn.

    Hỗ trợ độ lồng ngoặc không giới hạn (như {\\textendash}, {\\ensuremath{\\alpha}}, v.v.),
    tránh giới hạn của regex tĩnh khi gặp macro lồng sâu bên trong tiêu đề.
    Trả về (nội dung tiêu đề thô, vị trí bắt đầu, vị trí kết thúc) hoặc None.
    """
    m = _STRUCT_TITLE_PAT.search(raw)
    if not m:
        return None
    end = _balanced_close(raw, m.end())
    return (raw[m.end():end], m.start(), end) if end != -1 else None


class _SpanMatch:
    """Giả lập re.Match chỉ có .start(), để _extract_authors biết phần tác giả dừng ở đâu."""

    def __init__(self, start_pos: int):
        self._start = start_pos

    def start(self) -> int:
        return self._start


def _structured_authors(raw: str) -> list[str]:
    """Nội dung thô của mọi \\bibinfo{author|person}{...} theo thứ tự xuất hiện."""
    out = []
    for m in _STRUCT_AUTHOR_PAT.finditer(raw):
        end = _balanced_close(raw, m.end())
        if end != -1:
            out.append(raw[m.end():end])
    return out


# Lệnh định dạng chỉ bọc nội dung, phải GỠ trước khi xoá ngoặc nhọn.
# Nếu xoá ngoặc trước thì \\text{Hermitian} thành \\textHermitian, rồi
# bib_dedup.py (dòng 110, 123, 348) xoá nguyên cụm \\[a-zA-Z]+ -> mất chữ.
# Đo 26/11: 1.637/1.692.998 title dính lỗi này (0,097%), chủ yếu \\mathrm trong công thức.
_UNWRAP_CMD = (
    "text|textrm|textbf|textit|texttt|textsc|textsf|textnormal|textup|"
    "emph|mathrm|mathbf|mathit|mathsf|mathtt|mathcal|mbox|hbox|"
    "ensuremath|boldsymbol|bm|uppercase|lowercase|"
    "bibnamefont|bibfnamefont|citenamefont|bibsc|enquote"
)
_UNWRAP_PAT = re.compile(r"\\(?:" + _UNWRAP_CMD + r")\s*\{([^{}]*)\}")

# APS ghi dấu bằng `\ifmmode \check{c}\else \v{c}\fi{}`: giữ nhánh \else (dạng văn bản).
# Không xử lý thì `Skvar\ifmmode~\check{c}\else \v{c}\fi{}` ra `Skvar č` (đo 27/11: 287 tên).
_IFMMODE_PAT = re.compile(r"\\ifmmode\b.*?\\else\b\s*(.*?)\s*\\fi\b(?:\{\})?", re.DOTALL)
# Lệnh REVTeX không mang nội dung: \BibitemOpen, \BibitemShut{NoStop}, \href@noop{}, \natexlab{a}.
_REVTEX_NOISE_PAT = re.compile(
    r"\\BibitemOpen\b|\\BibitemShut\s*\{[^{}]*\}|\\href@noop\s*\{\s*\}|\\natexlab\s*\{[^{}]*\}"
    # nhãn trường REVTeX/ACM: `\bibinfo{howpublished}{X}` -> X, `\bibfield{journal}{X}` -> X
    r"|\\bibinfo\s*\{\s*\w+\s*\}|\\bibfield\s*\{\s*\w+\s*\}"
)
# Khoảng trắng TeX: `\ ` (control space), `\,` `\;` `\!` `\/`. REVTeX chèn `\ ` giữa chữ cái
# đầu và họ (`W.~J.\ Percival`); để lại thì `\` dính vào tên (đo 27/11: ~33.000 tên).
_CTRL_SPACE_PAT = re.compile(r"\\[ ,;!/]")
# Khai báo định dạng không có đối số (`{\em Title}`, `{\bf 55}`): chỉ đổi kiểu chữ, bỏ đi.
_FONT_DECL_PAT = re.compile(
    r"\\(?:em|it|bf|rm|sc|sf|tt|sl|normalfont|itshape|bfseries|scshape|upshape|mdseries|"
    r"tiny|scriptsize|footnotesize|small|normalsize|large|Large)\b\s*"
)
# Liên kết lọt vào tiêu đề/tác giả ở .bbl: `\href{url}{X}` giữ X, `\doi{...}`/`\url{...}` bỏ hẳn.
_LINK_PAT = re.compile(r"\\href\s*\{[^{}]*\}|\\(?:doi|url|urlprefix|doibase|Eprint)\b\s*(?:\{[^{}]*\})?")
# Ký tự thoát: `\&` -> `&`, `\%` -> `%`, `\_` -> `_`, `\#` -> `#`, `\$` -> `$`.
_ESCAPED_CHAR_PAT = re.compile(r"\\([&%_#$])")


def _clean_bib_text(val: str | None) -> str | None:
    if not val:
        return None
    # Đổi dấu TeX sang Unicode khi ngoặc còn nguyên. Xoá ngoặc trước thì `\v{c}` thành
    # `\vc`, chốt (?![a-zA-Z]) của bib_dedup._ACC_CMD (chặn `\bibnamefont`) không nhận
    # ra dấu nữa và bước xoá `\\[a-zA-Z]+` cắt luôn tên: `Veli{\v{c}}kovi{\'c}` -> `Veli ć`.
    # Đo 27/11 trên 500 pub dải 24120177: 3.518/114.598 trường author .bib bị đổi.
    cleaned = _IFMMODE_PAT.sub(r"\1", val)
    cleaned = _REVTEX_NOISE_PAT.sub(" ", cleaned)
    cleaned = _tex_to_unicode(cleaned)
    for _ in range(4):                      # lệnh có thể lồng vài lớp
        new = _UNWRAP_PAT.sub(r"\1", cleaned)
        if new == cleaned:
            break
        cleaned = new
    cleaned = _CTRL_SPACE_PAT.sub(" ", cleaned)
    cleaned = _FONT_DECL_PAT.sub("", cleaned)
    cleaned = _LINK_PAT.sub(" ", cleaned)
    cleaned = _ESCAPED_CHAR_PAT.sub(r"\1", cleaned)
    cleaned = re.sub(r"[{}]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _fields_lower(e: Any) -> dict[str, Any]:
    """Trường của entry theo tên viết thường. Tên trường BibTeX không phân biệt hoa thường:
    BibDesk/Papers ghi `Author = {...}`, `Title = {...}`. Tra `fields_dict` trần thì mọi trường
    ra None, và entry rỗng từ .bib còn ghi đè entry đầy đủ bóc từ .bbl (đo 27/11: 2503.12256)."""
    return {k.lower(): v for k, v in e.fields_dict.items()}


def _find_arxiv(fields: dict[str, Any]) -> str | None:
    """Tìm arXiv ID rải rác trong các trường của entry BibTeX (M3 matching pool)."""
    # 1. Ưu tiên trường eprint (có thể có hoặc không có tiền tố arXiv:)
    fld_eprint = fields.get("eprint")
    if fld_eprint:
        val = str(fld_eprint.value).strip()
        m_eprint = re.search(r"(?:arXiv[:\s]*)?(\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?", val, re.IGNORECASE)
        if m_eprint:
            return m_eprint.group(1)

    # 2. Tìm trong các trường khác (cần có tiền tố arXiv: hoặc abs/)
    for name in ("doi", "url", "journal", "note", "volume"):
        fld = fields.get(name)
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

        fields = _fields_lower(e)

        def f(name: str) -> str | None:
            fld = fields.get(name)
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
        arxiv_id = _find_arxiv(fields)

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
    # rstrip(".") ở trên ăn luôn dấu chấm của chữ viết tắt cuối ("Farhood, M." -> "Farhood, M");
    # trả lại nếu ngay trước là một chữ cái hoa đứng riêng.
    if re.search(r"(?:^|[\s,.~-])[A-Z]$", prefix) and clean_raw[len(prefix):len(prefix) + 1] == ".":
        prefix += "."

    # Làm sạch các macro LaTeX thường gặp trong \\bibitem như \\bibinfo{author}, \\newblock
    prefix = re.sub(r"\\newblock\s*", " ", prefix)
    prefix = re.sub(r"\\bibinfo\s*\{author\}\s*", " ", prefix)
    # REVTeX: `\bibfield author` — nhãn `author` KHÔNG nằm trong ngoặc nên phải
    # xoá cả cụm, nếu không chữ "author" ở lại và thành một tác giả giả.
    prefix = re.sub(r"\\bibfield\s*\{?\s*author\s*\}?\s*", " ", prefix)

    # Tách theo 'and' hoặc '&' (kể cả dạng LaTeX '\&') trước nếu có
    if re.search(r"\band\b|\\?&", prefix, re.IGNORECASE):
        chunks = [c.strip() for c in re.split(r",?\s*(?:\band\b|\\?&)\s*", prefix, flags=re.IGNORECASE) if c.strip()]
    else:
        chunks = [prefix]

    raw_authors: list[str] = []
    for chunk in chunks:
        raw_authors.extend(_split_author_chunk(chunk))

    return _tidy_authors(raw_authors)


_ET_AL_ONLY_PAT = re.compile(r"[\W_]*et[\s~.]*al[\W_]*", re.IGNORECASE)
_TRAILING_YEAR_PAT = re.compile(r"\s*\(\s*(?:19|20)\d{2}[a-z]?\s*\)\s*\.?$")
_HAS_NAME_PAT = re.compile(r"[^\W\d_]{2,}|[^\W\d_]\.")


def _tidy_authors(raw_authors: list[str]) -> list[str] | None:
    """Làm sạch từng tên và bỏ phần không phải tên người.

    - Giữ `et al` (hợp đồng có test), nhưng gộp các biến thể `et al.\\`, `\\ et al.`, `et al. (`.
    - Bỏ đuôi năm kiểu tác giả-năm: `Abbeel, P. (2020)` -> `Abbeel, P.`
    - Bỏ mảnh không có chữ (`\\`, `. , .`, `(`) và rác REVTeX (`title`, `@noop`, URL).
    """
    authors = []
    for p in raw_authors:
        cleaned = _clean_bib_text(p)
        if not cleaned:
            continue
        cleaned = cleaned.replace("~", " ")
        cleaned = re.sub(r"\\[a-zA-Z]+\s*", " ", cleaned)        # lệnh còn sót (`\bibnamefont`)
        cleaned = re.sub(r"\\", " ", cleaned)                     # `\` lẻ còn sót
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;")
        cleaned = re.sub(r"^and\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = _TRAILING_YEAR_PAT.sub("", cleaned).strip(" ,;")
        if _ET_AL_ONLY_PAT.fullmatch(cleaned):
            authors.append("et al")
            continue
        if (
            cleaned.lower() in ("in", "by", "title")
            or "@noop" in cleaned
            or re.search(r"https?:|doi\.org", cleaned, re.IGNORECASE)
            or not _HAS_NAME_PAT.search(cleaned)
        ):
            continue
        authors.append(cleaned)
    return authors or None


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
    newblocks = [s.strip() for s in _NEWBLOCK_PAT.split(clean_raw)]

    # 1. Ưu tiên bóc tách cân bằng ngoặc cho \bibinfo{title}{...} (REVTeX/APS) và
    #    \showarticletitle{...} (ACM), hỗ trợ lồng ngoặc sâu
    res_bibinfo = _extract_bibinfo_title_span(clean_raw)
    if res_bibinfo:
        raw_title, t_start, _ = res_bibinfo
        title = _clean_bib_text(raw_title)
        title_match = _SpanMatch(t_start)
    elif len(newblocks) >= 2 and newblocks[0]:
        # 2. natbib (plainnat, abbrvnat, ieee_fullname...): "Tác giả. \newblock Tiêu đề. \newblock Nơi đăng".
        #    Trường thứ hai là tiêu đề; \emph ở trường thứ ba là tên hội nghị, không phải tiêu đề.
        #    Đo 27/11 trên 500 pub dải 24120177: 3.826/8.172 entry kiểu này không ra tiêu đề.
        seg = newblocks[1]
        m = TITLE_PATS[0].search(seg) or TITLE_PATS[1].search(seg)
        title = _clean_bib_text(m.group(1) if m else seg)
        title_match = _SpanMatch(_NEWBLOCK_PAT.search(clean_raw).start())
    elif (m_lncs := _LNCS_PAT.match(clean_raw)) and not TITLE_PATS[0].search(clean_raw):
        # 3. LNCS (splncs04): "Họ, A., Họ, B.: Tiêu đề. In: Hội nghị ...". Chỉ nhận khi trước
        #    dấu ':' là chữ cái đầu viết tắt, để không nhầm với tiêu đề có dấu ':'.
        title = _clean_bib_text(m_lncs.group("title"))
        title_match = _SpanMatch(m_lncs.end("authors"))
    else:
        # 4. Thử các pattern regex fallback. \emph/\textit lấy theo ngoặc cân bằng:
        #    `\textit{Generalized almost-K\"{a}hler}` với [^}]+ chỉ ra `Generalized almost-K\"a`.
        for pat in TITLE_PATS:
            m = pat.search(clean_raw)
            if not m:
                continue
            body = m.group(1)
            if pat is TITLE_PATS[2]:
                open_end = clean_raw.index("{", m.start()) + 1
                close = _balanced_close(clean_raw, open_end)
                if close != -1:
                    body = clean_raw[open_end:close]
            title = _clean_bib_text(body)
            title_match = m
            break
    if title:
        title = title.rstrip(" ,.") or None
    # "\newblock et al." hay "\newblock {\scriptsize\url{...}}" không phải tiêu đề.
    if title and (_ET_AL_ONLY_PAT.fullmatch(title) or not _HAS_NAME_PAT.search(re.sub(r"\\[a-zA-Z]+", "", title))):
        title = None

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

    # Authors -> list[str]. REVTeX/ACM ghi sẵn từng tác giả trong \bibinfo{author|person}{...}:
    # lấy thẳng, không đoán theo dấu phẩy/'and' (cách đó sinh `\`, `\ title`, URL thành tác giả).
    # Entry REVTeX không có trường author (vd. chỉ có \bibinfo{note}) thì không có tác giả,
    # đừng đoán: đoán sẽ biến câu ghi chú thành tên tác giả.
    structured = _structured_authors(clean_raw)
    if structured:
        authors = _tidy_authors(structured)
    elif re.search(r"\\bibinfo\s*\{", clean_raw):
        authors = None
    else:
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
                # .bib thắng, nhưng trường nào .bib để trống thì giữ giá trị đã bóc từ
                # \bibitem/.bbl thay vì xoá mất (vd. @misc chỉ có `note`).
                prev = collected.get(key) or {}
                for k, v in prev.items():
                    if k != "raw" and v not in (None, "", []) and entry.get(k) in (None, "", []):
                        entry[k] = v
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

