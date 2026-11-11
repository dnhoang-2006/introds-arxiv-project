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
    """
    raise NotImplementedError
