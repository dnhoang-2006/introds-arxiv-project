"""Dong goi du lieu M1 (paper_meta.json + references.json) de gui Minh Thu.

    python scripts/pack_m1.py 24120053

Ghi ra m1_<MSSV>.zip ngay tai thu muc goc repo.
"""
import sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("paper_meta.json", "references.json")


def main(mssv: str) -> int:
    out = ROOT / f"m1_{mssv}.zip"
    files = [f for n in NAMES for f in sorted((ROOT / "corpus").glob(f"*/{n}"))]
    if not files:
        print("Khong tim thay file nao trong corpus/ — dung dung thu muc goc repo chua?")
        return 1
    raw = sum(f.stat().st_size for f in files)
    print(f"Nen {len(files):,} file, {raw/1024/1024:,.1f} MB chua nen...")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, f in enumerate(files, 1):
            z.write(f, arcname=f.relative_to(ROOT).as_posix())
            if i % 2000 == 0:
                print(f"  {i:,}/{len(files):,}")
    # kiem lai
    with zipfile.ZipFile(out) as z:
        bad, names = z.testzip(), z.namelist()
    print(f"\n{out.name}: {out.stat().st_size/1024/1024:,.1f} MB")
    print(f"  zip hop le : {'OK' if bad is None else 'HONG o ' + bad}")
    print(f"  so file    : {len(names):,}")
    print(f"  vi du      : {names[0]}")
    print(f"\n=> Gui file {out.name} cho Minh Thu")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Dung: python scripts/pack_m1.py <MSSV>")
    sys.exit(main(sys.argv[1]))
