from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Đảm bảo test chạy độc lập dù có hay chưa có conftest.py
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from parser.bib import parse_bibitem, read_bib_file, split_bibitems


SAMPLE_BIB = """
@article{vaswani2017attention,
  title = {{Attention} Is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  journal = {Advances in Neural Information Processing Systems},
  year = {2017},
  doi = {10.5555/3295222},
  url = {https://arxiv.org/abs/1706.03762}
}

@book{goodfellow2016deep,
  title = {Deep Learning},
  author = {Ian Goodfellow and Yoshua Bengio},
  year = 2016
}

@misc{anonymous2022repo,
  title = {Open Source Codebase},
  year = 2022
}

@article{devlin2018bert,
  title = {BERT: Pre-training of Deep Bidirectional Transformers},
  author = {Jacob Devlin and Ming-Wei Chang},
  eprint = {arXiv:1810.04805},
  year = 2018
}

@article{old_physics1999,
  title = {Superstring Theory Analysis},
  author = {John Doe},
  eprint = {hep-th/9901001},
  year = 1999
}
"""

SAMPLE_TEX = r"""
\begin{thebibliography}{99}

% Có nhãn ngoặc vuông [...]
\bibitem[Vaswani et al., 2017]{vaswani2017}
A. Vaswani, N. Shazeer, et al. ``Attention Is All You Need''.
In \emph{NeurIPS}, 2017. doi:10.5555/3295222.

% Không có nhãn ngoặc vuông
\bibitem{goodfellow2016}
I. Goodfellow and Y. Bengio. \textbf{Deep Learning}. MIT Press, 2016. https://deeplearningbook.org

% Mục này bị comment - KHÔNG ĐƯỢC BẮT
% \bibitem{commented_key} B. Commented. ``Ignored Paper''. 2020.

% Chứa arXiv ID chuẩn mới
\bibitem{devlin2018bert}
J. Devlin, M. Chang. \emph{BERT: Pre-training of Deep Bidirectional Transformers}.
arXiv: 1810.04805, 2018.

% Chứa arXiv ID kiểu cũ (có dấu /) VÀ là mục cuối trước \end{thebibliography}
\bibitem[Maldacena, 1998]{maldacena1998}
J. Maldacena. ``The Large N Limit of Superconformal Field Theories''.
Adv. Theor. Math. Phys. 2:231-252, 1998. arXiv:hep-th/9901001.

\end{thebibliography}
\end{document}
"""

# Test read_bib_file

def test_read_bib_file_standard_entries(tmp_path: Path):
    """Kiểm tra đọc file .bib chuẩn (@article và @book)."""
    bib_file = tmp_path / "refs.bib"
    bib_file.write_text(SAMPLE_BIB, encoding="utf-8")

    entries = read_bib_file(bib_file)
    assert len(entries) == 5

    # Entry 1: @article
    e1 = entries[0]
    assert e1["citation_key"] == "vaswani2017attention"
    assert e1["entry_type"] == "article"
    assert e1["title"] == "Attention Is All You Need"
    assert e1["authors"] == ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]
    assert e1["year"] == 2017
    assert e1["doi"] == "10.5555/3295222"
    assert e1["journal"] == "Advances in Neural Information Processing Systems"
    assert e1["url"] == "https://arxiv.org/abs/1706.03762"
    assert e1["arxiv_id"] == "1706.03762"

    # Entry 2: @book khuyết doi, url
    e2 = entries[1]
    assert e2["citation_key"] == "goodfellow2016deep"
    assert e2["entry_type"] == "book"
    assert e2["year"] == 2016
    assert e2["doi"] is None
    assert e2["url"] is None


def test_read_bib_file_edge_cases(tmp_path: Path):
    """Kiểm tra các ca biên: thiếu author, @misc không journal, file rỗng."""
    bib_file = tmp_path / "edge.bib"
    bib_file.write_text(SAMPLE_BIB, encoding="utf-8")
    entries = read_bib_file(bib_file)

    # Entry @misc thiếu tác giả và không có journal
    e_misc = next(e for e in entries if e["citation_key"] == "anonymous2022repo")
    assert e_misc["entry_type"] == "misc"
    assert e_misc["authors"] is None
    assert e_misc["journal"] is None
    assert e_misc["year"] == 2022

    # Trích xuất arXiv ID từ eprint dạng mới và dạng cũ
    e_bert = next(e for e in entries if e["citation_key"] == "devlin2018bert")
    assert e_bert["arxiv_id"] == "1810.04805"

    e_old = next(e for e in entries if e["citation_key"] == "old_physics1999")
    assert e_old["arxiv_id"] == "hep-th/9901001"

    # File rỗng -> trả về []
    empty_bib = tmp_path / "empty.bib"
    empty_bib.write_text("", encoding="utf-8")
    assert read_bib_file(empty_bib) == []

    # File không tồn tại -> trả về []
    assert read_bib_file(tmp_path / "not_found.bib") == []


def test_read_bib_file_syntax_error_raises(tmp_path: Path):
    """Không nuốt exception: file hỏng cú pháp nghiêm trọng phải raise lỗi, không trả []."""
    corrupt_bib = tmp_path / "corrupt.bib"
    corrupt_bib.write_text("@article{broken_entry, title={Missing closing brace", encoding="utf-8")

    with pytest.raises(ValueError):
        read_bib_file(corrupt_bib)


# Test split_bibitems & parse_bibitem

def test_split_bibitems_ignores_comments_and_limits_env():
    """Kiểm tra cắt mục bibitem: bỏ qua comment, không bỏ ngoài thebibliography."""
    items = split_bibitems(SAMPLE_TEX)
    assert len(items) == 4
    keys = [it[0] for it in items]
    assert "commented_key" not in keys
    assert keys == ["vaswani2017", "goodfellow2016", "devlin2018bert", "maldacena1998"]

    # Mục cuối trước \end{thebibliography}
    assert r"\end{thebibliography}" not in items[3][1]
    assert r"\end{document}" not in items[3][1]


def test_split_bibitems_multiple_environments():
    """Kiểm tra khi tài liệu có nhiều khối thebibliography riêng biệt."""
    two_bibs_tex = r"""
    \begin{thebibliography}{9}
    \bibitem{ref1} Author One. Title One. 2021.
    \end{thebibliography}
    Some middle content.
    \begin{thebibliography}{9}
    \bibitem{ref2} Author Two. Title Two. 2022.
    \end{thebibliography}
    """
    items = split_bibitems(two_bibs_tex)
    assert len(items) == 2
    assert items[0][0] == "ref1"
    assert "Some middle content" not in items[0][1]
    assert items[1][0] == "ref2"


def test_parse_bibitem_all_cases():
    """Kiểm tra parse_bibitem: đầy đủ danh sách tác giả, arXiv mới/cũ, bảo toàn raw."""
    # Đầy đủ danh sách tác giả
    raw_vaswani = "A. Vaswani, N. Shazeer, et al. ``Attention Is All You Need''. In NeurIPS, 2017."
    p_vaswani = parse_bibitem("vaswani2017", raw_vaswani)
    assert p_vaswani["title"] == "Attention Is All You Need"
    assert p_vaswani["authors"] == ["A. Vaswani", "N. Shazeer", "et al"]
    assert p_vaswani["year"] == 2017

    # Dạng tên BibTeX "Last, First and Last, First" (không bị tách nhầm thành 4 phần)
    raw_bibtex_names = "Vaswani, Ashish and Shazeer, Noam. ``Attention Is All You Need''. In NeurIPS, 2017."
    p_bibtex_names = parse_bibitem("vaswani2017", raw_bibtex_names)
    assert p_bibtex_names["authors"] == ["Vaswani, Ashish", "Shazeer, Noam"]

    # Tác giả nối bằng ký tự '&' hoặc dạng LaTeX '\&'
    raw_amp = "A. Smith & B. Jones. ``Graph Neural Networks''. 2020."
    p_amp = parse_bibitem("smith2020", raw_amp)
    assert p_amp["authors"] == ["A. Smith", "B. Jones"]

    raw_latex_amp = r"A. Smith \& B. Jones. ``Graph Neural Networks''. 2020."
    p_latex_amp = parse_bibitem("smith2020_latex", raw_latex_amp)
    assert p_latex_amp["authors"] == ["A. Smith", "B. Jones"]

    # arXiv ID mới
    raw_bert = "J. Devlin, M. Chang. \\emph{BERT}. arXiv: 1810.04805, 2018."
    p_bert = parse_bibitem("devlin2018bert", raw_bert)
    assert p_bert["arxiv_id"] == "1810.04805"
    assert p_bert["title"] == "BERT"
    assert p_bert["year"] == 2018
    assert p_bert["authors"] == ["J. Devlin", "M. Chang"]
    assert p_bert["raw"] == raw_bert

    # arXiv ID cũ trước 2007 có dấu slash
    raw_old = "J. Maldacena. ``AdS/CFT''. 1998. arXiv:hep-th/9901001."
    p_old = parse_bibitem("maldacena1998", raw_old)
    assert p_old["arxiv_id"] == "hep-th/9901001"
    assert p_old["title"] == "AdS/CFT"
    assert p_old["year"] == 1998
    assert p_old["raw"] == raw_old


def test_parse_bibitem_preserves_multiline_raw():
    """Đảm bảo cột raw giữ nguyên vẹn chuỗi gốc (xuống dòng, thụt lề, khoảng trắng thừa)."""
    raw_multiline = (
        "  A. Vaswani, N. Shazeer, et al.\n"
        "    ``Attention Is All You Need''.\n"
        "    In \\emph{NeurIPS}, 2017. doi:10.5555/3295222.  "
    )
    parsed = parse_bibitem("vaswani2017", raw_multiline)

    assert parsed["citation_key"] == "vaswani2017"
    assert parsed["title"] == "Attention Is All You Need"
    assert parsed["authors"] == ["A. Vaswani", "N. Shazeer", "et al"]
    assert parsed["year"] == 2017
    assert parsed["doi"] == "10.5555/3295222"
    assert parsed["raw"] == raw_multiline
