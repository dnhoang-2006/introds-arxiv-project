"""Matcher tự động gán nhãn cặp BibTeX entry và reference có arXiv ID (Milestone 3).

Dùng chung cho 5 thành viên (chỉ cần đổi `--ids` và `--mssv`):

    python src/matching/auto_label.py --ids ids/<MSSV>.txt --mssv <MSSV> --n 500 --seed 42 [--exclude FILE] [--overwrite] [--dry-run]
    python src/matching/auto_label.py --eval --gold <file_nhan_tay.jsonl>

Thứ tự khớp (dừng ở bước đầu tiên khớp): arXiv ID trong `url`/`journal`/`doi`,
tách `10.48550/arXiv.<id>` từ `doi`, lọc ứng viên theo họ tác giả đầu và năm rồi so
tiêu đề chuẩn hóa bằng `difflib.SequenceMatcher`.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SRC_DIR = str(Path(__file__).resolve().parent.parent)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config  # noqa: E402
from matching.textnorm import (  # noqa: E402
    Author,
    clean_year,
    first_author,
    norm_arxiv,
    norm_doi,
    norm_title,
    same_first_author,
)

PARSED_ROOT = Path(os.environ.get("PARSED_ROOT", config.PROJECT_ROOT / "parsed"))
LABELS_ROOT = Path(os.environ.get("LABELS_ROOT", config.PROJECT_ROOT / "labels"))

DEFAULT_TITLE_THRESHOLD = 0.90
DEFAULT_MARGIN_THRESHOLD = 0.03
DEFAULT_YEAR_DELTA = 1
DEFAULT_MIN_ENTRIES = 1
DEFAULT_MAX_ENTRIES = 1000
DEFAULT_SAMPLE_N = 500
DEFAULT_SEED = 42
SHORT_TITLE_MIN_CHARS = 20
SHORT_TITLE_MIN_WORDS = 4
_FLOAT_EPS = 1e-12
_MSSV_PAT = re.compile(r"^[A-Za-z0-9_-]+$")
# Tên tác giả còn rác từ .bbl (vd `ibfieldauthor`, `bibnamefont`): không dùng làm bằng chứng.
_GARBLED_AUTHOR_PAT = re.compile(r"bfield|bfname|bibname|namefont|bibinfo|binfo", re.IGNORECASE)
# Không có tác giả đáng tin để lọc nên đòi tiêu đề khớp chặt hơn.
GARBLED_AUTHOR_TITLE_THRESHOLD = 0.95

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
    parsed_root: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Đọc `parsed/<pub_key>/bibtex.jsonl`; trả None nếu thiếu file hoặc JSON lỗi."""
    root = PARSED_ROOT if parsed_root is None else parsed_root
    path = root / config.pub_key(arxiv_id) / "bibtex.jsonl"
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


def _inspect_references_status(
    arxiv_id: str,
    corpus_root: Path,
) -> tuple[str, list[dict[str, Any]] | None]:
    """Phân loại trạng thái `references.json`: ok / missing / not_ok và lọc ref arXiv."""
    path = corpus_root / config.pub_key(arxiv_id) / "references.json"
    if not path.is_file():
        return "missing", None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "not_ok", None
    if not isinstance(data, dict) or data.get("status") != "ok":
        return "not_ok", None
    refs = data.get("references")
    if not isinstance(refs, list):
        return "not_ok", None
    cands = [
        ref for ref in refs
        if isinstance(ref, dict) and _canon_arxiv(str(ref.get("ref_arxiv_id") or "")) is not None
    ]
    return "ok", cands


def load_arxiv_candidates(
    arxiv_id: str,
    corpus_root: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Đọc `references.json` và giữ các reference có `ref_arxiv_id` khác null.

    Chỉ nhận publication có `status == "ok"`; trả None nếu thiếu file hoặc status khác.
    """
    root = config.CORPUS_ROOT if corpus_root is None else corpus_root
    status, cands = _inspect_references_status(arxiv_id, root)
    return cands if status == "ok" else None


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    ref: dict[str, Any]
    canon_arxiv: str
    title: str | None
    first_author: Author | None
    year: int | None


@dataclass(frozen=True, slots=True)
class _CandidateIndex:
    by_arxiv: dict[str, dict[str, Any]]
    prepared: list[_PreparedCandidate]


def _build_candidate_index(candidates: Iterable[dict[str, Any]]) -> _CandidateIndex:
    """Lập bảng tra cứu theo arXiv ID, DOI và thông tin đã chuẩn hóa của candidate."""
    by_arxiv: dict[str, dict[str, Any]] = {}
    prepared: list[_PreparedCandidate] = []
    for ref in candidates:
        aid = _canon_arxiv(str(ref.get("ref_arxiv_id") or ""))
        if not aid:
            continue
        by_arxiv.setdefault(aid, ref)
        prepared.append(
            _PreparedCandidate(
                ref=ref,
                canon_arxiv=aid,
                title=norm_title(ref.get("ref_title")),
                first_author=first_author(ref.get("ref_authors")),
                year=clean_year(ref.get("ref_year")),
            )
        )
    return _CandidateIndex(by_arxiv=by_arxiv, prepared=prepared)


def _is_short_title(normed_title: str) -> bool:
    return (
        len(normed_title) < SHORT_TITLE_MIN_CHARS
        or len(normed_title.split()) < SHORT_TITLE_MIN_WORDS
    )


def _passes_author_year_filter(
    entry_author: Author | None,
    entry_year: int | None,
    cand: _PreparedCandidate,
    *,
    require_author: bool,
    year_delta: int,
) -> bool:
    if entry_author and cand.first_author:
        if not same_first_author(entry_author, cand.first_author):
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

    raw_authors = entry.get("authors")
    first_raw = raw_authors[0] if isinstance(raw_authors, list) and raw_authors else raw_authors
    garbled = bool(first_raw) and bool(_GARBLED_AUTHOR_PAT.search(str(first_raw)))
    entry_author = None if garbled else first_author(raw_authors)
    if garbled:
        title_threshold = max(title_threshold, GARBLED_AUTHOR_TITLE_THRESHOLD)
    short_title = _is_short_title(entry_title)
    if short_title and not entry_author:
        return None, None

    entry_year = clean_year(entry.get("year"))
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for cand in prepared:
        if not cand.title:
            continue
        if not _passes_author_year_filter(
            entry_author,
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
    rule: str | None,
    score: float | None,
    *,
    labeler: str = "auto",
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
        "labeler": labeler,
        "method": "auto",
        "rule": rule,
        "score": score,
    }


def _match_entry_indexed(
    entry: dict[str, Any],
    index: _CandidateIndex,
    *,
    pub_arxiv_id: str = "",
    labeler: str = "auto",
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
        return _label_record(
            entry_arxiv_id, citation_key, index.by_arxiv[url_aid], "arxiv_url", 1.0, labeler=labeler
        )

    # 1b. Trường journal dạng "arXiv preprint arXiv:<id>" (ID tường minh)
    raw_journal = str(entry.get("journal") or "").strip()
    jr_aid = _search_arxiv_patterns(raw_journal, (_ARXIV_PREFIX_PAT,)) if raw_journal else None
    if jr_aid and jr_aid in index.by_arxiv:
        return _label_record(
            entry_arxiv_id, citation_key, index.by_arxiv[jr_aid], "arxiv_url", 1.0, labeler=labeler
        )

    # 2. Trường doi: tách 10.48550/arXiv.<id> (D4); reference S2 không có DOI nên không đối sánh DOI thường
    doi_aid = extract_arxiv_id_from_doi(entry.get("doi"))
    if doi_aid and doi_aid in index.by_arxiv:
        return _label_record(
            entry_arxiv_id, citation_key, index.by_arxiv[doi_aid], "doi", 1.0, labeler=labeler
        )

    # 3. Fallback khi doi trống/không khớp nhưng url lại là link doi.org/10.48550/arXiv.<id>
    url_doi_aid = _search_arxiv_patterns(raw_url, (_ARXIV_DOI_IN_URL_PAT,)) if raw_url else None
    if url_doi_aid and url_doi_aid in index.by_arxiv:
        return _label_record(
            entry_arxiv_id, citation_key, index.by_arxiv[url_doi_aid], "arxiv_url", 1.0, labeler=labeler
        )

    # 4. Lọc tác giả+năm và khớp tiêu đề chuẩn hóa (difflib + margin)
    title_ref, title_score = _match_by_title(
        entry,
        index.prepared,
        title_threshold=title_threshold,
        margin_threshold=margin_threshold,
        year_delta=year_delta,
    )
    if title_ref is not None:
        return _label_record(
            entry_arxiv_id, citation_key, title_ref, "title", title_score, labeler=labeler
        )

    return _label_record(entry_arxiv_id, citation_key, None, None, None, labeler=labeler)


def match_entry(
    entry: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    pub_arxiv_id: str = "",
    labeler: str = "auto",
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    year_delta: int = DEFAULT_YEAR_DELTA,
) -> dict[str, Any]:
    """Khớp một entry BibTeX với danh sách candidate có arXiv ID; trả về 1 bản ghi nhãn."""
    return _match_entry_indexed(
        entry,
        _build_candidate_index(candidates),
        pub_arxiv_id=pub_arxiv_id,
        labeler=labeler,
        title_threshold=title_threshold,
        margin_threshold=margin_threshold,
        year_delta=year_delta,
    )


def label_entries(
    entries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    pub_arxiv_id: str = "",
    labeler: str = "auto",
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
            labeler=labeler,
            title_threshold=title_threshold,
            margin_threshold=margin_threshold,
            year_delta=year_delta,
        )
        for entry in entries
    ]


def label_publication(
    arxiv_id: str,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
    *,
    labeler: str = "auto",
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
        labeler=labeler,
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


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Ghi dict JSON UTF-8 qua file `.tmp` rồi replace nguyên tử."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _normalize_raw_id(raw: str) -> str:
    s = raw.strip()
    if s.lower().startswith("arxiv:"):
        s = s[6:].strip()
    return config.strip_version(s)


def load_ids_file(path: Path) -> list[str]:
    """Đọc file danh sách arXiv ID (1 ID/dòng); bỏ trống, comment, version và trùng."""
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file ID: {path}")
    result: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        aid = _normalize_raw_id(s)
        if aid and aid not in seen:
            seen.add(aid)
            result.append(aid)
    return result


def load_exclude_ids(path: Path | None) -> set[str]:
    """Đọc danh sách `arxiv_id` gán tay cần loại khỏi mẫu tự động (--exclude)."""
    if path is None:
        return set()
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file --exclude: {path}")

    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return set()

    # Hỗ trợ JSON (list ID/dict hoặc object có `publications`/`arxiv_id`), JSONL hoặc text 1 ID/dòng.
    if text[0] in "[{":
        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                out: set[str] = set()
                for item in obj:
                    raw_id = item.get("arxiv_id") if isinstance(item, dict) else item
                    if raw_id:
                        out.add(_normalize_raw_id(str(raw_id)))
                return out
            if isinstance(obj, dict):
                if "publications" in obj and isinstance(obj["publications"], list):
                    return {
                        _normalize_raw_id(str(item["arxiv_id"] if isinstance(item, dict) else item))
                        for item in obj["publications"]
                        if item and (not isinstance(item, dict) or item.get("arxiv_id"))
                    }
                if "arxiv_id" in obj and obj["arxiv_id"]:
                    return {_normalize_raw_id(str(obj["arxiv_id"]))}
        except json.JSONDecodeError:
            pass

    excluded: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("{"):
            row = json.loads(s)
            if isinstance(row, dict) and row.get("arxiv_id"):
                excluded.add(_normalize_raw_id(str(row["arxiv_id"])))
                continue
        aid = _normalize_raw_id(s)
        if aid:
            excluded.add(aid)
    return excluded


def _count_bibtex_entries_bounded(
    arxiv_id: str,
    parsed_root: Path,
    max_entries: int,
) -> int | None:
    """Đếm entry trong `bibtex.jsonl`, dừng sớm ngay khi vượt `max_entries` để tiết kiệm I/O và RAM."""
    path = parsed_root / config.pub_key(arxiv_id) / "bibtex.jsonl"
    if not path.is_file():
        return None
    count = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    count += 1
                    if count > max_entries:
                        return count
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return count


def select_eligible_publications(
    ids: list[str],
    *,
    exclude_ids: set[str],
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
    min_entries: int = DEFAULT_MIN_ENTRIES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> tuple[list[str], dict[str, int]]:
    """Lọc các publication đủ điều kiện (D3 + D6) và thống kê số lượng bị loại theo từng lý do."""
    p_root = PARSED_ROOT if parsed_root is None else parsed_root
    c_root = config.CORPUS_ROOT if corpus_root is None else corpus_root
    counts = {
        "total_ids": len(ids),
        "excluded_manual": 0,
        "references_missing": 0,
        "references_not_ok": 0,
        "no_arxiv_candidates": 0,
        "bibtex_missing": 0,
        "no_bibtex_entries": 0,
        "too_many_bibtex_entries": 0,
        "eligible": 0,
    }
    eligible: list[str] = []

    for aid in ids:
        if aid in exclude_ids:
            counts["excluded_manual"] += 1
            continue

        ref_status, candidates = _inspect_references_status(aid, c_root)
        if ref_status == "missing":
            counts["references_missing"] += 1
            continue
        if ref_status != "ok" or candidates is None:
            counts["references_not_ok"] += 1
            continue
        if not candidates:
            counts["no_arxiv_candidates"] += 1
            continue

        n_entries = _count_bibtex_entries_bounded(aid, p_root, max_entries)
        if n_entries is None:
            counts["bibtex_missing"] += 1
            continue
        if n_entries < min_entries:
            counts["no_bibtex_entries"] += 1
            continue
        if n_entries > max_entries:
            counts["too_many_bibtex_entries"] += 1
            continue

        eligible.append(aid)

    counts["eligible"] = len(eligible)
    return eligible, counts


def _rule_key(rule: str | None) -> str:
    return rule if rule is not None else "null"


def run_auto_label(
    *,
    ids_path: Path,
    mssv: str,
    n: int = DEFAULT_SAMPLE_N,
    seed: int = DEFAULT_SEED,
    exclude_path: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Chọn mẫu `n` publication hợp lệ (D3+D6), chạy matcher và ghi `.jsonl` + `.pubs.json`."""
    if n < 1:
        raise ValueError("--n phải >= 1")
    if not _MSSV_PAT.fullmatch(mssv):
        raise ValueError(f"--mssv không hợp lệ: {mssv!r}")
    if not ids_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file ID: {ids_path}")
    if exclude_path is not None and not exclude_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file --exclude: {exclude_path}")

    p_root = PARSED_ROOT if parsed_root is None else parsed_root
    c_root = config.CORPUS_ROOT if corpus_root is None else corpus_root
    target_dir = out_dir if out_dir is not None else (LABELS_ROOT / "auto")
    labels_path = target_dir / f"{mssv}.jsonl"
    pubs_path = target_dir / f"{mssv}.pubs.json"

    if not dry_run and not overwrite and (labels_path.exists() or pubs_path.exists()):
        existing_n: int | None = None
        try:
            existing_n = json.loads(pubs_path.read_text(encoding="utf-8")).get("n_selected")
        except (OSError, ValueError, AttributeError):
            pass
        return {
            "skipped": True,
            "labels_path": str(labels_path),
            "pubs_path": str(pubs_path),
            "existing_n_selected": existing_n,
            "n_requested": n,
        }

    ids = load_ids_file(ids_path)
    exclude_ids = load_exclude_ids(exclude_path)
    eligible, eligibility_counts = select_eligible_publications(
        ids,
        exclude_ids=exclude_ids,
        parsed_root=p_root,
        corpus_root=c_root,
    )

    shuffled = list(eligible)
    random.Random(seed).shuffle(shuffled)
    selected = shuffled[: min(n, len(shuffled))]

    all_rows: list[dict[str, Any]] = []
    pub_records: list[dict[str, Any]] = []
    total_rules: Counter[str] = Counter()

    for aid in selected:
        entries = load_bibtex_entries(aid, parsed_root=p_root) or []
        candidates = load_arxiv_candidates(aid, corpus_root=c_root) or []
        rows = label_entries(entries, candidates, pub_arxiv_id=aid, labeler=mssv)
        all_rows.extend(rows)

        pub_rules: Counter[str] = Counter(_rule_key(r["rule"]) for r in rows)
        total_rules.update(pub_rules)
        n_matched = sum(1 for r in rows if r["groundtruth_arxiv_id"] is not None)
        n_unmatched = len(rows) - n_matched
        pub_records.append(
            {
                "arxiv_id": aid,
                "pub_key": config.pub_key(aid),
                "n_entries": len(rows),
                "n_candidates": len(candidates),
                "n_matched": n_matched,
                "n_unmatched": n_unmatched,
                "rules": dict(sorted(pub_rules.items())),
            }
        )

    total_entries = len(all_rows)
    total_matched = sum(p["n_matched"] for p in pub_records)
    total_unmatched = total_entries - total_matched
    match_rate = round(total_matched / total_entries, 4) if total_entries else 0.0
    n_pubs_with_matches = sum(1 for p in pub_records if p["n_matched"] > 0)
    n_pubs_zero_matched = len(pub_records) - n_pubs_with_matches

    pubs_meta: dict[str, Any] = {
        "mssv": mssv,
        "ids_file": str(ids_path),
        "exclude_file": str(exclude_path) if exclude_path is not None else None,
        "seed": seed,
        "n_requested": n,
        "n_selected": len(selected),
        "excluded_ids_count": len(exclude_ids),
        "criteria": {
            "references_status": "ok",
            "requires_ref_arxiv_id": True,
            "min_entries": DEFAULT_MIN_ENTRIES,
            "max_entries": DEFAULT_MAX_ENTRIES,
            "manual_publications_excluded": True,
            "title_threshold": DEFAULT_TITLE_THRESHOLD,
            "margin_threshold": DEFAULT_MARGIN_THRESHOLD,
            "year_delta": DEFAULT_YEAR_DELTA,
            "short_title_min_chars": SHORT_TITLE_MIN_CHARS,
            "short_title_min_words": SHORT_TITLE_MIN_WORDS,
            "garbled_author_title_threshold": GARBLED_AUTHOR_TITLE_THRESHOLD,
        },
        "eligibility": eligibility_counts,
        "summary": {
            "total_entries": total_entries,
            "total_matched": total_matched,
            "total_unmatched": total_unmatched,
            "match_rate": match_rate,
            "n_pubs_with_matches": n_pubs_with_matches,
            "n_pubs_zero_matched": n_pubs_zero_matched,
            "rules": dict(sorted(total_rules.items())),
        },
        "publications": pub_records,
    }

    if not dry_run:
        write_jsonl_atomic(labels_path, all_rows)
        write_json_atomic(pubs_path, pubs_meta)

    return {
        "skipped": False,
        "dry_run": dry_run,
        "labels_path": str(labels_path),
        "pubs_path": str(pubs_path),
        "meta": pubs_meta,
        "rows": all_rows,
    }


def _safe_ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den > 0 else None


def _diagnose_missing_pub(arxiv_id: str, parsed_root: Path, corpus_root: Path) -> list[str]:
    reasons: list[str] = []
    if load_bibtex_entries(arxiv_id, parsed_root=parsed_root) is None:
        reasons.append("bibtex_missing_or_invalid")
    ref_status, _ = _inspect_references_status(arxiv_id, corpus_root)
    if ref_status != "ok":
        reasons.append(f"references_{ref_status}")
    return reasons


def evaluate_gold(
    gold_path: Path,
    *,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
) -> dict[str, Any]:
    """Đánh giá matcher trên file nhãn tay JSONL: precision cặp gán, recall cặp gold, theo rule."""
    if not gold_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file --gold: {gold_path}")
    p_root = PARSED_ROOT if parsed_root is None else parsed_root
    c_root = config.CORPUS_ROOT if corpus_root is None else corpus_root

    gold_entries: dict[tuple[str, str], str | None] = {}
    gold_pubs_order: list[str] = []
    seen_pubs: set[str] = set()
    n_duplicate_keys = 0

    for line_no, line in enumerate(gold_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not row.get("arxiv_id") or not row.get("citation_key"):
            raise ValueError(f"Dòng {line_no} trong {gold_path} thiếu arxiv_id hoặc citation_key")
        pub_id = _normalize_raw_id(str(row["arxiv_id"]))
        ckey = str(row["citation_key"])
        raw_gt = row.get("groundtruth_arxiv_id")
        gt_aid = _canon_arxiv(str(raw_gt)) if raw_gt else None

        pair_key = (pub_id, ckey)
        if pair_key in gold_entries:
            n_duplicate_keys += 1
        gold_entries[pair_key] = gt_aid
        if pub_id not in seen_pubs:
            seen_pubs.add(pub_id)
            gold_pubs_order.append(pub_id)

    n_gold_positive = sum(1 for v in gold_entries.values() if v is not None)
    n_gold_null = len(gold_entries) - n_gold_positive

    preds_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    evaluated_pubs: list[str] = []
    missing_pubs: list[str] = []
    missing_pub_details: dict[str, list[str]] = {}
    total_pub_entries = 0

    for pub_id in gold_pubs_order:
        pred_rows = label_publication(pub_id, parsed_root=p_root, corpus_root=c_root)
        if pred_rows is None:
            missing_pubs.append(pub_id)
            missing_pub_details[pub_id] = _diagnose_missing_pub(pub_id, p_root, c_root)
            continue
        evaluated_pubs.append(pub_id)
        total_pub_entries += len(pred_rows)
        for r in pred_rows:
            preds_by_key[(r["arxiv_id"], r["citation_key"])] = r

    evaluated_pub_set = set(evaluated_pubs)
    n_gold_entries_evaluated = sum(1 for (pid, _) in gold_entries if pid in evaluated_pub_set)
    n_gold_positive_evaluated = sum(
        1 for (pid, _), v in gold_entries.items() if pid in evaluated_pub_set and v is not None
    )

    auto_matched_on_gold = 0
    correct_on_gold = 0
    auto_matched_unlisted = 0
    missing_entry_in_bibtex = 0
    by_rule_counts: dict[str, dict[str, int]] = {}

    for (pub_id, ckey), pred in preds_by_key.items():
        if pred["groundtruth_arxiv_id"] is None:
            continue
        if (pub_id, ckey) not in gold_entries:
            auto_matched_unlisted += 1

    for pair_key, gt_aid in gold_entries.items():
        pred = preds_by_key.get(pair_key)
        if pred is None:
            if pair_key[0] in evaluated_pub_set:
                missing_entry_in_bibtex += 1
            continue
        pred_raw = pred["groundtruth_arxiv_id"]
        if pred_raw is None:
            continue

        pred_aid = _canon_arxiv(str(pred_raw))
        rule = _rule_key(pred["rule"])
        slot = by_rule_counts.setdefault(rule, {"matched": 0, "correct": 0})
        slot["matched"] += 1
        auto_matched_on_gold += 1
        if gt_aid is not None and pred_aid == gt_aid:
            slot["correct"] += 1
            correct_on_gold += 1

    by_rule: dict[str, dict[str, Any]] = {}
    for rule, counts in sorted(by_rule_counts.items()):
        m = counts["matched"]
        c = counts["correct"]
        by_rule[rule] = {
            "matched": m,
            "correct": c,
            "precision": _safe_ratio(c, m),
            "recall_share": _safe_ratio(c, n_gold_positive_evaluated),
        }

    return {
        "gold_file": str(gold_path),
        "n_gold_pubs": len(gold_pubs_order),
        "n_evaluated_pubs": len(evaluated_pubs),
        "missing_pubs": missing_pubs,
        "missing_pub_details": missing_pub_details,
        "n_gold_entries": len(gold_entries),
        "n_gold_entries_evaluated": n_gold_entries_evaluated,
        "n_gold_positive": n_gold_positive,
        "n_gold_positive_evaluated": n_gold_positive_evaluated,
        "n_gold_null": n_gold_null,
        "n_duplicate_keys": n_duplicate_keys,
        "total_pub_entries": total_pub_entries,
        "missing_entry_in_bibtex": missing_entry_in_bibtex,
        "auto_matched_on_gold": auto_matched_on_gold,
        "correct_on_gold": correct_on_gold,
        "auto_matched_unlisted": auto_matched_unlisted,
        "precision": _safe_ratio(correct_on_gold, auto_matched_on_gold),
        "recall": _safe_ratio(correct_on_gold, n_gold_positive_evaluated),
        "by_rule": by_rule,
    }


def _fmt_rate(correct: int, total: int) -> str:
    if total == 0:
        return f"N/A ({correct}/{total})"
    return f"{correct / total:.2%} ({correct}/{total})"


def _print_run_summary(res: dict[str, Any]) -> None:
    if res.get("skipped"):
        print(
            f"Đã có sẵn {res['labels_path']} và/hoặc {res['pubs_path']}; "
            "bỏ qua (dùng --overwrite để ghi đè)."
        )
        existing_n = res.get("existing_n_selected")
        requested_n = res.get("n_requested")
        if existing_n is not None and requested_n is not None and existing_n != requested_n:
            print(
                f"Lưu ý: file cũ chứa {existing_n} pub nhưng đang yêu cầu {requested_n} pub; "
                "cần chạy lại với --overwrite."
            )
        elif existing_n is not None:
            print(f"Lưu ý: file cũ chứa {existing_n} pub (có thể là bản chạy thử).")
        return

    meta = res["meta"]
    elig = meta["eligibility"]
    summ = meta["summary"]
    tag = "[DRY-RUN] " if res.get("dry_run") else ""
    print(
        f"{tag}Chọn {meta['n_selected']}/{meta['n_requested']} pub "
        f"(eligible={elig['eligible']}/{elig['total_ids']}, "
        f"excluded={elig['excluded_manual']}, not_ok={elig['references_not_ok']}, "
        f"no_cand={elig['no_arxiv_candidates']}, no_bib={elig['no_bibtex_entries']}, "
        f">1000_entries={elig['too_many_bibtex_entries']})"
    )
    print(
        f"{tag}Tổng entry: {summ['total_entries']} | "
        f"Khớp: {summ['total_matched']} ({summ['match_rate']:.2%}) | "
        f"Rules: {summ['rules']}"
    )
    if meta["n_selected"] < meta["n_requested"]:
        print(
            f"{tag}Cảnh báo: chỉ có {meta['n_selected']} pub đủ điều kiện "
            f"(< --n {meta['n_requested']})."
        )
    if summ.get("n_pubs_zero_matched", 0) > 0:
        print(
            f"{tag}Lưu ý: {summ['n_pubs_zero_matched']}/{meta['n_selected']} pub không khớp được "
            "cặp nào (n_matched=0); không chọn các pub này vào tập Valid/Test."
        )
    matched_rows = [r for r in res.get("rows", []) if r["groundtruth_arxiv_id"] is not None]
    samples: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for rule_name in ("arxiv_url", "doi", "title"):
        for r in matched_rows:
            if r["rule"] == rule_name:
                samples.append(r)
                seen_keys.add((r["arxiv_id"], r["citation_key"]))
                break
    for r in matched_rows:
        if len(samples) >= 5:
            break
        key = (r["arxiv_id"], r["citation_key"])
        if key not in seen_keys:
            samples.append(r)
            seen_keys.add(key)
    if samples:
        print(f"{tag}Vài cặp mẫu ({len(samples)}):")
        for r in samples:
            print(
                f"  - {r['arxiv_id']} [{r['citation_key']}] -> "
                f"{r['groundtruth_arxiv_id']} (rule={r['rule']}, score={r['score']})"
            )
    if not res.get("dry_run"):
        print(f"Đã ghi: {res['labels_path']}")
        print(f"Đã ghi: {res['pubs_path']}")


def _print_eval_summary(ev: dict[str, Any]) -> None:
    print(
        f"Đánh giá trên {ev['n_evaluated_pubs']}/{ev['n_gold_pubs']} pub "
        f"(gold entries={ev['n_gold_entries']}: positive={ev['n_gold_positive']}, "
        f"null={ev['n_gold_null']})"
    )
    if ev["n_duplicate_keys"] > 0:
        print(f"Cảnh báo: file gold có {ev['n_duplicate_keys']} cặp (arxiv_id, citation_key) trùng (giữ dòng sau).")
    if ev["missing_pubs"]:
        details = ev.get("missing_pub_details") or {}
        formatted = ", ".join(
            f"{pid} ({'+'.join(details.get(pid, []))})" if details.get(pid) else pid
            for pid in ev["missing_pubs"]
        )
        print(f"Cảnh báo thiếu dữ liệu pub (cần bibtex.jsonl và references.json status=ok): {formatted}")
        if ev["n_evaluated_pubs"] > 0:
            print(
                f"Lưu ý: Recall chỉ tính trên {ev['n_evaluated_pubs']} pub có đủ dữ liệu "
                f"(positive={ev['n_gold_positive_evaluated']}/{ev['n_gold_positive']})."
            )
    if ev["n_evaluated_pubs"] == 0:
        print(
            "Không đánh giá được publication nào vì thiếu dữ liệu cục bộ; "
            "cần chép dữ liệu về hoặc truyền --parsed-root / --corpus-root."
        )
        return
    if ev["missing_entry_in_bibtex"]:
        print(f"Cảnh báo entry có trong gold nhưng thiếu ở bibtex.jsonl: {ev['missing_entry_in_bibtex']}")
    print(f"Precision (cặp matcher gán): {_fmt_rate(ev['correct_on_gold'], ev['auto_matched_on_gold'])}")
    print(f"Recall    (cặp gold):        {_fmt_rate(ev['correct_on_gold'], ev['n_gold_positive_evaluated'])}")
    if ev["auto_matched_unlisted"]:
        print(
            f"Ghi chú: còn {ev['auto_matched_unlisted']} cặp trên cùng pub được matcher gán "
            "nhưng không có trong danh sách entry của file gold."
        )
    print("Theo rule:")
    for rule, stats in ev["by_rule"].items():
        prec = _fmt_rate(stats["correct"], stats["matched"])
        rec = _fmt_rate(stats["correct"], ev["n_gold_positive_evaluated"])
        print(f"  - {rule:10s} | precision={prec:20s} | recall_share={rec}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Matcher tự động gán nhãn BibTeX entry <-> reference có arXiv ID (M3)"
    )
    p.add_argument("--ids", type=Path, help="File danh sách arXiv ID theo thành viên")
    p.add_argument("--mssv", type=str, help="MSSV để đặt tên file output trong labels/auto/")
    p.add_argument("--n", type=int, default=DEFAULT_SAMPLE_N, help="Số pub cần chọn (mặc định 500)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Seed chọn mẫu cố định (mặc định 42)")
    p.add_argument("--exclude", type=Path, default=None, help="File các pub gán tay cần loại")
    p.add_argument("--overwrite", action="store_true", help="Ghi đè file kết quả đã có")
    p.add_argument("--dry-run", action="store_true", help="Chỉ chạy và in thống kê, không ghi file")
    p.add_argument("--eval", action="store_true", help="Chế độ đánh giá precision/recall trên --gold")
    p.add_argument("--gold", type=Path, default=None, help="File nhãn tay JSONL để đánh giá")
    p.add_argument("--parsed-root", type=Path, default=None, help="Thư mục parsed/ (mặc định parsed/ hoặc PARSED_ROOT)")
    p.add_argument("--corpus-root", type=Path, default=None, help="Thư mục corpus/ (mặc định corpus/ hoặc CORPUS_ROOT)")
    return p


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.eval:
            if args.gold is None:
                parser.error("--eval yêu cầu phải truyền --gold <file nhãn tay jsonl>")
            ev = evaluate_gold(
                args.gold,
                parsed_root=args.parsed_root,
                corpus_root=args.corpus_root,
            )
            _print_eval_summary(ev)
            return

        if args.ids is None or not args.mssv:
            parser.error("Cần truyền đủ --ids và --mssv (hoặc dùng --eval --gold)")
        res = run_auto_label(
            ids_path=args.ids,
            mssv=args.mssv,
            n=args.n,
            seed=args.seed,
            exclude_path=args.exclude,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            parsed_root=args.parsed_root,
            corpus_root=args.corpus_root,
        )
        _print_run_summary(res)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
