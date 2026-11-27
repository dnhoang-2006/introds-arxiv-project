"""Gán nhãn TAY cặp entry BibTeX <-> reference cho Milestone 3 (docs/schema_m3.md).

    # 1. Gợi ý publication đủ điều kiện để chọn 5 bài
    python scripts/manual_label.py --mssv <MSSV> --suggest

    # 2. Gán nhãn 5 bài đã chọn (chạy lại là làm tiếp chỗ đang dừng)
    python scripts/manual_label.py --mssv <MSSV> --pubs 2503.13964,2503.15390,...

Kết quả ghi vào labels/manual/<MSSV>.jsonl, mỗi entry một dòng, đúng schema mục 1:
    {"arxiv_id", "citation_key", "groundtruth_arxiv_id", "labeler", "method": "manual"}

Với mỗi entry, công cụ in tiêu đề/tác giả/năm của entry và 5 reference có tiêu đề
giống nhất (chỉ để đỡ phải lục cả danh sách). Công cụ KHÔNG đánh dấu sẵn đáp án:
người gán tự đối chiếu rồi gõ lựa chọn. Lệnh tại dấu nhắc:

    1..5   chọn reference tương ứng trong danh sách gợi ý
    r<N>   chọn reference số N trong danh sách đầy đủ (xem bằng `s`)
    0      entry không khớp reference nào -> groundtruth_arxiv_id = null
    s      in toàn bộ reference có arXiv ID của bài
    b      quay lại entry trước (xoá nhãn vừa gán)
    q      thoát, lần sau chạy lại sẽ làm tiếp

Ràng buộc lấy từ schema_m3:
  - Mục 2: entry không khớp vẫn có dòng, ghi null; chỉ tiêu 20 nhãn/bài đếm dòng KHÁC null.
  - Mục 4: bài đã gán tay không đưa qua matcher tự động -> chạy matcher với
    `--exclude labels/manual/<MSSV>.jsonl`.
  - Mục 7: đáp án phải nằm trong reference của chính publication đó.
Cần parse lại bằng code mới trước khi gán, để citation_key khớp bảng bibtex cuối.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
from matching.clean import clean_title  # noqa: E402
from matching.label_io import Label, load_entries, load_references, write_labels  # noqa: E402

MIN_LABELS_PER_PUB = 20      # schema_m3 mục 4
N_SHOWN = 5


#  Phần thuần (có test): xếp hạng gợi ý, đọc/ghi tiến độ, gợi ý publication

def rank_candidates(entry: dict[str, Any], refs: list[dict[str, Any]], k: int = N_SHOWN) -> list[int]:
    """Chỉ số k reference có tiêu đề giống tiêu đề entry nhất (giữ thứ tự gốc khi hoà)."""
    t = clean_title(entry.get("title"))
    scores = [SequenceMatcher(None, t, clean_title(r.get("ref_title"))).ratio() if t else 0.0 for r in refs]
    return sorted(range(len(refs)), key=lambda i: -scores[i])[:k]


def load_progress(path: Path) -> list[Label]:
    """Nhãn đã gán trong file của người gán (để làm tiếp)."""
    if not path.is_file():
        return []
    out = []
    for n, line in enumerate(path.open(encoding="utf-8"), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("method") != "manual":
            raise ValueError(f"{path}:{n} không phải nhãn manual")
        out.append(Label(r["arxiv_id"], r["citation_key"], r.get("groundtruth_arxiv_id"),
                         str(r.get("labeler", "")), "manual"))
    return out


def append_label(path: Path, label: Label) -> None:
    """Ghi thêm một dòng ngay khi gán, để thoát giữa chừng không mất nhãn."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(label.__dict__, ensure_ascii=False) + "\n")


def count_matched(labels: list[Label], arxiv_id: str) -> int:
    return sum(1 for lb in labels if lb.arxiv_id == arxiv_id and lb.groundtruth_arxiv_id)


def _auto_pubs(mssv: str) -> set[str]:
    p = ROOT / "labels" / "auto" / f"{mssv}.jsonl"
    if not p.is_file():
        return set()
    return {json.loads(l)["arxiv_id"] for l in p.open(encoding="utf-8") if l.strip()}


def suggest_pubs(
    ids: list[str],
    *,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
    exclude: set[str] = frozenset(),
    min_refs: int = 25,
    max_entries: int = 90,
) -> list[tuple[str, int, int]]:
    """(arxiv_id, số entry, số reference có arXiv ID) của các bài dễ gán đủ 20 nhãn.

    Tiêu chí: còn ít nhất `min_refs` reference có arXiv ID (dư so với 20 vì có entry
    không khớp), số entry vừa phải để gán trong ~10 phút, không nằm trong `exclude`.
    """
    out = []
    for aid in ids:
        if aid in exclude:
            continue
        refs = load_references(aid, corpus_root)
        if len(refs) < min_refs:
            continue
        n_ent = len(load_entries(aid, parsed_root))
        if min_refs <= n_ent <= max_entries:
            out.append((aid, n_ent, len(refs)))
    return out

#  Phần tương tác

def _fmt_authors(a: Any, n: int = 3) -> str:
    if not a:
        return "-"
    a = a if isinstance(a, list) else [str(a)]
    return ", ".join(map(str, a[:n])) + (f" (+{len(a) - n})" if len(a) > n else "")


def _show_entry(i: int, total: int, e: dict[str, Any]) -> None:
    print(f"\n[{i}/{total}] {e.get('citation_key')}")
    print(f"   title  : {e.get('title') or '-'}")
    print(f"   authors: {_fmt_authors(e.get('authors'))}")
    # Không in `arxiv_id`: ở bảng bibtex (schema_m2 mục 1.3) đó là ID của publication
    # chứa entry, không phải của bài được trích. arXiv ID thật nếu có nằm trong journal/url.
    extra = {k: e.get(k) for k in ("year", "doi", "url", "journal") if e.get(k)}
    print("   " + " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else "   (không có year/doi/url)")


def _show_ref(label: str, r: dict[str, Any]) -> None:
    print(f"   {label:>4}  {r.get('ref_arxiv_id'):<16} {r.get('ref_year') or '----'}  "
          f"{(r.get('ref_title') or '-')[:90]}")
    print(f"         {_fmt_authors(r.get('ref_authors'))}")


def label_publication(
    aid: str,
    mssv: str,
    out_path: Path,
    labels: list[Label],
    *,
    ask: Callable[[str], str] = input,
    parsed_root: Path | None = None,
    corpus_root: Path | None = None,
) -> bool:
    """Gán từng entry chưa có nhãn của một bài. Trả về False nếu người dùng thoát (q)."""
    entries = load_entries(aid, parsed_root)
    refs = load_references(aid, corpus_root)
    if not entries or not refs:
        print(f"{aid}: không có entry hoặc reference có arXiv ID, bỏ qua.")
        return True
    done = {lb.citation_key for lb in labels if lb.arxiv_id == aid}
    todo = [e for e in entries if e.get("citation_key") not in done]
    print(f"\n===== {aid}: {len(entries)} entry, {len(refs)} reference có arXiv ID, "
          f"còn {len(todo)} entry chưa gán =====")

    i = 0
    while i < len(todo):
        e = todo[i]
        _show_entry(len(entries) - len(todo) + i + 1, len(entries), e)
        shown = rank_candidates(e, refs)
        for n, j in enumerate(shown, 1):
            _show_ref(str(n), refs[j])
        while True:
            cmd = ask("   chọn [1-5 | r<N> | 0=không khớp | s | b | q]: ").strip().lower()
            gt: str | None
            if cmd == "q":
                return False
            if cmd == "s":
                for n, r in enumerate(refs, 1):
                    _show_ref(f"r{n}", r)
                continue
            if cmd == "b":
                if i == 0:
                    print("   đang ở entry đầu của bài này.")
                    continue
                i -= 1
                prev = todo[i]["citation_key"]
                labels[:] = [lb for lb in labels if not (lb.arxiv_id == aid and lb.citation_key == prev)]
                write_labels(out_path, labels)
                break
            if cmd == "0":
                gt = None
            elif cmd.isdigit() and 1 <= int(cmd) <= len(shown):
                gt = refs[shown[int(cmd) - 1]]["ref_arxiv_id"]
            elif cmd.startswith("r") and cmd[1:].isdigit() and 1 <= int(cmd[1:]) <= len(refs):
                gt = refs[int(cmd[1:]) - 1]["ref_arxiv_id"]
            else:
                print("   không hiểu lệnh.")
                continue
            lb = Label(aid, e["citation_key"], gt, mssv, "manual")
            labels.append(lb)
            append_label(out_path, lb)
            i += 1
            break

    n = count_matched(labels, aid)
    flag = "OK" if n >= MIN_LABELS_PER_PUB else f"THIẾU (cần >= {MIN_LABELS_PER_PUB}, nên thay bài khác)"
    print(f"\n{aid}: {n} nhãn khác null — {flag}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gán nhãn tay entry BibTeX <-> reference (M3)")
    ap.add_argument("--mssv", required=True)
    ap.add_argument("--ids", type=Path, default=None, help="Mặc định ids/<MSSV>.txt")
    ap.add_argument("--pubs", default=None, help="Các arXiv ID cần gán, ngăn bởi dấu phẩy")
    ap.add_argument("--suggest", action="store_true", help="In danh sách publication đủ điều kiện")
    ap.add_argument("--seed", type=int, default=177)
    a = ap.parse_args(argv)

    out_path = ROOT / "labels" / "manual" / f"{a.mssv}.jsonl"
    labels = load_progress(out_path)

    if a.suggest:
        ids_file = a.ids or ROOT / "ids" / f"{a.mssv}.txt"
        ids = list(dict.fromkeys(config.strip_version(i) for i in config.load_ids(str(ids_file))))
        auto = _auto_pubs(a.mssv)
        cands = suggest_pubs(ids, exclude=auto | {lb.arxiv_id for lb in labels})
        random.Random(a.seed).shuffle(cands)
        print(f"{len(cands)} publication đủ điều kiện (bỏ {len(auto)} bài đã có nhãn tự động). Gợi ý:")
        for aid, n_ent, n_ref in cands[:15]:
            title = json.loads((config.CORPUS_ROOT / config.pub_key(aid) / "paper_meta.json")
                               .read_text(encoding="utf-8")).get("title", "")
            print(f"  {aid}  entry={n_ent:3}  ref_arXiv={n_ref:3}  {title[:80]}")
        print("Chọn 5 bài khác lĩnh vực nhau, rồi chạy lại với --pubs.")
        return 0

    if not a.pubs:
        ap.error("cần --pubs hoặc --suggest")
    pubs = [config.strip_version(p.strip()) for p in a.pubs.split(",") if p.strip()]
    if len(pubs) != 5:
        print(f"Lưu ý: schema_m3 mục 4 quy định 5 publication gán tay mỗi người, đang có {len(pubs)}.")
    clash = _auto_pubs(a.mssv) & set(pubs)
    if clash:
        print(f"Lưu ý: {sorted(clash)} đang có trong labels/auto/{a.mssv}.jsonl. Sau khi gán tay xong "
              f"phải chạy lại matcher với --exclude {out_path.relative_to(ROOT)} --overwrite.")

    for aid in pubs:
        if not label_publication(aid, a.mssv, out_path, labels):
            print(f"\nĐã lưu {len(labels)} nhãn vào {out_path}. Chạy lại cùng lệnh để làm tiếp.")
            return 0

    print(f"\nXong. {len(labels)} nhãn trong {out_path}:")
    for aid in pubs:
        print(f"  {aid}: {count_matched(labels, aid)} nhãn khác null")
    return 0


if __name__ == "__main__":
    sys.exit(main())
