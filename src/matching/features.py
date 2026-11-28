"""Đặc trưng cho một cặp (entry BibTeX, reference ứng viên).

Mỗi ô của ma trận `m entry × n reference` biến thành một vector số. Thứ tự trong
`FEATURE_NAMES` là **cố định** — model lưu lại chỉ dùng được với đúng thứ tự này.

Thực nghiệm che định danh
-------------------------
`mask_ids=True` ép về 0 các đặc trưng trong `ID_FEATURES`, tức mọi đặc trưng rút
từ `url`/`doi` của entry. Lúc đó model buộc phải khớp bằng tiêu đề, tác giả và
năm.

Vì sao cần: M3 câu 7, một nhóm khác báo baseline chỉ so tiêu đề đã đạt
MRR@5 ≈ 0,99. Con số MRR một mình không phân biệt được nhóm nào với nhóm nào.
Thầy nói *"nhóm có thể báo cáo những kết quả phụ... Nếu nhóm phân tích rõ ràng
và đánh giá hợp lý thì điểm sẽ tính vào phần Eval & Analysis"*. Hiệu số giữa
MRR có che và không che cho thấy bài toán dễ tới đâu là nhờ định danh, chứ không
nhờ model.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

try:                                     # chạy được cả `python src/match_main.py`
    from matching.clean import (         # pyrefly: ignore[missing-import]
        author_key_set, clean_title, first_author_matches, title_tokens,
    )
    from matching.label_io import Pair   # pyrefly: ignore[missing-import]
except ImportError:                      # ...lẫn `from src.matching import features`
    from .clean import (
        author_key_set, clean_title, first_author_matches, title_tokens,
    )
    from .label_io import Pair

#: Thứ tự cố định. Đổi thứ tự là model cũ đọc sai đặc trưng.
FEATURE_NAMES: tuple[str, ...] = (
    "title_sim",
    "title_jaccard",
    "title_containment",
    "title_missing",
    "first_author_match",
    "author_overlap",
    "author_missing",
    "year_match",
    "year_diff",
    "year_missing",
    # --- định danh, bị che khi mask_ids=True ---
    "arxiv_in_url",
    "arxiv_in_doi",
)

#: Đặc trưng rút từ định danh của entry. `--mask-ids` ép cả nhóm này về 0.
ID_FEATURES: frozenset[str] = frozenset({"arxiv_in_url", "arxiv_in_doi"})

_ID_INDEX: tuple[int, ...] = tuple(
    i for i, n in enumerate(FEATURE_NAMES) if n in ID_FEATURES
)

#: Năm lệch quá ngưỡng này thì coi như lệch tối đa. Bản in lại của một bài cũ
#: hiếm khi lệch quá 5 năm so với năm ghi trong mục trích dẫn.
MAX_YEAR_DIFF = 5


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _year(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.search(r"\b(19|20)\d{2}\b", v)
        return int(m.group(0)) if m else None
    return None


def _arxiv_in(text: str | None, arxiv_id: str) -> float:
    """`arxiv_id` có xuất hiện trong chuỗi không, bỏ qua phiên bản `v2`.

    Bắt cả `arxiv.org/abs/2301.12345`, `10.48550/arXiv.2301.12345v2` và
    `https://doi.org/10.48550/arxiv.2301.12345`.
    """
    if not text or not arxiv_id:
        return 0.0
    return 1.0 if arxiv_id.lower() in text.lower() else 0.0


def pair_features(p: Pair, *, mask_ids: bool = False) -> list[float]:
    """Vector đặc trưng của một cặp, theo đúng thứ tự `FEATURE_NAMES`."""
    et, ct = clean_title(p.entry_title), clean_title(p.cand_title)
    etok, ctok = set(title_tokens(p.entry_title)), set(title_tokens(p.cand_title))
    inter = etok & ctok
    union = etok | ctok

    ea, ca = author_key_set(p.entry_authors), author_key_set(p.cand_authors)
    a_inter = ea & ca

    ey, cy = _year(p.entry_year), _year(p.cand_year)
    if ey is None or cy is None:
        year_match = year_diff = 0.0
        year_missing = 1.0
    else:
        d = abs(ey - cy)
        year_match = 1.0 if d == 0 else 0.0
        year_diff = min(d, MAX_YEAR_DIFF) / MAX_YEAR_DIFF
        year_missing = 0.0

    feats = [
        _ratio(et, ct),
        len(inter) / len(union) if union else 0.0,
        # containment: entry bóc từ .bbl hay bị cắt cụt tiêu đề, nên tiêu đề ngắn
        # nằm trọn trong tiêu đề dài vẫn là dấu hiệu khớp mạnh.
        len(inter) / min(len(etok), len(ctok)) if etok and ctok else 0.0,
        1.0 if not et or not ct else 0.0,
        1.0 if first_author_matches(p.entry_authors, p.cand_authors) else 0.0,
        len(a_inter) / min(len(ea), len(ca)) if ea and ca else 0.0,
        1.0 if not ea or not ca else 0.0,
        year_match,
        year_diff,
        year_missing,
        _arxiv_in(p.entry_url, p.cand_arxiv_id),
        _arxiv_in(p.entry_doi, p.cand_arxiv_id),
    ]
    assert len(feats) == len(FEATURE_NAMES), "lệch số đặc trưng"
    if mask_ids:
        for i in _ID_INDEX:
            feats[i] = 0.0
    return feats


def feature_matrix(pairs: list[Pair], *, mask_ids: bool = False) -> list[list[float]]:
    return [pair_features(p, mask_ids=mask_ids) for p in pairs]
