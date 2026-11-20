"""tests/test_gather.py - Kiểm src/parser/gather.py trên corpus giả dựng trong tmp_path.

Chạy từ thư mục gốc dự án:
    pytest tests/test_gather.py -v
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from parser.gather import (  # noqa: E402  # pyrefly: ignore[missing-import]
    LOG_COLUMNS,
    gather,
    gather_detail,
    ordered_includes,
    resolve_path,
    run,
)

DOC = "\\documentclass{article}\n\\begin{document}\n"
END = "\n\\end{document}\n"


def make(vdir: Path, files: dict[str, str]) -> Path:
    """Tạo một thư mục version giả: {đường dẫn tương đối: nội dung}."""
    for rel, text in files.items():
        p = vdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return vdir


def names(paths: list[Path], vdir: Path) -> list[str]:
    return [p.relative_to(vdir.resolve()).as_posix() for p in paths]


# Các ca bắt buộc
def test_basic_path_and_unused(tmp_path):
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "\\input{sec/intro}\n\\include{sec/method}" + END,
        "sec/intro.tex": "Intro.",
        "sec/method.tex": "Method.",
        "old_draft.tex": "Not compiled.",
    })
    path, unused = gather(v)
    assert names(path, v) == ["main.tex", "sec/intro.tex", "sec/method.tex"]
    assert names(unused, v) == ["old_draft.tex"]


def test_include_cycle_does_not_hang(tmp_path):
    """a gọi b, b gọi lại a — phải dừng, mỗi file xuất hiện đúng một lần."""
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "\\input{a}" + END,
        "a.tex": "\\input{b}",
        "b.tex": "\\input{a}\n\\input{main}",
    })
    path, unused = gather(v)
    assert names(path, v) == ["main.tex", "a.tex", "b.tex"]
    assert unused == []


def test_self_include(tmp_path):
    v = make(tmp_path / "v1", {"main.tex": DOC + "\\input{main}" + END})
    path, _ = gather(v)
    assert names(path, v) == ["main.tex"]


def test_no_root(tmp_path):
    v = make(tmp_path / "v1", {"a.tex": "No documentclass.", "b.tex": "Neither."})
    r = gather_detail(v)
    assert r.compile_path == []
    assert names(r.unused, v) == ["a.tex", "b.tex"]
    assert (r.status, r.error_type) == ("fail", "no_root")


def test_documentclass_in_comment_is_not_root(tmp_path):
    v = make(tmp_path / "v1", {"a.tex": "% \\documentclass{article}\nText."})
    assert gather_detail(v).error_type == "no_root"


def test_empty_version(tmp_path):
    v = make(tmp_path / "v1", {"_EMPTY.json": '{"reason": "pdf_only"}'})
    r = gather_detail(v)
    assert (r.compile_path, r.unused) == ([], [])
    assert (r.status, r.error_type) == ("empty", "empty_version")


def test_missing_include_counted_not_crash(tmp_path):
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "\\input{missing}\n\\input{fig.pgf}\n\\input{ok}" + END,
        "ok.tex": "OK.",
    })
    r = gather_detail(v)
    assert names(r.compile_path, v) == ["main.tex", "ok.tex"]
    assert r.n_missing_includes == 2
    assert r.status == "ok"


def test_commented_include_is_plain_text(tmp_path):
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "%\\input{old}\nText % \\include{old2}\n\\input{new}" + END,
        "old.tex": "x", "old2.tex": "y", "new.tex": "z",
    })
    path, unused = gather(v)
    assert names(path, v) == ["main.tex", "new.tex"]
    assert names(unused, v) == ["old.tex", "old2.tex"]


def test_escaped_percent_is_not_comment(tmp_path):
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "50\\% done \\input{a}" + END, "a.tex": "A",
    })
    assert names(gather(v)[0], v) == ["main.tex", "a.tex"]


# Thứ tự, đường dẫn
def test_depth_first_order(tmp_path):
    """Thứ tự phải là thứ tự LaTeX đọc: con1, CHÁU của con1, rồi mới con2."""
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "\\input{c1}\n\\input{c2}" + END,
        "c1.tex": "\\input{g1}", "c2.tex": "C2", "g1.tex": "G1",
    })
    assert names(gather(v)[0], v) == ["main.tex", "c1.tex", "g1.tex", "c2.tex"]


def test_bare_input_keeps_order():
    assert ordered_includes("\\input a\n\\input{b}\n\\input c.tex") == ["a", "b", "c.tex"]


def test_includegraphics_is_not_include():
    assert ordered_includes("\\includegraphics{fig1}\\includeonly{x}") == []


def test_resolve_does_not_replace_suffix(tmp_path):
    """\\input{sec/intro.v2} phải ra sec/intro.v2.tex, không phải sec/intro.tex."""
    make(tmp_path, {"sec/intro.v2.tex": "x", "sec/intro.tex": "y"})
    got = resolve_path(tmp_path, "sec/intro.v2", tmp_path)
    assert got == (tmp_path / "sec/intro.v2.tex").resolve()


def test_resolve_relative_to_parent_file(tmp_path):
    make(tmp_path, {"chap/a.tex": "x", "chap/b.tex": "y"})
    assert resolve_path(tmp_path / "chap", "b", tmp_path) == (tmp_path / "chap/b.tex").resolve()


def test_resolve_refuses_outside_version(tmp_path):
    (tmp_path / "secret.tex").write_text("x")
    v = tmp_path / "v1"
    v.mkdir()
    assert resolve_path(v, "../secret", v) is None


def test_root_in_subfolder_resolves_from_root_dir(tmp_path):
    v = make(tmp_path / "v1", {
        "paper/main.tex": DOC + "\\input{sections/a}" + END,
        "paper/sections/a.tex": "A",
    })
    assert names(gather(v)[0], v) == ["paper/main.tex", "paper/sections/a.tex"]


def test_multiple_roots_picks_main(tmp_path):
    v = make(tmp_path / "v1", {
        "main.tex": DOC + "\\input{body}" + END,
        "template.tex": DOC + END,
        "body.tex": "B",
    })
    r = gather_detail(v)
    assert names([r.root], v) == ["main.tex"]
    assert names(r.unused, v) == ["template.tex"]


# run() và logs/gather.csv
def test_run_writes_log_with_schema_columns(tmp_path, monkeypatch):
    import config  # pyrefly: ignore[missing-import]
    corpus = tmp_path / "corpus"
    monkeypatch.setattr(config, "CORPUS_ROOT", corpus)
    make(corpus / "2507-06659" / "v1", {"main.tex": DOC + "\\input{a}" + END, "a.tex": "A"})
    make(corpus / "2507-06659" / "v2", {"_EMPTY.json": "{}"})
    make(corpus / "2507-06660" / "v1", {"x.tex": "no root"})
    log = tmp_path / "logs" / "gather.csv"

    run(["2507.06659", "2507.06660"], log_path=log, quiet=True)

    with open(log, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == LOG_COLUMNS
    got = [(r["arxiv_id"], r["version"], r["root_file"], r["n_files_path"],
            r["n_files_unused"], r["status"], r["error_type"]) for r in rows]
    assert got == [
        ("2507.06659", "1", "main.tex", "2", "0", "ok", ""),
        ("2507.06659", "2", "", "0", "0", "empty", "empty_version"),
        ("2507.06660", "1", "", "0", "1", "fail", "no_root"),
    ]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))