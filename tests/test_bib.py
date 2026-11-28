from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Đảm bảo test chạy độc lập dù có hay chưa có conftest.py
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from parser.bib import collect_bib, parse_bibitem, read_bib_file, split_bibitems


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


# Test collect_bib

def test_collect_bib_bib_only(tmp_path: Path):
    """Kiểm tra collect_bib khi thư mục chỉ có file .bib."""
    bib_file = tmp_path / "refs.bib"
    bib_file.write_text(SAMPLE_BIB, encoding="utf-8")

    entries = collect_bib(tmp_path)
    assert len(entries) == 5
    keys = {e["citation_key"] for e in entries}
    assert "vaswani2017attention" in keys
    assert "devlin2018bert" in keys


def test_collect_bib_tex_only(tmp_path: Path):
    """Kiểm tra collect_bib khi thư mục chỉ có file .tex chứa thebibliography."""
    tex_file = tmp_path / "main.tex"
    tex_file.write_text(SAMPLE_TEX, encoding="utf-8")

    entries = collect_bib(tmp_path)
    assert len(entries) == 4
    keys = {e["citation_key"] for e in entries}
    assert keys == {"vaswani2017", "goodfellow2016", "devlin2018bert", "maldacena1998"}


def test_collect_bib_both_sources_with_overlap(tmp_path: Path):
    """Kiểm tra ca trọng tâm: có cả .bib và thebibliography, trùng key -> .bib luôn thắng."""
    # File .tex định nghĩa vaswani2017 dạng thô
    tex_file = tmp_path / "paper.tex"
    tex_file.write_text(
        r"""
        \begin{thebibliography}{1}
        \bibitem{vaswani2017} A. Vaswani et al. ``Attention Is All You Need''. 2017.
        \bibitem{tex_only_key} B. Author. ``Only In TeX''. 2021.
        \end{thebibliography}
        """,
        encoding="utf-8",
    )

    # File .bib định nghĩa vaswani2017 dạng có cấu trúc và trường journal
    bib_file = tmp_path / "paper.bib"
    bib_file.write_text(
        """
        @article{vaswani2017,
          title = {Attention Is All You Need},
          author = {Ashish Vaswani and Noam Shazeer},
          journal = {NeurIPS},
          year = {2017},
          doi = {10.5555/3295222}
        }
        @misc{bib_only_key,
          title = {Only In Bib},
          year = {2022}
        }
        """,
        encoding="utf-8",
    )

    entries = collect_bib(tmp_path)
    # Tổng cộng 3 key duy nhất: vaswani2017 (trùng), tex_only_key, bib_only_key
    assert len(entries) == 3
    by_key = {e["citation_key"]: e for e in entries}

    assert "tex_only_key" in by_key
    assert "bib_only_key" in by_key
    assert "vaswani2017" in by_key

    # Bản vaswani2017 phải lấy từ file .bib (có journal, không có trường 'raw')
    vaswani = by_key["vaswani2017"]
    assert vaswani["journal"] == "NeurIPS"
    assert vaswani["doi"] == "10.5555/3295222"
    assert "raw" not in vaswani or vaswani.get("raw") is None


def test_collect_bib_empty_and_nonexistent(tmp_path: Path):
    """Kiểm tra thư mục rỗng, không tồn tại hoặc không chứa tham chiếu."""
    assert collect_bib(tmp_path / "nonexistent") == []
    assert collect_bib(tmp_path) == []

    # File .tex không có thebibliography
    (tmp_path / "empty.tex").write_text("Hello world without bibliography", encoding="utf-8")
    assert collect_bib(tmp_path) == []


def test_collect_bib_nested_subdirectories(tmp_path: Path):
    """Kiểm tra quét đệ quy tìm .bib và .tex trong các thư mục con."""
    sub_tex = tmp_path / "sections" / "appendix"
    sub_tex.mkdir(parents=True)
    (sub_tex / "app.tex").write_text(
        r"""
        \begin{thebibliography}{1}
        \bibitem{nested_tex_ref} Nested Author. ``Nested Title''. 2023.
        \end{thebibliography}
        """,
        encoding="utf-8",
    )

    sub_bib = tmp_path / "assets" / "bib"
    sub_bib.mkdir(parents=True)
    (sub_bib / "extra.bib").write_text(
        """
        @article{nested_bib_ref,
          title = {Nested Bib Title},
          year = {2024}
        }
        """,
        encoding="utf-8",
    )

    entries = collect_bib(tmp_path)
    assert len(entries) == 2
    keys = {e["citation_key"] for e in entries}
    assert keys == {"nested_tex_ref", "nested_bib_ref"}


def test_collect_bib_failed_blocks_tracking(tmp_path: Path):
    """Kiểm tra collect_bib thu thập failed_blocks và ghi nhận lỗi khi có block lỗi cú pháp."""
    (tmp_path / "broken.bib").write_text(
        """
        @article{ok_key,
          title = {OK Title},
          year = {2024}
        }
        @article{broken_key,
          title = {Broken Title
        """,
        encoding="utf-8",
    )
    failed: list[Any] = []
    errors: list[str] = []
    entries = collect_bib(tmp_path, failed_blocks_out=failed, errors_out=errors)
    assert len(entries) == 1
    assert entries[0]["citation_key"] == "ok_key"
    assert len(failed) == 1


def test_collect_bib_emits_warning_even_without_failed_blocks_arg(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Kiểm tra collect_bib luôn phát cảnh báo warning kể cả khi caller không truyền failed_blocks_out."""
    import logging

    (tmp_path / "broken.bib").write_text(
        """
        @article{ok_key2,
          title = {OK Title 2},
          year = {2024}
        }
        @article{broken_key2,
          title = {Broken Title 2
        """,
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        entries = collect_bib(tmp_path)
    assert len(entries) == 1
    assert entries[0]["citation_key"] == "ok_key2"
    assert any("chứa 1 block lỗi cú pháp bị bỏ qua" in r.message for r in caplog.records)


def test_parse_bibitem_revtex_bibinfo():
    """Kiểm tra parse_bibitem trích xuất tiêu đề và tác giả từ định dạng REVTeX có \bibinfo."""
    raw = (
        r"\bibitem{zhang2021} "
        r"\bibinfo{author}{{Zhang}, W.-L.} \emph{et~al.} "
        r"\newblock \bibinfo{title}{{Two Periodic Activity Epochs in FRB 20201124A: Coincident with Critical RM}} "
        r"\newblock \emph{\bibinfo{journal}{Astrophys. J.}} \textbf{\bibinfo{volume}{920}}, "
        r"\bibinfo{pages}{153} (\bibinfo{year}{2021})."
    )
    item = parse_bibitem("zhang2021", raw)
    assert item["citation_key"] == "zhang2021"
    assert item["title"] == "Two Periodic Activity Epochs in FRB 20201124A: Coincident with Critical RM"
    assert item["year"] == 2021
    assert item["authors"] is not None
    assert "Zhang, W.-L." in item["authors"][0]


def test_parse_bibitem_nested_braces_baptista():
    """Kiểm tra parse_bibitem trích xuất tiêu đề có độ lồng ngoặc sâu nhiều cấp như Baptista2024."""
    raw = (
        r"\bibitem[{J. {Baptista} {et~al.}(2024){Baptista}}]{Baptista2024}"
        r"{Baptista}, J., {Prochaska}, J.~X., {Mannings}, A.~G., {et~al.} 2024, "
        r"\bibinfo{title}{{Measuring the Variance of the Macquart Relation in Redshift{\textendash}Extragalactic Dispersion Measure Modeling},} "
        r"\apj, 965, 57, \dodoi{10.3847/1538-4357/ad2705}"
    )
    item = parse_bibitem("Baptista2024", raw)
    assert item["citation_key"] == "Baptista2024"
    assert item["title"] is not None
    assert "Measuring the Variance" in item["title"]
    assert "Extragalactic Dispersion Measure Modeling" in item["title"]
    assert item["year"] == 2024
    assert item["doi"] == "10.3847/1538-4357/ad2705"





def test_read_bib_file_letter_accents_survive_brace_removal(tmp_path: Path):
    r"""Dấu viết bằng chữ cái (\v \c \H) phải đổi sang Unicode trước khi xoá ngoặc.

    Xoá ngoặc trước thì `\v{c}` thành `\vc`, chốt chặn `\bibnamefont` không nhận
    ra dấu nữa và tên bị cắt: `Veli{\v{c}}kovi{\'c}` -> `Veli ć` (đo 27/11).
    """
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{a,\n"
        r"  title={On a problem of {E}rd{\H{o}}s}," "\n"
        r"  author={Veli{\v{c}}kovi{\'c}, Petar and {\v{S}}mejkal, Libor and Gon\c{c}alves, F.}," "\n"
        "  year={2018}\n}\n",
        encoding="utf-8",
    )
    (entry,) = read_bib_file(bib)
    assert entry["authors"] == ["Veličković, Petar", "Šmejkal, Libor", "Gonçalves, F."]
    assert entry["title"] == "On a problem of Erdős"




def test_parse_bibitem_revtex_authors_from_bibinfo():
    """REVTeX: lấy tác giả từ \\bibinfo{author}{...}, không đoán theo dấu phẩy/'and'."""
    raw = (
        r"\BibitemOpen \bibfield {author} {\bibinfo {author} {\bibfnamefont {M.}~\bibnamefont {Alidoust}}, "
        r"\bibinfo {author} {\bibfnamefont {C.}~\bibnamefont {Shen}},\ and\ \bibinfo {author} "
        r"{\bibfnamefont {I.}~\bibnamefont {{\v{Z}}uti{\'c}}},\ }\bibfield {title} {\bibinfo {title} "
        r"{Cubic spin-orbit coupling and anomalous {Josephson} effect in planar junctions},\ }"
        r"\href {https://link.aps.org/doi/10.1103/PhysRevB.103.L060503} {\bibfield {journal} "
        r"{\bibinfo {journal} {Phys. Rev. B}\ }\textbf {\bibinfo {volume} {103}},\ \bibinfo {pages} "
        r"{L060503} (\bibinfo {year} {2021})}\BibitemShut {NoStop}"
    )
    item = parse_bibitem("Alidoust2021", raw)
    assert item["title"] == "Cubic spin-orbit coupling and anomalous Josephson effect in planar junctions"
    assert len(item["authors"]) == 3
    assert "Alidoust" in item["authors"][0] and "Žutić" in item["authors"][2]
    assert not any("\\" in a or "title" in a or "http" in a for a in item["authors"])


def test_parse_bibitem_aps_ifmmode_accent():
    """APS: `\\ifmmode \\check{c}\\else \\v{c}\\fi{}` lấy nhánh \\else, không ra `Skvar č`."""
    raw = (
        r"\BibitemOpen \bibfield {author} {\bibinfo {author} {\bibfnamefont {J.}~\bibnamefont "
        r"{Skvar\ifmmode~\check{c}\else \v{c}\fi{}}}},\ }\bibinfo {journal} {Nucl. Phys. A}"
    )
    (author,) = parse_bibitem("Skvarc", raw)["authors"]
    assert author.endswith("Skvarč")


def test_parse_bibitem_acm_person_and_showarticletitle():
    raw = (
        r"\bibfield{author}{\bibinfo{person}{Valeri Chukhlomin} {et~al\mbox{.}}} \bibinfo{year}{2024}"
        r"\natexlab{}. \newblock \showarticletitle{Socratic Prompts: Engineered Dialogue as a Tool}. "
        r"\newblock \bibinfo{journal}{\emph{Latin American Business and Sustainability Review}}"
    )
    item = parse_bibitem("chukhlomin2024", raw)
    assert item["authors"] == ["Valeri Chukhlomin"]
    assert item["title"] == "Socratic Prompts: Engineered Dialogue as a Tool"


def test_parse_bibitem_note_only_has_no_author():
    raw = (
        r"\BibitemOpen \href@noop {} {}\bibinfo {note} {See Supplemental Material for a discussion "
        r"of the effective mass approximation and computational details.}\BibitemShut {Stop}"
    )
    assert parse_bibitem("SM", raw)["authors"] is None


def test_parse_bibitem_natbib_newblock_title_is_second_field():
    """natbib: trường thứ hai là tiêu đề; \\emph ở trường thứ ba là tên hội nghị."""
    raw = (
        "Jonathan Ho, Ajay Jain, and Pieter Abbeel.\n\\newblock Denoising diffusion probabilistic models.\n"
        "\\newblock \\emph{Advances in neural information processing systems}, 33:\\penalty0 6840--6851, 2020."
    )
    item = parse_bibitem("ho2020denoising", raw)
    assert item["title"] == "Denoising diffusion probabilistic models"
    assert item["authors"] == ["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"]
    assert item["year"] == 2020


def test_parse_bibitem_newblock_url_only_is_not_title():
    raw = r"{BlenderKit}. \newblock {\scriptsize{\url{https://www.blenderkit.com/asset-gallery}}}."
    assert parse_bibitem("blenderkit", raw)["title"] is None


def test_parse_bibitem_textbf_volume_is_not_title():
    raw = r"D.~J.~Gross and E.~Witten, Nucl. Phys. B \textbf{277}, 1 (1986) doi:10.1016/0550-3213(86)90429-3"
    item = parse_bibitem("Gross:1986", raw)
    assert item["title"] is None
    assert item["doi"] == "10.1016/0550-3213(86)90429-3"


def test_parse_bibitem_textit_title_with_nested_accent():
    raw = (
        "M. Albanese, G. Barbaro and M. Lejmi,\n\\textit{ Generalized almost-K\\\"{a}hler-Ricci solitons},\n"
        "Differential Geom. Appl., \\textbf{97} (2024), Paper No. 102193, 27 pp."
    )
    assert parse_bibitem("ABL", raw)["title"] == "Generalized almost-Kähler-Ricci solitons"


def test_parse_bibitem_et_al_variants_normalized():
    raw = r"T.~Abramovich, M.~Udeshi, et~al.\ \newblock Enigma: Enhanced interactive agent. \newblock arXiv, 2024."
    assert parse_bibitem("abramovich2024", raw)["authors"][-1] == "et al"


def test_parse_bibitem_lncs_colon_splits_authors_and_title():
    raw = (
        "{Abou Jaoude}, D., Garoche, P.L., Farhood, M.: Computing state invariants using\n"
        "  point-wise integral quadratic constraints and the {S}-procedure. In: 2021\n"
        "  {A}merican {C}ontrol {C}onference (ACC). pp. 2394--2399 (2021)"
    )
    item = parse_bibitem("AboujaoudeGarocheFarhood21", raw)
    assert item["title"] == (
        "Computing state invariants using point-wise integral quadratic constraints and the S-procedure"
    )
    assert item["authors"] == ["Abou Jaoude, D.", "Garoche, P.L.", "Farhood, M."]
    assert item["year"] == 2021


def test_read_bib_file_field_names_are_case_insensitive(tmp_path: Path):
    """BibDesk ghi `Author = {...}`, `Title = {...}`; tên trường BibTeX không phân biệt hoa thường.

    Trước 27/11 mọi trường ra None (đo trên 2503.12256: 7 entry rỗng hoàn toàn).
    """
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{noiri_highfidelity_2022,\n"
        "\tAuthor = {Noiri, Akito and Takeda, Kenta},\n"
        "\tDoi = {10.1038/s41586-021-04182-y},\n"
        "\tJournal = {Nature},\n"
        "\tTitle = {Fast universal quantum gate above the fault-tolerance threshold in silicon},\n"
        "\tYear = {2022},\n"
        "\tEprint = {2108.02626}}\n",
        encoding="utf-8",
    )
    (e,) = read_bib_file(bib)
    assert e["title"] == "Fast universal quantum gate above the fault-tolerance threshold in silicon"
    assert e["authors"] == ["Noiri, Akito", "Takeda, Kenta"]
    assert (e["year"], e["doi"], e["journal"], e["arxiv_id"]) == (2022, "10.1038/s41586-021-04182-y", "Nature", "2108.02626")


def test_collect_bib_bib_entry_keeps_fields_from_bbl(tmp_path: Path):
    """.bib ghi đè .bbl khi trùng khoá, nhưng không được xoá trường .bib để trống."""
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{1}\n"
        "\\bibitem{site} Some Author.\n\\newblock The project homepage.\n\\newblock 2024.\n"
        "\\end{thebibliography}\n",
        encoding="utf-8",
    )
    (tmp_path / "refs.bib").write_text("@misc{site, note = {Accessed 2024}}\n", encoding="utf-8")
    (e,) = collect_bib(tmp_path)
    assert e["title"] == "The project homepage"
    assert e["authors"] == ["Some Author"]
    assert e["entry_type"] == "misc"                # trường .bib có giá trị vẫn thắng


def test_read_bib_file_normalizes_doi_url_and_year(tmp_path: Path):
    """doi bỏ tiền tố URL, url bỏ chữ thừa phía trước, year không nhận số > MAX_YEAR (đo 27/11)."""
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{a, title={T}, doi={https://doi.org/10.1016/0370-2693(83)91529-0},\n"
        "  url={URl: https://advantage.mandiant.com/}, year={2041, reprinted 2019}}\n"
        "@article{b, title={T}, doi={99.9999/woot07-S422}, url={shorturl.at/gAVpz}, year={2058}}\n",
        encoding="utf-8",
    )
    a, b = read_bib_file(bib)
    assert (a["doi"], a["url"], a["year"]) == ("10.1016/0370-2693(83)91529-0", "https://advantage.mandiant.com/", 2019)
    assert (b["doi"], b["url"], b["year"]) == (None, "shorturl.at/gAVpz", None)


def test_parse_bibitem_year_skips_page_numbers_after_max_year():
    raw = r"A. Smith. \newblock A title. \newblock J. Phys., 12:2041--2058, 2019."
    assert parse_bibitem("smith", raw)["year"] == 2019
