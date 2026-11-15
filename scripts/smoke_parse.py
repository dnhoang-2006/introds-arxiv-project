"""Kiểm khói (smoke test) cho src/parse_main.py trên corpus thật.

Hai chế độ:

1. Chỉ KIỂM kết quả của một lần chạy thật đã có:
       python src/parse_main.py --ids ids/24120053.txt --limit 20
       python scripts/smoke_parse.py --check --ids ids/24120053.txt --limit 20

2. CHẠY rồi kiểm, ghi vào thư mục riêng (không đụng parsed/ và logs/ của repo):
       python scripts/smoke_parse.py --out tmp_smoke --ids ids/24120053.txt --limit 20
   Thêm --passthrough để thay các hàm CHƯA GIAO (clean_latex, normalize_math,
   collect_bib, unify_publication) bằng bản đi thẳng — chỉ để kiểm phần ghép nối.
   ⚠️ Kết quả --passthrough KHÔNG phải số liệu chính thức: không chuẩn hoá, không
   đổi \\cite, nên dedup_ratio thấp hơn thực tế.

Ba phép kiểm (exit code 1 nếu có cái hỏng):
  - mỗi publication có đủ elements.jsonl, hierarchy.jsonl, bibtex.jsonl
  - parse.csv có đúng 1 dòng cho mỗi version trong corpus
  - bài nhiều version có dedup_ratio > 0, với
        dedup_ratio = 1 - len(elements) / tổng n_elements của các version
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
import parse_main as pm  # noqa: E402

TABLES = ["bibtex.jsonl", "elements.jsonl", "hierarchy.jsonl"]


def _passthrough() -> None:
    pm.clean_latex = lambda s: s
    pm.normalize_math = lambda s: s
    pm.collect_bib = lambda vdir: []
    pm.unify_publication = lambda norm_text, bib: (dict(norm_text), [], {})


def _n_versions(arxiv_id: str) -> int:
    d = config.pub_dir(arxiv_id)
    if not d.is_dir():
        return 0
    return sum(1 for v in d.iterdir() if v.is_dir() and v.name[:1] == "v" and v.name[1:].isdigit())


def check(ids: list[str], parsed: Path, log: Path) -> int:
    """In báo cáo, trả số phép kiểm hỏng."""
    rows = list(csv.DictReader(log.open(encoding="utf-8", newline="")))
    rows = [r for r in rows if r["arxiv_id"] in set(ids) and r["status"] != "skipped"]
    per_pub = Counter(r["arxiv_id"] for r in rows)
    problems = 0

    print(f"{'arxiv_id':<12} {'ver':>3} {'log':>3} {'tables':<7} "
          f"{'elements':>8} {'nodes':>7} {'dedup':>6}")
    for aid in ids:
        d = parsed / config.pub_key(aid)
        have = sorted(p.name for p in d.glob("*.jsonl")) if d.is_dir() else []
        n_ver = _n_versions(aid)
        tables_ok = have == TABLES
        log_ok = per_pub[aid] == n_ver
        n_el = nodes = 0
        ratio = None
        if "elements.jsonl" in have:
            with (d / "elements.jsonl").open(encoding="utf-8") as fh:
                n_el = sum(1 for _ in fh)
            nodes = sum(int(r["n_elements"] or 0) for r in rows if r["arxiv_id"] == aid)
            ratio = 1 - n_el / nodes if nodes else 0.0
        dedup_ok = n_ver < 2 or (ratio is not None and ratio > 0)
        bad = [name for name, ok in (("tables", tables_ok), ("log", log_ok),
                                     ("dedup", dedup_ok)) if not ok]
        problems += len(bad)
        print(f"{aid:<12} {n_ver:>3} {per_pub[aid]:>3} {'ok' if tables_ok else 'THIẾU':<7} "
              f"{n_el:>8} {nodes:>7} {'' if ratio is None else f'{ratio:.3f}':>6}"
              + (f"   <-- HỎNG: {', '.join(bad)}" if bad else ""))

    statuses = Counter((r["status"], r["error_type"]) for r in rows)
    print("\nstatus:", ", ".join(f"{s}{'/' + e if e else ''}={n}" for (s, e), n in statuses.items()))
    leaked = _leaked_latex(parsed, ids)
    if leaked:
        print(f"Cảnh báo: {leaked} content của itemize/item còn \\item thô")
    print("KẾT QUẢ:", "ĐẠT" if problems == 0 else f"{problems} phép kiểm hỏng")
    return problems


def _leaked_latex(parsed: Path, ids: list[str]) -> int:
    n = 0
    for aid in ids:
        f = parsed / config.pub_key(aid) / "elements.jsonl"
        if f.exists():
            for line in f.open(encoding="utf-8"):
                e = json.loads(line)
                n += e["kind"] in ("itemize", "item") and bool(_RAW_ITEM.search(e["content"]))
    return n


# \item thật, không bắt nhầm \itemsep / \itemindent.
_RAW_ITEM = re.compile(r"\\item(?![A-Za-z])")


def main() -> None:
    # Console Windows mặc định cp1252, không in được tiếng Việt.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ids", default="ids/24120053.txt")
    p.add_argument("--limit", type=int, default=20)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="chỉ kiểm parsed/ và logs/parse.csv của lần chạy thật")
    mode.add_argument("--out", type=Path, help="chạy parse vào thư mục này rồi kiểm")
    p.add_argument("--passthrough", action="store_true",
                   help="thay các hàm chưa giao bằng bản đi thẳng (chỉ với --out)")
    args = p.parse_args()

    ids = list(dict.fromkeys(config.strip_version(i) for i in config.load_ids(args.ids)))
    ids = ids[:args.limit]

    if args.check:
        parsed, log = ROOT / "parsed", config.LOGS_ROOT / "parse.csv"
    else:
        parsed, log = args.out / "parsed", args.out / "parse.csv"
        if args.passthrough:
            _passthrough()
        log.unlink(missing_ok=True)
        print("counts:", pm.run(ids, parsed, overwrite=True, verbose=False, log_path=log))
    sys.exit(1 if check(ids, parsed, log) else 0)


if __name__ == "__main__":
    main()
