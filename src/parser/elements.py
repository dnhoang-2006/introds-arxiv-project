"""Kho element dùng chung và dedup nội dung xuyên version."""

from __future__ import annotations

import hashlib
from typing import Any

from .hierarchy import Node

KIND_CODE = {
    "document": "doc", "section": "sec", "subsection": "sub",
    "subsubsection": "ssb", "paragraph": "par", "itemize": "itz",
    "item": "itm", "sentence": "snt", "formula": "eqn", "figure": "fig",
}


def element_uid(pub_key: str, kind: str, clean_content: str) -> str:
    """2310-12345#snt_a3f9c201 — xem docs/schema_m2.md mục 2.

    Dedup xảy ra TỰ ĐỘNG: cùng nội dung đã chuẩn hoá -> cùng id.
    """
    payload = f"{kind}\x00{clean_content}".encode("utf-8")
    return f"{pub_key}#{KIND_CODE[kind]}_{hashlib.sha1(payload).hexdigest()[:8]}"


def build_store(
    pub_key: str,
    arxiv_id: str,
    trees: dict[int, Node],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dựng bảng elements (dùng chung) và hierarchy (theo từng version).

    ⚠️ `trees` phải dựng từ văn bản ĐÃ đổi tên \\cite (đầu ra bước 4 của pipeline).
       Băm nhầm văn bản chưa đổi tên thì code vẫn chạy trơn, không báo lỗi gì,
       chỉ là dedup_ratio gần 0 ở các bài nhiều version. Đó là dấu hiệu nhận biết.

    Node gốc KHÔNG có dòng trong hierarchy (nó không có cha).
    content của node gốc là f"{arxiv_id}v{version}" để hai version không bị gộp.

    Returns:
        (elements, hierarchy) theo đúng schema mục 1.1 và 1.2.
        Version có cây rỗng (chỉ có gốc) cho đúng một dòng element và 0 dòng
        hierarchy — khớp schema mục 6.
    """
    # Dedup = ghi đè theo element_id: cùng kind + nội dung đã chuẩn hoá -> cùng id.
    elements: dict[str, dict[str, Any]] = {}
    hierarchy: list[dict[str, Any]] = []

    def add_element(kind: str, content: str) -> str:
        eid = element_uid(pub_key, kind, content)
        elements[eid] = {"element_id": eid, "arxiv_id": arxiv_id,
                         "kind": kind, "content": content}
        return eid

    for version in sorted(trees):
        root = trees[version]
        if root.kind != "document":
            raise ValueError(f"gốc của v{version} phải có kind='document', gặp {root.kind!r}")
        root_id = add_element("document", f"{arxiv_id}v{version}")

        # Cùng một câu lặp lại dưới cùng một cha trong một version -> chỉ một cạnh.
        seen: set[tuple[str, str]] = set()
        stack: list[tuple[Node, str]] = [(c, root_id) for c in reversed(root.children)]
        while stack:                              # DFS tiền thứ tự, giữ thứ tự văn bản
            node, parent_id = stack.pop()
            eid = add_element(node.kind, node.content)
            if (eid, parent_id) not in seen:
                seen.add((eid, parent_id))
                hierarchy.append({"arxiv_id": arxiv_id, "version": version,
                                  "element_id": eid, "parent_id": parent_id})
            stack.extend((c, eid) for c in reversed(node.children))

    return list(elements.values()), hierarchy
