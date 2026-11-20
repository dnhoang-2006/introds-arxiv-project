"""Test cơ chế chạy lại được từ giữa chừng của src/parse_main.py.

parse_one() là việc tuần 2 nên ở đây thay bằng hàm giả; chỉ kiểm phần vòng lặp:
bỏ qua bài đã xong, --overwrite, ghi log, lỗi một bài không dừng cả mẻ.
"""

import csv
from pathlib import Path

import pytest

from src.parse_main import PARSE_LOG_FIELDS, already_done, run, write_outputs 


def _fake_parse(calls):
    def fn(arxiv_id: str, out_root: Path):
        calls.append(arxiv_id)
        key = arxiv_id.replace(".", "-")
        write_outputs(key, out_root,
                      elements=[{"element_id": f"{key}#doc_0", "arxiv_id": arxiv_id,
                                 "kind": "document", "content": f"{arxiv_id}v1"}],
                      hierarchy=[], bibtex=[])
        return [{"version": 1, "n_elements": 1, "seconds": 0.01, "status": "ok"}]
    return fn


def _read_log(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_write_outputs_creates_three_tables_and_no_tmp(tmp_path):
    d = write_outputs("2310-12345", tmp_path,
                      elements=[{"content": "Câu có dấu, \"nháy\"\nxuống dòng"}],
                      hierarchy=[{"a": 1}], bibtex=[])
    assert sorted(p.name for p in d.iterdir()) == ["bibtex.jsonl", "elements.jsonl", "hierarchy.jsonl"]
    assert "Câu có dấu" in (d / "elements.jsonl").read_text(encoding="utf-8")
    assert already_done("2310-12345", tmp_path)


def test_crash_while_writing_elements_is_not_marked_done(tmp_path):
    """Đứt giữa lúc ghi elements.jsonl -> không được coi là đã xong."""
    def rows_then_crash():
        yield {"x": 1}
        raise OSError("mất điện")

    with pytest.raises(OSError):
        write_outputs("2310-12345", tmp_path, elements=rows_then_crash(),
                      hierarchy=[], bibtex=[])
    assert not already_done("2310-12345", tmp_path)


def test_rerun_skips_done_publications(tmp_path):
    out, log = tmp_path / "parsed", tmp_path / "parse.csv"
    calls: list[str] = []
    ids = ["2310.12345", "2310.12346"]

    c1 = run(ids, out, verbose=False, log_path=log, parse_fn=_fake_parse(calls))
    c2 = run(ids, out, verbose=False, log_path=log, parse_fn=_fake_parse(calls))

    assert calls == ids                       # lần 2 không parse lại bài nào
    assert c1["ok"] == 2 and c2["skipped"] == 2
    rows = _read_log(log)
    assert list(rows[0].keys()) == list(PARSE_LOG_FIELDS)   # header chỉ ghi một lần
    assert [r["status"] for r in rows] == ["ok", "ok", "skipped", "skipped"]
    assert rows[2]["error_type"] == "" and rows[2]["arxiv_id"] == "2310.12345"


def test_overwrite_forces_reparse(tmp_path):
    out, log = tmp_path / "parsed", tmp_path / "parse.csv"
    calls: list[str] = []
    run(["2310.12345"], out, verbose=False, log_path=log, parse_fn=_fake_parse(calls))
    run(["2310.12345"], out, overwrite=True, verbose=False, log_path=log, parse_fn=_fake_parse(calls))
    assert calls == ["2310.12345", "2310.12345"]


def test_resume_after_interruption(tmp_path):
    """Đứt sau bài thứ nhất -> chạy lại chỉ làm bài còn lại."""
    out, log = tmp_path / "parsed", tmp_path / "parse.csv"
    calls: list[str] = []
    run(["2310.12345"], out, verbose=False, log_path=log, parse_fn=_fake_parse(calls))
    run(["2310.12345", "2310.12346"], out, verbose=False, log_path=log, parse_fn=_fake_parse(calls))
    assert calls == ["2310.12345", "2310.12346"]


def test_one_failure_does_not_stop_batch_and_is_retried(tmp_path):
    out, log = tmp_path / "parsed", tmp_path / "parse.csv"
    calls: list[str] = []
    good = _fake_parse(calls)

    def flaky(arxiv_id, out_root):
        if arxiv_id == "2310.12345":
            raise ValueError("tex hỏng")
        return good(arxiv_id, out_root)

    counts = run(["2310.12345", "2310.12346"], out, verbose=False, log_path=log, parse_fn=flaky)
    assert counts["fail"] == 1 and counts["ok"] == 1
    fail = _read_log(log)[0]
    assert fail["status"] == "fail" and fail["error_type"] == "ValueError"
    assert not already_done("2310-12345", out)    # bài lỗi lần sau được thử lại


def test_not_implemented_propagates(tmp_path):
    def stub(arxiv_id, out_root):
        raise NotImplementedError
    with pytest.raises(NotImplementedError):
        run(["2310.12345"], tmp_path / "parsed", verbose=False,
            log_path=tmp_path / "parse.csv", parse_fn=stub)


# --------------------------------------------------------------------------- #
# parse_one trả dòng log đúng theo PARSE_LOG_FIELDS — tức là CÓ cả arxiv_id
# --------------------------------------------------------------------------- #
def test_rows_containing_arxiv_id_do_not_kill_batch(tmp_path):
    """Hồi quy: _log_row(arxiv_id, **r) từng ném TypeError 'multiple values for
    argument arxiv_id' ngoài khối try -> chết ngay bài đầu, log 0/3 dòng."""
    out, log = tmp_path / "parsed", tmp_path / "parse.csv"
    calls: list[str] = []
    good = _fake_parse(calls)

    def full_rows(arxiv_id, out_root):
        good(arxiv_id, out_root)
        return [{f: 0 for f in PARSE_LOG_FIELDS} | {
            "arxiv_id": "SAI-ID", "version": v, "seconds": 0.5,
            "status": "ok", "error_type": ""} for v in (1, 2)]

    ids = ["2310.12345", "2310.12346", "2310.12347"]
    counts = run(ids, out, verbose=False, log_path=log, parse_fn=full_rows)

    rows = _read_log(log)
    assert counts["ok"] == 6 and len(rows) == 6
    assert [r["arxiv_id"] for r in rows] == [i for i in ids for _ in (1, 2)]  # ID của run() thắng
    assert rows[0]["seconds"] == "0.50"


def test_malformed_rows_fail_only_that_publication(tmp_path):
    out, log = tmp_path / "parsed", tmp_path / "parse.csv"
    calls: list[str] = []
    good = _fake_parse(calls)

    def bad_return(arxiv_id, out_root):
        if arxiv_id == "2310.12345":
            return None                       # quên return danh sách
        return good(arxiv_id, out_root)

    counts = run(["2310.12345", "2310.12346"], out, verbose=False,
                 log_path=log, parse_fn=bad_return)
    assert counts["fail"] == 1 and counts["ok"] == 1
    assert _read_log(log)[0]["error_type"] == "TypeError"


def test_unknown_keys_in_rows_ignored(tmp_path):
    def extra(arxiv_id, out_root):
        return [{"version": 1, "status": "ok", "khoa_la": 123}]
    counts = run(["2310.12345"], tmp_path / "p", verbose=False,
                 log_path=tmp_path / "parse.csv", parse_fn=extra)
    assert counts["ok"] == 1


# --------------------------------------------------------------------------- #
# --workers N (Minh Thư). Tiến trình con nhận parse_fn qua pickle nên hàm giả
# phải ở cấp module, không dùng closure/lambda như các test tuần tự phía trên.
# --------------------------------------------------------------------------- #
def _fake_parse_mod(arxiv_id: str, out_root: Path):
    key = arxiv_id.replace(".", "-")
    write_outputs(key, out_root,
                  elements=[{"element_id": f"{key}#doc_0", "arxiv_id": arxiv_id,
                             "kind": "document", "content": f"{arxiv_id}v1"}],
                  hierarchy=[], bibtex=[])
    return [{"version": v, "n_elements": 1, "status": "ok"} for v in (1, 2)]


def _flaky_mod(arxiv_id: str, out_root: Path):
    if arxiv_id == "2310.12343":
        raise ValueError("tex hỏng")
    return _fake_parse_mod(arxiv_id, out_root)


def _not_implemented_mod(arxiv_id: str, out_root: Path):
    raise NotImplementedError


def _sorted_rows(log: Path):
    keep = ("arxiv_id", "version", "n_elements", "status", "error_type")
    return sorted(tuple(r[k] for k in keep) for r in _read_log(log))


IDS = [f"2310.1234{i}" for i in range(6)]


def test_workers_invalid():
    with pytest.raises(ValueError):
        run([], Path("unused"), log_path=Path("unused.csv"), workers=0)


def test_workers_2_same_result_as_workers_1(tmp_path):
    """Song song phải ra ĐÚNG cùng kết quả với tuần tự (chỉ khác thứ tự dòng log)."""
    c1 = run(IDS, tmp_path / "p1", verbose=False, log_path=tmp_path / "w1.csv",
             parse_fn=_flaky_mod, workers=1)
    c2 = run(IDS, tmp_path / "p2", verbose=False, log_path=tmp_path / "w2.csv",
             parse_fn=_flaky_mod, workers=2)
    assert c1 == c2 == {"ok": 10, "empty": 0, "fail": 1, "skipped": 0}
    assert _sorted_rows(tmp_path / "w1.csv") == _sorted_rows(tmp_path / "w2.csv")
    for i in IDS:
        assert already_done(i.replace(".", "-"), tmp_path / "p2") == (i != "2310.12343")


def test_workers_log_not_interleaved(tmp_path):
    """Chỉ tiến trình chính ghi CSV: đủ dòng, header một lần, mọi dòng đủ cột."""
    log = tmp_path / "parse.csv"
    run(IDS, tmp_path / "p", verbose=False, log_path=log,
        parse_fn=_fake_parse_mod, workers=3)
    rows = _read_log(log)
    assert len(rows) == 2 * len(IDS)
    assert all(list(r.keys()) == list(PARSE_LOG_FIELDS) for r in rows)
    assert all(None not in r.values() for r in rows)
    assert log.read_text(encoding="utf-8").count("arxiv_id,version") == 1


def test_workers_resume_skips_done(tmp_path):
    out, log = tmp_path / "p", tmp_path / "parse.csv"
    run(IDS[:3], out, verbose=False, log_path=log, parse_fn=_fake_parse_mod, workers=2)
    c = run(IDS, out, verbose=False, log_path=log, parse_fn=_fake_parse_mod, workers=2)
    assert c["skipped"] == 3 and c["ok"] == 6


def test_workers_not_implemented_propagates(tmp_path):
    with pytest.raises(NotImplementedError):
        run(IDS[:2], tmp_path / "p", verbose=False, log_path=tmp_path / "parse.csv",
            parse_fn=_not_implemented_mod, workers=2)


def test_workers_unpicklable_parse_fn_logged_as_fail(tmp_path):
    """Lambda không pickle được -> mỗi bài một dòng fail, không treo, không crash."""
    c = run(IDS[:2], tmp_path / "p", verbose=False, log_path=tmp_path / "parse.csv",
            parse_fn=lambda a, o: [], workers=2)
    assert c["fail"] == 2


def test_parse_main_does_not_need_arxiv_library():
    """parse_main không được import discovery (discovery sys.exit() khi thiếu `arxiv`)."""
    import subprocess, sys, textwrap
    code = textwrap.dedent("""
        import builtins, sys
        real = builtins.__import__
        def guard(name, *a, **k):
            if name == "arxiv" or name.startswith("arxiv."):
                raise ImportError("giả lập máy không cài arxiv")
            return real(name, *a, **k)
        builtins.__import__ = guard
        sys.path.insert(0, "src")
        import parse_main
        print("OK", "discovery" in sys.modules)
    """)
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-c", code], cwd=root,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr + r.stdout
    assert r.stdout.strip() == "OK False"


# --------------------------------------------------------------------------- #
# parse_one thật trên corpus giả trong tmp_path.
# clean_latex / normalize_math / collect_bib / unify_publication của các bạn khác
# được thay bằng bản giả TỐI THIỂU, để chỉ kiểm phần ghép nối của parse_one.
# --------------------------------------------------------------------------- #
import json  # noqa: E402

import src.parse_main as pm  # noqa: E402
from parser.elements import element_uid  # noqa: E402

AID = "2310.12345"
KEY = "2310-12345"
_PREAMBLE = "\\documentclass{article}\n\\begin{document}\n"
_END = "\n\\end{document}\n"


def _fake_unify(norm_text, bib_entries):
    """Bản giả của unify_publication: đổi \\cite{vit} -> \\cite{vaswani2017}."""
    renamed = {v: t.replace(r"\cite{vit}", r"\cite{vaswani2017}") for v, t in norm_text.items()}
    rows = [{"citation_key": "vaswani2017", "entry_type": "article", "title": "Attention",
             "authors": ["A. Vaswani"], "year": 2017, "doi": None, "journal": None,
             "url": None, "arxiv_id": "1706.03762", "raw": "x", "version": 1}]
    return renamed, rows, {"vit": "vaswani2017"}


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Corpus giả + thay 4 hàm của các module chưa giao. Trả hàm ghi file .tex."""
    root = tmp_path / "corpus"
    monkeypatch.setattr(pm.config, "CORPUS_ROOT", root)
    monkeypatch.setattr(pm, "clean_latex", lambda s: s)
    monkeypatch.setattr(pm, "normalize_math", lambda s: s)
    monkeypatch.setattr(pm, "collect_bib", lambda vdir: [])
    monkeypatch.setattr(pm, "unify_publication", _fake_unify)

    def write(version: int, files: dict[str, str] | None = None) -> Path:
        vdir = root / KEY / f"v{version}"
        vdir.mkdir(parents=True, exist_ok=True)
        for name, text in (files or {}).items():
            (vdir / name).write_text(text, encoding="utf-8")
        return vdir
    return write


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _tables(out: Path):
    d = out / KEY
    return (_read_jsonl(d / "elements.jsonl"), _read_jsonl(d / "hierarchy.jsonl"),
            _read_jsonl(d / "bibtex.jsonl"))


# Ca bắt buộc 1
def test_parse_one_dedup_across_versions(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + r"\section{Intro} Shared sentence here. Only v1." + _END})
    corpus(2, {"main.tex": _PREAMBLE + r"\section{Intro} Shared sentence here. Only v2." + _END})
    rows = pm.parse_one(AID, tmp_path / "parsed")

    assert [(r["version"], r["status"]) for r in rows] == [(1, "ok"), (2, "ok")]
    elements, hierarchy, _ = _tables(tmp_path / "parsed")
    total_nodes = sum(r["n_elements"] for r in rows)
    assert len(elements) < total_nodes                       # dedup có chạy
    assert sum(e["content"] == "Shared sentence here." for e in elements) == 1
    for v in (1, 2):                                          # đúng một gốc mỗi version
        es = [h for h in hierarchy if h["version"] == v]
        assert len({h["parent_id"] for h in es} - {h["element_id"] for h in es}) == 1


def test_parse_one_uses_renamed_text_for_hashing(corpus, tmp_path):
    """BẪY LỚN NHẤT: cùng câu, v1 trích \\cite{vaswani2017}, v2 trích \\cite{vit}.
    Băm trên renamed_text -> một element; băm nhầm norm_text -> hai element."""
    corpus(1, {"main.tex": _PREAMBLE + r"We use attention \cite{vaswani2017}." + _END})
    corpus(2, {"main.tex": _PREAMBLE + r"We use attention \cite{vit}." + _END})
    pm.parse_one(AID, tmp_path / "parsed")

    elements, hierarchy, _ = _tables(tmp_path / "parsed")
    sents = [e for e in elements if e["kind"] == "sentence"]
    assert [s["content"] for s in sents] == [r"We use attention \cite{vaswani2017}."]
    assert {h["version"] for h in hierarchy
            if h["element_id"] == sents[0]["element_id"]} == {1, 2}
    assert not any(r"\cite{vit}" in e["content"] for e in elements)


def test_parse_one_content_is_exactly_what_was_hashed(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + r"\section{A} One \cite{vit}. $$x$$ Two." + _END})
    pm.parse_one(AID, tmp_path / "parsed")
    elements, _, _ = _tables(tmp_path / "parsed")
    for e in elements:
        assert e["element_id"] == element_uid(KEY, e["kind"], e["content"])


# Ca bắt buộc 2
def test_parse_one_empty_version_still_logged(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + "Some text." + _END})
    corpus(2, {"_EMPTY.json": "{}"})                          # không có .tex
    rows = pm.parse_one(AID, tmp_path / "parsed")

    assert [(r["version"], r["status"]) for r in rows] == [(1, "ok"), (2, "empty")]
    assert rows[1]["n_elements"] == 1
    elements, hierarchy, _ = _tables(tmp_path / "parsed")
    # schema mục 6: một dòng document cho version rỗng, không có cạnh nào
    assert any(e["kind"] == "document" and e["content"] == f"{AID}v2" for e in elements)
    assert {h["version"] for h in hierarchy} == {1}


def test_parse_one_only_empty_versions_still_written(corpus, tmp_path):
    corpus(1, {})
    rows = pm.parse_one(AID, tmp_path / "parsed")
    assert [(r["version"], r["status"]) for r in rows] == [(1, "empty")]
    elements, hierarchy, _ = _tables(tmp_path / "parsed")
    assert [e["content"] for e in elements] == [f"{AID}v1"] and hierarchy == []


# Ca bắt buộc 3
def test_parse_one_one_bad_version_others_finish(corpus, tmp_path, monkeypatch):
    def flaky_clean(s):
        if "BROKEN" in s:
            raise ValueError("tex hỏng")
        return s
    monkeypatch.setattr(pm, "clean_latex", flaky_clean)
    corpus(1, {"main.tex": _PREAMBLE + "Good one." + _END})
    corpus(2, {"main.tex": _PREAMBLE + "BROKEN." + _END})
    corpus(3, {"main.tex": _PREAMBLE + "Good three." + _END})
    rows = pm.parse_one(AID, tmp_path / "parsed")

    assert [(r["version"], r["status"], r["error_type"]) for r in rows] == [
        (1, "ok", ""), (2, "fail", "ValueError"), (3, "ok", "")]
    elements, hierarchy, _ = _tables(tmp_path / "parsed")
    assert {h["version"] for h in hierarchy} == {1, 3}
    assert not any("BROKEN" in e["content"] for e in elements)


def test_parse_one_build_tree_failure_isolated(corpus, tmp_path, monkeypatch):
    real = pm.build_tree

    def flaky_tree(tex):
        if "EXPLODE" in tex:
            raise RecursionError("cây quá sâu")
        return real(tex)
    monkeypatch.setattr(pm, "build_tree", flaky_tree)
    corpus(1, {"main.tex": _PREAMBLE + "EXPLODE." + _END})
    corpus(2, {"main.tex": _PREAMBLE + "Fine." + _END})
    rows = pm.parse_one(AID, tmp_path / "parsed")
    assert [(r["version"], r["status"]) for r in rows] == [(1, "fail"), (2, "ok")]


def test_parse_one_no_root_is_fail_not_empty(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + "Ok." + _END})
    corpus(2, {"orphan.tex": "No documentclass here."})
    rows = pm.parse_one(AID, tmp_path / "parsed")
    assert [(r["version"], r["status"], r["error_type"]) for r in rows] == [
        (1, "ok", ""), (2, "fail", "no_root")]


def test_parse_one_all_versions_fail_writes_nothing(corpus, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "clean_latex", lambda s: 1 / 0)
    corpus(1, {"main.tex": _PREAMBLE + "x." + _END})
    rows = pm.parse_one(AID, tmp_path / "parsed")
    assert [r["status"] for r in rows] == ["fail"]
    assert not already_done(KEY, tmp_path / "parsed")       # lần sau còn được thử lại


def test_parse_one_not_implemented_propagates(corpus, tmp_path, monkeypatch):
    def stub(s):
        raise NotImplementedError
    monkeypatch.setattr(pm, "normalize_math", stub)
    corpus(1, {"main.tex": _PREAMBLE + "x." + _END})
    with pytest.raises(NotImplementedError):
        pm.parse_one(AID, tmp_path / "parsed")


# Ca bắt buộc 4
def test_parse_one_elements_written_last(corpus, tmp_path, monkeypatch):
    order: list[str] = []
    real = pm._write_jsonl_atomic

    def spy(path, rows):
        order.append(path.name)
        real(path, rows)
    monkeypatch.setattr(pm, "_write_jsonl_atomic", spy)
    corpus(1, {"main.tex": _PREAMBLE + "Text." + _END})
    pm.parse_one(AID, tmp_path / "parsed")
    assert order[-1] == "elements.jsonl"
    assert sorted(order) == ["bibtex.jsonl", "elements.jsonl", "hierarchy.jsonl"]


def test_parse_one_log_rows_and_counts(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + r"\section{A}\subsection{B} S one. S two."
               r"\begin{equation}x\end{equation}\begin{figure}f\end{figure}" + _END})
    [row] = pm.parse_one(AID, tmp_path / "parsed")
    assert set(row) <= set(PARSE_LOG_FIELDS)
    # document + section + subsection + 2 câu + formula + figure
    assert (row["n_elements"], row["n_sentences"], row["n_formulas"], row["n_figures"]) \
        == (7, 2, 1, 1)
    assert row["max_depth"] == 3                              # doc > sec > sub > lá
    assert row["seconds"] >= 0


def test_parse_one_inlines_input_in_place(corpus, tmp_path):
    corpus(1, {
        "main.tex": _PREAMBLE + "\\section{Intro} First.\n\\input{sec/method}\n"
                    "\\section{End} Last.\n% \\input{ghost}\n" + _END,
        "ghost.tex": "Ghost text.",
    })
    (tmp_path / "corpus" / KEY / "v1" / "sec").mkdir()
    (tmp_path / "corpus" / KEY / "v1" / "sec" / "method.tex").write_text(
        "\\section{Method} Middle.", encoding="utf-8")
    pm.parse_one(AID, tmp_path / "parsed")
    elements, hierarchy, _ = _tables(tmp_path / "parsed")
    content = {e["element_id"]: e["content"] for e in elements}
    sections = [content[h["element_id"]] for h in hierarchy if "#sec_" in h["element_id"]]
    assert sections == ["Intro", "Method", "End"]             # đúng thứ tự biên dịch
    assert "Ghost text." not in content.values()              # \input bị comment


def test_parse_one_bibtex_rows_match_schema(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + "x." + _END})
    pm.parse_one(AID, tmp_path / "parsed")
    _, _, bib = _tables(tmp_path / "parsed")
    assert list(bib[0]) == list(pm.BIBTEX_FIELDS)
    assert bib[0]["arxiv_id"] == AID                          # bài đang parse, không phải bài được trích


def test_parse_one_through_run_writes_log(corpus, tmp_path):
    corpus(1, {"main.tex": _PREAMBLE + "A." + _END})
    corpus(2, {})
    log = tmp_path / "parse.csv"
    counts = run([AID], tmp_path / "parsed", verbose=False, log_path=log)
    assert counts == {"ok": 1, "empty": 1, "fail": 0, "skipped": 0}
    assert [(r["version"], r["status"]) for r in _read_log(log)] == [("1", "ok"), ("2", "empty")]
