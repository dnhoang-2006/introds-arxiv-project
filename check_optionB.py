"""Kiem tra parsed/ dung la phuong an B truoc khi gui cho Tu va Tuan.

    python check_optionB.py parsed

Phai thay:
  - La co hau to ~k      : 0        (la duoc dung chung, khong tach)
  - Node khong-la nhieu cha: 0      (V4 doi hoi cay o tang chua)
"""
import json, sys
from collections import defaultdict
from pathlib import Path

LEAF_KINDS = {"sentence", "formula", "figure"}
root = Path(sys.argv[1] if len(sys.argv) > 1 else "parsed")

leaf_suffix = nonleaf_suffix = 0
leaf_multi = nonleaf_multi = 0
total_el = total_pub = 0
examples = []

for pub in sorted(root.iterdir()):
    ef, hf = pub / "elements.jsonl", pub / "hierarchy.jsonl"
    if not ef.exists():
        continue
    total_pub += 1
    kind = {}
    for ln in ef.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        kind[r["element_id"]] = r["kind"]
        total_el += 1
        if "~" in r["element_id"]:
            if r["kind"] in LEAF_KINDS:
                leaf_suffix += 1
                if len(examples) < 3:
                    examples.append((pub.name, r["kind"], r["element_id"]))
            else:
                nonleaf_suffix += 1

    parents = defaultdict(set)
    for ln in hf.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        parents[(r["version"], r["element_id"])].add(r["parent_id"])
    for (_, eid), ps in parents.items():
        if len(ps) > 1:
            if kind.get(eid) in LEAF_KINDS:
                leaf_multi += 1
            else:
                nonleaf_multi += 1

print(f"Publication doc duoc     : {total_pub}")
print(f"Tong element             : {total_el:,}")
print()
print(f"La   co hau to ~k        : {leaf_suffix:<10}  phai = 0   {'OK' if leaf_suffix == 0 else '<-- VAN LA PHUONG AN A'}")
print(f"Khong-la co hau to ~k    : {nonleaf_suffix:<10}  > 0 la dung")
print()
print(f"La   nhieu cha           : {leaf_multi:<10}  > 0 la dung (dedup noi dung)")
print(f"Khong-la nhieu cha       : {nonleaf_multi:<10}  phai = 0   {'OK' if nonleaf_multi == 0 else '<-- V4 SE FAIL'}")
if examples:
    print("\nVi du la bi gan hau to (khong duoc co):")
    for e in examples:
        print("   ", e)
print()
print("=> SAN SANG GUI" if leaf_suffix == 0 and nonleaf_multi == 0 else "=> CHUA DUNG, DUNG GUI")