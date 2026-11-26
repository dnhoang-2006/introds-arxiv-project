import json, glob, collections, os
LEAF = {"sentence", "formula", "figure"}
nonleaf = leaf = tot = 0
files = glob.glob("parsed/*/hierarchy.jsonl")
for i, f in enumerate(files, 1):
    d = os.path.dirname(f)
    kind = {}
    for l in open(d + "/elements.jsonl", encoding="utf-8"):
        e = json.loads(l); kind[e["element_id"]] = e["kind"]
    P = collections.defaultdict(set)
    for l in open(f, encoding="utf-8"):
        h = json.loads(l)
        P[(h["version"], h["element_id"])].add(h["parent_id"])
    tot += len(P)
    for (v, eid), par in P.items():
        if len(par) > 1:
            if kind.get(eid) in LEAF: leaf += 1
            else: nonleaf += 1
    if i % 1000 == 0: print(f"  {i}/{len(files)} ...", flush=True)
print()
print("KHONG PHAI LA, nhieu cha:", nonleaf, "  <- V4 ERROR, phai = 0")
print("LA, nhieu cha          :", leaf, "  <- chi la canh bao, dung thiet ke")
print("tong node              :", tot)
