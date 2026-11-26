"""Dung lai so entry bibtex TRUOC hai ban sua, khong can parse lai.

    python scripts/estimate_before.py              # toan bo
    python scripts/estimate_before.py 300          # lay mau 300 bai cho nhanh

Chi doc corpus/ va parsed/, khong doi gi. Dem khoa citation_key duy nhat:
  A  tu .tex \\bibitem va .bib        -> TRUOC khi giu .bbl, TRUOC khi loc \\cite
  B  A cong them .bbl                 -> SAU khi giu .bbl, TRUOC khi loc \\cite
  C  B giao voi tap khoa duoc \\cite  -> SAU ca hai ban sua
C phai xap xi so entry trong parsed/ hien tai; neu lech nhieu thi bao nhom.
"""
import json, random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
BIBENTRY = re.compile(r"@[a-zA-Z]+\s*\{\s*([^,\s}]+)", re.M)
CITE = re.compile(r"\\[a-zA-Z]*[Cc]ite[a-zA-Z]*\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}")
NOCITE = re.compile(r"\\nocite\s*\{\s*\*\s*\}")


def read(p):
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def main(sample=None):
    pubs = sorted(d for d in (ROOT / "corpus").iterdir() if d.is_dir())
    if sample:
        random.seed(11)
        pubs = random.sample(pubs, min(sample, len(pubs)))
    A = B = C = now = 0
    for i, d in enumerate(pubs, 1):
        vdirs = [v for v in d.glob("v*") if v.is_dir()]
        a, bbl, cited, nocite = set(), set(), set(), False
        for v in vdirs:
            for p in v.rglob("*.tex"):
                t = re.sub(r"(?<!\\)%.*", "", read(p))
                a |= set(BIBITEM.findall(t))
                if NOCITE.search(t):
                    nocite = True
                for g in CITE.findall(t):
                    cited |= {k.strip() for k in g.split(",") if k.strip()}
            for p in v.rglob("*.bib"):
                a |= set(BIBENTRY.findall(read(p)))
            for p in v.rglob("*.bbl"):
                bbl |= set(BIBITEM.findall(read(p)))
        b = a | bbl
        c = b if (nocite or not cited) else (b & cited) or b
        A += len(a); B += len(b); C += len(c)
        f = ROOT / "parsed" / d.name / "bibtex.jsonl"
        if f.exists():
            now += sum(1 for _ in f.open(encoding="utf-8"))
        if i % 500 == 0:
            print(f"  {i}/{len(pubs)}...", flush=True)

    print(f"\n{len(pubs):,} publication\n")
    print(f"  A  truoc ca hai ban sua      : {A:,}")
    print(f"  B  sau khi giu .bbl          : {B:,}   ({B-A:+,})")
    print(f"  C  sau khi loc \\cite         : {C:,}   ({C-B:+,})")
    print(f"\n  parsed/ hien tai            : {now:,}")
    if now:
        d = abs(C - now) / now
        print(f"  lech giua C va thuc te      : {d:.1%}  "
              f"{'OK' if d < 0.15 else '<-- LECH NHIEU, bao nhom'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
