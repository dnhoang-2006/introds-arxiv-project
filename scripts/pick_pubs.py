"""Chọn 5 publication để gán tay, bằng tiêu chí đo được thay vì cảm tính.

`manual_label.py --suggest` chỉ lọc theo số entry và số reference. Hai con số đó
không trả lời được câu hỏi thật sự: **bài này có đủ 20 nhãn khác null không**, và
**gán mất bao lâu**. Script này ước tính cả hai trước khi bạn bỏ ra một tiếng.

Ba tiêu chí, theo đúng thứ tự ưu tiên
-------------------------------------
1. KHẢ THI — ước tính >= 20 entry khớp được. Dưới ngưỡng này thì gán xong vẫn
   phải bỏ bài, mất trắng công.
2. RẺ — ít entry. Bạn phải gán HẾT mọi entry của bài đã chọn, nên số entry
   chính là số lần bấm phím.
3. KHÁC NHAU — 5 bài không trùng lĩnh vực. Đo bằng độ chồng lấn danh sách
   reference: hai bài cùng ngành trích dẫn cùng một đám bài.

Vì sao KHÔNG xếp hạng theo "độ dễ"
----------------------------------
Chọn bài mà tiêu đề khớp rõ ràng sẽ làm tập test dễ một cách giả tạo, và MRR
cao lên vì lý do sai. Đúng hiện tượng thầy cảnh báo ở M3 câu 7. Nên `uoc_tinh`
ở đây chỉ dùng làm NGƯỠNG LOẠI, không dùng làm khoá sắp xếp.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
from matching.clean import clean_title  # noqa: E402
from matching.label_io import load_entries, load_references  # noqa: E402

MIN_LABELS = 20          # schema_m3 mục 4
MARGIN = 5               # chọn dư ra, vì ước tính có sai số
TITLE_HIT = 0.60         # ngưỡng coi là "có thể khớp bằng tiêu đề"
SECONDS_PER_ENTRY = 12   # đo thô: đọc entry + liếc 5 ứng viên + bấm

#: arXiv ID nằm lẫn trong url/doi/journal của entry.
_ARXIV_IN_TEXT = re.compile(r"(?:arxiv[:.]|abs/)\s*(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", re.I)


def _entry_ids(e: dict[str, Any]) -> set[str]:
    """arXiv ID đọc được từ chính entry.

    Chỉ còn url/doi/journal: `bibtex.jsonl` đúng 9 cột theo schema_m2 mục 1.3,
    nên ID mà bib.py bóc từ trường `eprint` đã bị bỏ ở `_bibtex_row`. Đây là lý do
    con số `co_id` dưới đây là CẬN DƯỚI, không phải số thật.
    """
    out: set[str] = set()
    for k in ("url", "doi", "journal"):
        v = e.get(k)
        if v:
            out.update(m.group(1) for m in _ARXIV_IN_TEXT.finditer(str(v)))
    return out


def score_pub(aid: str, *, parsed_root: Path | None = None,
              corpus_root: Path | None = None) -> dict[str, Any] | None:
    entries = load_entries(aid, parsed_root)
    refs = load_references(aid, corpus_root)
    if not entries or not refs:
        return None
    ref_ids = {r["ref_arxiv_id"] for r in refs}
    ref_titles = [clean_title(r.get("ref_title")) for r in refs]

    co_id = 0
    co_title = 0
    uoc_tinh = 0
    for e in entries:
        hit_id = bool(_entry_ids(e) & ref_ids)
        t = clean_title(e.get("title"))
        best = max((SequenceMatcher(None, t, rt).ratio() for rt in ref_titles if rt),
                   default=0.0) if t else 0.0
        hit_title = best >= TITLE_HIT
        co_id += hit_id
        co_title += hit_title
        uoc_tinh += hit_id or hit_title

    return {
        "arxiv_id": aid,
        "entry": len(entries),
        "ref": len(refs),
        "co_id": co_id,
        "co_title": co_title,
        "uoc_tinh": uoc_tinh,
        "ref_ids": ref_ids,
        "phut": round(len(entries) * SECONDS_PER_ENTRY / 60),
    }


def overlap(a: set[str], b: set[str]) -> float:
    """Tỉ lệ chồng lấn reference giữa hai bài, chia cho bên nhỏ hơn."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _title_of(aid: str, corpus_root: Path | None = None) -> str:
    p = (corpus_root or config.CORPUS_ROOT) / config.pub_key(aid) / "paper_meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("title", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _already_labelled(mssv: str) -> set[str]:
    out: set[str] = set()
    for sub in ("manual", "auto"):
        p = ROOT / "labels" / sub / f"{mssv}.jsonl"
        if p.is_file():
            out |= {json.loads(l)["arxiv_id"] for l in p.open(encoding="utf-8") if l.strip()}
    return out


def _print_table(rows: list[dict[str, Any]], corpus_root: Path | None) -> None:
    print(f"\n{'arxiv_id':<14}{'entry':>6}{'ref':>6}{'co_id':>7}{'co_title':>9}"
          f"{'uoc_tinh':>9}{'phut':>6}  tiêu đề")
    print("-" * 110)
    for r in rows:
        ok = "" if r["uoc_tinh"] >= MIN_LABELS + MARGIN else "  <-- RỦI RO"
        print(f"{r['arxiv_id']:<14}{r['entry']:>6}{r['ref']:>6}{r['co_id']:>7}"
              f"{r['co_title']:>9}{r['uoc_tinh']:>9}{r['phut']:>6}  "
              f"{_title_of(r['arxiv_id'], corpus_root)[:48]}{ok}")


def cmd_rank(a: argparse.Namespace) -> int:
    ids_file = a.ids or ROOT / "ids" / f"{a.mssv}.txt"
    ids = list(dict.fromkeys(config.strip_version(i) for i in config.load_ids(str(ids_file))))
    skip = _already_labelled(a.mssv)
    rows = []
    for n, aid in enumerate(ids, 1):
        if aid in skip:
            continue
        if n % 200 == 0:
            print(f"  ...đã quét {n}/{len(ids)}", file=sys.stderr)
        r = score_pub(aid, parsed_root=a.parsed_root, corpus_root=a.corpus_root)
        if r and r["uoc_tinh"] >= MIN_LABELS + MARGIN and a.min_entry <= r["entry"] <= a.max_entry:
            rows.append(r)

    if not rows:
        print(f"Không bài nào đạt: ước tính >= {MIN_LABELS + MARGIN} nhãn và "
              f"{a.min_entry} <= entry <= {a.max_entry}.")
        print("Nới --max-entry lên, hoặc kiểm tra parsed/ đã chạy lại sau PR #58 chưa.")
        return 1

    rows.sort(key=lambda r: r["entry"])      # rẻ trước, KHÔNG sắp theo độ dễ
    print(f"{len(rows)} bài đạt cả hai ngưỡng (bỏ {len(skip)} bài đã có nhãn).")
    _print_table(rows[:a.top], a.corpus_root)

    n_id = sum(r["co_id"] for r in rows)
    n_ent = sum(r["entry"] for r in rows)
    print(f"\nTrên {len(rows)} bài này: {n_id}/{n_ent} entry ({n_id/n_ent:.1%}) còn đọc "
          f"được arXiv ID trong url/doi/journal.")
    print("Chọn 5 dòng khác lĩnh vực nhau rồi chạy:")
    print(f"  python scripts/pick_pubs.py check --mssv {a.mssv} --pubs <id1>,...,<id5>")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    pubs = [config.strip_version(p.strip()) for p in a.pubs.split(",") if p.strip()]
    rows = []
    for aid in pubs:
        r = score_pub(aid, parsed_root=a.parsed_root, corpus_root=a.corpus_root)
        if r is None:
            print(f"{aid}: không có entry hoặc reference có arXiv ID — loại.")
            return 1
        rows.append(r)

    _print_table(rows, a.corpus_root)
    bad = [r["arxiv_id"] for r in rows if r["uoc_tinh"] < MIN_LABELS + MARGIN]

    print(f"\nChồng lấn reference giữa các cặp (cao = cùng lĩnh vực):")
    worst = 0.0
    for x, y in combinations(rows, 2):
        o = overlap(x["ref_ids"], y["ref_ids"])
        worst = max(worst, o)
        flag = "  <-- TRÙNG LĨNH VỰC" if o >= 0.15 else ""
        print(f"  {x['arxiv_id']} / {y['arxiv_id']}  {o:.1%}{flag}")

    tong = sum(r["entry"] for r in rows)
    print(f"\nTổng: {tong} entry, ước tính {sum(r['uoc_tinh'] for r in rows)} nhãn khác null, "
          f"khoảng {round(tong * SECONDS_PER_ENTRY / 60)} phút.")

    if len(pubs) != 5:
        print(f"CẢNH BÁO: schema_m3 mục 4 quy định đúng 5 bài, đang có {len(pubs)}.")
    if bad:
        print(f"CẢNH BÁO: {', '.join(bad)} ước tính dưới {MIN_LABELS + MARGIN} nhãn — "
              f"dễ không đạt ngưỡng {MIN_LABELS}. Nên thay bài khác.")
    if worst >= 0.15:
        print("CẢNH BÁO: có cặp chồng lấn >= 15% reference. Đổi một bài sang lĩnh vực khác, "
              "nếu không model chỉ học được một kiểu trích dẫn.")
    if not bad and worst < 0.15 and len(pubs) == 5:
        print("Cả 3 tiêu chí đều đạt. Chạy:")
        print(f"  python scripts/manual_label.py --mssv {a.mssv} --pubs {a.pubs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chọn và kiểm 5 publication để gán tay (M3)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in (("rank", cmd_rank), ("check", cmd_check)):
        p = sub.add_parser(name)
        p.add_argument("--mssv", required=True)
        p.add_argument("--parsed-root", type=Path, default=None)
        p.add_argument("--corpus-root", type=Path, default=None)
        p.set_defaults(fn=fn)
        if name == "rank":
            p.add_argument("--ids", type=Path, default=None)
            p.add_argument("--min-entry", type=int, default=25)
            p.add_argument("--max-entry", type=int, default=55)
            p.add_argument("--top", type=int, default=20)
        else:
            p.add_argument("--pubs", required=True)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
