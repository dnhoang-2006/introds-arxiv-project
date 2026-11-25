"""Matcher tự động gán nhãn cặp BibTeX entry và reference có arXiv ID (Milestone 3).

Sau khi hoàn thiện CLI (GĐ 4), các thành viên khác chạy chung bằng cách đổi `--ids` và `--mssv`:

    python src/matching/auto_label.py --ids ids/<MSSV>.txt --mssv <MSSV> --n 500 --seed 42 --exclude <file_pub_tay>
    python src/matching/auto_label.py --eval --gold <file_nhan_tay.jsonl>

Thứ tự khớp (dừng ở bước đầu tiên khớp): arXiv ID trong `url`/`journal`/`doi`,
đối sánh DOI (nếu candidate có), lọc ứng viên theo họ tác giả đầu và năm rồi so
tiêu đề chuẩn hóa bằng `difflib.SequenceMatcher`.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
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
from matching.textnorm import (  # noqa: E402
    clean_year,
    first_author_last_name,
    norm_arxiv,
    norm_doi,
    norm_title,
)

PARSED_ROOT = Path(os.environ.get("PARSED_ROOT", config.PROJECT_ROOT / "parsed"))
LABELS_ROOT = Path(os.environ.get("LABELS_ROOT", config.PROJECT_ROOT / "labels"))

DEFAULT_TITLE_THRESHOLD = 0.90
DEFAULT_MARGIN_THRESHOLD = 0.03
DEFAULT_YEAR_DELTA = 1
SHORT_TITLE_MIN_CHARS = 20
SHORT_TITLE_MIN_WORDS = 4
_MIN_PARTIAL_SURNAME_LEN = 3
_FLOAT_EPS = 1e-12

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


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    ref: dict[str, Any]
    canon_arxiv: str
    title: str | None
    surname: str | None
    year: int | None


@dataclass(frozen=True, slots=True)
class _CandidateIndex:
    by_arxiv: dict[str, dict[str, Any]]
    by_doi: dict[str, dict[str, Any]]
    prepared: list[_PreparedCandidate]


def _build_candidate_index(candidates: Iterable[dict[str, Any]]) -> _CandidateIndex:
    """Lập bảng tra cứu theo arXiv ID, DOI và thông tin đã chuẩn hóa của candidate."""
    by_arxiv: dict[str, dict[str, Any]] = {}
    by_doi: dict[str, dict[str, Any]] = {}
    prepared: list[_PreparedCandidate] = []
    for ref in candidates:
        aid = _canon_arxiv(str(ref.get("ref_arxiv_id") or ""))
        if not aid:
            continue
        by_arxiv.setdefault(aid, ref)
        ref_doi = norm_doi(ref.get("ref_doi") or ref.get("doi"))
        if ref_doi:
            by_doi.setdefault(ref_doi, ref)
        prepared.append(
            _PreparedCandidate(
                ref=ref,
                canon_arxiv=aid,
                title=norm_title(ref.get("ref_title")),
                surname=first_author_last_name(ref.get("ref_authors")),
                year=clean_year(ref.get("ref_year")),
            )
        )
    return _CandidateIndex(by_arxiv=by_arxiv, by_doi=by_doi, prepared=prepared)


def _surnames_match(a: str, b: str) -> bool:
    """So họ tác giả đầu, xử lý trường hợp bất đối xứng kiểu `benamor` vs `amor`."""
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= _MIN_PARTIAL_SURNAME_LEN and longer.endswith(shorter)


def _is_short_title(normed_title: str) -> bool:
    return (
        len(normed_title) < SHORT_TITLE_MIN_CHARS
        or len(normed_title.split()) < SHORT_TITLE_MIN_WORDS
    )


def _passes_author_year_filter(
    entry_surname: str | None,
    entry_year: int | None,
    cand: _PreparedCandidate,
    *,
    require_author: bool,
    year_delta: int,
) -> bool:
    if entry_surname and cand.surname:
        if not _surnames_match(entry_surname, cand.surname):
            return False
    elif require_author:
        return False

    if entry_year is not None and cand.year is not None:
        if abs(entry_year - cand.year) > year_delta:
            return False
    return True


def _match_by_title(
    entry: dict[str, Any],
    prepared: list[_PreparedCandidate],
    *,
    title_threshold: float,
    margin_threshold: float,
    year_delta: int,
) -> tuple[dict[str, Any] | None, float | None]:
    entry_title = norm_title(entry.get("title"))
    if not entry_title or not prepared:
        return None, None

    entry_surname = first_author_last_name(entry.get("authors"))
    short_title = _is_short_title(entry_title)
    if short_title and not entry_surname:
        return None, None

    entry_year = clean_year(entry.get("year"))
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for cand in prepared:
        if not cand.title:
            continue
        if not _passes_author_year_filter(
            entry_surname,
            entry_year,
            cand,
            require_author=short_title,
            year_delta=year_delta,
        ):
            continue
        ratio = SequenceMatcher(None, entry_title, cand.title).ratio()
        scored.append((ratio, cand.canon_arxiv, cand.ref))

    if not scored:
        return None, None

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_aid, best_ref = scored[0]
    if best_score + _FLOAT_EPS < title_threshold:
        return None, None

    second_score = next((s for s, aid, _ in scored[1:] if aid != best_aid), None)
    if second_score is not None and (best_score - second_score) + _FLOAT_EPS < margin_threshold:
        return None, None

    return best_ref, round(best_score, 4)


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


def _match_entry_indexed(
    entry: dict[str, Any],
    index: _CandidateIndex,
    *,
    pub_arxiv_id: str = "",
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    year_delta: int = DEFAULT_YEAR_DELTA,
) -> dict[str, Any]:
    raw_pub_id = entry.get("arxiv_id") or pub_arxiv_id
    entry_arxiv_id = config.strip_version(str(raw_pub_id)) if raw_pub_id else ""
    citation_key = str(entry.get("citation_key") or "")

    # 1. URL có host arxiv.org hoặc tiền tố arXiv:
    raw_url = str(entry.get("url") or "").strip()
    url_aid = _search_arxiv_patterns(raw_url, (_ARXIV_HOST_URL_PAT, _ARXIV_PREFIX_PAT)) if raw_url else None
    if url_aid and url_aid in index.by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, index.by_arxiv[url_aid], "arxiv_url", 1.0)

    # 1b. Trường journal dạng "arXiv preprint arXiv:<id>" (ID tường minh)
    raw_journal = str(entry.get("journal") or "").strip()
    jr_aid = _search_arxiv_patterns(raw_journal, (_ARXIV_PREFIX_PAT,)) if raw_journal else None
    if jr_aid and jr_aid in index.by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, index.by_arxiv[jr_aid], "arxiv_url", 1.0)

    # 2. Trường doi: tách 10.48550/arXiv.<id> (D4), hoặc khớp DOI nếu reference có
    doi_aid = extract_arxiv_id_from_doi(entry.get("doi"))
    if doi_aid and doi_aid in index.by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, index.by_arxiv[doi_aid], "doi", 1.0)

    clean_doi = norm_doi(entry.get("doi"))
    if clean_doi and clean_doi in index.by_doi:
        return _label_record(entry_arxiv_id, citation_key, index.by_doi[clean_doi], "doi", 1.0)

    # 3. Fallback khi doi trống/không khớp nhưng url lại là link doi.org/10.48550/arXiv.<id>
    url_doi_aid = _search_arxiv_patterns(raw_url, (_ARXIV_DOI_IN_URL_PAT,)) if raw_url else None
    if url_doi_aid and url_doi_aid in index.by_arxiv:
        return _label_record(entry_arxiv_id, citation_key, index.by_arxiv[url_doi_aid], "arxiv_url", 1.0)

    # 4. Lọc tác giả+năm và khớp tiêu đề chuẩn hóa (difflib + margin)
    title_ref, title_score = _match_by_title(
        entry,
        index.prepared,
        title_threshold=title_threshold,
        margin_threshold=margin_threshold,
        year_delta=year_delta,
    )
    if title_ref is not None:
        return _label_record(entry_arxiv_id, citation_key, title_ref, "title", title_score)

    return _label_record(entry_arxiv_id, citation_key, None, None, None)


def match_entry(
    entry: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    pub_arxiv_id: str = "",
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    year_delta: int = DEFAULT_YEAR_DELTA,
) -> dict[str, Any]:
    """Khớp một entry BibTeX với danh sách candidate có arXiv ID; trả về 1 bản ghi nhãn."""
    return _match_entry_indexed(
        entry,
        _build_candidate_index(candidates),
        pub_arxiv_id=pub_arxiv_id,
        title_threshold=title_threshold,
        margin_threshold=margin_threshold,
        year_delta=year_delta,
    )


def label_entries(
    entries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    pub_arxiv_id: str = "",
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    year_delta: int = DEFAULT_YEAR_DELTA,
) -> list[dict[str, Any]]:
    """Gán nhãn cho mọi entry của một publication; entry không khớp ghi `null` (D2)."""
    index = _build_candidate_index(candidates)
    return [
        _match_entry_indexed(
            entry,
            index,
            pub_arxiv_id=pub_arxiv_id,
            title_threshold=title_threshold,
            margin_threshold=margin_threshold,
            year_delta=year_delta,
        )
        for entry in entries
    ]


def label_publication(
    arxiv_id: str,
    parsed_root: Path = PARSED_ROOT,
    corpus_root: Path = config.CORPUS_ROOT,
    *,
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    year_delta: int = DEFAULT_YEAR_DELTA,
) -> list[dict[str, Any]] | None:
    """Đọc bibtex.jsonl + references.json và gán nhãn mọi entry của một publication."""
    base_id = config.strip_version(arxiv_id)
    entries = load_bibtex_entries(base_id, parsed_root=parsed_root)
    candidates = load_arxiv_candidates(base_id, corpus_root=corpus_root)
    if entries is None or candidates is None:
        return None
    return label_entries(
        entries,
        candidates,
        pub_arxiv_id=base_id,
        title_threshold=title_threshold,
        margin_threshold=margin_threshold,
        year_delta=year_delta,
    )


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
