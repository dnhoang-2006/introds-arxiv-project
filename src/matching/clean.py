"""clean.py - Làm sạch tiêu đề và tên tác giả

Dùng CÙNG các hàm này cho cả hai phía, nếu không hai bên không bao giờ khớp:
  - bibtex (parsed/<pub>/bibtex.jsonl): ``clean_bibtex_entry(entry)``
  - references (corpus/<pub>/references.json): ``clean_reference_row(row)``

Quy tắc:
  1. Bỏ lệnh LaTeX: ``\\emph{x}`` -> ``x``; bỏ hẳn nội dung ``\\footnote``, ``\\cite``...;
     ``{}`` và ``~`` bị bỏ; ``{\\"u}`` -> ``ü``; ``$\\alpha$`` và ``α`` -> ``alpha``.
  2. Dấu: ä/ö/ü -> ae/oe/ue, ß -> ss, ø -> o, ł -> l...; dấu còn lại bỏ bằng NFKD.
  3. Chữ thường, bỏ dấu câu, gộp khoảng trắng. Token tiêu đề bỏ stop-word.
  4. Khoá tác giả = "họ + chữ cái đầu của tên": ``Vaswani, A.`` = ``A. Vaswani`` = ``vaswani a``.

Giới hạn đã biết: tên viết họ trước mà không có dấu phẩy (``Nguyen Van An``,
``Zhang Wei``) bị hiểu theo thứ tự phương Tây; tên không có chữ Latin (``张伟``) bị bỏ.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from typing import Any, NamedTuple

# ============================================================ LaTeX
# Dấu: \"u, {\"u}, \"{u}, \'e, \c{c}, \v{s}, \H{o}...
_ACCENT_MARK = {
    '"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303",
    "=": "\u0304", ".": "\u0307", "c": "\u0327", "v": "\u030c", "H": "\u030b",
    "u": "\u0306", "k": "\u0328", "r": "\u030a",
}
_ACCENT_RE = re.compile(
    r"\{?\\([\"'`^~=.]|[cvHukr](?![A-Za-z]))\s*\{?\s*\\?([A-Za-z])\s*\}?\}?"
)
# Ký tự đặc biệt: \ss, \o, \ae, \l, \i...
_SPECIAL_CHAR = {
    r"\ss": "ß", r"\o": "ø", r"\O": "Ø", r"\ae": "æ", r"\AE": "Æ", r"\oe": "œ",
    r"\OE": "Œ", r"\aa": "å", r"\AA": "Å", r"\l": "ł", r"\L": "Ł", r"\i": "i",
    r"\j": "j", r"\&": "&",
}
_SPECIAL_RE = re.compile(
    r"\{?("
    + "|".join(re.escape(k) for k in sorted(_SPECIAL_CHAR, key=len, reverse=True))
    + r")(?![A-Za-z])\}?"
)
_GREEK = (
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho",
    "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
)
_GREEK_CMD_RE = re.compile(r"\\(var)?(" + "|".join(_GREEK) + r")(?![A-Za-z])", re.IGNORECASE)
_GREEK_UNICODE = {
    chr(cp): name
    for base in (0x3B1, 0x391)  # chữ thường, chữ hoa
    # 25 mã liên tiếp; vị trí thứ 18 là ς (sigma cuối từ) nên chèn thêm "sigma"
    for cp, name in zip(range(base, base + 25), (*_GREEK[:17], "sigma", *_GREEK[17:]))
}
# Lệnh mà nội dung KHÔNG thuộc tiêu đề -> bỏ cả đối số
_DROP_CMD_RE = re.compile(
    r"\\(?:footnote|thanks|cite[a-z]*|label|ref|url|href)\*?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}"
)
_MATH_RE = re.compile(r"\$([^$]*)\$")
_CMD_WITH_ARG_RE = re.compile(r"\\[A-Za-z]+\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_BARE_CMD_RE = re.compile(r"\\[A-Za-z]+\*?")
_SYMBOL_CMD_RE = re.compile(r"\\[^A-Za-z\s]")
_MAX_NESTING = 5


def _apply_accent(m: re.Match) -> str:
    return unicodedata.normalize("NFC", m.group(2) + _ACCENT_MARK[m.group(1)])


def strip_latex(s: str | None) -> str:
    """Bỏ lệnh LaTeX, giữ chữ. ``\\emph{Deep} nets~\\cite{x}`` -> ``Deep nets ``."""
    if not s:
        return ""
    s = _ACCENT_RE.sub(_apply_accent, s)
    s = _SPECIAL_RE.sub(lambda m: _SPECIAL_CHAR[m.group(1)], s)
    s = _GREEK_CMD_RE.sub(lambda m: f" {m.group(2).lower()} ", s)
    s = _DROP_CMD_RE.sub(" ", s)
    s = _MATH_RE.sub(r" \1 ", s)
    for _ in range(_MAX_NESTING):  # lệnh lồng nhau: \textbf{\emph{x}}
        unwrapped = _CMD_WITH_ARG_RE.sub(r"\1", s)
        if unwrapped == s:
            break
        s = unwrapped
    s = _BARE_CMD_RE.sub(" ", s)
    s = _SYMBOL_CMD_RE.sub(" ", s)
    return s.replace("~", " ").replace("{", "").replace("}", "")


# ============================================================ dấu
_FOLD = {
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe",
    "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "þ": "th",
}


def fold_accents(s: str) -> str:
    """``Müller`` -> ``Mueller``, ``Gödel`` -> ``Goedel``, ``é`` -> ``e``, ``α`` -> `` alpha ``."""
    s = unicodedata.normalize("NFC", s)
    s = "".join(_FOLD.get(ch) or (f" {_GREEK_UNICODE[ch]} " if ch in _GREEK_UNICODE else ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)  # NFKD cũng tách ligature: ﬁ -> fi
    return "".join(ch for ch in s if not unicodedata.combining(ch))


# ============================================================ tiêu đề
STOPWORDS = frozenset([
    "a", "an", "the", "and", "or", "of", "for", "in", "on", "at", "to", "by",
    "with", "from", "via", "into", "onto", "as", "is", "are", "be", "its", "it",
    "this", "that", "these", "those", "we", "our", "using", "use", "based",
    "towards", "toward", "than",
])
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_text(s: str | None) -> str:
    """Bỏ LaTeX, bỏ dấu, chữ thường, bỏ dấu câu, gộp khoảng trắng."""
    if not s:
        return ""
    s = fold_accents(strip_latex(s)).lower()
    return _NON_ALNUM_RE.sub(" ", s).strip()


def clean_title(title: str | None) -> str:
    return normalize_text(title)


def title_tokens(title: str | None) -> list[str]:
    """Token tiêu đề dùng để so khớp, đã bỏ stop-word."""
    return [t for t in clean_title(title).split() if t not in STOPWORDS]


# ============================================================ tác giả
_PARTICLES = frozenset({
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "du", "la",
    "le", "dos", "das", "ter", "ten", "bin", "al", "el",
})
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})
_NOT_A_PERSON = frozenset({"others", "et al", "et al."})
_BIBTEX_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)


class Author(NamedTuple):
    last: str      # "van der waals"
    initials: str  # "jd"

    @property
    def key(self) -> str:
        """Khoá so khớp: họ + chữ cái đầu tiên của tên, vd ``vaswani a``."""
        return f"{self.last} {self.initials[:1]}".strip()


def _is_suffix(word: str) -> bool:
    return word.lower().strip(". ") in _SUFFIXES


def _split_first_last(name: str) -> tuple[str, str]:
    """Tách (tên, họ) cho cả dạng ``Họ, Tên`` lẫn ``Tên Họ``."""
    if "," in name:  # "Last, First" | "Last, Jr., First" | "Last, First, Jr."
        parts = [p.strip() for p in name.split(",") if p.strip() and not _is_suffix(p)]
        return (parts[1] if len(parts) > 1 else ""), parts[0]

    words = [w for w in name.split() if not _is_suffix(w)]
    if len(words) <= 1:
        return "", " ".join(words)
    # Họ bắt đầu từ particle viết thường đầu tiên: "Johannes van der Waals"
    start = len(words) - 1
    while start > 0 and words[start - 1][0].islower() and words[start - 1].lower() in _PARTICLES:
        start -= 1
    return " ".join(words[:start]), " ".join(words[start:])


@lru_cache(maxsize=200_000)  # tên tác giả lặp lại rất nhiều giữa 1,3 triệu entry
def parse_author(name: str | None) -> Author | None:
    """``Vaswani, A.`` / ``A. Vaswani`` / ``Ashish Vaswani`` -> ``Author('vaswani', 'a')``."""
    if not name:
        return None
    name = name.strip()
    if name.startswith("{") and name.endswith("}") and name.count("{") == 1:
        # BibTeX: {Google Research} là tên tổ chức, không tách họ/tên
        return Author(normalize_text(name), "") if normalize_text(name) else None
    raw = fold_accents(strip_latex(name)).strip()
    if not raw or raw.lower() in _NOT_A_PERSON:
        return None

    first, last = _split_first_last(raw)
    last = normalize_text(last)
    if not last:
        return None
    first = normalize_text(first.replace(".", " ").replace("-", " "))
    return Author(last, "".join(w[0] for w in first.split()))


def split_bibtex_authors(field: str | None) -> list[str]:
    """Trường author của BibTeX: ``A and B and others`` -> ``['A', 'B']``."""
    if not field:
        return []
    names = (p.strip() for p in _BIBTEX_AND_RE.split(field.replace("\n", " ")))
    return [n for n in names if n and n.lower() not in _NOT_A_PERSON]


def _as_name_list(authors: str | Iterable[str] | None) -> list[str]:
    if authors is None:
        return []
    if isinstance(authors, str):
        return split_bibtex_authors(authors)
    return [a for a in authors if isinstance(a, str)]


def parse_authors(authors: str | Iterable[str] | None) -> list[Author]:
    """Nhận ``list[str]`` (bibtex.jsonl, references.json) hoặc chuỗi BibTeX."""
    parsed = (parse_author(a) for a in _as_name_list(authors))
    return [a for a in parsed if a is not None]


def author_keys(authors: str | Iterable[str] | None) -> list[str]:
    return [a.key for a in parse_authors(authors)]


def last_names(authors: str | Iterable[str] | None) -> set[str]:
    return {a.last for a in parse_authors(authors)}


# ============================================================ một hàng dữ liệu
def _cleaned_fields(title: str | None, authors: Any) -> dict[str, Any]:
    return {
        "title_clean": clean_title(title),
        "title_tokens": title_tokens(title),
        "author_keys": author_keys(authors),
    }


def clean_bibtex_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Một dòng parsed/<pub>/bibtex.jsonl -> thêm title_clean, title_tokens, author_keys."""
    authors = entry.get("authors") or entry.get("author")  # list, hoặc chuỗi BibTeX gốc
    return {**entry, **_cleaned_fields(entry.get("title"), authors)}


def clean_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    """Một reference trong corpus/<pub>/references.json -> thêm 3 trường như trên."""
    return {**row, **_cleaned_fields(row.get("ref_title"), row.get("ref_authors"))}