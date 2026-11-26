"""Tests cho src/export_hf.py: validate schema, preflight, sharding Parquet và manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import export_hf  # noqa: E402


def _make_sample_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    corpus = tmp_path / "corpus"
    parsed = tmp_path / "parsed"
    ids_file = tmp_path / "24120152.txt"
    ids = ["2504.12523", "2504.12524"]
    ids_file.write_text("# comment\n2504.12523v1\n2504.12524\n2504.12523\n", encoding="utf-8")

    for i, aid in enumerate(ids):
        pk = config.pub_key(aid)
        cdir = corpus / pk
        pdir = parsed / pk
        cdir.mkdir(parents=True)
        pdir.mkdir(parents=True)

        (cdir / "paper_meta.json").write_text(json.dumps({
            "arxiv_id": aid,
            "title": f"Paper {i}",
            "authors": ["Alice", "Bob"],
            "submission_date": "2025-04-01T00:00:00+00:00",
            "revised_dates": ["2025-04-02T00:00:00+00:00"] if i == 0 else [],
            "venue": None if i == 0 else "NeurIPS",
        }), encoding="utf-8")

        refs = [] if i == 1 else [{
            "arxiv_id": aid,
            "ref_s2_id": "s2-1",
            "ref_title": "Ref Title",
            "ref_authors": ["Carol"],
            "ref_submission_date": None,
            "ref_arxiv_id": "2301.00001",
            "has_arxiv_id": True,
            "ref_venue": "ICLR",
            "ref_year": 2023,
        }]
        (cdir / "references.json").write_text(json.dumps({
            "arxiv_id": aid,
            "status": "ok" if i == 0 else "not_indexed",
            "n_total": len(refs),
            "n_with_arxiv": len(refs),
            "references": refs,
        }), encoding="utf-8")

        elems = [
            {"element_id": f"{pk}#doc_00000001", "arxiv_id": aid, "kind": "document", "content": f"{aid}v1"},
            {"element_id": f"{pk}#snt_00000001", "arxiv_id": aid, "kind": "sentence", "content": f"Hello {i}."},
        ]
        if i == 0:
            elems.append({"element_id": f"{pk}#snt_00000002", "arxiv_id": aid, "kind": "sentence", "content": "Second."})
        (pdir / "elements.jsonl").write_text("\n".join(json.dumps(r) for r in elems), encoding="utf-8")

        hier = [
            {"arxiv_id": aid, "version": 1, "element_id": f"{pk}#snt_00000001", "parent_id": f"{pk}#doc_00000001"},
        ]
        (pdir / "hierarchy.jsonl").write_text("\n".join(json.dumps(r) for r in hier), encoding="utf-8")

        bib = [] if i == 1 else [{
            "arxiv_id": aid,
            "citation_key": "k1",
            "entry_type": "article",
            "title": "Cited Work",
            "authors": ["Dan"],
            "year": 2022,
            "doi": None,
            "journal": "JMLR",
            "url": None,
        }]
        (pdir / "bibtex.jsonl").write_text("\n".join(json.dumps(r) for r in bib), encoding="utf-8")

    return corpus, parsed, ids_file


def test_load_assigned_ids(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# header\n\n2504.12523v2\n2504.12524\n2504.12523\n", encoding="utf-8")
    assert export_hf._load_assigned_ids(f) == ["2504.12523", "2504.12524"]

    empty = tmp_path / "empty.txt"
    empty.write_text("# only comment\n\n", encoding="utf-8")
    with pytest.raises(export_hf.ExportError):
        export_hf._load_assigned_ids(empty)
    with pytest.raises(export_hf.ExportError):
        export_hf._load_assigned_ids(tmp_path / "missing.txt")


def test_row_validators_catch_bad_inputs():
    with pytest.raises(export_hf.ExportError):
        export_hf._hierarchy_row(
            {"arxiv_id": "2504.12523", "version": 0, "element_id": "a", "parent_id": "b"},
            "2504.12523",
            "h",
        )
    with pytest.raises(export_hf.ExportError):
        export_hf._bibtex_row(
            {
                "arxiv_id": "2504.12523", "citation_key": "k1", "entry_type": "article",
                "title": None, "authors": None, "year": True, "doi": None, "journal": None, "url": None,
            },
            "2504.12523",
            "b",
        )
    with pytest.raises(export_hf.ExportError):
        export_hf._reference_row(
            {
                "arxiv_id": "2504.12523", "ref_s2_id": None, "ref_title": None,
                "ref_authors": [], "ref_submission_date": None, "ref_arxiv_id": "2301.00001",
                "has_arxiv_id": False, "ref_venue": None, "ref_year": None,
            },
            "2504.12523",
            "r",
        )


def test_preflight_requires_all_five_inputs(tmp_path):
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    (parsed / config.pub_key("2504.12524") / "bibtex.jsonl").unlink()
    ids = export_hf._load_assigned_ids(ids_file)
    with pytest.raises(export_hf.ExportError, match="Thiếu 1 file đầu vào"):
        export_hf._preflight(ids, corpus, parsed)


def test_export_dataset_end_to_end_and_sharding(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    _ = pa

    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    out = tmp_path / "hf_out"
    rc = export_hf.main([
        "--mssv", "24120152",
        "--ids-file", str(ids_file),
        "--corpus", str(corpus),
        "--parsed", str(parsed),
        "--out", str(out),
        "--shard-rows", "2",
    ])
    assert rc == 0

    readme = (out / "README.md").read_text(encoding="utf-8")
    for name in export_hf.TABLE_NAMES:
        assert f"config_name: {name}" in readme
        assert f'path: "data/{name}/*.parquet"' in readme

    manifest = json.loads((out / "metadata" / "export-manifest-24120152.json").read_text(encoding="utf-8"))
    assert manifest["n_publications"] == 2
    assert manifest["n_rows_papers"] == 2
    assert manifest["n_rows_references"] == 1
    assert manifest["n_rows_elements"] == 5
    assert manifest["n_shards_elements"] == 3
    assert manifest["n_rows_hierarchy"] == 2
    assert manifest["n_rows_bibtex"] == 1
    assert manifest["predictions_included"] is False

    elem_shards = sorted((out / "data" / "elements").glob("*.parquet"))
    assert len(elem_shards) == 3
    assert sum(pq.read_table(p).num_rows for p in elem_shards) == 5

    # Không có --overwrite thì không ghi đè
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 1

    # Có --overwrite thì ghi đè sạch sẽ
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out), "--overwrite",
    ]) == 0


def test_export_fails_on_bad_reference_status(tmp_path):
    pytest.importorskip("pyarrow")
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    ref_path = corpus / config.pub_key("2504.12523") / "references.json"
    data = json.loads(ref_path.read_text(encoding="utf-8"))
    data["status"] = "rate_limited"
    ref_path.write_text(json.dumps(data), encoding="utf-8")

    out = tmp_path / "hf_bad"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 1
    assert not out.exists()
