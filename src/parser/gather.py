"""Multi-file Gathering — tìm đường biên dịch thật của một version.

Chỉ parse những file thực sự được biên dịch vào PDF cuối, bỏ qua file thừa
nằm lẫn trong thư mục source. Theo \\input và \\include ĐỆ QUY, coi lệnh bị comment là
văn bản thường.

Chạy thử:
    python src/parser/gather.py --ids ids/24120144.txt --limit 20
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import config  # noqa: E402
from tex_prescan import (  # noqa: E402
    DOC_CLASS_PATTERN,
    INCLUDE_PATTERN,
    INPUT_BARE_PATTERN,
    clean_tex_comments,
    read_text_safe,
    score_root_candidate,
)

LOG_COLUMNS = [
    "arxiv_id", "version", "root_file", "n_files_path", "n_files_unused",
    "n_missing_includes", "seconds", "status", "error_type",
]

_VERSION_DIR = re.compile(r"^v(\d+)$")


@dataclass
class GatherResult:
    """Kết quả đầy đủ của một version (gather() chỉ trả 2 trường đầu)."""
    compile_path: list[Path] = field(default_factory=list)
    unused: list[Path] = field(default_factory=list)
    root: Path | None = None
    n_missing_includes: int = 0
    status: str = "ok"            # ok | fail | empty
    error_type: str = ""          # "" | no_root | empty_version | read_error


# Tiện ích
def _all_tex(vdir: Path) -> list[Path]:
    """Mọi file .tex trong version, đã resolve, sắp xếp ổn định."""
    return sorted(p.resolve() for p in vdir.rglob("*.tex") if p.is_file())


def ordered_includes(clean_text: str) -> list[str]:
    """Danh sách include theo ĐÚNG thứ tự xuất hiện trong file.

    Khác extract_includes() của prescan ở chỗ: prescan gom hết dạng {…} rồi mới tới
    dạng bare, nên \\input a / \\input{b} bị đảo thứ tự. Ở đây trộn theo vị trí.
    Không bỏ trùng: cùng một file include hai lần thì seen ở gather() lo.
    """
    hits = [(m.start(), m.group(1)) for m in INCLUDE_PATTERN.finditer(clean_text)]
    hits += [(m.start(), m.group(1)) for m in INPUT_BARE_PATTERN.finditer(clean_text)]
    hits.sort()
    out = []
    for _, raw in hits:
        raw = raw.strip().strip("\"'")
        if raw:
            out.append(raw)
    return out


def find_root(vdir: Path, arxiv_id: str = "") -> Path | None:
    """Chọn root file — CÙNG LUẬT với tex_prescan.prescan_version().

    Ứng viên = file .tex có \\documentclass/\\documentstyle ngoài comment.
    Một ứng viên -> lấy luôn. Nhiều ứng viên -> điểm cao nhất theo
    score_root_candidate(); hoà điểm thì lấy file đứng trước theo thứ tự tên.
    Giữ đúng luật này để root_file khớp với kết quả prescan của Duy.
    """
    candidates: list[str] = []
    has_inc: dict[str, bool] = {}
    for p in sorted(vdir.glob("**/*.tex")):
        rel = p.relative_to(vdir).as_posix()
        text = clean_tex_comments(read_text_safe(p))
        if DOC_CLASS_PATTERN.search(text):
            candidates.append(rel)
            has_inc[rel] = bool(ordered_includes(text))
    if not candidates:
        return None
    if len(candidates) == 1:
        best = candidates[0]
    else:
        best = max(candidates,
                   key=lambda c: score_root_candidate(c, has_inc[c], arxiv_id))
    return (vdir / best).resolve()


def resolve_path(base: Path, raw: str, vdir: Path,
                 root_dir: Path | None = None) -> Path | None:
    """Đổi tham số của \\input/\\include thành đường dẫn file thật.

    Thử theo thứ tự:
        1. tương đối với thư mục chứa root (đây là cách LaTeX thật làm:
           đường dẫn tính từ thư mục chạy pdflatex, tức chỗ đặt root)
        2. tương đối với thư mục của file cha (\\import, \\subfile làm kiểu này)
        3. tương đối với thư mục gốc version
    Với mỗi chỗ: thử nguyên tên trước, rồi thêm ".tex".

    Không dùng Path.with_suffix(): \\input{sec/intro.v2} sẽ bị đổi thành
    sec/intro.tex — sai file. LaTeX chỉ NỐI thêm .tex chứ không thay đuôi.

    Trả None nếu không thấy, hoặc nếu đường dẫn trỏ ra ngoài vdir
    (\\input{../../x} hay đường dẫn tuyệt đối) — không đọc file ngoài corpus.
    """
    raw = raw.strip().strip("\"'")
    if not raw:
        return None
    vroot = vdir.resolve()
    starts = []
    for d in (root_dir or vdir, base, vdir):
        if d not in starts:
            starts.append(d)
    for start in starts:
        p = Path(start) / raw
        for cand in (p, Path(str(p) + ".tex")):
            if cand.is_file():
                cand = cand.resolve()
                if cand == vroot or vroot in cand.parents:
                    return cand
    return None


# Hàm chính
def gather_detail(vdir: Path, arxiv_id: str = "") -> GatherResult:
    """Như gather() nhưng trả thêm root, số include hỏng, status, error_type."""
    vdir = Path(vdir)
    all_tex = _all_tex(vdir)

    # Ca 4: version rỗng (M1 ghi _EMPTY.json, hoặc thư mục không còn .tex nào)
    if (vdir / "_EMPTY.json").is_file() or not all_tex:
        return GatherResult(status="empty", error_type="empty_version")

    # Ca 3: không có root
    root = find_root(vdir, arxiv_id)
    if root is None:
        return GatherResult(unused=all_tex, status="fail", error_type="no_root")

    # Duyệt sâu trước (DFS preorder) = đúng thứ tự LaTeX đọc file:
    # root -> con thứ nhất -> cháu của con thứ nhất -> con thứ hai ...
    # (BFS với pop(0) sẽ cho root, con1, con2, cháu1 — sai thứ tự.)
    order: list[Path] = []
    seen: set[Path] = set()
    stack: list[Path] = [root]
    n_missing = 0
    while stack:
        f = stack.pop()
        if f in seen:
            continue                     # Ca 1: chống vòng lặp a -> b -> a
        seen.add(f)
        order.append(f)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return GatherResult(root=root, unused=all_tex,
                                status="fail", error_type="read_error")
        children = []
        for raw in ordered_includes(clean_tex_comments(text)):
            t = resolve_path(f.parent, raw, vdir, root.parent)
            if t is None:
                n_missing += 1           # Ca 2: file không tồn tại -> đếm, bỏ qua
            elif t not in seen:
                children.append(t)
        stack.extend(reversed(children))  # đảo để con đầu tiên được pop trước

    unused = [p for p in all_tex if p not in seen]
    return GatherResult(compile_path=order, unused=unused, root=root,
                        n_missing_includes=n_missing)


def gather(vdir: Path) -> tuple[list[Path], list[Path]]:
    """Trả về (đường biên dịch theo thứ tự, danh sách file thừa).

    compile_path rỗng nghĩa là không parse được (rỗng / không có root).
    Cần thêm thông tin (root, số include hỏng, lý do lỗi) thì gọi gather_detail().
    """
    r = gather_detail(vdir)
    return r.compile_path, r.unused


# Chạy hàng loạt + ghi log
def version_dirs(pub: Path) -> list[Path]:
    """Các thư mục v1, v2, ... sắp theo số (v10 đứng sau v9)."""
    if not pub.is_dir():
        return []
    vs = [d for d in pub.iterdir() if d.is_dir() and _VERSION_DIR.match(d.name)]
    return sorted(vs, key=lambda d: int(d.name[1:]))


def gather_row(arxiv_id: str, vdir: Path) -> dict:
    """Một dòng của logs/gather.csv theo docs/schema_m2.md mục 8."""
    t0 = time.perf_counter()
    r = gather_detail(vdir, arxiv_id)
    secs = time.perf_counter() - t0
    root_rel = r.root.relative_to(vdir.resolve()).as_posix() if r.root else ""
    return {
        "arxiv_id": arxiv_id,
        "version": int(vdir.name[1:]),
        "root_file": root_rel,
        "n_files_path": len(r.compile_path),
        "n_files_unused": len(r.unused),
        "n_missing_includes": r.n_missing_includes,
        "seconds": f"{secs:.2f}",
        "status": r.status,
        "error_type": r.error_type,
    }


def read_ids(spec: str) -> list[str]:
    """--ids nhận đường dẫn file (1 ID/dòng, # là comment) hoặc 'id1,id2'."""
    p = Path(spec)
    if p.is_file():
        lines = p.read_text(encoding="utf-8-sig").splitlines()
    else:
        lines = spec.split(",")
    ids = [config.strip_version(s.strip()) for s in lines]
    return [i for i in ids if i and not i.startswith("#")]


def run(ids: list[str], limit: int | None = None,
        log_path: Path | None = None, quiet: bool = False) -> list[dict]:
    """Chạy gather cho nhiều publication và ghi logs/gather.csv (ghi đè)."""
    if limit is not None:
        ids = ids[:limit]
    log_path = log_path or config.LOGS_ROOT / "gather.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    missing_pubs: list[str] = []
    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
        w.writeheader()
        for i, aid in enumerate(ids, 1):
            vds = version_dirs(config.pub_dir(aid))
            if not vds:
                missing_pubs.append(aid)
                continue
            for vdir in vds:
                row = gather_row(aid, vdir)
                w.writerow(row)
                rows.append(row)
            fh.flush()
            if not quiet and i % 200 == 0:
                print(f"  {i}/{len(ids)} publication")

    if not quiet:
        _print_summary(rows, missing_pubs, log_path)
    return rows


def _print_summary(rows: list[dict], missing_pubs: list[str], log_path: Path) -> None:
    from collections import Counter
    st = Counter(r["status"] for r in rows)
    et = Counter(r["error_type"] for r in rows if r["error_type"])
    used = sum(r["n_files_path"] for r in rows)
    unused = sum(r["n_files_unused"] for r in rows)
    miss = sum(r["n_missing_includes"] for r in rows)
    print(f"Versions: {len(rows)}  status={dict(st)}  error_type={dict(et)}")
    total = used + unused
    if total:
        print(f"File .tex: {used} trong đường biên dịch, {unused} thừa "
              f"({unused / total:.1%} là file thừa)")
    print(f"Include trỏ vào file không tồn tại: {miss}")
    if missing_pubs:
        print(f"⚠ {len(missing_pubs)} publication không có thư mục trong corpus, "
              f"vd: {missing_pubs[:3]}")
    print(f"Log: {log_path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Multi-file gathering cho Milestone 2")
    ap.add_argument("--ids", required=True, help="File ID (1 ID/dòng) hoặc 'id1,id2'")
    ap.add_argument("--limit", type=int, default=None, help="Chỉ chạy N publication đầu")
    ap.add_argument("--log", type=Path, default=None, help="Mặc định logs/gather.csv")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    run(read_ids(a.ids), limit=a.limit, log_path=a.log, quiet=a.quiet)


if __name__ == "__main__":
    main()