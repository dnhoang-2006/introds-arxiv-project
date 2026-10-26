"""corpus_builder.py - Dựng cây thư mục corpus, ghi paper_meta.json, _EMPTY.json và logs/extract.csv.

Theo docs/schema.md (chốt 21/10/2026):
  * Tên thư mục bài = config.pub_key(arxiv_id)  (KHÔNG tự viết lại quy tắc đổi dấu)
  * Giá trị `arxiv_id` trong file JSON giữ nguyên bản gốc (vd hep-th/9901001)
  * Version không có TeX source -> vẫn có thư mục vN/, bên trong có _EMPTY.json
  * references.json / prescan.json do Hữu Duy ghi -> module này KHÔNG tạo
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import pub_key  # hàm chung của nhóm (schema.md §1)
from extractor import ExtractionResult, extract_archive

logger = logging.getLogger("corpus_builder")

LOCAL_TZ = timezone(timedelta(hours=7))  # giờ local +07:00 cho các trường *_at

# 6 trường của bảng `papers` (đề bài) + 3 trường nội bộ (schema.md §3)
PAPERS_FIELDS = ("arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue")
INTERNAL_FIELDS = ("n_versions", "latest_versioned_id", "discovered_at")

EXTRACT_LOG_HEADER = [
    "arxiv_id", "version", "bytes_before", "bytes_after", "n_tex", "n_bib", "status", "error_type",
]


# --------------------------------------------------------------------------- #
# Ngày tháng
# --------------------------------------------------------------------------- #
def _to_iso(value) -> Optional[str]:
    """Chuẩn hóa về chuỗi ISO 8601. Chấp nhận datetime hoặc string ISO / RFC 2822."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    raise ValueError(f"Không parse được ngày: {value!r}")


def now_local_iso() -> str:
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# paper_meta.json
# --------------------------------------------------------------------------- #
def build_paper_meta(
    arxiv_id: str,
    title: str,
    authors: List[str],
    submission_date,
    revised_dates: List,
    venue: Optional[str],
    n_versions: int,
    discovered_at: Optional[str] = None,
) -> dict:
    """Tạo dict paper_meta đủ 6 trường `papers` + 3 trường nội bộ.

    `revised_dates` lấy từ metadata API (arXiv Atom chỉ có `updated` của version cuối),
    nên: 1 version -> []; N >= 2 -> [updated]. Caller truyền đúng như vậy;
    hàm này chỉ chuẩn hóa. Khi n_versions > 2 ghi thêm `revised_dates_complete: false`.
    """
    meta = {
        "arxiv_id": arxiv_id,                                   # bản gốc, chưa đổi dấu
        "title": " ".join(title.split()),                       # gộp về 1 dòng
        "authors": [a.strip() for a in authors],                # [] nếu API không trả
        "submission_date": _to_iso(submission_date),
        "revised_dates": [_to_iso(d) for d in revised_dates],
        "venue": (venue.strip() or None) if isinstance(venue, str) else None,  # null, không phải ""
        "n_versions": n_versions,
        "latest_versioned_id": f"{arxiv_id}v{n_versions}",
        "discovered_at": discovered_at or now_local_iso(),
    }
    if n_versions > 2:
        meta["revised_dates_complete"] = False
    return meta


def validate_paper_meta(meta: dict) -> None:
    missing = [f for f in PAPERS_FIELDS + INTERNAL_FIELDS if f not in meta]
    if missing:
        raise ValueError(f"paper_meta thiếu trường: {missing}")
    if not isinstance(meta["authors"], list) or not all(isinstance(a, str) for a in meta["authors"]):
        raise ValueError("authors phải là list[str]")
    if not isinstance(meta["revised_dates"], list) or not all(isinstance(d, str) for d in meta["revised_dates"]):
        raise ValueError("revised_dates phải là list[str]")
    if not isinstance(meta["submission_date"], str):
        raise ValueError("submission_date phải là chuỗi ISO 8601 (không được null)")
    if meta["venue"] == "" or meta["venue"] == "None":
        raise ValueError('venue nullable: ghi null, không ghi "" hay "None"')
    if not isinstance(meta["n_versions"], int):
        raise ValueError("n_versions phải là int")


def write_paper_meta(paper_dir: Path, meta: dict) -> Path:
    validate_paper_meta(meta)
    path = paper_dir / "paper_meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# _EMPTY.json
# --------------------------------------------------------------------------- #
def write_empty_marker(
    version_dir: Path,
    arxiv_id: str,
    version: int,
    result: Optional[ExtractionResult] = None,
    reason: Optional[str] = None,
    detail: Optional[str] = None,
    http_status: Optional[int] = 200,
) -> Path:
    """Ghi _EMPTY.json (schema.md §2). `reason` thuộc enum; dùng tham số reason/http_status
    khi download thất bại (http_403, http_404, timeout...) và chưa có archive để giải nén."""
    from extractor import EMPTY_REASONS

    reason = reason or (result.empty_reason if result else "other")
    detail = detail or (result.empty_detail if result else "") or ""
    if reason not in EMPTY_REASONS:
        raise ValueError(f"reason không hợp lệ: {reason!r}; phải thuộc {sorted(EMPTY_REASONS)}")

    version_dir.mkdir(parents=True, exist_ok=True)
    path = version_dir / "_EMPTY.json"
    payload = {
        "arxiv_id": arxiv_id,
        "version": version,
        "reason": reason,
        "detail": detail,
        "http_status": http_status,
        "fetched_at": now_local_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# logs/extract.csv  (một dòng = một lần thử; retry thì thêm dòng, không sửa dòng cũ)
# --------------------------------------------------------------------------- #
def append_extract_log(log_path: str | Path, arxiv_id: str, version: int, res: ExtractionResult) -> None:
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not log_path.exists() or log_path.stat().st_size == 0
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(EXTRACT_LOG_HEADER)
        w.writerow([
            arxiv_id, version, res.size_before, res.size_after,
            res.n_tex, res.n_bib, res.status, res.error_type,
        ])


# --------------------------------------------------------------------------- #
# Dựng một bài
# --------------------------------------------------------------------------- #
def build_paper(
    corpus_root: str | Path,
    meta: dict,
    version_archives: Dict[int, str | Path],
    log_path: str | Path = "logs/extract.csv",
) -> Dict[str, ExtractionResult]:
    """Dựng corpus/<pub_key>/ cho một bài.

    version_archives: {1: 'path/v1.tar.gz', 2: ...}. Trả về {'<pub_key>/vN': ExtractionResult}
    để lấy số liệu dung lượng trước/sau.
    """
    corpus_root = Path(corpus_root)
    arxiv_id = meta["arxiv_id"]
    paper_dir = corpus_root / pub_key(arxiv_id)
    paper_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, ExtractionResult] = {}
    for v in sorted(version_archives):
        vdir = paper_dir / f"v{v}"                 # v1, v2, ... v10 (không zero-pad)
        res = extract_archive(version_archives[v], vdir)
        if res.is_empty:
            write_empty_marker(vdir, arxiv_id, v, result=res)
        append_extract_log(log_path, arxiv_id, v, res)
        results[f"{paper_dir.name}/v{v}"] = res

    write_paper_meta(paper_dir, meta)
    return results


def write_anomaly_report(results: Dict[str, ExtractionResult], out_path: str | Path) -> Path:
    """Gom mọi ca lạ vào một file; tuần 2 biến thành test case."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: {
            "archive_format": r.archive_format,
            "anomalies": r.anomalies,
            "empty_reason": r.empty_reason,
        }
        for key, r in results.items()
        if r.anomalies or r.empty_reason
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import argparse
    import io
    import tarfile
    import tempfile

    parser = argparse.ArgumentParser(description="Dựng cây thư mục corpus và ghi paper_meta.json")
    parser.add_argument("--test", action="store_true", help="Chạy kiểm tra tự động (self-test)")
    args = parser.parse_args()

    print("Chạy kiểm tra tự động corpus_builder...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tar_path = tmp_path / "v1.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            tex = b"\\begin{figure}\\end{figure}"
            ti = tarfile.TarInfo(name="main.tex")
            ti.size = len(tex)
            tf.addfile(ti, io.BytesIO(tex))

        meta = build_paper_meta(
            arxiv_id="hep-th/9901001",
            title="Old Style Paper",
            authors=["Author One"],
            submission_date="1999-01-01T00:00:00Z",
            revised_dates=[],
            venue=None,
            n_versions=1,
        )
        validate_paper_meta(meta)

        res = build_paper(tmp_path / "corpus", meta, {1: tar_path}, tmp_path / "logs" / "extract.csv")
        assert (tmp_path / "corpus" / "hep-th_9901001" / "paper_meta.json").exists()
        assert (tmp_path / "corpus" / "hep-th_9901001" / "v1" / "main.tex").exists()
        assert (tmp_path / "logs" / "extract.csv").exists()
    print("✅ Self-test hoàn tất: Mọi kiểm tra cơ bản đều PASSED!")

