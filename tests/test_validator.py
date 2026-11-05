"""tests/test_validator.py - Kiểm tra validator.py bằng corpus giả có lỗi cài sẵn.

Chạy từ thư mục gốc dự án:
    pytest tests/test_validator.py -v
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
from validator import Validator, id_problem, main  # noqa: E402

TEX = b"\\begin{figure}\\includegraphics{a.png}\\end{figure}\n"
NOW = "2026-10-29T10:00:00+07:00"


# --------------------------------------------------------------------------- #
# Dựng corpus giả
# --------------------------------------------------------------------------- #
def meta(arxiv_id="2301.00001", n=1, **over):
    m = {
        "arxiv_id": arxiv_id, "title": "A Title", "authors": ["A. One"],
        "submission_date": "2023-01-01T00:00:00+00:00", "revised_dates": [], "venue": None,
        "n_versions": n, "latest_versioned_id": f"{arxiv_id}v{n}", "discovered_at": NOW,
    }
    m.update(over)
    return m


def ref(arxiv_id, rid="1706.03762", **over):
    r = {
        "arxiv_id": arxiv_id, "ref_s2_id": "abc", "ref_title": "Attention", "ref_authors": ["V"],
        "ref_submission_date": "2017-06-12", "ref_arxiv_id": rid, "has_arxiv_id": bool(rid),
        "ref_venue": None, "ref_year": 2017,
    }
    r.update(over)
    return r


def refs_json(arxiv_id, refs=None, status="ok"):
    refs = [ref(arxiv_id)] if refs is None else refs
    return {
        "arxiv_id": arxiv_id, "crawled_at": NOW, "status": status, "n_total": len(refs),
        "n_with_arxiv": sum(bool(r.get("ref_arxiv_id")) for r in refs if isinstance(r, dict)),
        "references": refs,
    }


def empty_json(arxiv_id, v, reason="pdf_only"):
    return {"arxiv_id": arxiv_id, "version": v, "reason": reason, "detail": "d",
            "http_status": 200, "fetched_at": NOW}


def make_paper(root: Path, arxiv_id="2301.00001", n=1, versions=None, m=None, refs=..., folder=None):
    """versions: {v: {relpath: bytes}}; mặc định mỗi version có main.tex."""
    d = root / (folder or config.pub_key(arxiv_id))
    d.mkdir(parents=True, exist_ok=True)
    versions = versions if versions is not None else {v: {"main.tex": TEX} for v in range(1, n + 1)}
    for v, files in versions.items():
        for rel, data in files.items():
            f = d / f"v{v}" / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        (d / f"v{v}").mkdir(exist_ok=True)
    if m is not False:
        (d / "paper_meta.json").write_text(json.dumps(m or meta(arxiv_id, n)), encoding="utf-8")
    if refs is not None:
        content = refs_json(arxiv_id) if refs is ... else refs
        (d / "references.json").write_text(json.dumps(content), encoding="utf-8")
    return d


def run(root, **kw):
    v = Validator([root], None, kw.pop("raw", None), reextract=kw.pop("reextract", False))
    return v.run()


def found(report, check, needle="", version="any", severity="error"):
    return [
        e for e in report["errors"]
        if e["check"] == check and e["severity"] == severity and needle in e["message"]
        and (version == "any" or e["version"] == version)
    ]


# --------------------------------------------------------------------------- #
# Corpus sạch
# --------------------------------------------------------------------------- #
def test_clean_corpus_passes(tmp_path):
    make_paper(tmp_path, "2301.00001", n=2, versions={
        1: {"main.tex": TEX, "refs.bib": b"@a{}"},
        2: {"_EMPTY.json": empty_json("2301.00001", 2)},
    })
    make_paper(tmp_path, "hep-th/9901001", n=1)
    rep = run(tmp_path)

    assert rep["summary"]["passed"], rep["errors"]
    assert rep["summary"]["n_papers"] == 2 and rep["summary"]["n_versions"] == 3
    assert all(c["status"] == "pass" for c in rep["checks"].values())
    assert rep["stats"]["figure_envs"] == 2 and rep["stats"]["empty_versions"] == 1


# --------------------------------------------------------------------------- #
# C1
# --------------------------------------------------------------------------- #
def test_c1_missing_and_extra_version_dirs(tmp_path):
    make_paper(tmp_path, "2301.00001", n=3, versions={1: {"main.tex": TEX}, 3: {"main.tex": TEX}})
    make_paper(tmp_path, "2301.00002", n=1, versions={1: {"main.tex": TEX}, 2: {"main.tex": TEX}})
    rep = run(tmp_path)

    assert found(rep, "C1", "thiếu thư mục v2", version=2)
    assert found(rep, "C1", "thừa thư mục v2", version=2)
    assert rep["checks"]["C1"]["status"] == "fail"


def test_c1_noncanonical_version_dir_name(tmp_path):
    d = make_paper(tmp_path, "2301.00001", n=1)
    (d / "v1").rename(d / "v01")
    rep = run(tmp_path)
    assert found(rep, "C1", "thiếu thư mục v1")


# --------------------------------------------------------------------------- #
# C2
# --------------------------------------------------------------------------- #
def test_c2_version_without_tex_or_marker(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1, versions={1: {"refs.bib": b"@a{}"}})
    rep = run(tmp_path)
    assert found(rep, "C2", "không có file .tex và không có _EMPTY.json (chỉ có .bib)", version=1)


def test_c2_invalid_empty_markers(tmp_path):
    bad_reason = empty_json("2301.00001", 1, reason="whatever")
    missing = {"arxiv_id": "2301.00002", "version": 1}
    wrong_ver = empty_json("2301.00003", 2)
    make_paper(tmp_path, "2301.00001", n=1, versions={1: {"_EMPTY.json": bad_reason}})
    make_paper(tmp_path, "2301.00002", n=1, versions={1: {"_EMPTY.json": missing}})
    make_paper(tmp_path, "2301.00003", n=1, versions={1: {"_EMPTY.json": wrong_ver}})
    rep = run(tmp_path)

    assert found(rep, "C2", "reason='whatever'")
    assert found(rep, "C2", "thiếu trường 'reason'")
    assert found(rep, "C2", "version=2 khác thư mục v1")


def test_c2_marker_and_tex_conflict_is_warning(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1,
               versions={1: {"main.tex": TEX, "_EMPTY.json": empty_json("2301.00001", 1)}})
    rep = run(tmp_path)
    assert found(rep, "C2", "mâu thuẫn", severity="warning")
    assert rep["summary"]["passed"]


# --------------------------------------------------------------------------- #
# C3
# --------------------------------------------------------------------------- #
def test_c3_stray_files(tmp_path):
    d = make_paper(tmp_path, "2301.00001", n=1,
                   versions={1: {"main.tex": TEX, "fig/a.png": b"\x89PNG", ".DS_Store": b"x"}})
    (d / "references.json.tmp").write_text("{}", encoding="utf-8")
    (d / "notes.txt").write_text("hi", encoding="utf-8")
    rep = run(tmp_path)

    assert found(rep, "C3", "fig/a.png", version=1)
    assert found(rep, "C3", ".DS_Store", version=1)
    assert found(rep, "C3", "references.json.tmp", version=None)
    assert found(rep, "C3", "notes.txt", version=None)


def test_c3_uppercase_extensions_are_allowed(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1, versions={1: {"Main.TEX": TEX, "R.BIB": b"x"}})
    assert not found(run(tmp_path), "C3")


# --------------------------------------------------------------------------- #
# C4
# --------------------------------------------------------------------------- #
def test_c4_unbalanced_figure_is_warning(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1, versions={1: {"main.tex": b"\\begin{figure}\\caption{x}\n"}})
    rep = run(tmp_path)
    assert found(rep, "C4", "figure có thể bị cắt cụt", severity="warning")


def test_c4_commented_figure_not_counted(tmp_path):
    src = b"% \\begin{figure}\n\\begin{figure}\\end{figure}\n"
    make_paper(tmp_path, "2301.00001", n=1, versions={1: {"main.tex": src}})
    assert not found(run(tmp_path), "C4", severity="warning")


def _make_raw(raw: Path, folder: str, members: dict[str, bytes]) -> None:
    (raw / folder).mkdir(parents=True, exist_ok=True)
    with tarfile.open(raw / folder / "v1.tar.gz", "w:gz") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


def test_c4_detects_modified_and_missing_files_vs_archive(tmp_path):
    corpus, raw = tmp_path / "corpus", tmp_path / "raw"
    corpus.mkdir()
    members = {"main.tex": TEX, "sec/a.tex": b"original\n", "refs.bib": b"@a{}"}
    _make_raw(raw, "2301-00001", members)
    make_paper(corpus, "2301.00001", n=1, versions={1: {
        "main.tex": TEX.replace(b"\\includegraphics{a.png}", b""),  # bị sửa: mất includegraphics
        "refs.bib": b"@a{}",                                          # còn nguyên
        # sec/a.tex bị mất
    }})
    rep = run(corpus, raw=raw, reextract=True)

    assert found(rep, "C4", "'main.tex' khác archive gốc", version=1)
    assert found(rep, "C4", "'sec/a.tex' có trong archive nhưng thiếu", version=1)
    assert not found(rep, "C4", "refs.bib")
    assert rep["stats"]["reextract_compared"] == 1


def test_c4_identical_to_archive_passes(tmp_path):
    corpus, raw = tmp_path / "corpus", tmp_path / "raw"
    corpus.mkdir()
    _make_raw(raw, "2301-00001", {"main.tex": TEX, "fig.png": b"\x89PNG"})
    make_paper(corpus, "2301.00001", n=1)
    rep = run(corpus, raw=raw, reextract=True)
    assert rep["summary"]["passed"], rep["errors"]


# --------------------------------------------------------------------------- #
# C5
# --------------------------------------------------------------------------- #
def test_c5_meta_missing_fields_and_wrong_types(tmp_path):
    bad = meta("2301.00001", 1, authors="A. One", revised_dates=[1], venue="None",
               submission_date="yesterday", n_versions="1")
    del bad["title"]
    make_paper(tmp_path, "2301.00001", n=1, m=bad)
    make_paper(tmp_path, "2301.00002", n=1, m=False)
    rep = run(tmp_path)

    for needle in ("thiếu trường 'title'", "authors phải là list[str]", "revised_dates phải là list[str]",
                   "venue nullable", "submission_date không phải chuỗi ISO", "n_versions phải là số nguyên"):
        assert found(rep, "C5", needle), needle
    assert found(rep, "C5", "paper_meta.json không tồn tại")


def test_c5_null_venue_and_empty_authors(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1, m=meta("2301.00001", 1, authors=[]))
    rep = run(tmp_path)
    assert found(rep, "C5", "authors rỗng", severity="warning")
    assert rep["summary"]["passed"]


# --------------------------------------------------------------------------- #
# C6
# --------------------------------------------------------------------------- #
def test_c6_missing_references_file(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1, refs=None)
    assert found(run(tmp_path), "C6", "references.json không tồn tại")


def test_c6_reference_field_problems_are_aggregated(tmp_path):
    r_missing = ref("2301.00001")
    del r_missing["ref_s2_id"]
    refs = [r_missing, ref("2301.00001", ref_authors="V"), ref("2301.00001", ref_title=""),
            ref("2301.00009"), ref("2301.00001", has_arxiv_id=False)]
    make_paper(tmp_path, "2301.00001", n=1, refs=refs_json("2301.00001", refs))
    rep = run(tmp_path)

    assert found(rep, "C6", "thiếu trường ref_s2_id")
    assert found(rep, "C6", "ref_authors phải là list[str]")
    assert found(rep, "C6", "ref_title phải là chuỗi không rỗng hoặc null")
    assert found(rep, "C6", "arxiv_id='2301.00009' khác ID bài trích dẫn")
    assert found(rep, "C6", "has_arxiv_id không khớp")


def test_c6_status_handling(tmp_path):
    make_paper(tmp_path, "2301.00001", n=1, refs=refs_json("2301.00001", [], "rate_limited"))
    make_paper(tmp_path, "2301.00002", n=1, refs=refs_json("2301.00002", [], "not_indexed"))
    rep = run(tmp_path)
    assert found(rep, "C6", "status='rate_limited'")
    assert found(rep, "C6", "status='not_indexed'", severity="warning")
    assert not found(rep, "C6", "status='not_indexed'")


def test_c6_counts_must_match(tmp_path):
    bad = refs_json("2301.00001", [ref("2301.00001")])
    bad["n_total"], bad["n_with_arxiv"] = 5, 0
    make_paper(tmp_path, "2301.00001", n=1, refs=bad)
    rep = run(tmp_path)
    assert found(rep, "C6", "n_total=5")
    assert found(rep, "C6", "n_with_arxiv=0")


# --------------------------------------------------------------------------- #
# C7
# --------------------------------------------------------------------------- #
def test_id_problem_classifier():
    assert id_problem("2310.12345") is None
    assert id_problem("1706.03762") is None
    assert id_problem("hep-th/9901001") is None
    assert id_problem("math.GT/0309136") is None
    assert id_problem("hep-th_9901001") and "'/'" in id_problem("hep-th_9901001")
    assert "'.'" in id_problem("2310-12345")
    assert "version" in id_problem("2310.12345v2")
    assert id_problem("2310.12345v2", allow_version=True) is None
    assert "arXiv:" in id_problem("arXiv:2310.12345")
    assert id_problem(" 2310.12345") and id_problem("") and id_problem(None)
    assert "hoa/thường" in id_problem("HEP-TH/9901001")


def test_c7_deformed_old_id_in_meta(tmp_path):
    make_paper(tmp_path, "hep-th/9901001", n=1, m=meta("hep-th_9901001", 1), folder="hep-th_9901001")
    rep = run(tmp_path)
    assert found(rep, "C7", "dấu '/' bị đổi thành '_'")


def test_c7_folder_name_must_match_pub_key(tmp_path):
    make_paper(tmp_path, "hep-th/9901001", n=1, folder="hep-th-9901001")
    rep = run(tmp_path)
    assert found(rep, "C7", "không khớp config.pub_key")


def test_c7_latest_versioned_id_and_reference_ids(tmp_path):
    refs = [ref("2301.00001", rid="hep-th_9901001"), ref("2301.00001", rid="hep-th/9901001")]
    make_paper(tmp_path, "2301.00001", n=2, m=meta("2301.00001", 2, latest_versioned_id="2301.00001v1"),
               refs=refs_json("2301.00001", refs))
    rep = run(tmp_path)
    assert found(rep, "C7", "latest_versioned_id='2301.00001v1' nhưng phải là '2301.00001v2'")
    bad_ref = found(rep, "C7", "ref_arxiv_id bị biến dạng")
    assert len(bad_ref) == 1 and "1 reference" in bad_ref[0]["message"]


def test_c7_reference_and_empty_marker_ids_must_match_meta(tmp_path):
    make_paper(tmp_path, "hep-th/9901001", n=1,
               versions={1: {"_EMPTY.json": empty_json("hep-th_9901001", 1)}},
               refs=refs_json("hep-th_9901001"))
    rep = run(tmp_path)
    assert found(rep, "C2", "arxiv_id 'hep-th_9901001' bị biến dạng")
    assert found(rep, "C7", "references.json: arxiv_id='hep-th_9901001' khác paper_meta")


# --------------------------------------------------------------------------- #
# Owner, bài thiếu, nhiều corpus, CLI
# --------------------------------------------------------------------------- #
def test_owner_attribution_and_missing_papers(tmp_path):
    corpus, ids = tmp_path / "corpus", tmp_path / "ids"
    corpus.mkdir()
    ids.mkdir()
    (ids / "24120001.txt").write_text("# comment\n2301.00001\n2301.00002v3\n", encoding="utf-8")
    (ids / "24120002.txt").write_text("hep-th/9901001\n", encoding="utf-8")
    make_paper(corpus, "2301.00001", n=1, refs=None)
    v = Validator([corpus], ids, None, reextract=False)
    rep = v.run()

    err = found(rep, "C6", "references.json không tồn tại")[0]
    assert err["owner"] == "24120001" and err["arxiv_id"] == "2301.00001"
    missing = found(rep, "C1", "không có thư mục bài")
    assert {(m["arxiv_id"], m["owner"]) for m in missing} == {
        ("2301.00002", "24120001"), ("hep-th/9901001", "24120002")}
    assert rep["by_owner"]["24120001"]["errors"] == 2 and rep["stats"]["missing_papers"] == 2


def test_multiple_corpus_roots_merge_and_flag_duplicates(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    make_paper(a, "2301.00001", n=1)
    make_paper(b, "2301.00002", n=1)
    make_paper(b, "2301.00001", n=1)
    rep = Validator([a, b], None, None, reextract=False).run()
    assert rep["summary"]["n_papers"] == 2
    assert found(rep, "C1", "nhiều corpus", severity="warning")


def test_cli_writes_report_and_exit_codes(tmp_path):
    corpus, out = tmp_path / "corpus", tmp_path / "reports" / "validation.json"
    corpus.mkdir()
    make_paper(corpus, "2301.00001", n=1)
    argv = ["--corpus", str(corpus), "--no-ids", "--no-reextract", "--out", str(out)]
    assert main(argv) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["passed"] and set(data["checks"]) == {f"C{i}" for i in range(1, 8)}

    make_paper(corpus, "2301.00002", n=2, versions={1: {"main.tex": TEX}})
    assert main(argv) == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert not data["summary"]["passed"]
    e = data["errors"][0]
    assert {"check", "severity", "arxiv_id", "version", "message", "owner", "path"} <= set(e)
    assert (e["arxiv_id"], e["version"]) == ("2301.00002", 2)


def test_strict_turns_warnings_into_failures(tmp_path):
    corpus, out = tmp_path / "corpus", tmp_path / "v.json"
    corpus.mkdir()
    make_paper(corpus, "2301.00001", n=1, m=meta("2301.00001", 1, authors=[]))
    argv = ["--corpus", str(corpus), "--no-ids", "--no-reextract", "--out", str(out)]
    assert main(argv) == 0
    assert main(argv + ["--strict"]) == 1


def test_report_paths_are_relative_and_do_not_leak_local_dirs(tmp_path):
    corpus, out = tmp_path / "corpus", tmp_path / "reports" / "validation.json"
    corpus.mkdir()
    make_paper(corpus, "2301.00001", n=1, refs=None)
    main(["--corpus", str(corpus), "--no-ids", "--no-reextract", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    data = json.loads(text)

    assert str(tmp_path) not in text.replace("\\\\", "\\") and tmp_path.as_posix() not in text
    assert all(not Path(e["path"]).is_absolute() for e in data["errors"])
    assert data["errors"][0]["path"] == "corpus/2301-00001/references.json"
    assert data["corpus_roots"] == ["corpus"]


def test_cli_has_no_hardcoded_ids_and_rejects_missing_ids_file(tmp_path):
    corpus, out = tmp_path / "corpus", tmp_path / "v.json"
    corpus.mkdir()
    make_paper(corpus, "2301.00001", n=1)
    assert main(["--corpus", str(corpus), "--no-reextract", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ids_checked_against"] == []

    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["--corpus", str(corpus), "--ids-file", str(tmp_path / "nope.txt"),
              "--no-reextract", "--out", str(out)])
    assert exc.value.code == 2