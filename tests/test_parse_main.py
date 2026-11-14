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
