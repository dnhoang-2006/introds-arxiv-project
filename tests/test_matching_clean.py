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


# ------------------------------------------------------------------ API so khớp
def test_author_key_set_unions_both_key_forms():
    """`author_keys` tran bo mat khoa phu — day la ly do co `author_key_set`."""
    from src.matching.clean import author_key_set

    bib = ["Blümlein, J."]
    s2 = ["J. Blumlein"]
    assert not set(author_keys(bib)) & set(author_keys(s2))   # cách SAI
    assert author_key_set(bib) & author_key_set(s2)            # cách ĐÚNG


@pytest.mark.parametrize(
    ("left", "right", "expect"),
    [
        (["Blümlein, J."], ["J. Blumlein"], True),
        (["P. Moskal et al."], ["Pawel Moskal"], True),
        (["Valentin Cr'epel"], ["Crépel, Valentin"], True),
        (["T. O'Brien"], ["O'brien, Thomas"], True),
        (["Vaswani, Ashish"], ["Noam Shazeer"], False),
        ([], ["Vaswani, Ashish"], False),
        (None, None, False),
    ],
)
def test_authors_match(left, right, expect):
    from src.matching.clean import authors_match

    assert authors_match(left, right) is expect


def test_first_author_matches_only_looks_at_first():
    from src.matching.clean import first_author_matches

    assert first_author_matches(["Blümlein, J.", "X. Y."], ["J. Blumlein", "Z. W."])
    assert not first_author_matches(["X. Y.", "Blümlein, J."], ["J. Blumlein", "Z. W."])


def test_quote_regex_runs_before_lowercasing():
    """Bẫy Hửu Duy chỉ ra 27/11: dời regex xuống sau .lower() là hỏng O'Brien.

    Gộp từ test_quote_accent_only_before_lowercase cũ.
    """
    # nháy THẬT phải giữ, ở cả hai cách viết hoa
    assert parse_author("T. O'Brien").last == "o brien"
    assert parse_author("O'Brien, Thomas").last == "o brien"
    assert parse_author("T. O'Brien").matches(parse_author("O'brien, Thomas"))
    # nháy-thành-dấu vẫn phải được sửa
    assert parse_author("Valentin Cr'epel").last == "crepel"
    assert "crepel v" in parse_author("Valentin Cr'epel").keys


# ------------------------------------------------------------------ Hửu Duy soát 27/11
@pytest.mark.parametrize(
    ("left", "right"),
    [
        # 1. một bên không có chữ đầu tên -> chỉ so họ. Entry bóc từ .bbl rất hay
        #    chỉ ghi mỗi họ. Bỏ qua là mất 52 cặp.
        ("He", "Kaiming He"),
        ("Raffel et al.", "Colin A. Raffel"),
        ("Vaswani", "Vaswani, Ashish"),
        # 2. tiền tố tách lệch giữa hai nguồn. Bỏ qua là mất 77 cặp.
        ("G. Di Giulio", "Di Giulio, Giuseppe"),
        ("S. von Buddenbrock", "Buddenbrock, Stefan"),
        ("van der Waals, J. D.", "J. D. Waals"),
    ],
)
def test_surname_only_and_particle_cases_match(left, right):
    assert parse_author(left).matches(parse_author(right))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Kaiming He", "Xiangyu He"),      # cùng họ, khác chữ đầu tên
        ("Vaswani, Ashish", "Shazeer, Noam"),
        ("Giulio, G.", "Rossi, G."),       # đuôi không trọn từ
    ],
)
def test_still_rejects_different_people(left, right):
    assert not parse_author(left).matches(parse_author(right))


def test_le_wang_still_works_after_particle_rule():
    """Đừng sửa _split_first_last kiểu coi Di/Le viết hoa là tiền tố.

    `Le` trong `Le Wang` là tên riêng tiếng Trung, không phải particle.
    """
    assert parse_author("Le Wang").matches(parse_author("Wang, Le"))
    assert parse_author("Le Wang").last == "wang"


def test_first_author_matches_does_not_parse_whole_list():
    """Bài collaboration có hàng nghìn tác giả; chỉ parse người đầu."""
    from src.matching.clean import first_author_matches, parse_author

    huge = ["Kaiming He"] + [f"Author {i}" for i in range(3000)]
    parse_author.cache_clear()
    assert first_author_matches(huge, ["He"])
    assert parse_author.cache_info().currsize <= 4


def test_authors_match_caps_pairwise_work():
    from src.matching.clean import authors_match

    big_a = [f"Alpha{i}, A." for i in range(2000)] + ["Kaiming He"]
    big_b = [f"Beta{i}, B." for i in range(2000)] + ["He"]
    # "He" nằm ngoài ngưỡng _PAIRWISE_LIMIT nên không khớp -> không treo máy
    assert authors_match(big_a, big_b) is False
    assert authors_match(["Kaiming He"], ["He"]) is True


# ------------------------------------------------------------------ tên tổ chức
@pytest.mark.parametrize(
    ("left", "right", "expect"),
    [
        # KHÁC tổ chức: luật "họ là đuôi của nhau" không được nổ trên từ chung.
        # Đây đúng là ví dụ ATLAS mà schema_m3 mục 9 dùng để giải thích bỏ luật 4.
        ("{ATLAS Collaboration}", "CMS Collaboration", False),
        ("ATLAS Collaboration", "CMS Collaboration", False),
        ("{Google Research}", "Microsoft Research", False),
        # CÙNG tổ chức, một bên có ngoặc nhọn một bên không
        ("{ATLAS Collaboration}", "ATLAS Collaboration", True),
        ("{Google Research}", "Google Research", True),
        ("{LHCb Collaboration}", "LHCb collaboration", True),
    ],
)
def test_organisation_names(left, right, expect):
    assert parse_author(left).matches(parse_author(right)) is expect


def test_org_name_without_braces_kept_whole():
    """Không tách họ/tên cho tên tổ chức, dù không có ngoặc nhọn.

    Nếu tách thì "ATLAS Collaboration" ra họ `collaboration`, `ATLAS` chui vào
    initials — vừa không gặp `{ATLAS Collaboration}`, vừa gặp nhầm `CMS`.
    """
    a = parse_author("ATLAS Collaboration")
    assert (a.last, a.initials) == ("atlas collaboration", "")


def test_person_whose_surname_resembles_org_word_is_unaffected():
    """Một từ chung đứng một mình không biến tên người thành tổ chức."""
    assert parse_author("Group").last == "group"
    a, b = parse_author("K. Grouper"), parse_author("Kevin Grouper")
    assert a.matches(b)


# ------------------------------------------------------------------ Hửu Duy soát #2
@pytest.mark.parametrize(
    ("left", "right", "expect"),
    [
        # Cùng tổ chức, một bên viết tắt tên riêng của tổ chức
        ("ATLAS Collaboration", "A. Collaboration", True),
        ("CMS Collaboration", "C. Collaboration", True),
        # Cùng tổ chức, một bên viết kèm dấu phẩy nên bị tách họ/tên
        ("Collaboration, ATLAS", "ATLAS Collaboration", True),
        ("Team, Gemini", "Gemini Team", True),
        # Khác tổ chức thì vẫn phải loại, kể cả khi đuôi giống nhau
        ("{ATLAS Collaboration}", "CMS Collaboration", False),
        ("ATLAS Collaboration", "C. Collaboration", False),
        ("{Google Research}", "Microsoft Research", False),
    ],
)
def test_abbreviated_and_comma_written_organisations(left, right, expect):
    assert parse_author(left).matches(parse_author(right)) is expect


def test_comma_name_is_not_mistaken_for_organisation():
    """`Zhang, Research` là người tên Research họ Zhang, không phải tổ chức."""
    a = parse_author("Zhang, Research")
    assert (a.last, a.initials) == ("zhang", "r")
    assert a.matches(parse_author("Zhang, R."))


@pytest.mark.parametrize(
    ("left", "right", "expect"),
    [
        ("{The ATLAS Collaboration}", "A. Collaboration", True),
        ("{The ATLAS Collaboration}", "ATLAS Collaboration", True),
        ("The CMS Collaboration", "{CMS Collaboration}", True),
        # "the" không được làm mất khả năng loại tổ chức khác
        ("{The ATLAS Collaboration}", "CMS Collaboration", False),
        ("{The ATLAS Collaboration}", "C. Collaboration", False),
    ],
)
def test_leading_the_is_ignored_for_organisations(left, right, expect):
    assert parse_author(left).matches(parse_author(right)) is expect


def test_org_written_as_name_comma_generic_is_a_known_limitation():
    """`Gemini, Team` KHÔNG gặp `Gemini Team` — cố ý, đừng "sửa".

    Ca này cùng dạng hệt `Zhang, Research`: đều là "<từ thường>, <từ chung>".
    Luật nào cứu được cái trên cũng sẽ lại biến `Zhang, Research` thành tổ chức
    `zhang research`, đúng lỗi vừa vá ở commit trước. Phân biệt hai cái đòi phải
    biết `Gemini` là tên tổ chức còn `Zhang` là họ người — cần từ điển, không
    phải việc của một luật chuỗi.

    Hửu Duy đo 27/11: khoảng 20 tên kiểu này trên `parsed/`, 0 cặp bị ảnh hưởng.
    Ghi ở `docs/schema_m3.md` mục 9.
    """
    assert not parse_author("Gemini, Team").matches(parse_author("Gemini Team"))
    # ...và đây là cái phải giữ, lý do của việc không sửa ở trên
    assert parse_author("Zhang, Research").matches(parse_author("Zhang, R."))
    # thứ tự ngược lại thì vẫn gặp nhau bình thường
    assert parse_author("Team, Gemini").matches(parse_author("Gemini Team"))


@pytest.mark.parametrize(
    ("left", "right", "expect"),
    [
        ("Collaboration, The ATLAS", "The ATLAS Collaboration", True),
        ("Collaboration, The ATLAS", "ATLAS Collaboration", True),
        ("Collaboration, The ATLAS", "A. Collaboration", True),
        ("Collaboration, The ATLAS", "CMS Collaboration", False),
    ],
)
def test_article_the_in_given_part_of_organisation(left, right, expect):
    """`The` là mạo từ của tên tổ chức, không được sinh ra chữ đầu tên."""
    assert parse_author(left).matches(parse_author(right)) is expect


def test_the_is_only_dropped_for_organisations():
    """`Nguyễn Thế Anh` viết không dấu thành `Nguyen, The Anh` — `The` là tên thật.

    Chỉ bỏ `the` khi HỌ là từ chung chỉ tổ chức. Nếu bỏ vô điều kiện thì tên
    người Việt mất một chữ đầu.
    """
    a = parse_author("Nguyen, The Anh")
    assert (a.last, a.initials) == ("nguyen", "ta")
    assert a.matches(parse_author("T. Nguyen"))
    assert not a.matches(parse_author("Anh Nguyen"))
