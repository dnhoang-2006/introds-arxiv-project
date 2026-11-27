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


#: Như _FOLD nhưng BỎ ä/ö/ü để NFKD hạ thẳng về a/o/u. Dùng cho khoá phụ.
_FOLD_ALT = {k: v for k, v in _FOLD.items() if k not in "äöüÄÖÜ"}

# Semantic Scholar đôi khi ghi dấu sắc bằng nháy đơn trần: "Cr'epel" = "Crépel".
# Chỉ sửa khi nháy đứng trước chữ THƯỜNG. Nháy trước chữ HOA phần lớn là nháy thật
# (O'Brien, D'Agostino) và hai phía vốn đã ghi giống nhau nên không cần đụng.
# Đo 27/11: 3.891 chuỗi dạng nháy+thường, 2.935 chuỗi dạng nháy+hoa.
_QUOTE_ACCENT_RE = re.compile(r"['’ʼ](?=[a-z])")


def _fold(s: str, table: dict[str, str]) -> str:
    s = unicodedata.normalize("NFC", s)
    s = "".join(table.get(ch) or (f" {_GREEK_UNICODE[ch]} " if ch in _GREEK_UNICODE else ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)  # NFKD cũng tách ligature: ﬁ -> fi
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def fold_accents(s: str) -> str:
    """``Müller`` -> ``Mueller``, ``Gödel`` -> ``Goedel``, ``é`` -> ``e``, ``α`` -> `` alpha ``."""
    return _fold(s, _FOLD)


def strip_accents(s: str) -> str:
    """Như ``fold_accents`` nhưng ``Müller`` -> ``Muller``, dùng cho khoá phụ.

    Cần cả hai dạng vì hai nguồn ghi khác nhau: BibTeX giữ ``Blümlein`` (fold ra
    ``bluemlein``) còn Semantic Scholar ghi sẵn ``Blumlein`` (ra ``blumlein``).
    Đo 27/11 trên 217.892 khoá tác giả S2: fold khớp 2.329 tên, chỉ-bỏ-dấu khớp
    338 tên. Fold thắng gấp 7 lần nên nó vẫn là khoá chính; đây chỉ là khoá phụ.
    """
    return _fold(s, _FOLD_ALT)


# ============================================================ tiêu đề
STOPWORDS = frozenset([
    "a", "an", "the", "and", "or", "of", "for", "in", "on", "at", "to", "by",
    "with", "from", "via", "into", "onto", "as", "is", "are", "be", "its", "it",
    "this", "that", "these", "those", "we", "our", "using", "use", "based",
    "towards", "toward", "than",
])
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize(s: str | None, *, fold: bool = True) -> str:
    if not s:
        return ""
    # KHÔNG sửa nháy-thành-dấu ở đây: hàm này chạy cho cả tiêu đề, mà nháy trong
    # tiêu đề hầu hết là sở hữu cách ("survey's"). Việc sửa nháy chỉ làm ở
    # _author_raw, tức chỉ cho tên tác giả.
    s = (fold_accents if fold else strip_accents)(strip_latex(s)).lower()
    return _NON_ALNUM_RE.sub(" ", s).strip()


def normalize_text(s: str | None) -> str:
    """Bỏ LaTeX, bỏ dấu, chữ thường, bỏ dấu câu, gộp khoảng trắng."""
    return _normalize(s)


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

# "P. Moskal et al." -> nếu không cắt đuôi thì họ thành "al". _NOT_A_PERSON chỉ bắt
# được khi CẢ chuỗi đúng bằng "et al". Đo 27/11: 8.081/1.390.019 chuỗi tác giả
# BibTeX (0,581%) dính, phía Semantic Scholar chỉ có 2 chuỗi.
_ET_AL_RE = re.compile(r"[\s,]*\bet\.?\s*al\.?\s*$", re.I)


class Author(NamedTuple):
    last: str              # "van der waals"
    initials: str          # "jd"
    last_alt: str = ""     # họ theo kiểu bỏ dấu ("blumlein"); "" nếu trùng `last`

    @property
    def key(self) -> str:
        """Khoá so khớp: họ + chữ cái đầu tiên của tên, vd ``vaswani a``."""
        return f"{self.last} {self.initials[:1]}".strip()

    @property
    def alt_key(self) -> str:
        """Khoá phụ, dùng khi hai nguồn ghi dấu khác nhau (``Blümlein``/``Blumlein``)."""
        return f"{self.last_alt or self.last} {self.initials[:1]}".strip()

    @property
    def keys(self) -> frozenset[str]:
        return frozenset({self.key, self.alt_key})

    @property
    def surnames(self) -> frozenset[str]:
        """Họ ở cả hai dạng dấu, không kèm chữ đầu tên."""
        return frozenset({self.last, self.last_alt or self.last})

    def _surname_agrees(self, other: "Author") -> bool:
        """Họ trùng, hoặc họ ngắn hơn là ĐUÔI TRỌN TỪ của họ dài hơn.

        Vế sau xử lý tiền tố tách lệch giữa hai nguồn: ``G. Di Giulio`` ra họ
        ``giulio`` còn ``Di Giulio, Giuseppe`` ra ``di giulio``; ``S. von
        Buddenbrock`` ra ``von buddenbrock`` còn BibTeX ghi ``Buddenbrock,
        Stefan``. Hữu Duy đo 27/11: bỏ qua là mất 77 cặp.

        KHÔNG sửa bằng cách cho ``_split_first_last`` coi ``Di``/``Le`` viết hoa
        là tiền tố — ``Le Wang`` (tên Trung Quốc, ``Le`` là tên riêng) sẽ hỏng.
        """
        for a in self.surnames:
            for b in other.surnames:
                if a == b:
                    return True
                if a.endswith(f" {b}") and not _all_generic(b):
                    return True
                if b.endswith(f" {a}") and not _all_generic(a):
                    return True
        return False

    def _org_words(self) -> list[str] | None:
        """Dãy từ để so tên tổ chức, hoặc None nếu tên này không giống tổ chức.

        Cùng một tổ chức có thể tới từ hai nguồn ở hai dạng rất khác nhau:

            "ATLAS Collaboration"   -> giữ nguyên cụm  -> ['atlas', 'collaboration']
            "A. Collaboration"      -> giữ nguyên cụm  -> ['a', 'collaboration']
            "Collaboration, ATLAS"  -> bị tách họ/tên  -> ['a', 'collaboration']
            "Team, Gemini"          -> bị tách họ/tên  -> ['g', 'team']

        Quy về cùng một dãy từ rồi so từng từ, cho phép một chữ cái khớp với từ
        đầy đủ. Nhờ vậy `A. Collaboration` gặp `ATLAS Collaboration` nhưng
        `CMS Collaboration` thì không. Hữu Duy chỉ ra 27/11: thiếu nhánh này thì
        riêng dải 24120177 đã mất 10 cặp đúng, và dạng `Team, Gemini` có 132 tên.
        """
        words = self.last.split()
        if not self.initials and len(words) > 1 and words[-1] in _ORG_TAIL_WORDS:
            return words
        if self.initials and _all_generic(self.last):
            return [*self.initials, *words]
        return None

    @staticmethod
    def _word_agrees(a: str, b: str) -> bool:
        """Hai từ trùng, hoặc một bên là chữ cái đầu viết tắt của bên kia."""
        return a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))

    def _org_agrees(self, other: "Author") -> bool:
        x, y = self._org_words(), other._org_words()
        if x is None or y is None or len(x) != len(y):
            return False
        return all(self._word_agrees(p, q) for p, q in zip(x, y))

    def matches(self, other: "Author") -> bool:
        """Hai tên có thể là cùng một người không.

        Thiên về **bắt sót hơn là bắt nhầm**, vì theo `docs/schema_m3.md` mục 5
        tác giả chỉ dùng để LỌC ỨNG VIÊN, còn nhãn do độ giống tiêu đề quyết định.
        Chặt tay ở đây là mất cặp thật mà không được gì.

        Một bên thiếu chữ đầu tên thì chỉ so họ: ``He`` cho khoá ``he`` còn
        ``Kaiming He`` cho ``he k``, entry bóc từ `.bbl` rất hay chỉ ghi họ.
        Hữu Duy đo 27/11: bỏ qua là mất 52 cặp.
        """
        if self._org_agrees(other):
            return True
        if not self._surname_agrees(other):
            return False
        if not self.initials or not other.initials:
            return True
        return self.initials[0] == other.initials[0]


#: Từ chung kết thúc tên tổ chức. Dùng cho hai việc, cùng một lý do:
#:   1. ``_is_org_name``: "ATLAS Collaboration" là tổ chức, giữ nguyên cả cụm chứ
#:      không tách họ/tên, để nó gặp được ``{ATLAS Collaboration}`` phía BibTeX.
#:   2. ``_surname_agrees``: luật "họ là đuôi của nhau" không được nổ khi phần đuôi
#:      chỉ toàn từ chung — nếu không ``{ATLAS Collaboration}`` sẽ khớp
#:      ``CMS Collaboration`` và ``{Google Research}`` khớp ``Microsoft Research``.
#: Chính cặp ATLAS này là ví dụ mà schema_m3 mục 9 dùng để giải thích vì sao bỏ
#: luật "họ tác giả đầu + năm". Hữu Duy chỉ ra 27/11.
_ORG_TAIL_WORDS = frozenset({
    "collaboration", "collaborations", "consortium", "research", "group",
    "team", "project", "experiment", "committee",
})


def _is_org_name(raw: str) -> bool:
    """Tên kết thúc bằng từ chung chỉ tổ chức, và có từ hai từ trở lên."""
    words = _normalize(raw).split()
    return len(words) > 1 and words[-1] in _ORG_TAIL_WORDS


def _all_generic(surname: str) -> bool:
    """Họ chỉ gồm toàn từ chung — không đủ để kết luận cùng một tổ chức."""
    words = surname.split()
    return bool(words) and all(w in _ORG_TAIL_WORDS for w in words)


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


def _author_raw(name: str, *, fold: bool) -> str:
    """Chuỗi tên đã bỏ LaTeX, bỏ dấu và cắt đuôi ``et al.``, chưa tách họ/tên.

    ⚠️ THỨ TỰ QUAN TRỌNG: ``_QUOTE_ACCENT_RE`` phải chạy khi chuỗi **còn nguyên
    hoa thường**. Nếu dời nó xuống sau bước ``.lower()`` (nằm trong ``_normalize``)
    thì ``O'Brien`` đã thành ``o'brien``, nháy lúc đó đứng trước chữ thường nên bị
    xoá thành ``obrien`` — đúng cái lỗi mà bản vá muốn tránh. Nhìn regex thì tưởng
    an toàn vì nó "chỉ xoá trước chữ thường", nên chỗ này dễ sai.
    Hữu Duy chỉ ra 27/11. ``test_quote_regex_runs_before_lowercasing`` chặn việc này.
    """
    s = strip_latex(name)
    if fold:
        s = _QUOTE_ACCENT_RE.sub("", s)
    s = (fold_accents if fold else strip_accents)(s).strip()
    return _ET_AL_RE.sub("", s).strip()


@lru_cache(maxsize=200_000)  # tên tác giả lặp lại rất nhiều giữa 1,3 triệu entry
def parse_author(name: str | None) -> Author | None:
    """``Vaswani, A.`` / ``A. Vaswani`` / ``Ashish Vaswani`` -> ``Author('vaswani', 'a')``."""
    if not name:
        return None
    name = name.strip()
    if name.startswith("{") and name.endswith("}") and name.count("{") == 1:
        # BibTeX: {Google Research} là tên tổ chức, không tách họ/tên
        return Author(normalize_text(name), "") if normalize_text(name) else None
    raw = _author_raw(name, fold=True)
    if not raw or raw.lower() in _NOT_A_PERSON:
        return None

    if "," not in raw and _is_org_name(raw):
        # Tên tổ chức KHÔNG có ngoặc nhọn: giữ nguyên cả cụm như nhánh trên.
        # Nếu tách họ/tên thì "ATLAS Collaboration" ra họ `collaboration`, tên
        # `ATLAS` chui vào initials — vừa không gặp được `{ATLAS Collaboration}`
        # của phía BibTeX, vừa gặp nhầm `CMS Collaboration`.
        #
        # Có dấu phẩy thì KHÔNG đi nhánh này: `Zhang, Research` là người tên
        # Research họ Zhang chứ không phải tổ chức `zhang research`. Dạng tổ chức
        # viết kèm phẩy (`Collaboration, ATLAS`) vẫn gặp nhau được nhờ
        # `_org_words` ở dưới. Hữu Duy chỉ ra 27/11.
        whole = _normalize(raw)
        return Author(whole, "") if whole else None

    first, last = _split_first_last(raw)
    last = _normalize(last)
    if not last:
        return None
    first = _normalize(first.replace(".", " ").replace("-", " "))
    initials = "".join(w[0] for w in first.split())

    # Khoá phụ: cùng cách tách họ/tên nhưng bỏ dấu thay vì fold ae/oe/ue.
    raw_alt = _author_raw(name, fold=False)
    last_alt = _normalize(_split_first_last(raw_alt)[1], fold=False) if raw_alt else ""
    return Author(last, initials, last_alt if last_alt and last_alt != last else "")


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


def author_keys_alt(authors: str | Iterable[str] | None) -> list[str]:
    """Khoá phụ, cùng thứ tự với ``author_keys``. So khớp phải nhận cả hai bộ."""
    return [a.alt_key for a in parse_authors(authors)]


def author_key_set(authors: str | Iterable[str] | None) -> frozenset[str]:
    """Hợp của khoá chính và khoá phụ, dạng tập hợp — **dùng cái này để so khớp**.

    ``set(author_keys(x)) & set(author_keys(y))`` là sai: nó bỏ khoá phụ nên
    ``Blümlein`` (``bluemlein j``) không gặp ``Blumlein`` (``blumlein j``), và
    khoá phụ coi như không tồn tại.
    """
    return frozenset().union(*(a.keys for a in parse_authors(authors))) if authors else frozenset()


#: Số tác giả đầu danh sách đem ra so từng cặp trong ``authors_match``. Bài
#: collaboration có hàng nghìn tác giả nên so hết là O(n·m) không chấp nhận được;
#: tác giả đầu danh sách cũng là nhóm phân biệt được nhiều nhất.
_PAIRWISE_LIMIT = 25


def authors_match(
    left: str | Iterable[str] | None,
    right: str | Iterable[str] | None,
) -> bool:
    """Hai danh sách tác giả có chung ít nhất một người không.

    Trùng khoá thì xét hết danh sách; các ca lệch (thiếu chữ đầu tên, tiền tố
    tách lệch) chỉ xét trong ``_PAIRWISE_LIMIT`` tác giả đầu của mỗi bên.
    """
    if author_key_set(left) & author_key_set(right):
        return True
    a = parse_authors(_as_name_list(left)[:_PAIRWISE_LIMIT])
    b = parse_authors(_as_name_list(right)[:_PAIRWISE_LIMIT])
    return any(x.matches(y) for x in a for y in b)


def first_author_matches(
    left: str | Iterable[str] | None,
    right: str | Iterable[str] | None,
) -> bool:
    """Tác giả ĐẦU của hai bên có thể là cùng một người không.

    `docs/schema_m3.md` mục 5: họ tác giả đầu + năm chỉ để **lọc ứng viên**,
    không tự gán nhãn.

    ⚠️ Hàm này vẫn CHẶT HƠN bộ lọc chỉ-so-họ: khi cả hai bên đều có chữ đầu tên
    mà chữ đó khác nhau thì nó trả về False. Hữu Duy đo 27/11: so với bộ lọc
    chỉ-so-họ, sau khi parse lại vẫn chênh khoảng 65 cặp (~0,9%). Nếu cần thiên
    về bắt sót nữa thì so ``parse_author(x).surnames`` trực tiếp.

    Chỉ parse tác giả đầu, không parse cả danh sách — bài collaboration có hàng
    nghìn tên.
    """
    a = parse_authors(_as_name_list(left)[:1])
    b = parse_authors(_as_name_list(right)[:1])
    return bool(a and b and a[0].matches(b[0]))


def last_names(authors: str | Iterable[str] | None) -> set[str]:
    return {a.last for a in parse_authors(authors)}


# ============================================================ một hàng dữ liệu
def _cleaned_fields(title: str | None, authors: Any) -> dict[str, Any]:
    parsed = parse_authors(authors)
    return {
        "title_clean": clean_title(title),
        "title_tokens": title_tokens(title),
        "author_keys": [a.key for a in parsed],
        # Khoá phụ cho trường hợp hai nguồn ghi dấu khác nhau. Khi so khớp tác giả
        # phải nhận cả hai bộ (hoặc dùng Author.matches), không chỉ author_keys.
        "author_keys_alt": [a.alt_key for a in parsed],
    }


def clean_bibtex_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Một dòng parsed/<pub>/bibtex.jsonl -> thêm title_clean, title_tokens, author_keys."""
    authors = entry.get("authors") or entry.get("author")  # list, hoặc chuỗi BibTeX gốc
    return {**entry, **_cleaned_fields(entry.get("title"), authors)}


def clean_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    """Một reference trong corpus/<pub>/references.json -> thêm 3 trường như trên."""
    return {**row, **_cleaned_fields(row.get("ref_title"), row.get("ref_authors"))}