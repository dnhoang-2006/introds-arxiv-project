"""Buoc 4: tu kiem CSV gold truoc khi gui Tu.

    python gold/gold_check.py gold/gold_24120053.csv
"""
import csv, sys
from collections import defaultdict

KINDS = {"document", "section", "subsection", "subsubsection", "paragraph",
         "itemize", "item", "sentence", "formula", "figure"}
LEAF = {"sentence", "formula", "figure"}

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
err = []
byver = defaultdict(list)
for i, r in enumerate(rows, 2):
    byver[(r["arxiv_id"], r["version"])].append((i, r))

for i, r in enumerate(rows, 2):
    if r["kind"] and r["kind"] not in KINDS:
        err.append(f"dong {i}: kind '{r['kind']}' khong hop le")
    if r["status"] not in ("ok", "empty"):
        err.append(f"dong {i}: status phai la ok hoac empty, gap '{r['status']}'")

for (aid, v), items in sorted(byver.items()):
    ids = {r["gold_node_id"] for _, r in items}
    roots = [r for _, r in items if not r["parent_gold_node_id"].strip()]
    st = {r["status"] for _, r in items}
    if st == {"empty"}:
        if len(items) != 1:
            err.append(f"{aid} v{v}: version rong phai co dung 1 dong")
        continue
    if len(roots) != 1:
        err.append(f"{aid} v{v}: phai co dung 1 root, gap {len(roots)}")
    elif roots[0]["kind"] != "document":
        err.append(f"{aid} v{v}: root phai co kind=document")
    dup = [x for x in ids if sum(1 for _, r in items if r["gold_node_id"] == x) > 1]
    if dup:
        err.append(f"{aid} v{v}: gold_node_id trung: {sorted(set(dup))[:5]}")
    for _, r in items:
        p = r["parent_gold_node_id"].strip()
        if p and p not in ids:
            err.append(f"{aid} v{v}: node {r['gold_node_id']} tro toi cha '{p}' khong ton tai")
    parent_of = {r["gold_node_id"]: r["parent_gold_node_id"].strip() for _, r in items}
    kind_of = {r["gold_node_id"]: r["kind"] for _, r in items}
    for n in ids:                                   # bat chu trinh
        seen, cur = set(), n
        while cur and cur not in seen:
            seen.add(cur); cur = parent_of.get(cur, "")
        if cur:
            err.append(f"{aid} v{v}: chu trinh cha-con tai {n}")
            break
    for _, r in items:                              # la khong duoc lam cha
        p = r["parent_gold_node_id"].strip()
        if p and kind_of.get(p) in LEAF:
            err.append(f"{aid} v{v}: {r['gold_node_id']} co cha la node la '{p}'")

print(f"Dong: {len(rows)}   Bai: {len({r['arxiv_id'] for r in rows})}   "
      f"Version: {len(byver)}")
for (aid, v), items in sorted(byver.items()):
    st = items[0][1]["status"]
    print(f"   {aid} v{v}: {len(items):>4} node   status={st}")
print()
if err:
    print(f"CO {len(err)} VAN DE:")
    for e in err[:30]:
        print("  -", e)
else:
    print("=> CSV HOP LE, gui duoc cho Tu")
