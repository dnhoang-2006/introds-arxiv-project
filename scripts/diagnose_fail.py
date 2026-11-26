"""Phan loai mot bai bi no_root / khong co thu muc parsed.

    python scripts/diagnose_fail.py 2504.11639

In ra bai thuoc loai nao de quyet dinh: sua duoc, hay ghi vao gioi han da biet.
Chi doc corpus/ va logs/parse.csv, khong doi gi.
"""
import csv, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = re.compile(r"^[^%\n]*\\documentclass", re.M)
BEG = re.compile(r"^[^%\n]*\\begin\{document\}", re.M)
INC = re.compile(r"^[^%\n]*\\(?:input|include)\s*\{([^}]*)\}", re.M)


def main(arxiv_id: str) -> int:
    key = arxiv_id.replace(".", "-")
    cdir = ROOT / "corpus" / key
    print(f"=== {arxiv_id} ===\n")

    log = ROOT / "logs" / "parse.csv"
    if log.exists():
        rows = [r for r in csv.DictReader(log.open(encoding="utf-8"))
                if r.get("arxiv_id") == arxiv_id]
        if rows:
            last = {}
            for r in rows:
                last[r.get("version")] = r
            print("logs/parse.csv (lan chay gan nhat moi version):")
            for v, r in sorted(last.items()):
                print(f"   v{v}: status={r.get('status')}  error_type={r.get('error_type')}")
        else:
            print("logs/parse.csv: KHONG co dong nao -> bai chua bao gio duoc parse")
    print()

    if not cdir.is_dir():
        print("KHONG co thu muc corpus -> chua tai ve. Kiem lai buoc download.")
        return 1

    verdicts = []
    for v in sorted(cdir.glob("v*"), key=lambda p: int(p.name[1:] or 0)):
        if not v.is_dir():
            continue
        if (v / "_EMPTY.json").exists():
            print(f"{v.name}: _EMPTY.json -> M1 ghi nhan khong co source. DUNG, khong phai loi.")
            verdicts.append("empty"); continue
        tex = sorted(p for p in v.glob("**/*.tex") if not p.name.startswith("."))
        if not tex:
            print(f"{v.name}: khong co file .tex nao")
            verdicts.append("no_tex"); continue

        print(f"{v.name}: {len(tex)} file .tex")
        has_doc = has_beg = is_html = False
        for p in tex:
            t = p.read_text(encoding="utf-8", errors="ignore")
            d, b = bool(DOC.search(t)), bool(BEG.search(t))
            h = t.lstrip()[:200].lower().startswith(("<html", "<!doctype"))
            has_doc |= d; has_beg |= b; is_html |= h
            tags = []
            if d: tags.append("documentclass")
            if b: tags.append("begin{document}")
            if h: tags.append("** LA FILE HTML **")
            inc = INC.findall(t)
            if inc: tags.append(f"input/include -> {inc[:3]}")
            print(f"    {p.relative_to(v).as_posix():<34} {len(t.splitlines()):>5} dong"
                  f"   {' · '.join(tags) if tags else ''}")

        if is_html:
            print(f"  => HTML DOI LOT .tex. Gioi han da biet, KHONG sua.")
            verdicts.append("html")
        elif not has_doc and not has_beg:
            print(f"  => PLAIN TeX (khong co \\documentclass lan \\begin{{document}}). "
                  f"Gioi han da biet, KHONG sua.")
            verdicts.append("plaintex")
        else:
            print(f"  => CO dau hieu LaTeX hop le ma van no_root -> CA BIEN MOI, bao nhom.")
            verdicts.append("unknown")
        # file duoc goi qua input nhung khong co trong corpus
        missing = set()
        for p in tex:
            for tgt in INC.findall(p.read_text(encoding="utf-8", errors="ignore")):
                cands = [tgt, tgt + ".tex"]
                if not any((v / c).exists() for c in cands):
                    missing.add(tgt)
        if missing:
            print(f"  ! file goi qua \\input nhung KHONG co trong corpus: {sorted(missing)[:5]}")
        print()

    print("KET LUAN:", ", ".join(sorted(set(verdicts))) or "khong co version nao")
    if "unknown" in verdicts:
        print("  -> Co version dang ngo, gui ket qua nay cho nhom.")
    else:
        print("  -> Thuoc gioi han da biet. Ghi vao docs va poster, khong sua code.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Dung: python scripts/diagnose_fail.py <arxiv_id>")
    sys.exit(main(sys.argv[1]))
