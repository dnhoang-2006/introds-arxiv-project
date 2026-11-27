"""tests/test_manual_label.py — Kiểm scripts/manual_label.py.

Phần đáng kiểm: nhãn ghi đúng schema_m3 (mục 1–2), thoát giữa chừng không mất nhãn
và chạy lại thì làm tiếp, lệnh `b` xoá đúng nhãn vừa gán, đáp án luôn nằm trong
reference của chính bài (mục 7).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import manual_label as ml  # noqa: E402

AID = "2503.00001"
PK = "2503-00001"
REFS = [
    {"ref_arxiv_id": "1706.03762", "has_arxiv_id": True, "ref_title": "Attention is all you need",
     "ref_authors": ["Ashish Vaswani"], "ref_year": 2017},
    {"ref_arxiv_id": "1810.04805", "has_arxiv_id": True, "ref_title": "BERT: Pre-training of deep bidirectional transformers",
     "ref_authors": ["Jacob Devlin"], "ref_year": 2018},
    {"ref_arxiv_id": None, "has_arxiv_id": False, "ref_title": "Some book", "ref_authors": [], "ref_year": 1999},
]
ENTRIES = [
    {"citation_key": "vaswani2017", "title": "Attention Is All You Need", "authors": ["A. Vaswani"], "year": 2017},
    {"citation_key": "devlin2019", "title": "BERT", "authors": ["J. Devlin"], "year": 2019},
    {"citation_key": "knuth1984", "title": "Literate programming", "authors": ["D. Knuth"], "year": 1984},
]


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    parsed, corpus = tmp_path / "parsed", tmp_path / "corpus"
    (parsed / PK).mkdir(parents=True)
    (corpus / PK).mkdir(parents=True)
    (parsed / PK / "bibtex.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in ENTRIES), encoding="utf-8")
    (corpus / PK / "references.json").write_text(json.dumps({"status": "ok", "references": REFS}), encoding="utf-8")
    return parsed, corpus, tmp_path / "labels" / "manual" / "24120177.jsonl"


def _run(answers: list[str], parsed: Path, corpus: Path, out: Path, labels=None) -> tuple[bool, list]:
    it = iter(answers)
    labels = ml.load_progress(out) if labels is None else labels
    ok = ml.label_publication(AID, "24120177", out, labels, ask=lambda _: next(it),
                              parsed_root=parsed, corpus_root=corpus)
    return ok, labels


def _rows(out: Path) -> list[dict]:
    return [json.loads(l) for l in out.open(encoding="utf-8")]


def test_rank_puts_most_similar_title_first():
    refs = [r for r in REFS if r["ref_arxiv_id"]]
    assert ml.rank_candidates(ENTRIES[0], refs)[0] == 0
    assert ml.rank_candidates({"title": None}, refs) == [0, 1]       # không có tiêu đề: giữ thứ tự


def test_labels_follow_schema_and_null_rows_are_kept(tmp_path):
    parsed, corpus, out = _setup(tmp_path)
    ok, labels = _run(["1", "r2", "0"], parsed, corpus, out)
    assert ok
    rows = _rows(out)
    assert [r["citation_key"] for r in rows] == ["vaswani2017", "devlin2019", "knuth1984"]
    assert [r["groundtruth_arxiv_id"] for r in rows] == ["1706.03762", "1810.04805", None]
    assert all(set(r) == {"arxiv_id", "citation_key", "groundtruth_arxiv_id", "labeler", "method"} for r in rows)
    assert all(r["method"] == "manual" and r["labeler"] == "24120177" and r["arxiv_id"] == AID for r in rows)
    assert ml.count_matched(labels, AID) == 2


def test_quit_keeps_labels_and_rerun_resumes(tmp_path):
    parsed, corpus, out = _setup(tmp_path)
    ok, _ = _run(["1", "q"], parsed, corpus, out)
    assert not ok and len(_rows(out)) == 1
    ok, _ = _run(["0", "0"], parsed, corpus, out)             # chỉ còn 2 entry chưa gán
    assert ok
    assert [r["citation_key"] for r in _rows(out)] == ["vaswani2017", "devlin2019", "knuth1984"]


def test_back_removes_previous_label(tmp_path):
    parsed, corpus, out = _setup(tmp_path)
    _run(["1", "b", "0", "0", "0"], parsed, corpus, out)
    rows = _rows(out)
    assert len(rows) == 3
    assert rows[0]["citation_key"] == "vaswani2017" and rows[0]["groundtruth_arxiv_id"] is None


def test_invalid_choice_is_rejected_and_only_own_refs_allowed(tmp_path):
    parsed, corpus, out = _setup(tmp_path)
    _run(["9", "r3", "xyz", "2", "0", "0"], parsed, corpus, out)   # r3 là ref không có arXiv ID -> không có
    gts = {r["groundtruth_arxiv_id"] for r in _rows(out)} - {None}
    assert gts <= {r["ref_arxiv_id"] for r in REFS if r["ref_arxiv_id"]}


def test_suggest_filters_by_refs_and_exclude(tmp_path):
    parsed, corpus, _ = _setup(tmp_path)
    assert ml.suggest_pubs([AID], parsed_root=parsed, corpus_root=corpus, min_refs=2, max_entries=10) == [(AID, 3, 2)]
    assert ml.suggest_pubs([AID], parsed_root=parsed, corpus_root=corpus, min_refs=3) == []
    assert ml.suggest_pubs([AID], parsed_root=parsed, corpus_root=corpus, min_refs=2, exclude={AID}) == []
