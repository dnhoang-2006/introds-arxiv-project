"""tests/test_matching_clean.py - Kiểm src/matching/clean.py.

Chạy từ thư mục gốc dự án:
    pytest tests/test_matching_clean.py -v

Hai phía M2 (bibtex) và M1 (references) phải ra CÙNG một dạng; test đỏ nghĩa là
matcher sẽ trượt, phải báo Hửu Duy và Anh Tuấn.
"""
from __future__ import annotations

import pytest

from src.matching.clean import (
    author_keys,
    clean_bibtex_entry,
    clean_reference_row,
    clean_title,
    last_names,
    parse_author,
    split_bibtex_authors,
    title_tokens,
)


# ------------------------------------------------------------------ tiêu đề
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"\emph{Attention} Is All You~Need", "attention is all you need"),
        (r"{BERT}: Pre-training of Deep {B}idirectional Transformers",
         "bert pre training of deep bidirectional transformers"),
        (r"Learning \textbf{\emph{deep}} nets\footnote{Work done at X}", "learning deep nets"),
        ("  Self-Attention — a survey’s  view ", "self attention a survey s view"),
        ("ﬁne-tuning", "fine tuning"),
        (None, ""),
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_title_latex_and_unicode_sides_match():
    assert clean_title(r"$\alpha$-Divergence for {GAN}s") == clean_title("α-Divergence for GANs")
    assert clean_title(r"On M{\"u}ller's method") == clean_title("On Müller's method")


def test_title_tokens_drop_stopwords():
    assert title_tokens("Attention Is All You Need") == ["attention", "all", "you", "need"]


# ------------------------------------------------------------------ tác giả
@pytest.mark.parametrize(
    "names",
    [
        ["Vaswani, A.", "A. Vaswani", "Ashish Vaswani", "A.~Vaswani"],
        ["J. A. Aguilar", "Aguilar, Jose A.", "J.A. Aguilar"],
        [r"M{\"u}ller, K.", "Klaus Mueller", "Müller, Klaus", r"K. M\"{u}ller"],
        ["van der Waals, J. D.", "Johannes van der Waals"],
        ["Aguilar-Lopez, J.", "J. Aguilar-Lopez"],
        [r"Fran\c{c}ois Chollet", "François Chollet", "Chollet, F."],
        ["Smith, Jr., John", "Smith, John, Jr.", "John Smith Jr."],
    ],
)
def test_same_author_same_key(names):
    assert len({parse_author(n).key for n in names}) == 1, [parse_author(n) for n in names]


def test_author_fields():
    a = parse_author("Aguilar, Jose A.")
    assert (a.last, a.initials, a.key) == ("aguilar", "ja", "aguilar j")


def test_corporate_author_kept_whole():
    assert parse_author("{Google Research}").last == "google research"


@pytest.mark.parametrize("name", ["", None, "others", "et al.", "张伟"])
def test_not_a_person(name):
    assert parse_author(name) is None


def test_split_bibtex_authors():
    assert split_bibtex_authors("A. Smith and B. Jones AND others") == ["A. Smith", "B. Jones"]


def test_author_keys_accepts_list_and_bibtex_string():
    assert author_keys(["Vaswani, Ashish", "Noam Shazeer"]) == ["vaswani a", "shazeer n"]
    assert author_keys("Vaswani, Ashish and Shazeer, Noam") == ["vaswani a", "shazeer n"]


def test_last_names_without_initials():
    assert last_names(["van der Waals"]) == {"van der waals"}


# ------------------------------------------------------------------ hai phía khớp nhau
def test_bibtex_and_reference_sides_agree():
    bib = clean_bibtex_entry({
        "citation_key": "vaswani2017",
        "title": r"Attention is All you {N}eed",
        "authors": ["A.~Vaswani", "N. Shazeer"],
    })
    ref = clean_reference_row({
        "ref_title": "Attention Is All You Need",
        "ref_authors": ["Ashish Vaswani", "Noam M. Shazeer"],
    })
    for field in ("title_clean", "title_tokens", "author_keys"):
        assert bib[field] == ref[field]
    assert bib["citation_key"] == "vaswani2017"  # giữ nguyên trường gốc

# ------------------------------------------------------------------ hồi quy 27/11
# Bốn lỗi do Hửu Duy báo + đo lại trên dải 24120053. Test đỏ ở đây nghĩa là
# matcher trượt đúng những ca đã biết, xem docs/schema_m3.md mục 9.
@pytest.mark.parametrize(
    ("s2_side", "bibtex_side"),
    [
        # 1. "et al." nuốt họ: trước khi vá ra Author(last='al')
        ("P. Moskal et al.", "Moskal, Pawel"),
        ("Bian, Y. et al.", "Yong Bian"),
        # 2. S2 ghi dấu sắc bằng nháy đơn trần
        ("Valentin Cr'epel", "Crépel, Valentin"),
        ("Delphin S'enizergues", "Sénizergues, Delphin"),
        # 3. umlaut lệch hai phía -> cần khoá phụ
        ("Blumlein, J.", "Blümlein, J."),
        ("Niemela, M.", "Niemelä, M."),
        ("Lu, Linyuan", "Lü, Linyuan"),      # pinyin, không phải tiếng Đức
        # ...nhưng fold ae/oe/ue vẫn phải giữ được
        ("Mueller, H.", "Müller, H."),
        # nháy đơn THẬT: không được xoá, và hai cách viết hoa vẫn phải gặp nhau
        ("T. O'Brien", "O'brien, Thomas"),
        ("Marcelo D'Agostino", "D'Agostino, Marcelo"),
    ],
)
def test_two_sides_match_after_27_11_fixes(s2_side, bibtex_side):
    a, b = parse_author(s2_side), parse_author(bibtex_side)
    assert a is not None and b is not None
    assert a.matches(b), (a, b)


def test_et_al_does_not_become_surname():
    assert parse_author("P. Moskal et al.").last == "moskal"


def test_quote_accent_only_before_lowercase():
    assert parse_author("Valentin Cr'epel").last == "crepel"
    assert parse_author("T. O'Brien").last == "o brien"   # nháy thật, giữ nguyên


def test_fold_stays_primary_key_alt_is_extra():
    """Khoá chính vẫn là dạng fold (ü->ue); bỏ dấu chỉ là khoá phụ.

    Đo 27/11 trên 217.892 khoá S2: fold khớp 2.329 tên, bỏ-dấu khớp 338.
    Đảo hai cái này là mất nhiều hơn được.
    """
    a = parse_author("Blümlein, J.")
    assert a.key == "bluemlein j"
    assert a.alt_key == "blumlein j"
    assert a.keys == frozenset({"bluemlein j", "blumlein j"})


def test_author_without_accent_has_single_key():
    a = parse_author("Vaswani, Ashish")
    assert a.last_alt == "" and a.keys == frozenset({"vaswani a"})


def test_cleaned_rows_expose_alt_keys():
    row = clean_reference_row({"ref_title": "x", "ref_authors": ["Blümlein, J."]})
    assert row["author_keys"] == ["bluemlein j"]
    assert row["author_keys_alt"] == ["blumlein j"]


def test_possessive_apostrophe_in_title_unchanged():
    """Nháy trong tiêu đề hầu hết là sở hữu cách, không được coi là dấu."""
    assert clean_title("a survey's view") == "a survey s view"
