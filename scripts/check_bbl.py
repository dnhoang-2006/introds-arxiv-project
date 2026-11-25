"""Kiem viec khoi phuc reference tu .bbl.

    python scripts/check_bbl.py test     # thu 3 bai da biet co .bbl
    python scripts/check_bbl.py count    # dem bibtex rong trong parsed/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def test():
    from parser.bib import collect_bib
    ok = True
    for k in ["2507-10110", "2507-06991", "2507-08926"]:
        for v in sorted((ROOT / "corpus" / k).glob("v*")):
            if not v.is_dir():
                continue
            bbl = list(v.glob("*.bbl"))
            e = collect_bib(v)
            n_title = sum(1 for x in e if x.get("title"))
            n_year = sum(1 for x in e if x.get("year"))
            flag = "" if e else "   <-- VAN RONG"
            print(f"  {k}/{v.name}: {len(bbl)} file .bbl -> {len(e)} entry "
                  f"({n_title} co title, {n_year} co year){flag}")
            if bbl and not e:
                ok = False
            if e:
                x = e[0]
                print(f"      vd: key={x['citation_key']!r}")
                print(f"          title={str(x.get('title'))[:70]!r}")
                print(f"          authors={str(x.get('authors'))[:70]!r}  year={x.get('year')}")
    print("\n=> OK, chay duoc toan bo" if ok else "\n=> CHUA AN, dung chay full")


def count():
    p = ROOT / "parsed"
    dirs = [d for d in p.iterdir() if (d / "bibtex.jsonl").exists()]
    empty = [d for d in dirs if (d / "bibtex.jsonl").stat().st_size == 0]
    print(f"  publication co bibtex.jsonl : {len(dirs)}")
    print(f"  trong do RONG               : {len(empty)}  ({len(empty)/len(dirs):.1%})")
    tot = sum(1 for d in dirs for _ in (d / "bibtex.jsonl").open(encoding="utf-8"))
    print(f"  tong so dong bibtex         : {tot:,}")


if __name__ == "__main__":
    {"test": test, "count": count}[sys.argv[1] if len(sys.argv) > 1 else "test"]()
