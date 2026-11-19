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

    # Tạo file .tex
    (vdir / "main.tex").write_text(
        r"""
        \begin{thebibliography}{1}
        \bibitem{vaswani2017} A. Vaswani, N. Shazeer. ``Attention Is All You Need''. In NeurIPS, 2017. doi:10.5555/3295222.
        \end{thebibliography}
        """,
        encoding="utf-8",
    )

    # Tạo mock prescan_versions.csv
    prescan_csv = tmp_path / "prescan_versions.csv"
    with open(prescan_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["arxiv_id", "version", "bib_style"])
        writer.writeheader()
        writer.writerow({"arxiv_id": "2503.12000", "version": "v1", "bib_style": "both"})

    stats = evaluate_concordance(prescan_csv, corpus_root)
    assert stats["versions_evaluated"] == 1
    assert stats["overlap_keys_count"] == 1
    assert stats["title_exact_matches"] == 1
    assert stats["author_matches"] == 1
    assert stats["year_matches"] == 1
    assert stats["doi_matches"] == 1

    # Kiểm tra sinh markdown
    report_md = tmp_path / "report.md"
    content = generate_concordance_markdown(stats, report_md)
    assert report_md.exists()
    assert "100.00%" in content
    assert "Attention Is All You Need" not in content  # không leak private data mà chỉ có stats


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
    (v1_dir / "main.tex").write_text(r"Model in \cite{vaswani2017}.", encoding="utf-8")

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
    (v2_dir / "main.tex").write_text(r"Model in \cite{vit_transformer}.", encoding="utf-8")

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
