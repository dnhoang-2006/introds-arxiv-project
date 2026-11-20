"""tests/test_elements.py - Kiểm build_store của src/parser/elements.py.

Chạy từ thư mục gốc dự án:
    pytest tests/test_elements.py -v
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from parser.elements import KIND_CODE, build_store, element_uid  # noqa: E402
from parser.hierarchy import Node, build_tree  # noqa: E402

PUB = "2310-12345"
AID = "2310.12345"


def _tree(*sentences: str) -> Node:
    return Node("document", "", [Node("section", "Intro",
                                      [Node("sentence", s) for s in sentences])])


def _roots(hierarchy) -> dict[int, set[str]]:
    """Mỗi version: set(parent_id) - set(element_id)."""
    children: dict[int, set[str]] = defaultdict(set)
    parents: dict[int, set[str]] = defaultdict(set)
    for r in hierarchy:
        children[r["version"]].add(r["element_id"])
        parents[r["version"]].add(r["parent_id"])
    return {v: parents[v] - children[v] for v in parents}


# --------------------------------------------------------------------------- #
# Ca bắt buộc 6: hai version có 1 câu giống hệt
# --------------------------------------------------------------------------- #
def test_shared_sentence_one_element_two_edges():
    trees = {1: Node("document", "", [Node("sentence", "Same.")]),
             2: Node("document", "", [Node("sentence", "Same.")])}
    elements, hierarchy = build_store(PUB, AID, trees)

    sid = element_uid(PUB, "sentence", "Same.")
    assert [e for e in elements if e["kind"] == "sentence"] == [
        {"element_id": sid, "arxiv_id": AID, "kind": "sentence", "content": "Same."}]
    edges = [h for h in hierarchy if h["element_id"] == sid]
    assert len(edges) == 2
    assert {h["version"] for h in edges} == {1, 2}
    # Cùng câu nhưng cha khác nhau: gốc v1 và gốc v2.
    assert len({h["parent_id"] for h in edges}) == 2


# --------------------------------------------------------------------------- #
# Ca bắt buộc 7: set(parent_id) - set(element_id) có đúng 1 phần tử mỗi version
# --------------------------------------------------------------------------- #
def test_exactly_one_root_per_version():
    trees = {1: _tree("A b.", "C d."), 2: _tree("A b.", "E f."), 3: _tree("G h.")}
    _, hierarchy = build_store(PUB, AID, trees)
    roots = _roots(hierarchy)
    assert set(roots) == {1, 2, 3}
    for v, r in roots.items():
        assert r == {element_uid(PUB, "document", f"{AID}v{v}")}


def test_root_has_no_hierarchy_row_and_content_has_version():
    elements, hierarchy = build_store(PUB, AID, {1: _tree("x."), 2: _tree("x.")})
    docs = [e for e in elements if e["kind"] == "document"]
    assert sorted(d["content"] for d in docs) == [f"{AID}v1", f"{AID}v2"]
    doc_ids = {d["element_id"] for d in docs}
    assert not any(h["element_id"] in doc_ids for h in hierarchy)


def test_dedup_counts_across_versions():
    trees = {1: _tree("A.", "B."), 2: _tree("A.", "C.")}
    elements, hierarchy = build_store(PUB, AID, trees)
    # 2 gốc + 1 section "Intro" + câu A, B, C
    assert len(elements) == 6
    assert len({e["element_id"] for e in elements}) == len(elements)
    # Mỗi version: section + 2 câu = 3 cạnh.
    assert len(hierarchy) == 6


def test_schema_columns():
    elements, hierarchy = build_store(PUB, AID, {1: _tree("A.")})
    assert all(set(e) == {"element_id", "arxiv_id", "kind", "content"} for e in elements)
    assert all(set(h) == {"arxiv_id", "version", "element_id", "parent_id"}
               for h in hierarchy)
    assert all(isinstance(h["version"], int) for h in hierarchy)
    assert all(e["element_id"].startswith(PUB + "#") for e in elements)


def test_every_edge_endpoint_is_an_element():
    trees = {1: _tree("A.", "B."), 2: _tree("C.")}
    elements, hierarchy = build_store(PUB, AID, trees)
    ids = {e["element_id"] for e in elements}
    assert all(h["element_id"] in ids and h["parent_id"] in ids for h in hierarchy)


def test_empty_version_one_element_no_edges():
    # schema_m2.md mục 6
    elements, hierarchy = build_store(PUB, AID, {1: Node("document", "")})
    assert elements == [{"element_id": element_uid(PUB, "document", f"{AID}v1"),
                         "arxiv_id": AID, "kind": "document", "content": f"{AID}v1"}]
    assert hierarchy == []


def test_hierarchy_keeps_document_order():
    _, hierarchy = build_store(PUB, AID, {1: _tree("A.", "B.", "C.")})
    sentence_ids = [h["element_id"] for h in hierarchy if "#snt_" in h["element_id"]]
    assert sentence_ids == [element_uid(PUB, "sentence", s) for s in ("A.", "B.", "C.")]


def test_repeated_sentence_same_parent_single_edge():
    _, hierarchy = build_store(PUB, AID, {1: _tree("Dup.", "Dup.")})
    sid = element_uid(PUB, "sentence", "Dup.")
    assert sum(h["element_id"] == sid for h in hierarchy) == 1


def test_does_not_mutate_input_tree():
    t = _tree("A.")
    build_store(PUB, AID, {1: t})
    assert t.content == ""


def test_bad_root_kind_rejected():
    with pytest.raises(ValueError):
        build_store(PUB, AID, {1: Node("section", "x")})


def test_item_sentence_dedups_when_item_grows():
    # v1: \item một câu; v2: tác giả thêm một câu vào chính item đó.
    v1 = r"\begin{document}\begin{itemize}\item The model is fast.\end{itemize}\end{document}"
    v2 = (r"\begin{document}\begin{itemize}\item The model is fast. "
          r"We measured 3x speedup.\end{itemize}\end{document}")
    elements, hierarchy = build_store(PUB, AID, {1: build_tree(v1), 2: build_tree(v2)})
    fast = [e for e in elements
            if e["kind"] == "sentence" and e["content"] == "The model is fast."]
    assert len(fast) == 1                                # MỘT dòng, không phải hai
    assert {h["version"] for h in hierarchy if h["element_id"] == fast[0]["element_id"]} \
        == {1, 2}
    # Không còn element kind="item" nào là lá (item luôn có con).
    item_ids = {e["element_id"] for e in elements if e["kind"] == "item"}
    assert item_ids <= {h["parent_id"] for h in hierarchy}


def test_end_to_end_with_build_tree():
    v1 = (r"\begin{document}\section{Intro} We use BERT (Devlin et al. 2019). "
          r"The result is 3.14 times better.\begin{itemize}\item One.\item Two."
          r"\item Three.\end{itemize}\end{document}")
    v2 = v1.replace("3.14 times better.", "3.14 times better. New sentence.")
    elements, hierarchy = build_store(PUB, AID, {1: build_tree(v1), 2: build_tree(v2)})

    assert {e["kind"] for e in elements} <= set(KIND_CODE)
    roots = _roots(hierarchy)
    assert set(roots) == {1, 2}
    assert all(len(r) == 1 for r in roots.values())
    # Câu chung: một dòng element, mỗi version một cạnh.
    bert = element_uid(PUB, "sentence", "We use BERT (Devlin et al. 2019).")
    assert sum(e["element_id"] == bert for e in elements) == 1
    assert sum(h["element_id"] == bert for h in hierarchy) == 2
    assert sum(e["content"] == "New sentence." for e in elements) == 1
