"""tests/test_match_main.py — chia tập, MRR@5 và bảng predictions.

Ba thứ đáng kiểm nhất, vì sai là hỏng âm thầm chứ không văng lỗi:

1. Tập Q loại entry `groundtruth_arxiv_id = null` khỏi **mẫu số** MRR nhưng
   **vẫn giữ hàng** trong `predictions` (M3 câu 4 ý 2).
2. Chia tập theo **publication**, không theo entry — hai entry cùng bài rơi vào
   train với test khác nhau là rò rỉ dữ liệu.
3. `--mask-ids` phải ép đúng các đặc trưng định danh về 0, không đụng cái khác.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.match_main import (
    DEFAULT_N_TEST, K, Query, collect_queries, mrr_at_k, prediction_rows,
    rank_query, reciprocal_rank, run, split_publications,
)
from src.matching.features import FEATURE_NAMES, ID_FEATURES, pair_features
from src.matching.label_io import Label, Pair, load_labels

MSSV = "24120053"


def _pub(aid: str) -> str:
    return aid.replace(".", "-")


@pytest.fixture
def tree(tmp_path: Path):
    """Dựng labels/ + parsed/ + corpus/ giả cho `n_pub` publication.

    Mỗi bài: 3 entry, 4 reference. Entry 1 và 2 khớp reference 1 và 2; entry 3
    cố ý không khớp gì (nhãn null) để kiểm tập Q.
    """
    def build(n_pub: int = 4, method: str = "manual"):
        labels_dir = tmp_path / "labels" / method
        labels_dir.mkdir(parents=True)
        rows = []
        for i in range(n_pub):
            aid = f"2507.0{6659 + i}"
            pdir = tmp_path / "parsed" / _pub(aid)
            cdir = tmp_path / "corpus" / _pub(aid)
            pdir.mkdir(parents=True)
            cdir.mkdir(parents=True)

            entries = [
                {"citation_key": "vaswani2017", "title": "Attention Is All You Need",
                 "authors": ["Vaswani, Ashish"], "year": 2017, "doi": None, "url": None},
                {"citation_key": "he2016", "title": "Deep Residual Learning",
                 "authors": ["He, Kaiming"], "year": 2016, "doi": None,
                 "url": "https://arxiv.org/abs/1512.03385"},
                {"citation_key": "nomatch", "title": "A Book Nobody Indexed",
                 "authors": ["Nobody, A."], "year": 1990, "doi": None, "url": None},
            ]
            (pdir / "bibtex.jsonl").write_text(
                "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

            refs = [
                {"ref_arxiv_id": "1706.03762", "has_arxiv_id": True,
                 "ref_title": "Attention Is All You Need",
                 "ref_authors": ["Ashish Vaswani"], "ref_year": 2017},
                {"ref_arxiv_id": "1512.03385", "has_arxiv_id": True,
                 "ref_title": "Deep Residual Learning for Image Recognition",
                 "ref_authors": ["Kaiming He"], "ref_year": 2016},
                {"ref_arxiv_id": "1409.1556", "has_arxiv_id": True,
                 "ref_title": "Very Deep Convolutional Networks",
                 "ref_authors": ["Karen Simonyan"], "ref_year": 2014},
                {"ref_arxiv_id": "1810.04805", "has_arxiv_id": True,
                 "ref_title": "BERT Pre-training of Deep Bidirectional Transformers",
                 "ref_authors": ["Jacob Devlin"], "ref_year": 2018},
            ]
            (cdir / "references.json").write_text(
                json.dumps({"arxiv_id": aid, "status": "ok", "references": refs}),
                encoding="utf-8")

            for key, gt in (("vaswani2017", "1706.03762"),
                            ("he2016", "1512.03385"),
                            ("nomatch", None)):
                rows.append({"arxiv_id": aid, "citation_key": key,
                             "groundtruth_arxiv_id": gt, "labeler": MSSV,
                             "method": method})
        (labels_dir / f"{MSSV}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return tmp_path
    return build


def _run(root: Path, **kw):
    return run(labels_root=root / "labels", parsed_root=root / "parsed",
               corpus_root=root / "corpus", out_dir=root / "pred",
               n_test=1, n_valid=1, **kw)


# ----------------------------------------------------------------- tập Q

def test_null_label_keeps_row_but_leaves_q_set(tree):
    root = tree(4)
    res = _run(root, model_name="baseline")
    m = res["metrics"]
    # 4 bài × 3 entry = 12 entry, trong đó 4 entry nhãn null
    assert m["n_queries"] == 12
    assert sum(m[p]["n_queries"] for p in ("train", "valid", "test")) == 12
    assert sum(m[p]["n_scorable"] for p in ("train", "valid", "test")) == 8

    rows = [json.loads(l) for l in (root / "pred" / f"{MSSV}.jsonl").open(encoding="utf-8")]
    assert len(rows) == 12, "entry nhãn null vẫn phải có hàng trong predictions"
    assert sum(1 for r in rows if r["groundtruth_arxiv_id"] is None) == 4


def test_mrr_ignores_unscorable_queries():
    q_ok = Query("a", "k1", MSSV, "manual", "X", [])
    q_null = Query("a", "k2", MSSV, "manual", None, [])
    mrr, n = mrr_at_k([(q_ok, ["X"]), (q_null, ["Y"])])
    assert (mrr, n) == (1.0, 1), "entry null không được kéo MRR xuống"


@pytest.mark.parametrize(("gt", "top", "want"), [
    ("X", ["X", "a", "b"], 1.0),
    ("X", ["a", "X", "b"], 0.5),
    ("X", ["a", "b", "X"], 1 / 3),
    ("X", ["a", "b", "c"], 0.0),
    (None, ["X"], 0.0),
])
def test_reciprocal_rank(gt, top, want):
    assert reciprocal_rank(gt, top) == pytest.approx(want)


# ----------------------------------------------------------------- chia tập

def test_split_is_by_publication_not_by_entry(tree):
    root = tree(4)
    labels = load_labels(root / "labels")
    qs = collect_queries(labels, parsed_root=root / "parsed", corpus_root=root / "corpus")
    part = split_publications(qs, n_test=1, n_valid=1)
    for q in qs:
        assert q.arxiv_id in part
    # mọi entry của cùng một bài phải cùng một tập
    seen: dict[str, set[str]] = {}
    for q in qs:
        seen.setdefault(q.arxiv_id, set()).add(part[q.arxiv_id])
    assert all(len(v) == 1 for v in seen.values())
    assert sorted(part.values()).count("test") == 1


def test_split_is_deterministic_for_a_seed(tree):
    root = tree(6)
    labels = load_labels(root / "labels")
    qs = collect_queries(labels, parsed_root=root / "parsed", corpus_root=root / "corpus")
    a = split_publications(qs, seed=7, n_test=1, n_valid=1)
    b = split_publications(qs, seed=7, n_test=1, n_valid=1)
    assert a == b


def test_manual_and_auto_both_reach_test_set():
    """Test phải có cả nhãn tay lẫn nhãn tự động, không chỉ một loại.

    Nhãn tay đáng tin hơn nhiều; Test thiếu nhãn tay thì MRR chỉ đang đo lại
    chính matcher luật đã sinh ra nhãn tự động, không đo thêm được gì.
    """
    qs_manual = [Query(f"m{i}", "k", MSSV, "manual", "X", []) for i in range(3)]
    qs_auto = [Query(f"a{i}", "k", MSSV, "auto", "X", []) for i in range(3)]
    part = split_publications(qs_manual + qs_auto, n_test=1, n_valid=1)
    test_pubs = [a for a, v in part.items() if v == "test"]
    assert len(test_pubs) == 2
    assert any(a.startswith("m") for a in test_pubs)
    assert any(a.startswith("a") for a in test_pubs)


# ----------------------------------------------------------------- model

def test_baseline_ranks_by_title_alone(tree):
    root = tree(4)
    res = _run(root, model_name="baseline")
    assert res["metrics"]["test"]["mrr@5"] == pytest.approx(1.0), \
        "tiêu đề trong fixture khớp gần như hoàn hảo nên baseline phải đạt 1.0"


def test_logreg_runs_and_reports_coefficients(tree):
    root = tree(6)
    res = _run(root, model_name="logreg")
    assert res["metrics"]["model"] == "logreg"
    coef = res["metrics"].get("coefficients")
    assert coef and set(coef) == set(FEATURE_NAMES)


def test_logreg_survives_single_class_training_set(tree):
    """Chạy thử với --limit nhỏ có thể cho tập train toàn nhãn âm."""
    root = tree(4)
    res = _run(root, model_name="logreg", limit=2)
    assert "test" in res["metrics"]


# ----------------------------------------------------------------- che định danh

def test_mask_ids_zeroes_only_identifier_features():
    p = Pair(arxiv_id="a", citation_key="k", cand_arxiv_id="1512.03385", label=1,
             method="manual", entry_title="Deep Residual Learning",
             entry_authors=["He, Kaiming"], entry_year=2016, entry_doi=None,
             entry_url="https://arxiv.org/abs/1512.03385",
             cand_title="Deep Residual Learning for Image Recognition",
             cand_authors=["Kaiming He"], cand_year=2016, cand_venue=None)
    plain = dict(zip(FEATURE_NAMES, pair_features(p)))
    masked = dict(zip(FEATURE_NAMES, pair_features(p, mask_ids=True)))

    assert plain["arxiv_in_url"] == 1.0
    assert all(masked[n] == 0.0 for n in ID_FEATURES)
    for n in FEATURE_NAMES:
        if n not in ID_FEATURES:
            assert masked[n] == plain[n], f"{n} không được đụng tới"


def test_mask_ids_changes_nothing_else_in_the_run(tree):
    root = tree(4)
    plain = _run(root, model_name="baseline")
    masked = _run(root, model_name="baseline", mask_ids=True)
    assert masked["metrics"]["mask_ids"] is True
    # baseline chỉ dùng tiêu đề nên che định danh không đổi thứ hạng
    assert masked["metrics"]["test"]["mrr@5"] == plain["metrics"]["test"]["mrr@5"]


# ----------------------------------------------------------------- predictions

def test_predictions_has_exactly_eight_columns(tree):
    root = tree(4)
    _run(root, model_name="baseline")
    rows = [json.loads(l) for l in (root / "pred" / f"{MSSV}.jsonl").open(encoding="utf-8")]
    want = ["arxiv_id", "partition", "citation_key", "groundtruth_arxiv_id",
            *[f"cand_{i}" for i in range(1, K + 1)]]
    assert list(rows[0].keys()) == want
    assert all(r["partition"] in ("train", "valid", "test") for r in rows)


def test_predictions_pads_with_null_when_fewer_than_five_candidates():
    """M3 câu 4 ý 5: dưới 5 candidate thì điền null vào ô thiếu."""
    q = Query("a", "k", MSSV, "manual", "X", [])
    rows = prediction_rows({"train": [(q, ["X", "Y"])], "valid": [], "test": []},
                           {"a": "train"})
    r = rows[MSSV][0]
    assert (r["cand_1"], r["cand_2"]) == ("X", "Y")
    assert r["cand_3"] is r["cand_4"] is r["cand_5"] is None


def test_predictions_grouped_by_labeler():
    qs = [Query("a", "k", "24120053", "manual", "X", []),
          Query("b", "k", "24120177", "manual", "Y", [])]
    rows = prediction_rows(
        {"train": [(qs[0], ["X"]), (qs[1], ["Y"])], "valid": [], "test": []},
        {"a": "train", "b": "train"})
    assert set(rows) == {"24120053", "24120177"}


# ----------------------------------------------------------------- lỗi đầu vào

def test_empty_labels_dir_is_a_clear_error(tmp_path):
    (tmp_path / "labels").mkdir()
    with pytest.raises(ValueError, match="Không có nhãn nào"):
        run(labels_root=tmp_path / "labels", write=False)


def test_labels_without_parsed_data_is_a_clear_error(tmp_path, tree):
    root = tree(2)
    with pytest.raises(ValueError, match="không dựng được ứng viên"):
        run(labels_root=root / "labels", parsed_root=tmp_path / "khong-co",
            corpus_root=tmp_path / "khong-co", write=False)


def test_default_split_sizes_match_the_group_decision():
    assert DEFAULT_N_TEST == 5, "schema_m3: Test = 5 pub tay + 5 pub tự động"
