"""tests/fixtures_m2.py - Cây nhỏ tự dựng cho validator_m2: vài cây đúng, nhiều cây cố tình sai.

Mỗi cây là dict {"elements": [...], "hierarchy": [...], "arxiv_id", "n_versions"}.
Cây sai được tạo bằng cách sửa đúng MỘT chỗ của cây GOOD, để biết phép kiểm nào phải bắt.

GOOD là ví dụ do đề đưa ra (trang parsing): hai version, câu s1 giữ nguyên nên dùng chung một
element_id, gắn vào h1 ở v1 và h2 ở v2. Khác bản trong đề việc: có đủ root2 và h2 trong
`elements` (nếu thiếu thì chính hierarchy của v2 đã là cây mồ côi), và content của gốc là
f"{arxiv_id}v{version}" theo schema_m2.md mục 2 (để rỗng thì hai gốc cùng băm ra một id).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from parser.elements import element_uid  # noqa: E402  # pyrefly: ignore[missing-import]

AID = "2310.12345"
PK = "2310-12345"


def E(eid, kind, content):
    return {"element_id": eid, "arxiv_id": AID, "kind": kind, "content": content}


def H(version, eid, parent):
    return {"arxiv_id": AID, "version": version, "element_id": eid, "parent_id": parent}


def _good() -> dict:
    return {
        "arxiv_id": AID, "n_versions": 2,
        "elements": [
            E(f"{PK}#root1", "document", f"{AID}v1"),
            E(f"{PK}#root2", "document", f"{AID}v2"),
            E(f"{PK}#h1", "section", "Introduction"),
            E(f"{PK}#h2", "section", "Background and model"),
            E(f"{PK}#s1", "sentence", "We study the citation matching problem"),
        ],
        "hierarchy": [
            H(1, f"{PK}#h1", f"{PK}#root1"),
            H(1, f"{PK}#s1", f"{PK}#h1"),
            H(2, f"{PK}#h2", f"{PK}#root2"),
            H(2, f"{PK}#s1", f"{PK}#h2"),
        ],
    }


def _good_real() -> dict:
    """Cùng cấu trúc nhưng id sinh bằng element_uid() đúng như parser thật."""
    def uid(kind, content):
        return element_uid(PK, kind, content)

    root1, root2 = uid("document", f"{AID}v1"), uid("document", f"{AID}v2")
    h1, h2 = uid("section", "Introduction"), uid("section", "Background and model")
    s1 = uid("sentence", "We study the citation matching problem")
    s2 = uid("sentence", "A new sentence only in version two.")
    f1 = uid("formula", r"\begin{equation}a+b\end{equation}")
    return {
        "arxiv_id": AID, "n_versions": 2,
        "elements": [
            E(root1, "document", f"{AID}v1"), E(root2, "document", f"{AID}v2"),
            E(h1, "section", "Introduction"), E(h2, "section", "Background and model"),
            E(s1, "sentence", "We study the citation matching problem"),
            E(s2, "sentence", "A new sentence only in version two."),
            E(f1, "formula", r"\begin{equation}a+b\end{equation}"),
        ],
        "hierarchy": [
            H(1, h1, root1), H(1, s1, h1), H(1, f1, h1),
            H(2, h2, root2), H(2, s1, h2), H(2, s2, h2),
        ],
    }


GOOD = _good()
GOOD_REAL = _good_real()


def _good_empty_version() -> dict:
    """Bài 3 version, v3 không có TeX: một dòng document, không có cạnh (schema_m2 mục 6)."""
    d = _good()
    d["n_versions"] = 3
    d["elements"].append(E(f"{PK}#root3", "document", f"{AID}v3"))
    return d


GOOD_EMPTY_VERSION = _good_empty_version()


def _mut(fn) -> dict:
    d = copy.deepcopy(GOOD)
    fn(d)
    return d


def _two_roots(d):                       # v1 có thêm một gốc thứ hai
    d["elements"] += [E(f"{PK}#root1b", "document", f"{AID}v1b"), E(f"{PK}#h9", "section", "Orphan section")]
    d["hierarchy"].append(H(1, f"{PK}#h9", f"{PK}#root1b"))


def _orphan_parent(d):                   # cha không có trong elements (nó cũng thành "gốc" thứ hai)
    d["elements"].append(E(f"{PK}#s5", "sentence", "Hanging sentence."))
    d["hierarchy"].append(H(1, f"{PK}#s5", f"{PK}#ghost"))


def _orphan_element(d):                  # node con không có trong elements
    d["hierarchy"].append(H(1, f"{PK}#ghost", f"{PK}#h1"))


def _cycle(d):                           # a là cha của b, b là cha của a
    d["elements"] += [E(f"{PK}#a", "section", "A"), E(f"{PK}#b", "section", "B")]
    d["hierarchy"] += [H(1, f"{PK}#a", f"{PK}#b"), H(1, f"{PK}#b", f"{PK}#a")]


def _self_parent(d):
    d["elements"].append(E(f"{PK}#a", "section", "A"))
    d["hierarchy"].append(H(1, f"{PK}#a", f"{PK}#a"))


def _leaf_parent(d):                     # câu s1 làm cha của câu s2
    d["elements"].append(E(f"{PK}#s2", "sentence", "Child of a sentence."))
    d["hierarchy"].append(H(1, f"{PK}#s2", f"{PK}#s1"))


def _two_parents_section(d):             # section h1 có hai cha trong v1
    d["elements"].append(E(f"{PK}#h9", "section", "Other"))
    d["hierarchy"] += [H(1, f"{PK}#h9", f"{PK}#root1"), H(1, f"{PK}#h1", f"{PK}#h9")]


def _dup_edge(d):
    d["hierarchy"].append(H(1, f"{PK}#s1", f"{PK}#h1"))


def _bad_kind(d):
    d["elements"][2]["kind"] = "paragraphs"


def _document_as_child(d):
    d["elements"].append(E(f"{PK}#doc2", "document", "nested"))
    d["hierarchy"].append(H(1, f"{PK}#doc2", f"{PK}#h1"))


def _dup_content(d):                     # hai id cho cùng một câu: dedup thất bại
    d["elements"].append(E(f"{PK}#s1copy", "sentence", "We study the citation matching problem"))
    d["hierarchy"].append(H(1, f"{PK}#s1copy", f"{PK}#h1"))


def _dup_element_id(d):
    d["elements"].append(E(f"{PK}#s1", "sentence", "Another content, same id"))


def _wrong_prefix(d):
    d["elements"].append(E("9999-99999#s7", "sentence", "Wrong publication."))
    d["hierarchy"].append(H(1, "9999-99999#s7", f"{PK}#h1"))


def _dash_arxiv_id(d):                   # arxiv_id bị đổi dấu như tên thư mục
    d["hierarchy"][0]["arxiv_id"] = PK


def _null_content(d):
    d["elements"][4]["content"] = None


def _null_arxiv_elements(d):             # elements: arxiv_id null
    d["elements"][2]["arxiv_id"] = None


def _no_arxiv_elements(d):               # elements: không có trường arxiv_id
    del d["elements"][2]["arxiv_id"]


def _null_arxiv_hierarchy(d):
    d["hierarchy"][0]["arxiv_id"] = None


def _no_arxiv_hierarchy(d):
    del d["hierarchy"][0]["arxiv_id"]


def _kind_list(d):                       # kind sai kiểu: list không băm được
    d["elements"][4]["kind"] = ["sentence"]


def _kind_dict(d):
    d["elements"][2]["kind"] = {"k": "section"}


def _kind_null(d):
    d["elements"][4]["kind"] = None


def _missing_version(d):                # n_versions = 3 mà chỉ có v1, v2
    d["n_versions"] = 3


def _unknown_version(d):                 # cạnh của v2 mang số version 7
    for row in d["hierarchy"]:
        if row["version"] == 2:
            row["version"] = 7


# tên -> (cây, tập phép kiểm PHẢI báo lỗi, đúng tập đó, không hơn không kém)
BAD_CASES = {
    "two_roots": (_mut(_two_roots), {"V1"}),
    "orphan_parent": (_mut(_orphan_parent), {"V1", "V2"}),   # cha "ma" cũng là một gốc nữa
    "orphan_element": (_mut(_orphan_element), {"V2"}),
    "cycle": (_mut(_cycle), {"V3"}),
    "self_parent": (_mut(_self_parent), {"V3"}),
    "leaf_parent": (_mut(_leaf_parent), {"V4"}),
    "section_two_parents": (_mut(_two_parents_section), {"V4"}),
    "duplicate_edge": (_mut(_dup_edge), {"V4"}),
    "bad_kind": (_mut(_bad_kind), {"V4"}),
    "document_as_child": (_mut(_document_as_child), {"V4"}),
    "duplicate_content": (_mut(_dup_content), {"V5"}),
    "duplicate_element_id": (_mut(_dup_element_id), {"V5"}),
    "wrong_prefix": (_mut(_wrong_prefix), {"V5"}),
    "dash_arxiv_id": (_mut(_dash_arxiv_id), {"V5"}),
    "null_content": (_mut(_null_content), {"V5"}),
    "null_arxiv_elements": (_mut(_null_arxiv_elements), {"V5"}),
    "no_arxiv_elements": (_mut(_no_arxiv_elements), {"V5"}),
    "null_arxiv_hierarchy": (_mut(_null_arxiv_hierarchy), {"V5"}),
    "no_arxiv_hierarchy": (_mut(_no_arxiv_hierarchy), {"V5"}),
    "kind_list": (_mut(_kind_list), {"V4"}),
    "kind_dict": (_mut(_kind_dict), {"V4"}),
    "kind_null": (_mut(_kind_null), {"V4"}),
    "missing_version": (_mut(_missing_version), {"V6"}),
    "unknown_version": (_mut(_unknown_version), {"V6"}),
}