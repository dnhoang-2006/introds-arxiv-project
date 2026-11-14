"""Test cơ chế chạy lại được từ giữa chừng của src/parse_main.py.

parse_one() là việc tuần 2 nên ở đây thay bằng hàm giả; chỉ kiểm phần vòng lặp:
bỏ qua bài đã xong, --overwrite, ghi log, lỗi một bài không dừng cả mẻ.
"""

import csv
from pathlib import Path

import pytest

from parse_main import PARSE_LOG_FIELDS, already_done, run, write_outputs


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


def test_workers_plug_point(tmp_path):
    with pytest.raises(NotImplementedError):
        run(["2310.12345"], tmp_path / "p", verbose=False,
            log_path=tmp_path / "parse.csv", parse_fn=lambda a, o: [], workers=2)
    with pytest.raises(ValueError):
        run([], tmp_path / "p", log_path=tmp_path / "parse.csv", workers=0)


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
