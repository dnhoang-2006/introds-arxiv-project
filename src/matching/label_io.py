"""label_io.py — đọc/ghi nhãn và dựng candidate matrix cho Milestone 3.

    python src/matching/label_io.py --ids ids/24120053.txt --stats
    python src/matching/label_io.py --ids ids/24120053.txt --out data/candidates.jsonl

Quy ước lấy từ docs/schema_m3.md:
  - Nhãn nằm ở labels/manual/<MSSV>.jsonl và labels/auto/<MSSV>.jsonl
  - CHỈ sinh hàng cho entry đã gán nhãn. Entry chưa gán nhãn không có hàng nào.
  - Entry có nhãn nhưng groundtruth_arxiv_id = null vẫn sinh đủ hàng, nhãn toàn 0.
    Đây là dữ liệu âm hợp lệ để huấn luyện, nhưng KHÔNG vào mẫu số khi tính MRR@5
    (thầy chốt ở M3 câu 4 ý 2).

Đầu vào mỗi publication:
  parsed/<pub_key>/bibtex.jsonl      -> m entry BibTeX
  corpus/<pub_key>/references.json   -> n reference, chỉ lấy cái có arXiv ID
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402


# --------------------------------------------------------------------------- #
#  Nhãn
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Label:
    arxiv_id: str
    citation_key: str
    groundtruth_arxiv_id: str | None
    labeler: str
    method: str                      # "manual" | "auto"


def load_labels(labels_root: Path | str = None) -> dict[tuple[str, str], Label]:
    """Đọc mọi .jsonl trong labels/manual và labels/auto.

    Khi một cặp (arxiv_id, citation_key) có cả nhãn tay lẫn nhãn tự động thì
    nhãn TAY thắng — theo M3 câu 4 ý 1, bài đã gán tay không đưa qua matcher.
    """
    root = Path(labels_root) if labels_root else ROOT / "labels"
    out: dict[tuple[str, str], Label] = {}
    for method in ("auto", "manual"):            # manual đọc sau để ghi đè
        d = root / method
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.jsonl")):
            for n, line in enumerate(p.open(encoding="utf-8"), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{p}:{n} không phải JSON hợp lệ: {exc}") from exc
                for f in ("arxiv_id", "citation_key"):
                    if not r.get(f):
                        raise ValueError(f"{p}:{n} thiếu trường {f!r}")
                gt = r.get("groundtruth_arxiv_id")
                out[(r["arxiv_id"], r["citation_key"])] = Label(
                    arxiv_id=r["arxiv_id"],
                    citation_key=r["citation_key"],
                    groundtruth_arxiv_id=gt if gt not in ("", "None", None) else None,
                    labeler=str(r.get("labeler", "")),
                    method=r.get("method", method),
                )
    return out


def write_labels(path: Path | str, labels: list[Label]) -> int:
    """Ghi danh sách nhãn ra .jsonl, UTF-8 không BOM."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for lb in labels:
            f.write(json.dumps(asdict(lb), ensure_ascii=False) + "\n")
    return len(labels)


# --------------------------------------------------------------------------- #
#  Đọc entry và reference
# --------------------------------------------------------------------------- #

def load_entries(arxiv_id: str, parsed_root: Path = None) -> list[dict[str, Any]]:
    """m entry BibTeX của publication, từ parsed/<pub_key>/bibtex.jsonl."""
    root = parsed_root or (ROOT / "parsed")
    f = root / config.pub_key(arxiv_id) / "bibtex.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def load_references(arxiv_id: str, corpus_root: Path = None) -> list[dict[str, Any]]:
    """n reference CÓ arXiv ID — đây là toàn bộ không gian ứng viên của bài.

    Đo 26/11 trên dải 2507: trung vị 13, trung bình 20, max 177 reference mỗi bài.
    13% publication không có reference arXiv nào, những bài đó không dùng được
    cho matching.
    """
    root = corpus_root or config.CORPUS_ROOT
    f = Path(root) / config.pub_key(arxiv_id) / "references.json"
    if not f.exists():
        return []
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out = []
    for r in d.get("references") or []:
        rid = r.get("ref_arxiv_id")
        if not _truthy(r.get("has_arxiv_id")) or rid in (None, "", "None"):
            continue
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
#  Candidate matrix
# --------------------------------------------------------------------------- #

@dataclass
class Pair:
    """Một ô của ma trận m x n: cặp (entry BibTeX, reference ứng viên)."""
    arxiv_id: str
    citation_key: str
    cand_arxiv_id: str
    label: int                       # 1 = đúng, 0 = sai
    method: str                      # nhãn đến từ manual hay auto
    entry_title: str | None
    entry_authors: Any
    entry_year: Any
    entry_doi: str | None
    entry_url: str | None
    cand_title: str | None
    cand_authors: Any
    cand_year: Any
    cand_venue: str | None


def build_candidates(
    arxiv_id: str,
    labels: dict[tuple[str, str], Label],
    *,
    parsed_root: Path = None,
    corpus_root: Path = None,
    warn_out: list[str] = None,
) -> list[Pair]:
    """Dựng các hàng của ma trận cho MỘT publication.

    Chỉ entry đã gán nhãn mới sinh hàng. Mỗi entry sinh đúng n hàng, trong đó
    tối đa một hàng mang label = 1.
    """
    entries = load_entries(arxiv_id, parsed_root)
    refs = load_references(arxiv_id, corpus_root)
    if not entries or not refs:
        return []

    pairs: list[Pair] = []
    for e in entries:
        key = e.get("citation_key")
        lb = labels.get((arxiv_id, key)) if key else None
        if lb is None:                       # chưa gán nhãn -> không có hàng
            continue
        gt = lb.groundtruth_arxiv_id
        if gt and not any(r["ref_arxiv_id"] == gt for r in refs):
            if warn_out is not None:
                warn_out.append(
                    f"{arxiv_id}/{key}: groundtruth {gt} không nằm trong "
                    f"{len(refs)} reference của bài"
                )
        for r in refs:
            rid = r["ref_arxiv_id"]
            pairs.append(Pair(
                arxiv_id=arxiv_id,
                citation_key=key,
                cand_arxiv_id=rid,
                label=1 if gt and rid == gt else 0,
                method=lb.method,
                entry_title=e.get("title"),
                entry_authors=e.get("authors"),
                entry_year=e.get("year"),
                entry_doi=e.get("doi"),
                entry_url=e.get("url"),
                cand_title=r.get("ref_title"),
                cand_authors=r.get("ref_authors"),
                cand_year=r.get("ref_year"),
                cand_venue=r.get("ref_venue"),
            ))
    return pairs


def iter_candidates(
    arxiv_ids: list[str],
    labels: dict[tuple[str, str], Label],
    **kw,
) -> Iterator[Pair]:
    for aid in arxiv_ids:
        yield from build_candidates(aid, labels, **kw)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Dựng candidate matrix cho M3")
    ap.add_argument("--ids", required=True, help="File ID hoặc danh sách ngăn bởi dấu phẩy")
    ap.add_argument("--labels", default=None, help="Thư mục nhãn (mặc định: labels/)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None, help="Ghi ra .jsonl")
    ap.add_argument("--stats", action="store_true", help="Chỉ in thống kê, không ghi")
    a = ap.parse_args(argv)

    ids = [config.strip_version(i) for i in config.load_ids(a.ids, limit=a.limit)]
    ids = list(dict.fromkeys(ids))
    labels = load_labels(a.labels)
    print(f"Nhãn đọc được : {len(labels):,}")
    if not labels:
        print("Chưa có nhãn nào trong labels/manual hoặc labels/auto — "
              "chạy gán nhãn trước.")
        return 1

    by_method = Counter(l.method for l in labels.values())
    n_null = sum(1 for l in labels.values() if l.groundtruth_arxiv_id is None)
    print(f"  theo nguồn  : {dict(by_method)}")
    print(f"  không khớp  : {n_null:,} ({n_null/len(labels):.1%}) — "
          f"có hàng nhưng không vào mẫu số MRR")

    warns: list[str] = []
    n_pair = n_pos = 0
    pubs = set()
    fh = None
    if a.out and not a.stats:
        outp = Path(a.out); outp.parent.mkdir(parents=True, exist_ok=True)
        fh = outp.open("w", encoding="utf-8", newline="\n")
    try:
        for p in iter_candidates(ids, labels, warn_out=warns):
            n_pair += 1
            n_pos += p.label
            pubs.add(p.arxiv_id)
            if fh:
                fh.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    finally:
        if fh:
            fh.close()

    print(f"\nPublication có hàng : {len(pubs):,}")
    print(f"Tổng cặp (hàng)     : {n_pair:,}")
    print(f"  nhãn dương        : {n_pos:,}  ({n_pos/n_pair:.2%})" if n_pair else "  (không có cặp nào)")
    if warns:
        print(f"\n⚠️  {len(warns)} cảnh báo groundtruth không nằm trong references:")
        for w in warns[:10]:
            print("   ", w)
    if a.out and not a.stats:
        print(f"\nĐã ghi {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
