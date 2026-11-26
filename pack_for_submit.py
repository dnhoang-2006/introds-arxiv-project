"""Gop parsed/ thanh 3 file nop va nen lai.

    python pack_for_submit.py

Tao ra:
    all_elements.jsonl   (gop tu parsed/*/elements.jsonl)
    all_hierarchy.jsonl  (gop tu parsed/*/hierarchy.jsonl)
    all_bibtex.jsonl     (gop tu parsed/*/bibtex.jsonl)   <- schema_m2.md muc 1.3
    m2_24120053_<ngay>.zip   chua 3 file tren + logs/parse.csv

Ghi bang utf-8 KHONG BOM, vi json.loads bao loi khi gap BOM.
"""
import shutil, sys, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARSED = ROOT / "parsed"
STAMP = time.strftime("%Y%m%d")
ZIP = ROOT / f"m2_24120053_{STAMP}.zip"

pubs = sorted(p for p in PARSED.iterdir() if (p / "elements.jsonl").exists())
print(f"Gop {len(pubs)} publication...\n")

for src_name, out_name in (("elements.jsonl", "all_elements.jsonl"),
                           ("hierarchy.jsonl", "all_hierarchy.jsonl"),
                           ("bibtex.jsonl", "all_bibtex.jsonl")):
    out = ROOT / out_name
    t0, lines = time.perf_counter(), 0
    with out.open("w", encoding="utf-8", newline="\n") as w:   # khong BOM
        for i, pub in enumerate(pubs, 1):
            f = pub / src_name
            if not f.exists():
                continue
            with f.open(encoding="utf-8") as r:
                for ln in r:
                    ln = ln.strip()
                    if ln:
                        w.write(ln + "\n")
                        lines += 1
            if i % 500 == 0 or i == len(pubs):
                el = time.perf_counter() - t0
                print(f"\r  {out_name}: {i}/{len(pubs)}  {lines:,} dong  {el:.0f}s",
                      end="", flush=True)
    print(f"\r  {out_name}: xong  {lines:,} dong  "
          f"{out.stat().st_size/1024/1024:,.1f} MB  {time.perf_counter()-t0:.0f}s" + " " * 20)

parse_csv = ROOT / "logs" / "parse.csv"
if not parse_csv.exists():
    sys.exit("Khong thay logs/parse.csv")

print(f"\nNen -> {ZIP.name} ...")
t0 = time.perf_counter()
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in (ROOT / "all_elements.jsonl", ROOT / "all_hierarchy.jsonl",
              ROOT / "all_bibtex.jsonl", parse_csv):
        print(f"  + {p.name} ({p.stat().st_size/1024/1024:,.1f} MB)")
        z.write(p, arcname=p.name)
print(f"  xong, {ZIP.stat().st_size/1024/1024:,.1f} MB, {time.perf_counter()-t0:.0f}s")

# kiem lai zip doc duoc va khong co BOM
with zipfile.ZipFile(ZIP) as z:
    bad = z.testzip()
    names = z.namelist()
    first = z.open("all_elements.jsonl").readline()
print(f"\nKiem tra:")
print(f"  zip hop le   : {'OK' if bad is None else 'HONG o ' + bad}")
print(f"  so file      : {len(names)}  {names}")
print(f"  co BOM khong : {'CO BOM - LOI' if first.startswith(b'\\xef\\xbb\\xbf') else 'khong, OK'}")
print(f"\n=> Upload {ZIP.name} len Drive")
