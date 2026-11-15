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
from parser.elements import KIND_CODE  # noqa: E402
from parser.normalize import strip_noncontent  # noqa: E402
from parser.hierarchy import (  # noqa: E402
    Node,
    build_tree,
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


# --------------------------------------------------------------------------- #
# build_tree
# --------------------------------------------------------------------------- #
def _doc(body: str) -> str:
    return r"\documentclass{article}\begin{document}" + body + r"\end{document}"


def _walk(node: Node):
    yield node
    for c in node.children:
        yield from _walk(c)


def _of_kind(node: Node, kind: str) -> list[Node]:
    return [n for n in _walk(node) if n.kind == kind]


# Ca bắt buộc 1
def test_tree_three_sentences_not_six():
    tex = _doc(r"\section{Intro} We use BERT (Devlin et al. 2019). "
               r"The result is 3.14 times better. See Fig. 2 for details.")
    sec = build_tree(tex).children[0]
    assert (sec.kind, sec.content) == ("section", "Intro")
    assert [(c.kind, c.content) for c in sec.children] == [
        ("sentence", "We use BERT (Devlin et al. 2019)."),
        ("sentence", "The result is 3.14 times better."),
        ("sentence", "See Fig. 2 for details."),
    ]


# Ca bắt buộc 2
def test_tree_chapter_level_1_section_level_2():
    tex = _doc(r"\chapter{Intro} A b. \section{Background} C d. \subsection{Deep} E f.")
    root = build_tree(tex)
    assert root.kind == "document"
    chapter = root.children[0]
    assert (chapter.kind, chapter.content) == ("section", "Intro")
    section = [c for c in chapter.children if c.kind != "sentence"][0]
    assert (section.kind, section.content) == ("subsection", "Background")
    deep = [c for c in section.children if c.kind != "sentence"][0]
    assert (deep.kind, deep.content) == ("subsubsection", "Deep")


def test_tree_section_without_chapter_is_level_1():
    root = build_tree(_doc(r"\section{A} x y. \subsection{B} z w."))
    assert root.children[0].kind == "section"
    assert root.children[0].children[1].kind == "subsection"


def test_tree_sibling_sections_pop_back_up():
    root = build_tree(_doc(r"\section{A} \subsection{A1} t. \section{B} u."))
    assert [c.content for c in root.children] == ["A", "B"]


# Ca bắt buộc 3
def test_tree_appendix_after_references_kept():
    tex = _doc(r"\section{Intro} Body text. "
               r"\section*{References}\begin{thebibliography}{9}"
               r"\bibitem{x} Some Author. Some Title. 2019.\end{thebibliography}"
               r"\section*{Acknowledgements} We thank X. "
               r"\section*{Appendix} Proof details here.")
    root = build_tree(tex)
    assert [c.content for c in root.children] == ["Intro", "Acknowledgements", "Appendix"]
    assert root.children[2].children[0].content == "Proof details here."
    assert not any("bibitem" in n.content or "Some Title" in n.content
                   for n in _walk(root))


# Ca bắt buộc 4
def test_tree_figure_with_many_dots_is_one_leaf():
    tex = _doc(r"\section{R} Before. \begin{figure}[t]\centering"
               r"\includegraphics{a.png}\caption{Results. See Fig. 2. Value 0.5. Done.}"
               r"\end{figure} After.")
    sec = build_tree(tex).children[0]
    figs = _of_kind(sec, "figure")
    assert len(figs) == 1
    assert figs[0].children == []
    assert figs[0].content.startswith(r"\begin{figure}")
    assert figs[0].content.endswith(r"\end{figure}")
    assert [c.kind for c in sec.children] == ["sentence", "figure", "sentence"]
    assert not any("Results." in n.content for n in _of_kind(sec, "sentence"))


def test_tree_table_star_is_figure():
    sec = build_tree(_doc(r"\section{R} \begin{table*}\begin{tabular}{cc}1. & 2.\\"
                          r"\end{tabular}\end{table*}")).children[0]
    assert [c.kind for c in sec.children] == ["figure"]


# Luật "ngoài cùng thắng"
def test_tree_table_with_tabular_is_single_figure():
    tex = _doc(r"\section{R} \begin{table}\centering\caption{T. A.}"
               r"\begin{tabular}{ll} a. & b. \\ c. & d. \end{tabular}\end{table}")
    sec = build_tree(tex).children[0]
    assert [c.kind for c in sec.children] == ["figure"]
    fig = sec.children[0]
    assert fig.children == []
    assert fig.content.startswith(r"\begin{table}") and fig.content.endswith(r"\end{table}")
    assert r"\begin{tabular}" in fig.content and r"\end{tabular}" in fig.content


def test_tree_figure_with_subfigures_is_single_figure():
    tex = _doc(r"\begin{figure*}"
               r"\begin{subfigure}{.5\linewidth}\includegraphics{a}\caption{A.}\end{subfigure}"
               r"\begin{subfigure}{.5\linewidth}\includegraphics{b}\caption{B.}\end{subfigure}"
               r"\caption{Both. See text.}\end{figure*}")
    root = build_tree(tex)
    figs = _of_kind(root, "figure")
    assert len(figs) == 1 and root.children == figs
    assert figs[0].content.count(r"\begin{subfigure}") == 2


def test_tree_standalone_tabular_is_figure():
    tex = _doc(r"Before. \begin{center}\begin{tabular}{c} x. \end{tabular}\end{center} After.")
    assert [c.kind for c in build_tree(tex).children] == ["sentence", "figure", "sentence"]


def test_tree_equation_is_formula_leaf():
    sec = build_tree(_doc(r"\section{M} We have \begin{equation} a = 0.5. \end{equation}"
                          r" where a is small.")).children[0]
    assert [c.kind for c in sec.children] == ["sentence", "formula", "sentence"]
    assert sec.children[1].content == r"\begin{equation} a = 0.5. \end{equation}"


def test_tree_display_math_shorthand_is_formula():
    sec = build_tree(_doc(r"\section{M} So $$x = 1.$$ Then \[ y. \] End.")).children[0]
    assert [c.kind for c in sec.children] == [
        "sentence", "formula", "sentence", "formula", "sentence"]


def test_tree_linebreak_bracket_not_formula():
    sec = build_tree(_doc(r"\section{M} Line one\\[2pt] continues here.")).children[0]
    assert [c.kind for c in sec.children] == ["sentence"]


# Ca bắt buộc 5
def test_tree_itemize_three_items():
    tex = _doc(r"\section{L} \begin{itemize} \item One. \item Two. \item Three. "
               r"\end{itemize}")
    sec = build_tree(tex).children[0]
    lists = _of_kind(sec, "itemize")
    assert len(lists) == 1
    assert [(i.kind, i.content) for i in lists[0].children] == [
        ("item", "One."), ("item", "Two."), ("item", "Three.")]
    # Item một câu vẫn là node chứa, câu là lá — hình dạng cây nhất quán.
    assert [[(c.kind, c.content) for c in i.children] for i in lists[0].children] == [
        [("sentence", "One.")], [("sentence", "Two.")], [("sentence", "Three.")]]


def test_tree_itemize_content_has_no_raw_item_command():
    root = build_tree(_doc(r"\begin{itemize}\item Alpha is good. \item Beta only.\end{itemize}"))
    [itz] = _of_kind(root, "itemize")
    assert itz.content == "Alpha is good.\nBeta only."


def test_tree_nested_list_contents_clean():
    tex = _doc(r"\begin{itemize}[leftmargin=*]\item Third \begin{enumerate}[a)]"
               r"\item n1 \item[X] n2\end{enumerate}\item[Key] Last.\end{itemize}")
    root = build_tree(tex)
    for n in _walk(root):
        if n.kind in ("itemize", "item"):
            assert r"\item" not in n.content
            assert r"\begin" not in n.content and r"\end" not in n.content
    outer = _of_kind(root, "itemize")[0]
    assert [i.content for i in outer.children] == ["Third\nn1\nX n2", "Key Last."]
    assert outer.content == "Third\nn1\nX n2\nKey Last."


def test_tree_item_sentence_has_same_shape_when_item_grows():
    # v1 item một câu, v2 thêm câu: câu cũ phải là cùng (kind, content) ở cả hai.
    v1 = _doc(r"\begin{itemize}\item The model is fast.\end{itemize}")
    v2 = _doc(r"\begin{itemize}\item The model is fast. We measured 3x speedup."
              r"\end{itemize}")
    s1 = {(n.kind, n.content) for n in _walk(build_tree(v1)) if not n.children}
    s2 = {(n.kind, n.content) for n in _walk(build_tree(v2)) if not n.children}
    assert ("sentence", "The model is fast.") in s1 & s2
    assert not any(k == "item" for k, _ in s1 | s2)    # item không bao giờ là lá


def test_tree_long_item_split_into_sentences():
    tex = _doc(r"\begin{enumerate}\item First claim. Second claim.\end{enumerate}")
    item = _of_kind(build_tree(tex), "item")[0]
    assert item.content == "First claim. Second claim."
    assert [(c.kind, c.content) for c in item.children] == [
        ("sentence", "First claim."), ("sentence", "Second claim.")]


def test_tree_nested_list_items_not_merged():
    tex = _doc(r"\begin{itemize}\item A. \begin{itemize}\item a1. \item a2.\end{itemize}"
               r"\item B.\end{itemize}")
    outer = _of_kind(build_tree(tex), "itemize")[0]
    assert len(outer.children) == 2
    assert len(_of_kind(outer, "itemize")) == 2        # chính nó + danh sách lồng
    assert len(_of_kind(outer, "item")) == 4


def test_tree_theorem_unwrapped_into_sentences():
    tex = _doc(r"\section{T} \begin{theorem} Let $x$ be 1. Then $y = 2$. \end{theorem}"
               r"\begin{proof} Trivial. Done. \end{proof}")
    sec = build_tree(tex).children[0]
    assert [c.kind for c in sec.children] == ["sentence"] * 4
    assert not any(r"\begin" in c.content or r"\end" in c.content for c in sec.children)


def test_tree_noise_commands_do_not_become_sentences():
    root = build_tree(_doc(r"\maketitle \section{A}\label{sec:a} Real text."))
    assert [c.content for c in root.children[0].children] == ["Real text."]


# strip_noncontent nằm ở normalize.py (nguồn duy nhất, clean_latex cũng gọi nó);
# test ở đây vì build_tree phụ thuộc vào nó.
@pytest.mark.parametrize("s", [
    r"\section{A}\label{sec:a} Text\vspace{2mm}. \maketitle",
    r"\vspace*{\baselineskip}\noindent X \hspace{1em} Y",
    r"\la\label{x}bel{y} z",
    "plain text, nothing to strip.",
])
def test_strip_noncontent_idempotent(s):
    once = strip_noncontent(s)
    assert strip_noncontent(once) == once


def test_strip_noncontent_removes_args_and_keeps_prefixed_cmds():
    out = strip_noncontent(r"\vspace*{\baselineskip}A \partial \paragraph{P} \parbox \label{x}")
    assert "baselineskip" not in out and "label" not in out
    assert r"\partial" in out and r"\paragraph{P}" in out and r"\parbox" in out


def test_tree_commented_section_ignored():
    root = build_tree(_doc("\\section{A} x.\n% \\section{Ghost}\n y."))
    assert [c.content for c in root.children] == ["A"]


def test_tree_only_valid_kinds():
    tex = _doc(r"\begin{abstract} Abs. \end{abstract}\section{A} x. \paragraph{P} y. "
               r"$$ z $$ \begin{itemize}\item q\end{itemize}")
    assert {n.kind for n in _walk(build_tree(tex))} <= set(KIND_CODE)


def test_tree_child_file_without_document_env():
    root = build_tree(r"\section{Only} Child file text.")
    assert root.children[0].children[0].content == "Child file text."
