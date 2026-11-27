"""Tests cho src/export_hf.py: validate schema, preflight, sharding Parquet và manifest."""

from __future__ import annotations

import json
import shutil
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


def test_strict_stops_when_an_input_is_missing(tmp_path):
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    (parsed / config.pub_key("2504.12524") / "bibtex.jsonl").unlink()
    ids = export_hf._load_assigned_ids(ids_file)
    with pytest.raises(export_hf.ExportError, match="--strict: 1/2 bài thiếu đầu vào"):
        export_hf._partition_ids(ids, corpus, parsed, strict=True)


@pytest.mark.parametrize(
    ("break_it", "reason"),
    [
        # thư mục parsed chưa có — bài fail hẳn ở M2
        (lambda c, p: shutil.rmtree(p / config.pub_key("2504.12524")),
         export_hf.SKIP_MISSING_PARSED_DIR),
        # thư mục có nhưng thiếu file: parse bị ngắt giữa chừng (elements.jsonl ghi
        # sau cùng nên đây là trạng thái hay gặp nhất sau một lần Ctrl+C)
        (lambda c, p: (p / config.pub_key("2504.12524") / "elements.jsonl").unlink(),
         export_hf.SKIP_MISSING_INPUT_FILE),
        (lambda c, p: (c / config.pub_key("2504.12524") / "paper_meta.json").unlink(),
         export_hf.SKIP_MISSING_INPUT_FILE),
    ],
)
def test_one_broken_paper_is_skipped_not_fatal(tmp_path, break_it, reason):
    """Một bài hỏng trong N bài không được chặn cả lần xuất."""
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    break_it(corpus, parsed)
    ids = export_hf._load_assigned_ids(ids_file)

    export_ids, skipped = export_hf._partition_ids(ids, corpus, parsed)
    assert export_ids == ["2504.12523"]
    assert [s["arxiv_id"] for s in skipped] == ["2504.12524"]
    assert skipped[0]["reason"] == reason
    assert skipped[0]["detail"]


def test_empty_export_still_refused(tmp_path):
    """Bỏ qua từng bài thì được, nhưng bỏ qua HẾT thì không tạo dataset rỗng."""
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    for arxiv_id in ("2504.12523", "2504.12524"):
        shutil.rmtree(parsed / config.pub_key(arxiv_id))
    ids = export_hf._load_assigned_ids(ids_file)
    with pytest.raises(export_hf.ExportError, match="không tạo dataset rỗng"):
        export_hf._partition_ids(ids, corpus, parsed)


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


def _set_reference_status(corpus, arxiv_id: str, status: str) -> None:
    path = corpus / config.pub_key(arxiv_id) / "references.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    path.write_text(json.dumps(data), encoding="utf-8")


def test_bad_reference_status_skips_paper_from_all_five_tables(tmp_path):
    """`rate_limited` nghĩa là reference CHƯA BIẾT, không phải rỗng.

    Bài đó phải biến mất khỏi cả năm bảng, nếu không `papers` có bài mà
    `references` không có dòng nào -> người đọc hiểu nhầm là bài không có
    reference.
    """
    pytest.importorskip("pyarrow")
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    _set_reference_status(corpus, "2504.12523", "rate_limited")

    out = tmp_path / "hf_skip"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 0

    manifest = json.loads(
        (out / "metadata" / "export-manifest-24120152.json").read_text(encoding="utf-8")
    )
    assert manifest["n_requested_publications"] == 2
    assert manifest["n_publications"] == 1
    assert manifest["skipped_ids"] == ["2504.12523"]
    assert manifest["skipped"][0]["reason"] == export_hf.SKIP_BAD_REFERENCES_STATUS
    assert "rate_limited" in manifest["skipped"][0]["detail"]
    assert manifest["n_skipped_by_reason"] == {export_hf.SKIP_BAD_REFERENCES_STATUS: 1}

    import pyarrow.parquet as pq

    ids_in_papers = pq.read_table(
        next((out / "data" / "papers").glob("*.parquet"))
    ).column("arxiv_id").to_pylist()
    assert "2504.12523" not in ids_in_papers


def test_strict_restores_the_old_fail_fast_behaviour(tmp_path):
    pytest.importorskip("pyarrow")
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    _set_reference_status(corpus, "2504.12523", "rate_limited")

    out = tmp_path / "hf_strict"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
        "--strict",
    ]) == 1
    assert not out.exists()


def test_manifest_records_no_skips_when_everything_is_present(tmp_path):
    pytest.importorskip("pyarrow")
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    out = tmp_path / "hf_clean"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 0
    manifest = json.loads(
        (out / "metadata" / "export-manifest-24120152.json").read_text(encoding="utf-8")
    )
    assert manifest["n_skipped_publications"] == 0
    assert manifest["skipped"] == [] and manifest["n_skipped_by_reason"] == {}


def _rewrite_json(path: Path, **changes) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    "break_it",
    [
        # n_total lệch số dòng references
        lambda c, p: _rewrite_json(c / config.pub_key("2504.12524") / "references.json", n_total=99),
        # một dòng JSONL hỏng
        lambda c, p: (p / config.pub_key("2504.12524") / "elements.jsonl").write_text(
            "{bad\n", encoding="utf-8"),
        # cột sai kiểu trong paper_meta
        lambda c, p: _rewrite_json(c / config.pub_key("2504.12524") / "paper_meta.json", title=None),
        # references.json không phải JSON
        lambda c, p: (c / config.pub_key("2504.12524") / "references.json").write_text(
            "not json", encoding="utf-8"),
        # byte không phải UTF-8 (file lưu nhầm bằng cp1252...)
        lambda c, p: (p / config.pub_key("2504.12524") / "elements.jsonl").write_bytes(
            b'{"x": "\xff"}\n'),
        lambda c, p: (c / config.pub_key("2504.12524") / "paper_meta.json").write_bytes(
            b'{"title": "\xe9"}'),
        # surrogate lẻ: JSON hợp lệ nhưng pyarrow không ghi được
        lambda c, p: _rewrite_json(c / config.pub_key("2504.12524") / "paper_meta.json",
                                   title="Paper \ud835 1"),
    ],
    ids=["n_total", "bad_jsonl_line", "null_title", "broken_references_json",
         "non_utf8_jsonl", "non_utf8_json", "lone_surrogate"],
)
def test_invalid_content_skips_paper_from_all_tables(tmp_path, break_it):
    """File có đủ nhưng nội dung hỏng ở 1 bài: bỏ bài đó khỏi cả năm bảng, không dừng cả lần xuất."""
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    break_it(corpus, parsed)
    out = tmp_path / "hf_invalid"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 0

    manifest = json.loads(
        (out / "metadata" / "export-manifest-24120152.json").read_text(encoding="utf-8")
    )
    assert manifest["n_publications"] == 1
    assert manifest["skipped_ids"] == ["2504.12524"]
    assert manifest["skipped"][0]["detail"]
    for name in export_hf.TABLE_NAMES:
        ids_in_table = {
            a for shard in (out / "data" / name).glob("*.parquet")
            for a in pq.read_table(shard).column("arxiv_id").to_pylist()
        }
        assert "2504.12524" not in ids_in_table, name
    # Bài lành vẫn đủ dòng như khi không có bài hỏng
    assert manifest["n_rows_elements"] == 3
    assert manifest["n_rows_references"] == 1


def test_invalid_content_with_strict_stops_and_leaves_no_output(tmp_path):
    pytest.importorskip("pyarrow")
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    _rewrite_json(corpus / config.pub_key("2504.12524") / "references.json", n_total=99)
    out = tmp_path / "hf_invalid_strict"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out), "--strict",
    ]) == 1
    assert not out.exists()
    assert not list(tmp_path.glob(".hf_invalid_strict.staging-*"))


def test_all_papers_invalid_still_refuses_empty_dataset(tmp_path):
    pytest.importorskip("pyarrow")
    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    for arxiv_id in ("2504.12523", "2504.12524"):
        _rewrite_json(corpus / config.pub_key(arxiv_id) / "paper_meta.json", title=None)
    out = tmp_path / "hf_all_invalid"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 1
    assert not out.exists()


def test_references_table_matches_spec_and_keeps_only_arxiv_refs(tmp_path):
    """Đề M1: chỉ reference có arXiv ID thành dòng; đúng 6 cột, ref_arxiv_id non-null."""
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    path = corpus / config.pub_key("2504.12523") / "references.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["references"].append({
        "arxiv_id": "2504.12523", "ref_s2_id": "s2-2", "ref_title": "A Book",
        "ref_authors": ["Eve"], "ref_submission_date": None, "ref_arxiv_id": None,
        "has_arxiv_id": False, "ref_venue": None, "ref_year": 1999,
    })
    data["n_total"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")

    out = tmp_path / "hf_refs"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 0
    table = pq.read_table(next((out / "data" / "references").glob("*.parquet")))
    assert table.column_names == [
        "arxiv_id", "ref_arxiv_id", "ref_title", "ref_authors",
        "ref_submission_date", "ref_s2_id",
    ]
    assert table.schema.field("ref_arxiv_id").nullable is False
    assert table.column("ref_arxiv_id").to_pylist() == ["2301.00001"]


def test_schema_matches_spec_columns_and_dictionary_types(tmp_path):
    """Cột, thứ tự cột và kiểu dictionary đúng như đề M1/M2."""
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    corpus, parsed, ids_file = _make_sample_tree(tmp_path)
    out = tmp_path / "hf_schema"
    assert export_hf.main([
        "--mssv", "24120152", "--ids-file", str(ids_file),
        "--corpus", str(corpus), "--parsed", str(parsed), "--out", str(out),
    ]) == 0
    expected = {
        "papers": ["arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue"],
        "references": ["arxiv_id", "ref_arxiv_id", "ref_title", "ref_authors",
                       "ref_submission_date", "ref_s2_id"],
        "elements": ["element_id", "arxiv_id", "kind", "content"],
        "hierarchy": ["arxiv_id", "version", "element_id", "parent_id"],
        "bibtex": ["arxiv_id", "citation_key", "entry_type", "title", "authors",
                   "year", "doi", "journal", "url"],
    }
    tables = {
        name: pq.read_table(next((out / "data" / name).glob("*.parquet")))
        for name in export_hf.TABLE_NAMES
    }
    for name, columns in expected.items():
        assert tables[name].column_names == columns, name
    assert pa.types.is_dictionary(tables["elements"].schema.field("kind").type)
    assert pa.types.is_dictionary(tables["bibtex"].schema.field("entry_type").type)
    assert tables["elements"].column("kind").to_pylist() == [
        "document", "sentence", "sentence", "document", "sentence"]
    # authors / revised_dates là list[string] một cấp, không lồng object
    assert tables["papers"].schema.field("authors").type == pa.list_(pa.string())