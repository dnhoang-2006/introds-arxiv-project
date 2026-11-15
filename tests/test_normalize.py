"""tests/test_normalize.py - Kiểm src/parser/normalize.py.

Chạy từ thư mục gốc dự án:
    pytest tests/test_normalize.py -v

Quy tắc chuẩn hoá đóng băng nên test này đóng vai "hợp đồng": sửa hành vi của normalize.py
mà test đỏ nghĩa là element_id sẽ đổi theo, phải báo cả nhóm.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from parser.elements import element_uid  # noqa: E402  # pyrefly: ignore[missing-import]
from parser.hierarchy import _COMMENT as HIERARCHY_COMMENT  # noqa: E402
from parser.normalize import _COMMENT, clean_latex, normalize_math  # noqa: E402


def both(s: str) -> str:
    """Đúng thứ tự pipeline (schema_m2.md mục 4)."""
    return normalize_math(clean_latex(s))


# --------------------------------------------------------------------------- #
# Bốn ca bắt buộc của checklist
# --------------------------------------------------------------------------- #
def test_double_dollar_to_equation():
    assert normalize_math("so $$a+b$$ end") == r"so \begin{equation}a+b\end{equation} end"


def test_bracket_display_to_equation():
    assert normalize_math(r"so \[ a+b \] end") == r"so \begin{equation}a+b\end{equation} end"


def test_paren_inline_to_dollar():
    assert normalize_math(r"so \(a+b\) end") == "so $a+b$ end"


def test_figure_placement_removed():
    assert clean_latex(r"\begin{figure}[htbp] x \end{figure}") == r"\begin{figure}x\end{figure}"
    assert clean_latex(r"\begin{table*}[t!] x \end{table*}") == r"\begin{table*}x\end{table*}"


# --------------------------------------------------------------------------- #
# Không làm hỏng lệnh hình (đề Milestone 1 yêu cầu giữ nguyên)
# --------------------------------------------------------------------------- #
FIGURE = (
    "\\begin{figure}[htbp]\n  \\centering\n"
    "  \\includegraphics[width=0.8\\textwidth]{figs/a.png}\n"
    "  \\caption{\\small A \\textbf{bold} caption.}\n  \\label{fig:a}\n\\end{figure}"
)


def test_includegraphics_and_figure_survive():
    out = both(FIGURE)
    assert r"\begin{figure}" in out and r"\end{figure}" in out
    assert r"\includegraphics[width=0.8\textwidth]{figs/a.png}" in out
    assert r"\caption{A bold caption.}" in out
    assert "[htbp]" not in out and r"\centering" not in out and r"\label" not in out


def test_figure_dedups_with_or_without_centering():
    v1 = "\\begin{figure}[t]\\centering\\includegraphics{a.png}\\caption{X}\\end{figure}"
    v2 = "\\begin{figure}\n\n  \\includegraphics{a.png}\n  \\caption{X}\n  \\label{fig:new}\n\\end{figure}"
    assert both(v1) == both(v2)


# --------------------------------------------------------------------------- #
# Tính ổn định f(f(x)) == f(x)
# --------------------------------------------------------------------------- #
SAMPLES = [
    r"\textbf{a \emph{b}} end",                       # ngoặc lồng: code mẫu ban đầu vi phạm ca này
    r"\textbf{\textit{\emph{deep}}} x",
    "We study\nmatching.\n\n\n\nNew   paragraph\twith  tabs.",
    r"a \\[2pt] b \[ x \] c",
    r"\begin{align} a &= b \\ c &= d \end{align}",
    r"$ x $ and $y$ and \( z \) and $$ w $$",
    r"$a$$b$ then $c$$d$",
    r"\(\) $ $ $$ $$ empty",
    "text % comment with $$ and \\[\nreal $$x$$",
    FIGURE,
    r"{\small foo} bar \caption{\small baz} \hline \\\hline",
    r"\begin{alignat}{2} a &= b & c &= d \end{alignat}",
    r"price is \$5 and \$6 and 50\% off",
]


@pytest.mark.parametrize("x", SAMPLES)
def test_clean_idempotent(x):
    once = clean_latex(x)
    assert clean_latex(once) == once


@pytest.mark.parametrize("x", SAMPLES)
def test_math_idempotent(x):
    once = normalize_math(x)
    assert normalize_math(once) == once


@pytest.mark.parametrize("x", SAMPLES)
def test_pipeline_idempotent(x):
    once = both(x)
    assert both(once) == once


# Mảnh LaTeX hợp lệ: công thức và môi trường luôn đủ cặp, không lồng sai kiểu (khối trong
# inline). Chỉ ngoặc nhóm { } là cố tình lệch cặp, vì bản thảo thật hay gặp.
FRAGMENTS = [
    r"\textbf{", r"\emph{", "}", "{", r"\small ", r"{\large ", r"\centering", r"\hline", r"\\", r"\\[3pt]",
    r"$ x $", r"$y$", r"$$ w $$", r"\( z \)", r"\[ v \]", r"\(\)", "$ $",
    r"\begin{equation} a+b \end{equation}", r"\begin{align*} a &= b \\ c &= d \end{align*}",
    r"\begin{gather} a \end{gather}", r"\begin{figure}[h] \centering \includegraphics{a} \end{figure}",
    r"\begin{table}[t] \hline x \end{table}",
    r"\includegraphics{a}", r"\caption{", r"\label{x}", r"\cite{a,b}", r"\%", r"\$", "%c\n",
    "word", " ", "  ", "\n", "\n\n", "x_1", "a+b", ".", "Fig. 1",
]
# Mảnh hỏng: thêm dấu $, \( \), \[ \] và begin/end lẻ loi. LaTeX như vậy không biên dịch được nên
# không đòi ổn định, chỉ đòi không sập và cùng đầu vào thì cùng đầu ra (dedup vẫn đúng).
BROKEN = FRAGMENTS + ["$", "$$", r"\(", r"\)", r"\[", r"\]",
                      r"\begin{equation}", r"\end{equation}", r"\begin{align*}", r"\end{align*}",
                      r"\begin{figure}[h]", r"\end{figure}", r"\begin{math}"]


def _random_docs(pool, seed, n):
    rng = random.Random(seed)
    for _ in range(n):
        yield "".join(rng.choice(pool) for _ in range(rng.randint(1, 25)))


def test_fuzz_idempotent():
    """3000 chuỗi ngẫu nhiên từ mảnh LaTeX hợp lệ (ngoặc nhóm lệch cặp cũng có): f(f(x)) == f(x)."""
    for x in _random_docs(FRAGMENTS, 20261115, 3000):
        c = clean_latex(x)
        assert clean_latex(c) == c, f"clean_latex không ổn định: {x!r}"
        m = normalize_math(x)
        assert normalize_math(m) == m, f"normalize_math không ổn định: {x!r}"
        p = both(x)
        assert both(p) == p, f"pipeline không ổn định: {x!r}"


def test_fuzz_broken_input_deterministic_no_crash():
    for x in _random_docs(BROKEN, 7, 2000):
        assert both(x) == both(x)


# --------------------------------------------------------------------------- #
# Các lỗi của code mẫu trong đề việc
# --------------------------------------------------------------------------- #
def test_nested_braces():
    assert clean_latex(r"\textbf{a \emph{b}} end") == "a b end"


def test_table_linebreak_is_not_display_math():
    src = r"a \\[2pt] b \[ x \]"
    assert normalize_math(src) == r"a \\[2pt] b \begin{equation}x\end{equation}"


def test_text_in_math_untouched():
    assert both(r"$x = 1 \text{ if } y$") == r"$x = 1 \text{ if } y$"
    assert both(r"$$\mbox{rank}(A)$$") == r"\begin{equation}\mbox{rank}(A)\end{equation}"


def test_line_wrapping_does_not_break_dedup():
    assert both("We study\nmatching.") == both("We study matching.") == "We study matching."
    assert both("A.\n\nB.") == "A.\n\nB."          # ranh giới đoạn được giữ


def test_inline_math_spacing():
    assert both(r"so $ x $ and $x$") == "so $x$ and $x$"
    assert both(r"so \( x \) and $x$") == both("so $x$ and $x$")


def test_adjacent_inline_not_read_as_display():
    assert normalize_math("$a$$b$") == "$a$$b$"
    assert normalize_math(r"\(a\)\(b\)") == "$a$$b$"


def test_empty_math_dropped():
    assert normalize_math(r"x \(\) y $ $ z") == "x y z"


def test_align_family_wrapped_in_aligned():
    out = normalize_math(r"\begin{align*} a &= b \\ c &= d \end{align*}")
    assert out == r"\begin{equation}\begin{aligned}a &= b \\ c &= d\end{aligned}\end{equation}"
    out = normalize_math(r"\begin{alignat}{2} a &= b \end{alignat}")
    assert out == r"\begin{equation}\begin{aligned}a &= b\end{aligned}\end{equation}"
    out = normalize_math(r"\begin{gather} a \\ b \end{gather}")
    assert out == r"\begin{equation}\begin{gathered}a \\ b\end{gathered}\end{equation}"


def test_equation_envs_unified_and_stripped():
    for src in (
        "\\begin{equation}\n  a+b\n\\end{equation}",
        r"\begin{equation*}a+b\end{equation*}",
        r"\begin{displaymath} a+b \end{displaymath}",
        "$$ a+b $$",
        r"\[a+b\]",
    ):
        assert both(src) == r"\begin{equation}a+b\end{equation}"


def test_escaped_dollar_and_percent_kept():
    assert both(r"costs \$5 and \$6, 50\% off") == r"costs \$5 and \$6, 50\% off"


def test_unmatched_dollar_left_alone():
    assert normalize_math("a $ b") == "a $ b"


# --------------------------------------------------------------------------- #
# Comment, label, ref, cite
# --------------------------------------------------------------------------- #
def test_comment_regex_matches_hierarchy():
    assert _COMMENT.pattern == HIERARCHY_COMMENT.pattern


# def test_comment_after_linebreak_is_stripped():
#     assert both(r"line 1\\% comment here" + "\n" + r"line 2") == r"line 1\\ line 2"
#     assert both(r"line 1\\\% not a comment") == r"line 1\\\% not a comment"
#     assert both(r"line 1\\\\% comment" + "\n" + r"line 2") == r"line 1\\\\ line 2"

def test_comment_with_dollars_cannot_pair_with_real_math():
    assert both("see % cost $$\nreal $$x$$") == r"see real \begin{equation}x\end{equation}"


def test_label_removed_ref_and_cite_kept():
    out = both(r"Eq.~\eqref{e1} and \ref{f1} \cite{b,a}\label{x}")
    assert out == r"Eq.~\eqref{e1} and \ref{f1} \cite{b,a}"


def test_label_inside_equation_removed():
    assert both(r"\begin{equation} a \label{e} \end{equation}") == r"\begin{equation}a\end{equation}"


# --------------------------------------------------------------------------- #
# Lệnh định dạng
# --------------------------------------------------------------------------- #
def test_format_commands_removed():
    src = "\\noindent\\small Some text\\vspace{-2mm}\n\\begin{tabular}{cc}\\toprule A & B \\\\ \\midrule 1 & 2 \\\\ \\bottomrule\\end{tabular}"
    out = clean_latex(src)
    for bad in (r"\noindent", r"\small", r"\vspace", r"\toprule", r"\midrule", r"\bottomrule"):
        assert bad not in out
    assert r"A & B \\" in out and r"\begin{tabular}{cc}" in out


def test_row_break_before_hline_survives():
    assert clean_latex(r"a \\ \hline b") == r"a \\ b"
    assert clean_latex(r"a \\\hline b") == r"a \\ b"
    assert "hline" in clean_latex(r"literal \\hline text")   # \\ + chữ "hline", không phải lệnh


def test_declaration_group_unwrapped_only_when_standalone():
    assert clean_latex(r"x {\small foo} y") == "x foo y"
    assert clean_latex(r"\caption{\small foo}") == r"\caption{foo}"


def test_style_commands_keep_content():
    assert clean_latex(r"\texttt{x} \textsc{Y} \underline{z} \textit{w}") == "x Y z w"
    assert clean_latex(r"\text{keep} \mbox{keep}") == r"\text{keep} \mbox{keep}"


# --------------------------------------------------------------------------- #
# Dedup đầu-cuối: chữ "khác một chút" giữa hai version phải ra cùng element_id
# --------------------------------------------------------------------------- #
def test_same_sentence_same_element_id():
    v1 = "We study the \\textbf{citation}   matching\nproblem. % old note"
    v2 = "We study the citation matching problem."
    assert both(v1) == both(v2)
    assert element_uid("2310-12345", "sentence", both(v1)) == element_uid("2310-12345", "sentence", both(v2))


def test_different_sentence_different_element_id():
    a = element_uid("2310-12345", "sentence", both("We study matching."))
    b = element_uid("2310-12345", "sentence", both("We study matching again."))
    assert a != b


def test_empty_and_whitespace_only():
    assert clean_latex("") == "" and clean_latex(" \n\t ") == ""
    assert normalize_math("") == ""