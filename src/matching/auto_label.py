"""Matcher tự động gán nhãn cặp BibTeX entry và reference có arXiv ID (Milestone 3).

Sau khi hoàn thiện CLI (GĐ 4), các thành viên khác chạy chung bằng cách đổi `--ids` và `--mssv`:

    python src/matching/auto_label.py --ids ids/<MSSV>.txt --mssv <MSSV> --n 500 --seed 42 --exclude <file_pub_tay>
    python src/matching/auto_label.py --eval --gold <file_nhan_tay.jsonl>

Hiện tại (GĐ 2) module cung cấp phần đọc dữ liệu đầu vào, lọc candidate có `ref_arxiv_id`,
khớp bước 1 theo arXiv ID trong `url`/`doi` (và đối sánh DOI nếu candidate có), cùng ghi
JSONL nguyên tử.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SRC_DIR = str(Path(__file__).resolve().parent.parent)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config  # noqa: E402
from matching.textnorm import norm_arxiv, norm_doi  # noqa: E402

PARSED_ROOT = Path(os.environ.get("PARSED_ROOT", config.PROJECT_ROOT / "parsed"))
LABELS_ROOT = Path(os.environ.get("LABELS_ROOT", config.PROJECT_ROOT / "labels"))

# ID mới (YYMM.NNNN hoặc YYMM.NNNNN) hoặc ID cũ (archive[.subcat]/NNNNNNN).
_ARXIV_CORE = r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})"
_TAIL_BOUNDARY = r"(?:v\d+)?(?:\.pdf)?(?=$|[/?#&\s,;)\]}]|\.(?!\d))"

_ARXIV_HOST_URL_PAT = re.compile(
    rf"(?<![a-z0-9-])(?:[a-z0-9-]+\.)*arxiv\.org/(?:abs|pdf|html|e-print|src)/{_ARXIV_CORE}{_TAIL_BOUNDARY}",
    re.IGNORECASE,
)
_ARXIV_DOI_IN_URL_PAT = re.compile(
    rf"10\.48550/arxiv\.{_ARXIV_CORE}{_TAIL_BOUNDARY}",
    re.IGNORECASE,
)
_ARXIV_PREFIX_PAT = re.compile(
    rf"(?<![a-z0-9])arxiv:\s*{_ARXIV_CORE}{_TAIL_BOUNDARY}",
    re.IGNORECASE,
)
_DOI_ARXIV_PAT = re.compile(
    rf"^10\.48550/arxiv\.{_ARXIV_CORE}(?:v\d+)?$",
    re.IGNORECASE,
)


def _canon_arxiv(raw: str) -> str | None:
    """Chuẩn hóa ID và bỏ tiểu mục ID cũ (`math.GT/0309136` -> `math/0309136`) như Semantic Scholar."""
    aid = norm_arxiv(raw)
    return re.sub(r"^([a-z-]+)\.[a-z-]+/", r"\1/", aid) if aid else None


def _search_arxiv_patterns(raw: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for pattern in patterns:
        m = pattern.search(raw)
        if m:
            return _canon_arxiv(m.group(1))
    return None


def extract_arxiv_id_from_url(url: Any) -> str | None:
    """Tách arXiv ID chuẩn hóa từ `url`; trả None nếu URL không trỏ tới arXiv."""
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    return _search_arxiv_patterns(
        raw,
        (_ARXIV_HOST_URL_PAT, _ARXIV_PREFIX_PAT, _ARXIV_DOI_IN_URL_PAT),
    )


def extract_arxiv_id_from_doi(doi: Any) -> str | None:
    """Tách arXiv ID chuẩn hóa từ DOI dạng `10.48550/arXiv.<id>` (quyết định D4)."""
    clean_doi = norm_doi(doi)
    if not clean_doi:
        return None
    m = _DOI_ARXIV_PAT.match(clean_doi)
    return _canon_arxiv(m.group(1)) if m else None


def load_bibtex_entries(
    arxiv_id: str,
    parsed_root: Path = PARSED_ROOT,
) -> list[dict[str, Any]] | None:
    """Đọc `parsed/<pub_key>/bibtex.jsonl`; trả None nếu thiếu file hoặc JSON lỗi."""
    path = parsed_root / config.pub_key(arxiv_id) / "bibtex.jsonl"
    if not path.is_file():
        return None

    entries: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                entries.append(row)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return entries


def load_arxiv_candidates(
    arxiv_id: str,
    corpus_root: Path = config.CORPUS_ROOT,
) -> list[dict[str, Any]] | None:
    """Đọc `references.json` và giữ các reference có `ref_arxiv_id` khác null.

    Chỉ nhận publication có `status == "ok"`; trả None nếu thiếu file hoặc status khác.
    """
    path = corpus_root / config.pub_key(arxiv_id) / "references.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("status") != "ok":
        return None

    refs = data.get("references")
    if not isinstance(refs, list):
        return None
    return [
        ref for ref in refs
        if isinstance(ref, dict) and norm_arxiv(ref.get("ref_arxiv_id")) is not None
    ]


def _index_candidates(
    candidates: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Lập bảng tra cứu nhanh theo arXiv ID và DOI chuẩn hóa từ danh sách candidate."""
    by_arxiv: dict[str, dict[str, Any]] = {}
    by_doi: dict[str, dict[str, Any]] = {}
    for ref in candidates:
        aid = _canon_arxiv(str(ref.get("ref_arxiv_id") or ""))
        if not aid:
            continue
        by_arxiv.setdefault(aid, ref)
        ref_doi = norm_doi(ref.get("ref_doi") or ref.get("doi"))
        if ref_doi:
            by_doi.setdefault(ref_doi, ref)
    return by_arxiv, by_doi


def _label_record(
    arxiv_id: str,
    citation_key: str,
    ref: dict[str, Any] | None,
    method: str | None,
    score: float | None,
) -> dict[str, Any]:
    groundtruth = (
        config.strip_version(str(ref["ref_arxiv_id"]).strip())
        if ref is not None
        else None
    )
    return {
        "arxiv_id": arxiv_id,
        "citation_key": citation_key,
        "groundtruth_arxiv_id": groundtruth,
        "method": method,
        "score": score,
        "labeler": "auto",
    }


def match_entry(
    entry: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    pub_arxiv_id: str = "",
    by_arxiv: dict[str, dict[str, Any]] | None = None,
    by_doi: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Khớp một entry BibTeX với danh sách candidate có arXiv ID; trả về 1 bản ghi nhãn."""
    if by_arxiv is None or by_doi is None:
        by_arxiv, by_doi = _index_candidates(candidates)

    raw_pub_id = entry.get("arxiv_id") or pub_arxiv_id
    entry_arxiv_id = config.strip_version(str(raw_pub_id)) if raw_pub_id else ""
    citation_key = str(entry.get("citation_key") or "")

    # 1. URL có host arxiv.org hoặc tiền tố arXiv:
    raw_url = str(entry.get("url") or "").strip()
    url_aid = _search_arxiv_patterns(raw_url, (_ARXIV_HOST_URL_PAT, _ARXIV_PREFIX_PAT)) if raw_url else None
    if url_aid and url_aid in by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, by_arxiv[url_aid], "arxiv_url", 1.0)

    # 1b. Trường journal dạng "arXiv preprint arXiv:<id>" (ID tường minh)
    raw_journal = str(entry.get("journal") or "").strip()
    jr_aid = _search_arxiv_patterns(raw_journal, (_ARXIV_PREFIX_PAT,)) if raw_journal else None
    if jr_aid and jr_aid in by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, by_arxiv[jr_aid], "arxiv_url", 1.0)

    # 2. Trường doi: tách 10.48550/arXiv.<id> (D4), hoặc khớp DOI nếu reference có
    doi_aid = extract_arxiv_id_from_doi(entry.get("doi"))
    if doi_aid and doi_aid in by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, by_arxiv[doi_aid], "doi", 1.0)

    clean_doi = norm_doi(entry.get("doi"))
    if clean_doi and clean_doi in by_doi:
        return _label_record(entry_arxiv_id, citation_key, by_doi[clean_doi], "doi", 1.0)

    # 3. Fallback khi doi trống/không khớp nhưng url lại là link doi.org/10.48550/arXiv.<id>
    url_doi_aid = _search_arxiv_patterns(raw_url, (_ARXIV_DOI_IN_URL_PAT,)) if raw_url else None
    if url_doi_aid and url_doi_aid in by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, by_arxiv[url_doi_aid], "arxiv_url", 1.0)

    return _label_record(entry_arxiv_id, citation_key, None, None, None)


def label_entries(
    entries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    pub_arxiv_id: str = "",
) -> list[dict[str, Any]]:
    """Gán nhãn cho mọi entry của một publication; entry không khớp ghi `null` (D2)."""
    by_arxiv, by_doi = _index_candidates(candidates)
    return [
        match_entry(
            entry,
            candidates,
            pub_arxiv_id=pub_arxiv_id,
            by_arxiv=by_arxiv,
            by_doi=by_doi,
        )
        for entry in entries
    ]


def label_publication(
    arxiv_id: str,
    parsed_root: Path = PARSED_ROOT,
    corpus_root: Path = config.CORPUS_ROOT,
) -> list[dict[str, Any]] | None:
    """Đọc bibtex.jsonl + references.json và gán nhãn mọi entry của một publication."""
    base_id = config.strip_version(arxiv_id)
    entries = load_bibtex_entries(base_id, parsed_root=parsed_root)
    candidates = load_arxiv_candidates(base_id, corpus_root=corpus_root)
    if entries is None or candidates is None:
        return None
    return label_entries(entries, candidates, pub_arxiv_id=base_id)


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Ghi danh sách dict ra JSONL UTF-8 qua file `.tmp` rồi replace nguyên tử."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
