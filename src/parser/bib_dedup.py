"""Khử trùng lặp reference xuyên version: gộp trường và đổi tên \\cite.

Đề yêu cầu ba vế (docs/schema_m2.md mục 5):
    (1) chọn MỘT citation key chuẩn
    (2) đổi tên mọi \\cite{} của các key bị loại sang key đã chọn
    (3) HỢP NHẤT các trường, không được chọn một entry rồi vứt phần còn lại

Ví dụ của đề:
    v1  vaswani2017      title, author, year
    v2  vit_transformer  title, author, doi
    v3  vit_transformer  title, author          (mất year)
    -> một entry, một key, trường = title + author + year + doi
"""

from __future__ import annotations

import re
from typing import Any
import unicodedata
from urllib.parse import urlsplit


def _norm_doi(doi: Any) -> str | None:
    if not doi:
        return None
    d = str(doi).strip().lower()
    d = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    d = d.rstrip(".")
    return d if d else None


def _norm_arxiv(arxiv_id: Any) -> str | None:
    if not arxiv_id:
        return None
    a = str(arxiv_id).strip().lower()
    a = re.sub(r"^arxiv:\s*", "", a, flags=re.IGNORECASE)
    a = re.sub(r"v\d+$", "", a)
    return a if a else None


_SPECIAL_CHAR_MAP = {
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ł": "l", "Ł": "L",
    "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
    "ß": "ss",
}

_TEX_ACCENT_COMBINING = {
    '"': "\u0308",  # diaeresis / umlaut (Gödel)
    "'": "\u0301",  # acute (Poincaré)
    "`": "\u0300",  # grave (Ampère)
    "^": "\u0302",  # circumflex (Fermât)
    "~": "\u0303",  # tilde (Peña)
    "=": "\u0304",  # macron (Tōkyō)
    ".": "\u0307",  # dot above
    "u": "\u0306",  # breve
    "v": "\u030c",  # caron (Čech)
    "H": "\u030b",  # double acute (Erdős)
    "c": "\u0327",  # cedilla (Françoise)
    "d": "\u0323",  # dot below
    "b": "\u0331",  # bar/macron below
    "r": "\u030a",  # ring above
    "k": "\u0328",  # ogonek (Wałęsa)
}

_TEX_SPECIAL_LETTERS = [
    (re.compile(r"\{\\(?:aa)\}|\\aa(?:\{\}|\s+|\b)"), "å"),
    (re.compile(r"\{\\(?:AA)\}|\\AA(?:\{\}|\s+|\b)"), "Å"),
    (re.compile(r"\{\\(?:ae)\}|\\ae(?:\{\}|\s+|\b)"), "æ"),
    (re.compile(r"\{\\(?:AE)\}|\\AE(?:\{\}|\s+|\b)"), "Æ"),
    (re.compile(r"\{\\(?:oe)\}|\\oe(?:\{\}|\s+|\b)"), "œ"),
    (re.compile(r"\{\\(?:OE)\}|\\OE(?:\{\}|\s+|\b)"), "Œ"),
    (re.compile(r"\{\\(?:ss)\}|\\ss(?:\{\}|\s+|\b)"), "ß"),
    (re.compile(r"\{\\(?:o)\}|\\o(?:\{\}|\s+|\b)"), "ø"),
    (re.compile(r"\{\\(?:O)\}|\\O(?:\{\}|\s+|\b)"), "Ø"),
    (re.compile(r"\{\\(?:l)\}|\\l(?:\{\}|\s+|\b)"), "ł"),
    (re.compile(r"\{\\(?:L)\}|\\L(?:\{\}|\s+|\b)"), "Ł"),
    (re.compile(r"\{\\(?:i)\}|\\i(?:\{\}|\s+|\b)"), "ı"),
    (re.compile(r"\{\\(?:j)\}|\\j(?:\{\}|\s+|\b)"), "ȷ"),
]


def _tex_to_unicode(text: str) -> str:
    """Chuyển đổi các macro ký tự và dấu TeX sang dạng Unicode chuẩn (NFC)."""
    s = str(text)
    for pattern, repl in _TEX_SPECIAL_LETTERS:
        s = pattern.sub(repl, s)

    def _repl_accent(match: re.Match) -> str:
        cmd, ch = match.group(1), match.group(2)
        comb = _TEX_ACCENT_COMBINING.get(cmd)
        return ch + comb if comb else ch

    s = re.sub(r"\{\\([\"'^~=.`]|u|v|H|c|d|b|r|k)\s*([a-zA-Z\u0131\u0237])\}", _repl_accent, s)
    s = re.sub(r"\\([\"'^~=.`]|u|v|H|c|d|b|r|k)\s*\{([a-zA-Z\u0131\u0237])\}", _repl_accent, s)
    s = re.sub(r"\\([\"'^~=.`]|u|v|H|c|d|b|r|k)\s*([a-zA-Z\u0131\u0237])", _repl_accent, s)
    s = re.sub(r'\{([\"\'^~=.`])([a-zA-Z\u0131\u0237])\}', _repl_accent, s)
    s = re.sub(r'([\"\'^~=.`])\{([a-zA-Z\u0131\u0237])\}', _repl_accent, s)

    return unicodedata.normalize("NFC", s)


def _strip_tex_accents(text: str) -> str:
    """Quy đổi các lệnh tạo dấu trong TeX và dấu Unicode về chữ cái Latin chuẩn không dấu (ASCII)."""
    s = _tex_to_unicode(text)
    s = s.replace("~", " ")
    s = re.sub(r"\\[a-zA-Z]+\s*", " ", s)
    for ch, repl in _SPECIAL_CHAR_MAP.items():
        if ch in s:
            s = s.replace(ch, repl)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm_title(title: Any) -> str | None:
    if not title:
        return None
    t = str(title).strip()
    t = _strip_tex_accents(t)
    t = t.lower()
    t = re.sub(r"\\[a-zA-Z]+", " ", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if t else None


def _is_initial(w: str) -> bool:
    s = w.strip().rstrip(".,")
    return bool(re.match(r"^[A-Za-z](\.[A-Za-z])*$", s) or len(s) == 1)


_SURNAME_PREFIXES = {
    "van", "von", "de", "del", "della", "der", "den", "da", "di", "du",
    "la", "le", "ter", "ten", "te", "al", "el", "bin", "ibn", "san", "santa",
    "dos", "das", "d", "l",
}


def _extract_surname_from_western_name(words: list[str]) -> str:
    """Trích xuất họ từ danh sách từ theo thứ tự phương Tây 'Given [Particles] Surname'."""
    if not words:
        return ""
    if len(words) == 1:
        return words[0]

    last_idx = len(words) - 1
    start_surname_idx = last_idx
    while start_surname_idx > 0 and words[start_surname_idx - 1].lower().rstrip(".") in _SURNAME_PREFIXES:
        start_surname_idx -= 1

    return " ".join(words[start_surname_idx:])


def _extract_surname_from_chunk(chunk: str) -> str:
    words = chunk.split()
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    if _is_initial(words[-1]):
        # "Smith J." hoặc "van Rossum G." -> họ nằm trước chữ viết tắt
        non_initials = [w for w in words if not _is_initial(w)]
        return _extract_surname_from_western_name(non_initials) if non_initials else words[0]
    if _is_initial(words[0]):
        # "J. Smith" hoặc "A. Vaswani" -> họ là từ cuối hoặc cụm họ có tiền tố
        return _extract_surname_from_western_name(words)
    # Mặc định định dạng phương Tây "First Last" hoặc "First van Last"
    return _extract_surname_from_western_name(words)


def _first_author_last_name(authors: Any) -> str | None:
    if not authors:
        return None
    first_auth: str = ""
    if isinstance(authors, list):
        if not authors:
            return None
        first_auth = str(authors[0]).strip()
    elif isinstance(authors, str):
        # Tách theo 'and', '&', '\&' hoặc ';' trước nếu có
        chunks = [c.strip() for c in re.split(r"\s*(?:\band\b|\\?&|;)\s*", authors.strip(), flags=re.IGNORECASE) if c.strip()]
        first_auth = chunks[0] if chunks else ""
    else:
        first_auth = str(authors).strip()

    if not first_auth:
        return None

    first_auth = _strip_tex_accents(first_auth)
    first_auth = first_auth.replace("~", " ")
    first_auth = re.sub(r"\\[a-zA-Z]+\s*", " ", first_auth)
    # Bỏ ngoặc nhọn TeX và hậu tố "et al."
    first_auth = re.sub(r"[{}]", "", first_auth).strip()
    first_auth = re.sub(r"\s+et\s+al\.?$", "", first_auth, flags=re.IGNORECASE).strip()

    if not first_auth:
        return None

    # Nếu chuỗi có dấu phẩy: có thể là "Last, First", "First Last, First Last, ..." hoặc "Last Initial., Last Initial."
    if "," in first_auth:
        parts = [p.strip() for p in first_auth.split(",") if p.strip()]
        if len(parts) >= 2:
            p0 = parts[0]
            p1 = parts[1]
            words_p0 = p0.split()
            words_p1 = p1.split()

            # Nếu p0 là họ có hạt (ví dụ "van Rossum, Guido Peter"):
            if words_p0 and words_p0[0].lower() in _SURNAME_PREFIXES:
                last_name = p0
            # Nếu p0 chứa cả họ lẫn chữ viết tắt (ví dụ "Smith J." hoặc "J. Smith"):
            elif any(_is_initial(w) for w in words_p0):
                last_name = _extract_surname_from_chunk(p0)
            # Nếu cả p0 và p1 đều là full name (ví dụ "Ashish Vaswani, Noam Shazeer"):
            elif len(words_p0) >= 2 and len(words_p1) >= 2:
                last_name = _extract_surname_from_western_name(words_p0)
            # Nếu p0 là họ dạng "Last, First" (ví dụ "Smith, John", "Vaswani, A.", "van Rossum, Guido Peter"):
            else:
                last_name = p0
        else:
            last_name = _extract_surname_from_chunk(parts[0])
    else:
        last_name = _extract_surname_from_chunk(first_auth)

    last_name = re.sub(r"[^\w-]", "", last_name).lower()
    return last_name if last_name else None


def _clean_author_name(name: str) -> str:
    """Loại bỏ ký tự TeX thừa, dấu ngoặc, chuẩn hoá khoảng trắng cho tên tác giả, giữ nguyên dấu Unicode."""
    n = _tex_to_unicode(name)
    n = n.replace("~", " ")
    n = re.sub(r"\\[a-zA-Z]+\s*", " ", n)
    n = re.sub(r"[{}]", "", n).strip()
    n = re.sub(r"\s+", " ", n)
    return n


def _is_complete_single_name(chunk: str) -> bool:
    """Kiểm tra xem chuỗi có phải là tên hoàn chỉnh (gồm cả họ và tên/chữ viết tắt) hay không."""
    words = chunk.strip().split()
    if len(words) < 2:
        return False
    if _is_initial(words[0]):
        return True
    if _is_initial(words[-1]):
        return True
    if words[0].lower() in _SURNAME_PREFIXES:
        return False
    return True


def _split_authors_str(authors_str: str) -> list[str]:
    """Tách chuỗi tác giả thành danh sách các tác giả."""
    s = authors_str.strip()
    if not s:
        return []
    s = re.sub(r"\s+et\s+al\.?$", "", s, flags=re.IGNORECASE).strip()
    if not s:
        return []

    # 1. Thử tách theo 'and', '&', '\&', ';'
    chunks = [c.strip() for c in re.split(r"\s*(?:\band\b|\\?&|;)\s*", s, flags=re.IGNORECASE) if c.strip()]
    if len(chunks) > 1:
        return [_clean_author_name(c) for c in chunks if _clean_author_name(c)]

    # 2. Nếu không có 'and', kiểm tra dấu phẩy
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) <= 1:
        c = _clean_author_name(s)
        return [c] if c else []

    if len(parts) == 2:
        p0, p1 = parts[0], parts[1]
        if _is_complete_single_name(p0) and _is_complete_single_name(p1):
            return [_clean_author_name(p0), _clean_author_name(p1)]
        return [_clean_author_name(f"{p0}, {p1}")]

    # len(parts) > 2:
    # A. Nếu tất cả các phần tử đều có >= 2 từ (ví dụ "Ashish Vaswani, Noam Shazeer, Niki Parmar")
    if all(len(p.split()) >= 2 for p in parts):
        return [_clean_author_name(p) for p in parts if _clean_author_name(p)]

    # B. Nếu số phần tử là chẵn, kiểm tra xem có phải dạng các cặp "Last, First, Last, First, ..."
    if len(parts) % 2 == 0:
        all_pairs_valid = True
        for i in range(0, len(parts), 2):
            first_name_part = parts[i + 1]
            if len(first_name_part.split()) > 3:
                all_pairs_valid = False
                break
        if all_pairs_valid:
            paired = [f"{parts[i]}, {parts[i+1]}" for i in range(0, len(parts), 2)]
            return [_clean_author_name(p) for p in paired if _clean_author_name(p)]

    return [_clean_author_name(p) for p in parts if _clean_author_name(p)]


def _first_author_raw(authors: Any) -> str | None:
    """Lấy chuỗi biểu diễn của tác giả đầu tiên."""
    if not authors:
        return None
    if isinstance(authors, list):
        if not authors:
            return None
        return str(authors[0]).strip()
    if isinstance(authors, str):
        chunks = _split_authors_str(authors)
        if chunks:
            return chunks[0]
        return authors.strip()
    return str(authors).strip()


def _extract_given_words_from_token(token: str) -> list[str]:
    """Bóc tách các từ tên riêng hoặc chữ cái viết tắt từ một token.

    Hỗ trợ cả dạng viết tắt ghép nhiều chữ cái (ví dụ 'J.P.', 'J.-P.', 'A.B.C.').
    """
    t = token.strip()
    if not t:
        return []
    if "-" in t:
        sub_tokens = [st for st in t.split("-") if st.strip()]
        res: list[str] = []
        for st in sub_tokens:
            res.extend(_extract_given_words_from_token(st))
        return res
    if _is_initial(t):
        letters = re.findall(r"[a-zA-Z]", t)
        return [ch.lower() for ch in letters if ch]
    w_clean = re.sub(r"[^\w]", "", t).lower()
    return [w_clean] if w_clean else []


def _parse_author_components(name: str) -> tuple[str, list[str]]:
    """Bóc tách họ (surname) và danh sách các từ tên riêng (given_words).

    Trả về: (surname_normalized, [given_word_1, given_word_2, ...])
    """
    clean = _strip_tex_accents(name)
    clean = clean.replace("~", " ")
    clean = re.sub(r"\\[a-zA-Z]+\s*", " ", clean)
    clean = re.sub(r"[{}]", "", clean).strip()
    clean = re.sub(r"\s+et\s+al\.?$", "", clean, flags=re.IGNORECASE).strip()
    if not clean:
        return ("", [])

    last_name = _first_author_last_name(clean) or ""

    # Bóc các từ tên riêng (given words)
    given_words: list[str] = []
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 2:
            # Dạng "Last, First Middle" -> given words ở parts[1]
            for w in parts[1].split():
                given_words.extend(_extract_given_words_from_token(w))
    else:
        words = clean.split()
        if len(words) >= 2:
            if _is_initial(words[-1]):
                # Dạng "Smith J. D." hoặc "van Rossum G." -> given words ở cuối
                initials = [w for w in words if _is_initial(w)]
                for w in initials:
                    given_words.extend(_extract_given_words_from_token(w))
            else:
                # Dạng "First Middle [Particles] Last" -> các từ trước phần họ
                last_idx = len(words) - 1
                start_surname_idx = last_idx
                while start_surname_idx > 0 and words[start_surname_idx - 1].lower().rstrip(".") in _SURNAME_PREFIXES:
                    start_surname_idx -= 1
                for w in words[:start_surname_idx]:
                    given_words.extend(_extract_given_words_from_token(w))

    return (last_name, given_words)


def _is_same_author(name1: str, name2: str) -> bool:
    """Kiểm tra xem hai tên tác giả có đồng nhất (chắc chắn cùng một người) hay không.

    Quy tắc an toàn:
    - Bắt buộc cùng họ (surname).
    - Nếu cả hai bên đều không có given words (ví dụ "Einstein" và "Einstein"): trả về True.
    - Nếu một bên chỉ có họ ("Smith") còn bên kia có tên riêng ("John Smith"): trả về False (không suy đoán).
    - So sánh danh sách các từ tên riêng (given words):
      + Số lượng từ tên riêng phải bằng nhau.
      + Với mỗi vị trí:
        * Nếu cả hai là viết tắt: ký tự đầu phải khớp (ví dụ "J." và "J.").
        * Nếu cả hai là tên đầy đủ: phải giống nhau hoàn toàn (ví dụ "John" và "John").
        * Nếu một bên là viết tắt và một bên là tên đầy đủ: trả về False,
          vì "J. Smith" có thể là "John Smith" hoặc "Jane Smith" - không được tự ý coi là đồng nhất
          khi chưa có đối sánh 1-1 duy nhất giữa các entry.
    """
    sur1, given1 = _parse_author_components(name1)
    sur2, given2 = _parse_author_components(name2)

    if not sur1 or not sur2:
        return re.sub(r"[^\w]", "", name1).lower() == re.sub(r"[^\w]", "", name2).lower()

    if sur1 != sur2:
        return False

    if not given1 and not given2:
        return True

    if not given1 or not given2:
        return False

    if len(given1) != len(given2):
        return False

    for w1, w2 in zip(given1, given2):
        is_init1 = len(w1) == 1
        is_init2 = len(w2) == 1

        if is_init1 != is_init2:
            return False
        if is_init1:
            if w1[0] != w2[0]:
                return False
        else:
            if w1 != w2:
                return False

    return True


def _are_authors_compatible(name1: str, name2: str) -> bool:
    """Kiểm tra xem hai tên tác giả có tương thích (có thể là cùng một người) hay không."""
    sur1, given1 = _parse_author_components(name1)
    sur2, given2 = _parse_author_components(name2)

    if not sur1 or not sur2:
        return re.sub(r"[^\w]", "", name1).lower() == re.sub(r"[^\w]", "", name2).lower()

    if sur1 != sur2:
        return False

    if not given1 or not given2:
        return True

    min_len = min(len(given1), len(given2))
    for i in range(min_len):
        w1, w2 = given1[i], given2[i]
        is_init1 = len(w1) == 1
        is_init2 = len(w2) == 1

        if is_init1 or is_init2:
            if w1[0] != w2[0]:
                return False
        else:
            if w1 != w2:
                return False

    return True


def _has_compatible_author(authors_i: set[str], authors_j: set[str]) -> bool:
    """Kiểm tra xem giữa hai tập tác giả có tồn tại ít nhất một cặp tương thích hay không."""
    for a_i in authors_i:
        for a_j in authors_j:
            if _are_authors_compatible(a_i, a_j):
                return True
    return False


def _author_informativeness(name: str) -> int:
    """Đánh giá độ đầy đủ thông tin của tên tác giả để ưu tiên khi hợp nhất."""
    sur, given = _parse_author_components(name)
    n_full_given = sum(1 for w in given if len(w) > 1)
    return n_full_given * 1000 + len(name)


def _authors_positively_match(authors1: list[str], authors2: list[str]) -> bool:
    """Xác định hai danh sách tác giả có bằng chứng cùng người hay không.

    Điều kiện khớp:
    1. Tác giả đầu có tên riêng giống nhau hoàn toàn (ví dụ "John Smith" và "John Smith",
       hoặc cùng viết tắt "J. Smith" và "J. Smith").
    2. Tác giả đầu có ít nhất hai từ tên riêng hoặc viết tắt khớp nhau (ví dụ "J.P. Smith"
       và "John Paul Smith").
    3. Khi tác giả đầu chỉ có một chữ cái viết tắt đối chiếu với tên đầy đủ ("J. Smith"
       và "Jane Smith"): cần ít nhất một đồng tác giả khớp khẳng định (ví dụ cùng có "Alice Brown"
       hoặc viết tắt kép "A.B. Brown"). Nếu đồng tác giả cũng chỉ có viết tắt đơn lẻ,
       hai entry sẽ không được gộp.
    """
    if not authors1 or not authors2:
        return False
    a1_first = authors1[0]
    a2_first = authors2[0]
    sur1, given1 = _parse_author_components(a1_first)
    sur2, given2 = _parse_author_components(a2_first)
    if not sur1 or not sur2 or sur1 != sur2:
        return False

    # Trường hợp 1: given words giống nhau hoàn toàn
    if given1 == given2 and given1:
        return True

    # Trường hợp 2: Kiểm tra tính tương thích giữa given words của tác giả đầu
    if not _are_authors_compatible(a1_first, a2_first):
        return False

    # Nếu cả hai bên đều có ít nhất 2 từ tên riêng/viết tắt và đều khớp (ví dụ J.P. Smith và John Paul Smith)
    min_len = min(len(given1), len(given2))
    if min_len >= 2:
        all_match = True
        for i in range(min_len):
            w1, w2 = given1[i], given2[i]
            if len(w1) == 1 or len(w2) == 1:
                if w1[0] != w2[0]:
                    all_match = False
                    break
            elif w1 != w2:
                all_match = False
                break
        if all_match:
            return True

    # Trường hợp 3: Có ít nhất một đồng tác giả phân biệt được ở vị trí khác khớp khẳng định
    coauthors1 = authors1[1:]
    coauthors2 = authors2[1:]
    for co1 in coauthors1:
        for co2 in coauthors2:
            if _coauthor_positively_matches(co1, co2):
                return True

    return False


def _coauthor_positively_matches(co1: str, co2: str) -> bool:
    """Kiểm tra hai đồng tác giả có đủ bằng chứng là cùng một người hay không.

    Đồng tác giả được coi là khớp khẳng định khi:
    1. Cùng họ và thỏa mãn _is_same_author (ví dụ cùng là "Alice Brown" hoặc cùng "P. Jones").
    2. Cùng họ và có ít nhất hai từ tên riêng hoặc viết tắt kép khớp nhau
    """
    if _is_same_author(co1, co2):
        return True

    s1, g1 = _parse_author_components(co1)
    s2, g2 = _parse_author_components(co2)
    if not s1 or not s2 or s1 != s2 or not g1 or not g2:
        return False

    # Tên viết tắt kép hoặc nhiều từ tên riêng (min_len >= 2) khớp nhau
    min_len = min(len(g1), len(g2))
    if min_len >= 2:
        for i in range(min_len):
            w1, w2 = g1[i], g2[i]
            if len(w1) == 1 or len(w2) == 1:
                if w1[0] != w2[0]:
                    return False
            elif w1 != w2:
                return False
        return True

    return False


_GENERIC_URL_PATHS = {"", "/", "/index.html", "/index.htm", "/index.php"}


def _norm_url(url: Any) -> str | None:
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    to_parse = raw if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw) else f"http://{raw}"
    try:
        parts = urlsplit(to_parse)
    except Exception:
        return None

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    netloc = re.sub(r"^www\.", "", netloc)

    # Chỉ loại bỏ cổng mặc định tương ứng với từng giao thức (RFC 3986)
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    if not netloc:
        return None

    path = parts.path.rstrip("/")
    if path.lower() in _GENERIC_URL_PATHS and not parts.query:
        return None

    query = f"?{parts.query}" if parts.query else ""
    return f"{netloc}{path}{query}"


def _clean_url_for_conflict(url: Any) -> str | None:
    """Chuẩn hóa URL phục vụ kiểm tra xung đột giữa các cluster (không lọc bỏ trang chủ)."""
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    to_parse = raw if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw) else f"http://{raw}"
    try:
        parts = urlsplit(to_parse)
    except Exception:
        return None

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    netloc = re.sub(r"^www\.", "", netloc)

    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    if not netloc:
        return None

    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{netloc}{path}{query}"


def _clean_year(year: Any) -> int | None:
    if year is None:
        return None
    if isinstance(year, int):
        return year if 1000 <= year <= 2999 else None
    s = str(year).strip()
    m = re.search(r"[12]\d{3}", s)
    if m:
        val = int(m.group(0))
        if 1000 <= val <= 2999:
            return val
    return None


def signature(entry: dict[str, Any]) -> str:
    """Sinh khóa nhận diện chính cho một entry BibTeX.

    Thứ tự ưu tiên: doi > arxiv_id > (tiêu đề chuẩn hóa + họ tác giả đầu) > url > citation_key.

    Quy ước thiết kế:
    - Không đưa year vào khóa vì nhiều tài liệu mất năm ở các version sau.
    - Khi thiếu DOI và arXiv ID, khóa dùng tiêu đề chuẩn hóa và họ tác giả đầu.
      Đây là heuristic tạo ứng viên; các trường hợp trùng họ khác tên (như John Smith
      và Jane Smith) được cluster_entries phân định riêng qua đối sánh tên riêng.
    - Fallback theo url và citation_key giữ liên kết xuyên version cho tài liệu web
      hoặc khi metadata bị thiếu.
    """
    doi = _norm_doi(entry.get("doi"))
    if doi:
        return f"doi:{doi}"

    arxiv_id = _norm_arxiv(entry.get("arxiv_id"))
    if arxiv_id:
        return f"arxiv:{arxiv_id}"

    title = _norm_title(entry.get("title"))
    if title:
        auth = _first_author_last_name(entry.get("authors"))
        if auth:
            return f"title:{title}/{auth}"

    url = _norm_url(entry.get("url"))
    if url:
        return f"url:{url}"

    key = entry.get("citation_key")
    if key:
        k_str = str(key).strip().lower()
        if title:
            return f"key:{k_str}/{title}"
        return f"key:{k_str}"

    return ""


def entry_keys(entry: dict[str, Any]) -> set[str]:
    """Sinh tập hợp mọi khoá nhận diện của một entry để phục vụ gom nhóm bắc cầu."""
    keys: set[str] = set()

    doi = _norm_doi(entry.get("doi"))
    if doi:
        keys.add(f"doi:{doi}")

    arxiv_id = _norm_arxiv(entry.get("arxiv_id"))
    if arxiv_id:
        keys.add(f"arxiv:{arxiv_id}")

    title = _norm_title(entry.get("title"))
    if title:
        auth_raw = _first_author_raw(entry.get("authors"))
        if auth_raw:
            sur, given = _parse_author_components(auth_raw)
            if sur:
                if given:
                    first_g = given[0]
                    keys.add(f"title:{title}/{sur}/{first_g}")
                    if len(first_g) > 1:
                        keys.add(f"title:{title}/{sur}/{first_g[0]}")
                keys.add(f"title:{title}/{sur}")

    url = _norm_url(entry.get("url"))
    if url:
        keys.add(f"url:{url}")

    # Khoá theo citation_key: luôn sinh nếu có citation_key để kết nối các entry bị suy biến (degraded)
    # ở version khác (chỉ còn citation_key mà mất sạch metadata) với entry có metadata đầy đủ.
    # Tính an toàn được đảm bảo bởi can_union() và conflict check (ngăn chặn gộp khi khác DOI/arXiv/tác giả).
    key = entry.get("citation_key")
    if key:
        k_str = str(key).strip().lower()
        if title:
            keys.add(f"key:{k_str}/{title}")
        keys.add(f"key:{k_str}")

    return keys


def _key_priority(key: str) -> int:
    """Thứ tự ưu tiên xử lý khoá từ mạnh đến yếu: doi > arxiv > title (cụ thể) > title (họ) > url > key."""
    if key.startswith("doi:"):
        return 0
    if key.startswith("arxiv:"):
        return 1
    if key.startswith("title:"):
        if key.count("/") >= 2:
            return 2  # title:{title}/{surname}/{given}
        return 3      # title:{title}/{surname}
    if key.startswith("url:"):
        return 4
    return 5


def cluster_entries(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Gom các entry thành từng nhóm cùng một tài liệu theo quan hệ bắc cầu.

    Quy tắc định danh:
    - Khác DOI: tuyệt đối không gộp.
    - Khác arXiv ID: không gộp, trừ trường hợp cả hai có cùng DOI xuất bản chính thức.
    - Duyệt khóa theo thứ tự ưu tiên: doi > arxiv > title > url > key.
    - Ghép theo tiêu đề bắt buộc có bằng chứng khẳng định tác giả (_authors_positively_match).
    """
    if not entries:
        return []

    n = len(entries)
    parent = list(range(n))

    # Theo dõi tập hợp DOI, arXiv ID, URL, tiêu đề, tác giả đầu tiên và danh sách tác giả cho từng cluster
    cluster_dois: list[set[str]] = []
    cluster_arxivs: list[set[str]] = []
    cluster_urls: list[set[str]] = []
    cluster_titles: list[set[str]] = []
    cluster_first_authors: list[set[str]] = []
    cluster_author_lists: list[list[list[str]]] = []

    for entry in entries:
        d = _norm_doi(entry.get("doi"))
        cluster_dois.append({d} if d else set())
        a = _norm_arxiv(entry.get("arxiv_id"))
        cluster_arxivs.append({a} if a else set())
        u = _clean_url_for_conflict(entry.get("url"))
        cluster_urls.append({u} if u else set())
        t = _norm_title(entry.get("title"))
        cluster_titles.append({t} if t else set())

        raw_auth = entry.get("authors")
        if isinstance(raw_auth, list):
            auth_items = [_clean_author_name(str(x)) for x in raw_auth if str(x).strip()]
        elif isinstance(raw_auth, str):
            auth_items = _split_authors_str(raw_auth)
        elif raw_auth:
            auth_items = [_clean_author_name(str(raw_auth))]
        else:
            auth_items = []
        auth_items = [x for x in auth_items if x]

        if auth_items:
            cluster_first_authors.append({auth_items[0]})
            cluster_author_lists.append([auth_items])
        else:
            cluster_first_authors.append(set())
            cluster_author_lists.append([])

    def find(i: int) -> int:
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]

    def _clusters_authors_match(r_i: int, r_j: int) -> bool:
        lists_i = cluster_author_lists[r_i]
        lists_j = cluster_author_lists[r_j]
        if not lists_i or not lists_j:
            return False
        for l_i in lists_i:
            for l_j in lists_j:
                if _authors_positively_match(l_i, l_j):
                    return True
        return False

    def can_union(i: int, j: int) -> bool:
        root_i = find(i)
        root_j = find(j)
        if root_i == root_j:
            return True

        # 1. Kiểm tra DOI: Nếu cả 2 đều có DOI
        if cluster_dois[root_i] and cluster_dois[root_j]:
            if not (cluster_dois[root_i] & cluster_dois[root_j]):
                return False
            # Cùng DOI: định danh xuất bản chính thức, cho phép gộp bất kể khác biệt preprint arXiv ID.
            return True

        # 2. Kiểm tra arXiv ID: Khi ít nhất một bên không có DOI
        if cluster_arxivs[root_i] and cluster_arxivs[root_j]:
            if not (cluster_arxivs[root_i] & cluster_arxivs[root_j]):
                return False
            return True

        # 3. Khớp tiêu đề và tác giả khẳng định: gộp tài liệu, không để khác biệt URL phủ quyết.
        has_title_and_author_i = bool(cluster_titles[root_i] and cluster_author_lists[root_i])
        has_title_and_author_j = bool(cluster_titles[root_j] and cluster_author_lists[root_j])
        if has_title_and_author_i and has_title_and_author_j:
            titles_match = bool(cluster_titles[root_i] & cluster_titles[root_j])
            if not titles_match:
                return False
            if not _clusters_authors_match(root_i, root_j):
                return False
            return True

        # 4. Khi thiếu Title hoặc Author đầy đủ: kiểm tra xung đột URL, tiêu đề và tác giả đầu đơn lẻ
        if cluster_urls[root_i] and cluster_urls[root_j]:
            if not (cluster_urls[root_i] & cluster_urls[root_j]):
                return False

        if cluster_titles[root_i] and cluster_titles[root_j]:
            if not (cluster_titles[root_i] & cluster_titles[root_j]):
                return False

        auths_i = cluster_first_authors[root_i]
        auths_j = cluster_first_authors[root_j]
        if auths_i and auths_j:
            if not any(_are_authors_compatible(ai, aj) for ai in auths_i for aj in auths_j):
                return False
        return True

    def union(i: int, j: int) -> bool:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            if not can_union(root_i, root_j):
                return False
            parent[root_i] = root_j
            cluster_dois[root_j].update(cluster_dois[root_i])
            cluster_arxivs[root_j].update(cluster_arxivs[root_i])
            cluster_urls[root_j].update(cluster_urls[root_i])
            cluster_titles[root_j].update(cluster_titles[root_i])
            cluster_first_authors[root_j].update(cluster_first_authors[root_i])
            cluster_author_lists[root_j].extend(cluster_author_lists[root_i])
        return True

    key_to_indices: dict[str, list[int]] = {}
    for idx, entry in enumerate(entries):
        for k in entry_keys(entry):
            key_to_indices.setdefault(k, []).append(idx)

    # Xử lý theo thứ tự khoá từ mạnh đến yếu, tie-breaker bằng tên khoá để hoàn toàn tất định
    sorted_keys = sorted(key_to_indices.keys(), key=lambda k: (_key_priority(k), k))
    for k in sorted_keys:
        indices = key_to_indices[k]
        roots = {find(idx) for idx in indices}
        if len(roots) <= 1:
            continue

        # Kiểm tra xung đột định danh mạnh, URL, tiêu đề và tác giả giữa bất kỳ cặp cluster nào tham gia khoá này
        root_list = list(roots)
        conflict = False
        for idx_i in range(len(root_list)):
            r_i = root_list[idx_i]
            for idx_j in range(idx_i + 1, len(root_list)):
                r_j = root_list[idx_j]

                # 1. Nếu cả hai có DOI
                if cluster_dois[r_i] and cluster_dois[r_j]:
                    if not (cluster_dois[r_i] & cluster_dois[r_j]):
                        conflict = True
                        break
                    # Cùng DOI: định danh mạnh nhất, bỏ qua kiểm tra arXiv hay tác giả cho cặp này
                    continue

                # 2. Nếu ít nhất một bên không có DOI, kiểm tra arXiv ID
                if cluster_arxivs[r_i] and cluster_arxivs[r_j]:
                    if not (cluster_arxivs[r_i] & cluster_arxivs[r_j]):
                        conflict = True
                        break
                    # Cùng arXiv ID -> hợp lệ
                    continue

                # 3. Khi cả hai có tiêu đề: kiểm tra xung đột tiêu đề
                if cluster_titles[r_i] and cluster_titles[r_j]:
                    if not (cluster_titles[r_i] & cluster_titles[r_j]):
                        conflict = True
                        break

                # 4. Tác giả không tương thích (ví dụ "John Smith" vs "Jane Smith"): coi là xung đột
                auths_i = cluster_first_authors[r_i]
                auths_j = cluster_first_authors[r_j]
                if auths_i and auths_j:
                    if not any(_are_authors_compatible(ai, aj) for ai in auths_i for aj in auths_j):
                        conflict = True
                        break

                # 5. Kiểm tra xung đột URL khi thiếu tiêu đề hoặc tác giả
                has_title_and_author_i = bool(cluster_titles[r_i] and cluster_author_lists[r_i])
                has_title_and_author_j = bool(cluster_titles[r_j] and cluster_author_lists[r_j])
                if not (has_title_and_author_i and has_title_and_author_j):
                    if cluster_urls[r_i] and cluster_urls[r_j]:
                        if not (cluster_urls[r_i] & cluster_urls[r_j]):
                            conflict = True
                            break
            if conflict:
                break

        if conflict:
            # Bỏ qua khóa nếu nối các cluster đang xung đột để tránh phụ thuộc thứ tự duyệt
            continue

        # Thực hiện union các cluster trong indices có thể gộp được với nhau (can_union)
        changed = True
        while changed:
            changed = False
            for idx_a in indices:
                for idx_b in indices:
                    r_a = find(idx_a)
                    r_b = find(idx_b)
                    if r_a != r_b and can_union(r_a, r_b):
                        union(r_a, r_b)
                        changed = True

    groups: dict[int, list[dict[str, Any]]] = {}
    for idx, entry in enumerate(entries):
        r = find(idx)
        groups.setdefault(r, []).append(entry)

    return list(groups.values())


def _merge_authors(entries: list[dict[str, Any]]) -> list[str] | None:
    """Hợp nhất danh sách tác giả giữa các version.

    Nguyên tắc xử lý:
    - Trả về list[str] hoặc None theo schema M2.
    - Chuẩn hóa TeX macro về Unicode NFC, giữ nguyên dấu ký tự trong tên.
    - Giữ thứ tự xuất hiện ban đầu của tác giả.
    - Ghép tác giả giữa các version qua đối sánh 1-1 không nhập nhằng,
      nâng cấp chữ viết tắt lên tên đầy đủ khi không có mâu thuẫn.
    """
    cleaned_entry_authors: list[list[str]] = []
    for entry in entries:
        raw_authors = entry.get("authors")
        if not raw_authors:
            continue
        if isinstance(raw_authors, list):
            auth_items = [_clean_author_name(str(a)) for a in raw_authors if str(a).strip()]
        elif isinstance(raw_authors, str):
            auth_items = _split_authors_str(raw_authors)
        else:
            auth_items = [_clean_author_name(str(raw_authors))]
        auth_items = [a for a in auth_items if a]
        if auth_items:
            cleaned_entry_authors.append(auth_items)

    if not cleaned_entry_authors:
        return None

    # Khởi tạo danh sách tác giả đã gộp từ entry đầu tiên (đã được sắp theo rank ưu tiên)
    merged_list: list[str] = list(cleaned_entry_authors[0])

    # Hợp nhất từng danh sách tác giả tiếp theo vào merged_list qua đối sánh 1-1 (bipartite matching)
    for auth_items in cleaned_entry_authors[1:]:
        matched_merged_indices: set[int] = set()
        matched_incoming_indices: set[int] = set()

        # Pha 1: Đối sánh đồng nhất nghiêm ngặt (_is_same_author)
        for i_idx, incoming in enumerate(auth_items):
            for m_idx, current in enumerate(merged_list):
                if m_idx in matched_merged_indices:
                    continue
                if _is_same_author(incoming, current):
                    matched_merged_indices.add(m_idx)
                    matched_incoming_indices.add(i_idx)
                    if _author_informativeness(incoming) > _author_informativeness(current):
                        merged_list[m_idx] = incoming
                    break

        # Nâng cấp viết tắt lên tên đầy đủ khi đối sánh 1-1 không nhập nhằng
        unmatched_incoming = [i for i in range(len(auth_items)) if i not in matched_incoming_indices]
        unmatched_merged = [m for m in range(len(merged_list)) if m not in matched_merged_indices]

        # Tìm các cặp tương thích giữa tác giả chưa ghép
        compatible_pairs: list[tuple[int, int]] = []
        for i_idx in unmatched_incoming:
            incoming = auth_items[i_idx]
            for m_idx in unmatched_merged:
                current = merged_list[m_idx]
                if _are_authors_compatible(incoming, current):
                    sur_i, given_i = _parse_author_components(incoming)
                    sur_m, given_m = _parse_author_components(current)
                    if given_i and given_m:
                        compatible_pairs.append((i_idx, m_idx))

        # Chỉ ghép khi ứng viên là duy nhất theo cả hai chiều (1-1)
        for i_idx in unmatched_incoming:
            if i_idx in matched_incoming_indices:
                continue
            matching_m = [m for (i, m) in compatible_pairs if i == i_idx and m not in matched_merged_indices]
            if len(matching_m) == 1:
                target_m = matching_m[0]
                matching_i = [i for (i, m) in compatible_pairs if m == target_m and i not in matched_incoming_indices]
                if len(matching_i) == 1:
                    matched_incoming_indices.add(i_idx)
                    matched_merged_indices.add(target_m)
                    current = merged_list[target_m]
                    incoming = auth_items[i_idx]
                    if _author_informativeness(incoming) > _author_informativeness(current):
                        merged_list[target_m] = incoming

        # Bổ sung tác giả mới vào cuối danh sách
        for i_idx, incoming in enumerate(auth_items):
            if i_idx not in matched_incoming_indices:
                merged_list.append(incoming)

    return merged_list if merged_list else None


def _title_quality_score(title: str) -> tuple[int, int, int, int]:
    """Chấm điểm chất lượng tiêu đề để chọn bản ghi đại diện.

    Thứ tự ưu tiên:
    1. Kiểu chữ: Title Case (3) > Sentence Case (2) > Toàn chữ thường (1) > Toàn chữ hoa (0).
    2. Độ sạch: không chứa lệnh LaTeX thô (1 sạch, 0 có lệnh).
    3. Độ đầy đủ: số lượng từ và độ dài chuỗi.
    """
    s = title.strip()
    if not s:
        return (-1, -1, -1, -1)

    letters = [c for c in s if c.isalpha()]
    if not letters:
        return (0, 0, 0, len(s))

    n_upper = sum(1 for c in letters if c.isupper())
    ratio_upper = n_upper / len(letters)

    # 1. Phân loại kiểu viết hoa
    if ratio_upper > 0.6 and len(letters) > 4:
        # ALL CAPS: ví dụ "ATTENTION IS ALL YOU NEED" -> phạt điểm nặng
        case_rank = 0
    elif n_upper == 0:
        # Toàn chữ thường: ví dụ "attention is all you need"
        case_rank = 1
    else:
        # Mixed case: phân biệt Title Case và Sentence Case
        words = s.split()
        cap_words = sum(1 for w in words if w and w[0].isupper())
        if cap_words >= max(2, len(words) // 2):
            case_rank = 3  # Title Case (ví dụ "Attention Is All You Need")
        else:
            case_rank = 2  # Sentence Case (ví dụ "Attention is all you need")

    # 2. Sạch LaTeX (không có \command)
    clean_latex = 0 if re.search(r"\\[a-zA-Z]+", s) else 1

    # 3. Số từ và độ dài
    return (case_rank, clean_latex, len(s.split()), len(s))


def merge_group(entries: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Gộp các bản ghi tham chiếu trùng nhau thành một entry chuẩn duy nhất.

    Chọn citation key chuẩn theo thứ tự ưu tiên:
    version nhỏ hơn -> citation key ngắn hơn -> thứ tự từ điển.
    Khi trùng cả version và key, ưu tiên nguồn .bib cấu trúc trước \\bibitem và
    entry đầy đủ thông tin hơn.

    Returns:
        (entry đã hợp nhất trường, bảng ánh xạ {key_cũ: key_chuẩn})
    """
    if not entries:
        return {}, {}

    # Thứ tự ưu tiên tất định giữa các entry trong nhóm:
    def _entry_sort_rank(entry: dict[str, Any]) -> tuple[int, int, str, int, int, int, int, str, str]:
        # 1. Version nhỏ hơn
        ver = entry.get("version")
        ver_val = int(ver) if ver is not None and str(ver).isdigit() else 999999

        # 2. Key ngắn hơn, rồi đến thứ tự từ điển
        k = str(entry.get("citation_key") or "")
        len_k = len(k)

        # 3. Nguồn có cấu trúc (.bib không raw) xếp trước \bibitem (có raw)
        source_rank = 1 if entry.get("raw") else 0

        # 4. Loại entry cụ thể xếp trước "misc"
        et = str(entry.get("entry_type") or "").strip().lower()
        et_rank = 0 if (et and et != "misc") else 1

        # 5. Số lượng trường có dữ liệu
        fields = ["doi", "arxiv_id", "title", "authors", "year", "journal", "url", "entry_type"]
        richness = -sum(1 for f in fields if entry.get(f))

        # 6. Có năm xác định
        y = _clean_year(entry.get("year"))
        year_rank = y if y is not None else 999999

        # 7. Thứ tự chữ cái entry_type và chuỗi nội dung để phân định tuyệt đối
        content_str = (
            f"{et}|"
            f"{entry.get('doi') or ''}|"
            f"{entry.get('arxiv_id') or ''}|"
            f"{entry.get('title') or ''}|"
            f"{str(entry.get('authors') or '')}|"
            f"{entry.get('journal') or entry.get('booktitle') or ''}|"
            f"{entry.get('url') or ''}|"
            f"{entry.get('raw') or ''}"
        )

        return (ver_val, len_k, k, source_rank, et_rank, richness, year_rank, et, content_str)

    sorted_entries = sorted(entries, key=_entry_sort_rank)
    canonical_entry = sorted_entries[0]
    canonical_key = str(canonical_entry.get("citation_key") or "")

    # 2. Hợp nhất các trường (unionize fields)
    merged: dict[str, Any] = {"citation_key": canonical_key}

    # arxiv_id: thu thập mọi arXiv ID duy nhất từ các entries được gộp để không mất thông tin khi cùng DOI
    raw_arxivs = [str(e["arxiv_id"]).strip() for e in sorted_entries if e.get("arxiv_id")]
    seen_norm_arxiv: set[str] = set()
    unique_arxivs: list[str] = []
    for raw in raw_arxivs:
        norm = _norm_arxiv(raw) or raw
        if norm not in seen_norm_arxiv:
            seen_norm_arxiv.add(norm)
            unique_arxivs.append(raw)
    if unique_arxivs:
        merged["arxiv_id"] = ", ".join(unique_arxivs) if len(unique_arxivs) > 1 else unique_arxivs[0]
    elif "arxiv_id" in canonical_entry:
        merged["arxiv_id"] = canonical_entry.get("arxiv_id")
    else:
        merged["arxiv_id"] = None

    # entry_type: ưu tiên loại cụ thể hơn "misc", fallback "article"
    et = next(
        (str(e["entry_type"]).lower() for e in sorted_entries if e.get("entry_type") and str(e["entry_type"]).lower() != "misc"),
        None,
    )
    merged["entry_type"] = et or str(canonical_entry.get("entry_type") or "article").lower()

    # title: ưu tiên tiêu đề chuẩn (Title Case / Sentence Case), loại bỏ ALL CAPS
    merged["title"] = max(
        (str(e["title"]).strip() for e in sorted_entries if e.get("title")),
        key=_title_quality_score,
        default=None,
    )

    # authors: hợp nhất danh sách tác giả không làm mất thông tin, bảo đảm list[str]
    merged["authors"] = _merge_authors(sorted_entries)

    # year: lấy năm hợp lệ từ entry ưu tiên nhất theo thứ tự tất định
    merged["year"] = next(
        (y for e in sorted_entries if (y := _clean_year(e.get("year"))) is not None),
        None,
    )

    # doi, journal, url, raw
    merged["doi"] = next((str(e["doi"]).strip() for e in sorted_entries if e.get("doi")), None)
    merged["journal"] = next(
        (str(e.get("journal") or e.get("booktitle")).strip() for e in sorted_entries if e.get("journal") or e.get("booktitle")),
        None,
    )
    merged["url"] = next((str(e["url"]).strip() for e in sorted_entries if e.get("url")), None)

    merged_raw = next((e["raw"] for e in sorted_entries if e.get("raw")), None)
    if merged_raw is not None:
        merged["raw"] = merged_raw

    # 3. Tạo rename_map: mọi key cũ -> key chuẩn
    rename_map: dict[str, str] = {}
    for e in sorted_entries:
        k = e.get("citation_key")
        if k:
            rename_map[str(k)] = canonical_key

    return merged, rename_map


def rename_cites(tex: str, rename: dict[str, str]) -> str:
    """Đổi tên citation key trong chính văn bản.

    Bắt \\cite, \\citep, \\citet, \\citeyear, \\citealp, có cả dạng \\cite[tr.5]{key}.
    Nhiều key trong một lệnh: đổi tên xong thì SORT và bỏ trùng
    -> \\cite{b,a} và \\cite{a,b} ra cùng kết quả, nếu không thì băm ra hai id khác nhau.
    Key không tồn tại (dangling): giữ nguyên, đếm lại để báo cáo.
    """
    raise NotImplementedError


def unify_publication(
    norm_text: dict[int, str],
    bib_entries: dict[int, list[dict[str, Any]]],
) -> tuple[dict[int, str], list[dict[str, Any]], dict[str, str]]:
    """HÀM DUY NHẤT MÀ NHÓM TRƯỞNG GỌI. Chạy hai lượt.

    Lượt 1: đọc bib của TẤT CẢ version -> gom nhóm -> dựng rename_map
    Lượt 2: áp rename_cites() lên văn bản đã chuẩn hoá của từng version

    Phải hai lượt vì rename_map chỉ dựng được khi đã thấy hết mọi version.

    Args:
        norm_text:   {version: toàn văn đã chuẩn hoá (bước 2 của pipeline)}
        bib_entries: {version: entry từ .bib và \\bibitem}

    Returns:
        (renamed_text, bibtex_rows, rename_map)

    HẠN GIAO CHO NHÓM TRƯỞNG: 17/11.
    """
    raise NotImplementedError
