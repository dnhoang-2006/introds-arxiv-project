"""Milestone 3 — chia tập, huấn luyện, đo MRR@5 và sinh bảng `predictions`.

    # kiểm pipeline bằng baseline trước
    python src/match_main.py --model baseline --limit 50

    # bản chính
    python src/match_main.py --model logreg

    # thực nghiệm che định danh
    python src/match_main.py --model logreg --mask-ids

Ba điều dễ tính sai, chốt sẵn ở đây
-----------------------------------
1. **Tập Q loại entry không có nhãn.** M3 câu 4 ý 2: *"entry không có reference
   không phải là một sample hợp lệ, do đó không có trường hợp tính điểm cho các
   entry này"*. Entry `groundtruth_arxiv_id = null` **vẫn có hàng** trong
   `predictions` nhưng **không vào mẫu số** của MRR. Đây là nguồn lệch số dễ xảy
   ra nhất giữa người tính MRR và người viết validator.

2. **Ứng viên chỉ lấy từ references của chính bài đó.** M3 câu 4 ý 5. Việc này
   `label_io.build_candidates()` lo.

3. **Chia tập trên toàn nhóm, không phải từng người.** M3 câu 4 ý 3. Nên script
   đọc hết `labels/` của cả 5 người rồi mới chia, và chia theo **publication**
   chứ không theo entry — hai entry cùng bài mà rơi vào train với test khác nhau
   là rò rỉ dữ liệu.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
from matching.features import FEATURE_NAMES, feature_matrix  # noqa: E402
from matching.label_io import Label, Pair, build_candidates, load_labels  # noqa: E402
from matching.model import LogisticRanker, build_ranker  # noqa: E402

K = 5                      # top-K của MRR@K và số cột cand_1..cand_5
PARTITIONS = ("train", "valid", "test")

#: Mặc định theo quyết định của nhóm: Test và Valid mỗi tập 5 publication gán tay
#: + 5 publication gán tự động, phần còn lại là Train.
DEFAULT_N_TEST = 5
DEFAULT_N_VALID = 5


@dataclass
class Query:
    """Một entry đã gán nhãn, cùng toàn bộ ứng viên của nó."""
    arxiv_id: str
    citation_key: str
    labeler: str
    method: str                      # "manual" | "auto"
    groundtruth: str | None
    pairs: list[Pair]

    @property
    def scorable(self) -> bool:
        """Có vào mẫu số của MRR không. M3 câu 4 ý 2."""
        return self.groundtruth is not None


# --------------------------------------------------------------------------- #
#  Gom truy vấn
# --------------------------------------------------------------------------- #

def collect_queries(
    labels: dict[tuple[str, str], Label],
    *,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
    limit: int | None = None,
    warn_out: list[str] | None = None,
) -> list[Query]:
    by_pub: dict[str, list[Label]] = defaultdict(list)
    for lb in labels.values():
        by_pub[lb.arxiv_id].append(lb)

    pubs = sorted(by_pub)
    if limit:
        pubs = pubs[:limit]

    out: list[Query] = []
    for aid in pubs:
        pairs = build_candidates(
            aid, labels, parsed_root=parsed_root, corpus_root=corpus_root,
            warn_out=warn_out,
        )
        if not pairs:
            continue
        grouped: dict[str, list[Pair]] = defaultdict(list)
        for p in pairs:
            grouped[p.citation_key].append(p)
        for key, ps in grouped.items():
            lb = labels[(aid, key)]
            out.append(Query(
                arxiv_id=aid, citation_key=key, labeler=lb.labeler,
                method=lb.method, groundtruth=lb.groundtruth_arxiv_id, pairs=ps,
            ))
    return out


# --------------------------------------------------------------------------- #
#  Chia tập
# --------------------------------------------------------------------------- #

def split_publications(
    queries: list[Query],
    *,
    seed: int = 42,
    n_test: int = DEFAULT_N_TEST,
    n_valid: int = DEFAULT_N_VALID,
) -> dict[str, str]:
    """publication -> train | valid | test.

    Chia riêng nhóm gán tay và nhóm gán tự động, để Test và Valid đều có cả hai
    loại nhãn. Nhãn tay đáng tin hơn nhiều nên Test thiếu nhãn tay thì con số
    MRR chỉ đang đo lại chính matcher luật, không đo gì mới.
    """
    methods: dict[str, Counter] = defaultdict(Counter)
    for q in queries:
        methods[q.arxiv_id][q.method] += 1

    manual = sorted(a for a, c in methods.items() if c["manual"] >= c["auto"])
    auto = sorted(a for a, c in methods.items() if c["manual"] < c["auto"])

    out: dict[str, str] = {}
    for pool in (manual, auto):
        pool = list(pool)
        random.Random(seed).shuffle(pool)
        for i, aid in enumerate(pool):
            if i < n_test:
                out[aid] = "test"
            elif i < n_test + n_valid:
                out[aid] = "valid"
            else:
                out[aid] = "train"
    return out


# --------------------------------------------------------------------------- #
#  Xếp hạng và MRR
# --------------------------------------------------------------------------- #

def rank_query(q: Query, scores: list[float], k: int = K) -> list[str]:
    """arXiv ID của k ứng viên điểm cao nhất, cao xuống thấp."""
    order = sorted(range(len(q.pairs)), key=lambda i: -scores[i])
    return [q.pairs[i].cand_arxiv_id for i in order[:k]]


def reciprocal_rank(groundtruth: str | None, top: list[str]) -> float:
    if groundtruth is None:
        return 0.0
    for i, cand in enumerate(top, 1):
        if cand == groundtruth:
            return 1.0 / i
    return 0.0


def mrr_at_k(results: list[tuple[Query, list[str]]]) -> tuple[float, int]:
    """(MRR@5, cỡ tập Q). Chỉ tính entry có nhãn khác null — M3 câu 4 ý 2."""
    rrs = [reciprocal_rank(q.groundtruth, top) for q, top in results if q.scorable]
    return (sum(rrs) / len(rrs) if rrs else 0.0), len(rrs)


def recall_at_k(results: list[tuple[Query, list[str]]]) -> float:
    hits = [1.0 if q.groundtruth in top else 0.0 for q, top in results if q.scorable]
    return sum(hits) / len(hits) if hits else 0.0


# --------------------------------------------------------------------------- #
#  Chạy
# --------------------------------------------------------------------------- #

def run(
    *,
    model_name: str = "logreg",
    mask_ids: bool = False,
    seed: int = 42,
    limit: int | None = None,
    labels_root: Path | None = None,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
    out_dir: Path | None = None,
    n_test: int = DEFAULT_N_TEST,
    n_valid: int = DEFAULT_N_VALID,
    write: bool = True,
) -> dict[str, Any]:
    warns: list[str] = []
    labels = load_labels(labels_root)
    if not labels:
        raise ValueError(
            "Không có nhãn nào trong labels/. Mỗi người chạy scripts/manual_label.py "
            "rồi src/matching/auto_label.py trước."
        )
    queries = collect_queries(
        labels, parsed_root=parsed_root, corpus_root=corpus_root,
        limit=limit, warn_out=warns,
    )
    if not queries:
        raise ValueError(
            "Có nhãn nhưng không dựng được ứng viên nào — thường là parsed/ hoặc "
            "corpus/ của dải tương ứng không có trên máy này."
        )

    part = split_publications(queries, seed=seed, n_test=n_test, n_valid=n_valid)
    by_part: dict[str, list[Query]] = defaultdict(list)
    for q in queries:
        by_part[part[q.arxiv_id]].append(q)

    ranker = build_ranker(model_name, seed=seed)
    train_pairs = [p for q in by_part["train"] for p in q.pairs]
    if train_pairs:
        ranker.fit(
            feature_matrix(train_pairs, mask_ids=mask_ids),
            [p.label for p in train_pairs],
        )

    results: dict[str, list[tuple[Query, list[str]]]] = {}
    for name in PARTITIONS:
        got = []
        for q in by_part.get(name, []):
            scores = ranker.score(feature_matrix(q.pairs, mask_ids=mask_ids))
            got.append((q, rank_query(q, scores)))
        results[name] = got

    metrics: dict[str, Any] = {
        "model": ranker.name,
        "mask_ids": mask_ids,
        "seed": seed,
        "n_publications": len(part),
        "n_queries": len(queries),
    }
    for name in PARTITIONS:
        mrr, n_q = mrr_at_k(results[name])
        metrics[name] = {
            "n_publications": sum(1 for v in part.values() if v == name),
            "n_queries": len(results[name]),
            "n_scorable": n_q,
            "mrr@5": round(mrr, 4),
            "recall@5": round(recall_at_k(results[name]), 4),
        }
    if isinstance(ranker, LogisticRanker) and ranker.coefficients:
        metrics["coefficients"] = {k: round(v, 3) for k, v in ranker.coefficients.items()}

    written = {}
    if write:
        written = write_predictions(results, part, out_dir=out_dir)
    return {"metrics": metrics, "warnings": warns, "written": written}


# --------------------------------------------------------------------------- #
#  Bảng predictions
# --------------------------------------------------------------------------- #

def prediction_rows(
    results: dict[str, list[tuple[Query, list[str]]]],
    part: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Hàng `predictions` gom theo MSSV người gán nhãn.

    Đúng 8 cột. Entry `groundtruth_arxiv_id = null` **vẫn có hàng** — đó là dữ
    liệu âm hợp lệ, chỉ không vào mẫu số MRR.
    """
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name in PARTITIONS:
        for q, top in results[name]:
            row = {
                "arxiv_id": q.arxiv_id,
                "partition": name,
                "citation_key": q.citation_key,
                "groundtruth_arxiv_id": q.groundtruth,
            }
            for i in range(K):
                row[f"cand_{i + 1}"] = top[i] if i < len(top) else None
            out[q.labeler or "unknown"].append(row)
    return out


def write_predictions(
    results: dict[str, list[tuple[Query, list[str]]]],
    part: dict[str, str],
    *,
    out_dir: Path | None = None,
) -> dict[str, int]:
    d = out_dir or (ROOT / "labels" / "predictions")
    d.mkdir(parents=True, exist_ok=True)
    counts = {}
    for mssv, rows in prediction_rows(results, part).items():
        p = d / f"{mssv}.jsonl"
        with p.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        counts[mssv] = len(rows)
    return counts


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def _print(res: dict[str, Any]) -> None:
    m = res["metrics"]
    masked = " (đã che url/doi/arXiv ID)" if m["mask_ids"] else ""
    print(f"\nModel: {m['model']}{masked} · seed {m['seed']}")
    print(f"{m['n_publications']:,} publication · {m['n_queries']:,} entry đã gán nhãn\n")
    print(f"{'tập':<8}{'pub':>6}{'entry':>9}{'tính điểm':>11}{'MRR@5':>9}{'Recall@5':>10}")
    for name in PARTITIONS:
        s = m[name]
        print(f"{name:<8}{s['n_publications']:>6}{s['n_queries']:>9}"
              f"{s['n_scorable']:>11}{s['mrr@5']:>9.4f}{s['recall@5']:>10.4f}")
    print("\nMRR chỉ tính trên entry có nhãn khác null (M3 câu 4 ý 2); "
          "cột 'entry' trừ cột 'tính điểm' là số entry không khớp reference nào.")

    if m.get("coefficients"):
        print("\nHệ số (dấu + nghĩa là đặc trưng đẩy ứng viên lên hạng cao):")
        for k, v in sorted(m["coefficients"].items(), key=lambda kv: -abs(kv[1])):
            print(f"  {k:<20}{v:>8.3f}")

    if res["written"]:
        total = sum(res["written"].values())
        print(f"\nĐã ghi {total:,} hàng predictions: "
              + ", ".join(f"{k} ({v:,})" for k, v in sorted(res["written"].items())))
    if res["warnings"]:
        print(f"\n{len(res['warnings'])} cảnh báo, 5 cái đầu:")
        for w in res["warnings"][:5]:
            print(f"  - {w}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M3: chia tập, huấn luyện, MRR@5, predictions")
    ap.add_argument("--model", default="logreg", choices=["baseline", "logreg"])
    ap.add_argument("--mask-ids", action="store_true",
                    help="Che url/doi/arXiv ID của entry ở cả train lẫn đánh giá")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None,
                    help="Chỉ lấy N publication đầu, dùng để chạy thử nhanh")
    ap.add_argument("--labels-root", type=Path, default=None)
    ap.add_argument("--parsed-root", type=Path, default=None)
    ap.add_argument("--corpus-root", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--n-test", type=int, default=DEFAULT_N_TEST,
                    help="Số publication mỗi loại nhãn cho tập test")
    ap.add_argument("--n-valid", type=int, default=DEFAULT_N_VALID)
    ap.add_argument("--no-write", action="store_true", help="Chỉ in số, không ghi file")
    a = ap.parse_args(argv)

    try:
        res = run(
            model_name=a.model, mask_ids=a.mask_ids, seed=a.seed, limit=a.limit,
            labels_root=a.labels_root, parsed_root=a.parsed_root,
            corpus_root=a.corpus_root, out_dir=a.out_dir,
            n_test=a.n_test, n_valid=a.n_valid, write=not a.no_write,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 1
    _print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
