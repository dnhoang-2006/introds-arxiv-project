"""Buoc 1-2: chon 4 bai ngau nhien va in ra duong bien dich de gan tay.

    python gold/gold_prep.py              # chon 4 bai
    python gold/gold_prep.py 2507.07123   # xem chi tiet mot bai

KHONG doc parsed/ hay reports/ — giu bo gold doc lap voi parser.
"""
import random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "ids" / "24120053.txt"
CORPUS = ROOT / "corpus"
SEED = 24120053

DOC_CLASS = re.compile(r"^[^%\n]*\\documentclass", re.M)
INCLUDE = re.compile(r"^[^%\n]*\\(input|include)\s*\{([^}]*)\}", re.M)


def read(p):
    return p.read_text(encoding="utf-8", errors="ignore")


def report(arxiv_id):
    key = arxiv_id.replace(".", "-")
    d = CORPUS / key
    print(f"\n{'='*64}\n{arxiv_id}   ({d})")
    if not d.is_dir():
        print("  KHONG CO trong corpus/"); return
    for v in sorted(d.glob("v*"), key=lambda p: int(p.name[1:])):
        tex = sorted(v.glob("**/*.tex"))
        empty = (v / "_EMPTY.json").exists()
        print(f"\n  {v.name}: {len(tex)} file .tex" + ("   <-- _EMPTY.json, ghi status=empty" if empty else ""))
        if empty or not tex:
            continue
        roots = [p for p in tex if DOC_CLASS.search(read(p))]
        for p in tex:
            rel = p.relative_to(v).as_posix()
            mark = " <-- ROOT (co \\documentclass)" if p in roots else ""
            n = len(read(p).splitlines())
            print(f"      {rel:<40} {n:>5} dong{mark}")
        for p in roots or tex[:1]:
            inc = INCLUDE.findall(read(p))
            if inc:
                print(f"      duong bien dich tu {p.name}:")
                for _, target in inc:
                    print(f"         -> {target}")


def main():
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            report(a)
        return
    ids = [l.strip() for l in IDS.read_text(encoding="utf-8").splitlines() if l.strip()]
    # Tu dan: "Chon ngau nhien" va "version rong ghi empty, khong bo qua".
    # Vay KHONG loc bai rong — chung kiem dung hanh vi V6 cua parser.
    ids = [i for i in ids if (CORPUS / i.replace(".", "-")).is_dir()]
    random.seed(SEED)
    chosen = random.sample(ids, 4)
    print("4 BAI DA CHON (seed = MSSV, lap lai cho ra ket qua giong nhau):")
    for c in chosen:
        print("   ", c)
    for c in chosen:
        report(c)
    out = ROOT / "gold" / "gold_24120053.csv"
    if not out.exists():
        out.write_text("arxiv_id,version,status,gold_node_id,parent_gold_node_id,kind,content,source_file\n",
                       encoding="utf-8")
        print(f"\nDa tao file trong: {out}")


if __name__ == "__main__":
    main()
