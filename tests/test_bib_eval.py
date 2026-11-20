from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from parser.bib_eval import (
    BIB_DEDUP_COLUMNS,
    BIB_LOG_COLUMNS,
    _read_version_tex,
    evaluate_concordance,
    generate_concordance_markdown,
    process_publications_dedup,
)


def test_evaluate_concordance_and_markdown(tmp_path: Path):
    corpus_root = tmp_path / "corpus"
    vdir = corpus_root / "2503-12000" / "v1"
    vdir.mkdir(parents=True)

    # Tạo file .bib
    (vdir / "refs.bib").write_text(
        """
        @article{vaswani2017,
          title = {Attention Is All You Need},
          author = {Ashish Vaswani and Noam Shazeer},
          year = {2017},
          doi = {10.5555/3295222}
        }
        """,
        encoding="utf-8",
    )

    # Tạo file .tex có documentclass chuẩn
    (vdir / "main.tex").write_text(
        r"""
        \documentclass{article}
        \begin{document}
        \begin{thebibliography}{1}
        \bibitem{vaswani2017} A. Vaswani, N. Shazeer. ``Attention Is All You Need''. In NeurIPS, 2017. doi:10.5555/3295222.
        \end{thebibliography}
        \end{document}
        """,
        encoding="utf-8",
    )

    # Tạo mock prescan_versions.csv
    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12000", "version": "v1", "bib_style": "both"})

    bib_logs_csv = tmp_path / "logs" / "bib.csv"
    stats = evaluate_concordance(prescan_csv, corpus_root, bib_logs_csv=bib_logs_csv)
    assert stats["versions_evaluated"] == 1
    assert stats["overlap_keys_count"] == 1
    assert stats["title_exact_matches"] == 1
    assert stats["author_matches"] == 1
    assert stats["year_matches"] == 1
    assert stats["doi_matches"] == 1

    # Kiểm tra logs/bib.csv theo schema M2
    assert bib_logs_csv.exists()
    with open(bib_logs_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert list(rows[0].keys()) == BIB_LOG_COLUMNS
        assert rows[0]["arxiv_id"] == "2503.12000"
        assert rows[0]["version"] == "1"
        assert int(rows[0]["n_bibitem"]) == 1
        assert int(rows[0]["n_bibfile_entries"]) == 1
        assert rows[0]["status"] == "ok"
        assert rows[0]["error_type"] == ""

    # Kiểm tra sinh markdown
    report_md = tmp_path / "report.md"
    content = generate_concordance_markdown(stats, report_md)
    assert report_md.exists()
    assert "100.00%" in content
    assert "Attention Is All You Need" not in content  # không leak private data mà chỉ có stats


def test_read_version_tex_compile_path(tmp_path: Path):
    vdir = tmp_path / "corpus" / "2503-12099" / "v1"
    vdir.mkdir(parents=True)

    # Root file có documentclass
    (vdir / "main.tex").write_text(
        r"""
        \documentclass{article}
        \begin{document}
        \input{sections/intro}
        \end{document}
        """,
        encoding="utf-8",
    )
    (vdir / "sections").mkdir()
    (vdir / "sections" / "intro.tex").write_text(r"Intro section text with \cite{ref1}.", encoding="utf-8")

    # File template thừa không nằm trong compile path
    (vdir / "template_unused.tex").write_text(r"\cite{unused_template_key}", encoding="utf-8")

    tex = _read_version_tex(vdir, "2503.12099")
    assert "ref1" in tex
    assert "unused_template_key" not in tex



def test_process_publications_dedup_outputs(tmp_path: Path):
    corpus_root = tmp_path / "corpus"
    v1_dir = corpus_root / "2503-12001" / "v1"
    v2_dir = corpus_root / "2503-12001" / "v2"
    v1_dir.mkdir(parents=True)
    v2_dir.mkdir(parents=True)

    # v1
    (v1_dir / "refs.bib").write_text(
        """
        @article{vaswani2017,
          title = {Attention Is All You Need},
          author = {Ashish Vaswani},
          year = {2017}
        }
        """,
        encoding="utf-8",
    )
    (v1_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Model in \cite{vaswani2017}.\end{document}",
        encoding="utf-8",
    )

    # v2
    (v2_dir / "refs.bib").write_text(
        """
        @article{vit_transformer,
          title = {Attention Is All You Need},
          author = {Ashish Vaswani},
          doi = {10.5555/3295222}
        }
        """,
        encoding="utf-8",
    )
    (v2_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Model in \cite{vit_transformer}.\end{document}",
        encoding="utf-8",
    )

    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12001", "version": "v1", "bib_style": "both"})

    logs_csv = tmp_path / "logs" / "bib_dedup.csv"
    reports_map = tmp_path / "reports" / "cite_rename_map.json"

    n_pubs, n_done = process_publications_dedup(
        prescan_csv,
        corpus_root,
        logs_csv,
        reports_map,
    )
    assert n_pubs == 1
    assert n_done == 1

    # Kiểm tra logs/bib_dedup.csv
    assert logs_csv.exists()
    with open(logs_csv, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        row = reader[0]
        assert list(row.keys()) == BIB_DEDUP_COLUMNS
        assert row["arxiv_id"] == "2503.12001"
        assert int(row["n_before"]) == 2
        assert int(row["n_after"]) == 1
        assert int(row["n_cite_renamed"]) == 1
        assert row["status"] == "ok"

    # Kiểm tra reports/cite_rename_map.json
    assert reports_map.exists()
    with open(reports_map, encoding="utf-8") as f:
        data = json.load(f)
        assert "2503.12001" in data
        assert data["2503.12001"]["n_before"] == 2
        assert data["2503.12001"]["n_after"] == 1
        assert data["2503.12001"]["rename_map"].get("vit_transformer") == "vaswani2017"


def test_generate_concordance_markdown_empty_stats(tmp_path: Path):
    """Đảm bảo không bị ZeroDivisionError khi tập khảo sát rỗng hoặc 0 version."""
    empty_stats = {
        "total_versions_surveyed": 0,
        "versions_evaluated": 0,
        "total_bib_entries": 0,
        "total_bibitem_entries": 0,
        "overlap_keys_count": 0,
        "title_exact_matches": 0,
        "title_soft_matches": 0,
        "author_matches": 0,
        "year_matches": 0,
        "year_both_present": 0,
        "doi_matches": 0,
        "doi_both_present": 0,
        "arxiv_matches": 0,
        "arxiv_both_present": 0,
    }
    report_md = tmp_path / "empty_report.md"
    content = generate_concordance_markdown(empty_stats, report_md)
    assert report_md.exists()
    assert "0.00%" in content


def test_append_csv_preserves_history(tmp_path: Path):
    """Kiểm tra chế độ append-only: chạy lần 2 không xoá lịch sử lần 1."""
    corpus_root = tmp_path / "corpus"
    v1_dir = corpus_root / "2503-12002" / "v1"
    v1_dir.mkdir(parents=True)
    (v1_dir / "refs.bib").write_text("@article{k1, title={T1}, author={A1}, year={2020}}", encoding="utf-8")
    (v1_dir / "main.tex").write_text(r"\cite{k1}", encoding="utf-8")

    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12002", "version": "v1", "bib_style": "both"})

    logs_csv = tmp_path / "logs" / "bib_dedup.csv"
    reports_map = tmp_path / "reports" / "cite_rename_map.json"

    # Chạy lần 1
    process_publications_dedup(prescan_csv, corpus_root, logs_csv, reports_map, append=True, allow_fallback=True)
    with open(logs_csv, encoding="utf-8") as f:
        rows_1 = list(csv.DictReader(f))
    assert len(rows_1) == 1

    # Chạy lần 2 (append=True)
    process_publications_dedup(prescan_csv, corpus_root, logs_csv, reports_map, append=True, allow_fallback=True)
    with open(logs_csv, encoding="utf-8") as f:
        rows_2 = list(csv.DictReader(f))
    assert len(rows_2) == 2, "Chạy lại phải bảo toàn lịch sử lần trước (append-only)"


def test_read_version_tex_no_root_raises_or_fallback(tmp_path: Path):
    """Không có root: ném lỗi nếu allow_fallback=False; fallback nếu allow_fallback=True."""
    vdir = tmp_path / "corpus" / "2503-12003" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "frag.tex").write_text(r"Fragment without root \cite{key_frag}", encoding="utf-8")

    # Mặc định allow_fallback=False -> ném ValueError để không làm lệch thống kê
    with pytest.raises(ValueError, match="gather_fail"):
        _read_version_tex(vdir, "2503.12003", allow_fallback=False)

    # Nếu allow_fallback=True -> fallback an toàn
    tex = _read_version_tex(vdir, "2503.12003", allow_fallback=True)
    assert "key_frag" in tex


def test_read_bib_file_failed_blocks_and_logging(tmp_path: Path):
    """Ghi nhận rõ ràng các block lỗi cú pháp trong .bib thay vì nuốt lỗi âm thầm."""
    from parser.bib import read_bib_file

    bib_file = tmp_path / "broken.bib"
    bib_file.write_text(
        """
        @article{valid1,
          title = {Valid Paper},
          author = {Valid Author},
          year = {2021}
        }

        @article{broken_syntax,
          title = {Incomplete Syntax
        """,
        encoding="utf-8",
    )

    failed: list[Any] = []
    entries = read_bib_file(bib_file, lenient=True, failed_blocks_out=failed)
    assert len(entries) == 1
    assert entries[0]["citation_key"] == "valid1"
    assert len(failed) == 1, "Phải ghi nhận được block bị lỗi cú pháp"

    # Kiểm tra evaluate_concordance ghi error_type vào bib.csv
    corpus_root = tmp_path / "corpus"
    vdir = corpus_root / "2503-12004" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "refs.bib").write_text(bib_file.read_text(encoding="utf-8"), encoding="utf-8")
    (vdir / "main.tex").write_text(r"\cite{valid1}", encoding="utf-8")

    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12004", "version": "v1", "bib_style": "both"})

    bib_logs_csv = tmp_path / "logs" / "bib.csv"
    stats = evaluate_concordance(prescan_csv, corpus_root, bib_logs_csv=bib_logs_csv, append=False)
    assert stats["total_failed_bib_blocks"] == 1

    with open(bib_logs_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "fail"
    assert "bib_syntax_error:1" in rows[0]["error_type"]


def test_evaluate_concordance_no_compile_path_marked_fail(tmp_path: Path):
    """Khi không tìm được compile path (thiếu documentclass), version phải bị đánh dấu fail,
    không được fallback quét toàn bộ *.tex và không thu thập \\bibitem từ file mồ côi.
    """
    corpus_root = tmp_path / "corpus"
    vdir = corpus_root / "2503-12005" / "v1"
    vdir.mkdir(parents=True)

    # File .tex mồ côi (không có documentclass)
    (vdir / "orphan.tex").write_text(
        r"""
        \begin{thebibliography}{1}
        \bibitem{orphan_key} Orphan Author. ``Orphan Title''. 2024.
        \end{thebibliography}
        """,
        encoding="utf-8",
    )

    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12005", "version": "v1", "bib_style": "both"})

    bib_logs_csv = tmp_path / "logs" / "bib.csv"
    stats = evaluate_concordance(prescan_csv, corpus_root, bib_logs_csv=bib_logs_csv, append=False)

    with open(bib_logs_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "fail"
    assert "no_compile_path" in rows[0]["error_type"]
    assert int(rows[0]["n_bibitem"]) == 0
    assert stats["overlap_keys_count"] == 0


def test_generate_concordance_markdown_dynamic_coverage(tmp_path: Path):
    """Báo cáo Markdown phải tính tỷ lệ bao phủ động khi thiếu version trên đĩa."""
    stats = {
        "total_versions_surveyed": 2,
        "versions_evaluated": 1,
        "total_bib_entries": 10,
        "total_bibitem_entries": 10,
        "overlap_keys_count": 5,
        "title_exact_matches": 1,
        "title_soft_matches": 3,
        "author_matches": 4,
        "year_both_present": 5,
        "year_matches": 5,
        "doi_both_present": 2,
        "doi_matches": 2,
        "arxiv_both_present": 0,
        "arxiv_matches": 0,
    }
    report_md = tmp_path / "report_partial.md"
    content = generate_concordance_markdown(stats, report_md)
    assert "Đạt 50.0% (1/2)" in content
    assert "Đầy đủ 100%" not in content


def test_evaluate_concordance_sensitivity_tracking(tmp_path: Path):
    """Kiểm tra evaluate_concordance tính toán động số tham số bibliography và file .bib trên đĩa."""
    corpus_root = tmp_path / "corpus"
    vdir = corpus_root / "2503-12001" / "v1"
    vdir.mkdir(parents=True)

    # 2 file .bib trên đĩa: refs.bib (được gọi) và extra.bib (không được gọi)
    (vdir / "refs.bib").write_text(
        """
        @article{key1,
          title = {Ref Title},
          year = {2024}
        }
        """,
        encoding="utf-8",
    )
    (vdir / "extra.bib").write_text(
        """
        @article{extra1,
          title = {Extra Title},
          year = {2024}
        }
        """,
        encoding="utf-8",
    )

    # File .tex trong compile path có \bibliography{refs,missing}
    (vdir / "main.tex").write_text(
        r"""
        \documentclass{article}
        \begin{document}
        \bibliography{refs,missing}
        \begin{thebibliography}{1}
        \bibitem{key1} Author. ``Ref Title''. 2024.
        \end{thebibliography}
        \end{document}
        """,
        encoding="utf-8",
    )

    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12001", "version": "v1", "bib_style": "both"})

    bib_logs_csv = tmp_path / "logs" / "bib.csv"
    stats = evaluate_concordance(prescan_csv, corpus_root, bib_logs_csv=bib_logs_csv, append=False)

    assert stats["sensitivity_bib_args"] == 2
    assert stats["sensitivity_unresolved_args"] == 1  # 'missing' không tìm thấy
    assert stats["sensitivity_resolved_files"] == 1  # 'refs.bib' resolve thành công
    assert stats["sensitivity_total_disk_files"] == 2  # refs.bib và extra.bib
    assert stats["sensitivity_unreferenced_files"] == 1  # extra.bib

    report_md = tmp_path / "report.md"
    content = generate_concordance_markdown(stats, report_md)
    assert "2 tham số" in content
    assert "1 file `.bib` riêng biệt" in content

