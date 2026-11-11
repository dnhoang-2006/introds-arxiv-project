"""tests/test_hierarchy.py - Kiểm ba hàm thuần tuý của src/parser/hierarchy.py.

Chạy từ thư mục gốc dự án:
    pytest tests/test_hierarchy.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from parser.elements import element_uid  # noqa: E402
from parser.hierarchy import (  # noqa: E402
    extract_body,
    infer_levels,
    split_sentences,
    strip_references,
)


# --------------------------------------------------------------------------- #
# extract_body
# --------------------------------------------------------------------------- #
def test_body_drops_preamble_and_tail():
    tex = (r"\documentclass{article}\newtheorem{lemma}{Lemma}"
           r"\begin{document} Body. \end{document} trailing junk")
    out = extract_body(tex)
    assert out.strip() == "Body."
    assert "newtheorem" not in out and "junk" not in out


def test_body_child_file_returned_verbatim():
    child = r"\section{Intro} Child file without preamble."
    assert extract_body(child) == child


def test_body_missing_end_document():
    assert extract_body(r"\usepackage{x}\begin{document} A. B.").strip() == "A. B."


# --------------------------------------------------------------------------- #
# infer_levels
# --------------------------------------------------------------------------- #
def test_levels_book_class():
    tex = r"\chapter{A} \section{B} \subsection{C}"
    assert infer_levels(tex) == {"chapter": 1, "section": 2, "subsection": 3}


def test_levels_article_class():
    tex = r"\section{Intro} text \subsection{Setup} more"
    assert infer_levels(tex) == {"section": 1, "subsection": 2}


def test_levels_starred_and_short_title():
    tex = r"\section*{Acknowledgements} \subsection[Short]{Long title}"
    assert infer_levels(tex) == {"section": 1, "subsection": 2}


def test_levels_paragraph_before_section_does_not_become_top():
    # \paragraph trong abstract xuất hiện trước \section đầu tiên
    tex = r"\paragraph{Contributions} We... \section{Intro} \subsection{A}"
    assert infer_levels(tex) == {"section": 1, "subsection": 2, "paragraph": 3}


def test_levels_skip_missing_level():
    # Có section và subsubsection nhưng không có subsection -> không chừa cấp trống
    tex = r"\section{A} \subsubsection{B}"
    assert infer_levels(tex) == {"section": 1, "subsubsection": 2}


def test_levels_ignore_commented_commands():
    tex = "\\section{A}\n% \\chapter{Old}\n\\subsection{B}"
    assert infer_levels(tex) == {"section": 1, "subsection": 2}


def test_levels_empty():
    assert infer_levels("no headings here") == {}


# --------------------------------------------------------------------------- #
# strip_references
# --------------------------------------------------------------------------- #
def test_strip_keeps_appendix_after_thebibliography():
    tex = (r"\section{Intro} A. \begin{thebibliography}{9}\bibitem{x}Y"
           r"\end{thebibliography} \section*{Appendix} B.")
    out = strip_references(tex)
    assert "Appendix" in out and "bibitem" not in out
    assert "Intro" in out and "B." in out


def test_strip_references_section_with_bib_command_then_appendix():
    tex = (r"\section{Intro} A. \section*{References} \bibliographystyle{plain}"
           r"\bibliography{refs} \appendix \section{Proofs} P.")
    out = strip_references(tex)
    assert "References" not in out and "bibliography" not in out
    assert r"\appendix" in out and "Proofs" in out


def test_strip_acknowledgements_after_references_kept():
    tex = (r"\section{Intro} A. \section*{References} \begin{thebibliography}{1}"
           r"\bibitem{a} Foo.\end{thebibliography} \section*{Acknowledgements} Thanks.")
    out = strip_references(tex)
    assert "Acknowledgements" in out and "Thanks." in out
    assert "Foo." not in out


def test_strip_unterminated_thebibliography():
    tex = r"\section{Intro} A. \begin{thebibliography}{9}\bibitem{x} Y"
    out = strip_references(tex)
    assert "bibitem" not in out and "Intro" in out


def test_strip_printbibliography_and_references_env():
    tex = (r"Body. \printbibliography[title=Refs] "
           r"\begin{references}\reference X\end{references} End.")
    out = strip_references(tex)
    assert "printbibliography" not in out and "reference X" not in out
    assert "Body." in out and "End." in out


def test_strip_noop_without_references():
    tex = r"\section{Intro} Nothing to strip."
    assert strip_references(tex) == tex


# --------------------------------------------------------------------------- #
# split_sentences
# --------------------------------------------------------------------------- #
def test_split_notion_minimum_case():
    s = "We use BERT (Devlin et al. 2019). The result is 3.14 times better. See Fig. 2 for details."
    assert split_sentences(s) == [
        "We use BERT (Devlin et al. 2019).",
        "The result is 3.14 times better.",
        "See Fig. 2 for details.",
    ]


@pytest.mark.parametrize("s", [
    "The value $a.b$ is fine. Next sentence here.",
    "Visit http://x.com/a.b for code. Next sentence here.",
    "Some methods, i.e. Transformers, work. Next sentence here.",
    "Many models, e.g. BERT, work. Next sentence here.",
    r"As shown in \cite{smith.2020}. Next sentence here.",
    r"See Eq. \ref{eq:1.2} above. Next sentence here.",
    "Accuracy rose to 97.5 percent. Next sentence here.",
])
def test_split_protected_dots(s):
    assert len(split_sentences(s)) == 2


def test_split_url_trailing_dot_is_sentence_end():
    out = split_sentences("Code is at https://github.com/a/b. It is open.")
    assert out == ["Code is at https://github.com/a/b.", "It is open."]


def test_split_display_math_not_split():
    s = r"We have \begin{equation} x = 1. Y = 2. \end{equation} as shown. Next one."
    assert len(split_sentences(s)) == 2


@pytest.mark.parametrize("s, expected", [
    ("The value is 5. 10 samples were used.",
     ["The value is 5.", "10 samples were used."]),
    ("The AUC was 0.82. 95% confidence intervals are shown.",
     ["The AUC was 0.82.", "95% confidence intervals are shown."]),
])
def test_split_sentence_starting_with_digit(s, expected):
    assert split_sentences(s) == expected


@pytest.mark.parametrize("s", [
    "Results agree with Smith et al. 2019 closely.",
    "As in Fig. 3 and Sec. 4 above.",
    "It took approx. 5 hours.",
])
def test_split_abbreviation_before_digit_not_split(s):
    assert len(split_sentences(s)) == 1


def test_split_lowercase_after_dot_kept_together():
    # Cố ý: dấu chấm + chữ thường gần như luôn là viết tắt chưa bắt được.
    assert len(split_sentences("We tested it. nevertheless it failed.")) == 1


def test_split_question_and_exclamation():
    assert len(split_sentences("Does it work? Yes! It does.")) == 3


def test_split_collapses_whitespace_and_empty():
    assert split_sentences("  A   b.\n\n  C d.  ") == ["A b.", "C d."]
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_split_nested_mask_restored():
    s = r"A note\footnote{see $x.y$ there}. Next sentence."
    out = split_sentences(s)
    assert out == [r"A note\footnote{see $x.y$ there}.", "Next sentence."]


# --------------------------------------------------------------------------- #
# element_uid (đã chốt trong schema_m2.md mục 2)
# --------------------------------------------------------------------------- #
def test_element_uid_format_and_dedup():
    a = element_uid("2310-12345", "sentence", "Same text.")
    b = element_uid("2310-12345", "sentence", "Same text.")
    c = element_uid("2310-12345", "paragraph", "Same text.")
    assert a == b
    assert a != c
    assert a.startswith("2310-12345#snt_") and len(a.split("_")[-1]) == 8


def test_root_ids_differ_per_version():
    r1 = element_uid("2310-12345", "document", "2310.12345v1")
    r2 = element_uid("2310-12345", "document", "2310.12345v2")
    assert r1 != r2
