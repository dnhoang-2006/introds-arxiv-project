"""Orchestrator của Milestone 2 — ghép 4 module theo đúng thứ tự đã chốt.

    python src/parse_main.py --ids ids/24120053.txt --limit 20
    python src/parse_main.py --ids ids/24120053.txt --overwrite
    python src/parse_main.py --ids ids/24120053.txt --workers 2   # tuần 2, Minh Thư

Chạy lại được từ giữa chừng (docs/schema_m2.md mục 7): publication nào đã có
parsed/<pub_key>/elements.jsonl thì bỏ qua và ghi `skipped` vào logs/parse.csv,
trừ khi có --overwrite. Đứt giữa chừng thì chạy lại đúng lệnh cũ là đi tiếp.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import config
from parser.bib import collect_bib
from parser.bib_dedup import unify_publication
from parser.elements import build_store
# gather_detail = gather() + status/error_type, cần để tách "empty" khỏi "fail".
from parser.gather import gather, gather_detail, resolve_path, version_dirs  # noqa: F401
from parser.hierarchy import Node, build_tree
from parser.normalize import clean_latex, normalize_math
from tex_prescan import (
    INCLUDE_PATTERN,
    INPUT_BARE_PATTERN,
    clean_tex_comments,
    read_text_safe,
)

# Định dạng ở docs/schema_m2.md mục 8 — đổi ở đây thì phải đổi cả ở đó.
PARSE_LOG_FIELDS = (
    "arxiv_id", "version", "n_elements", "n_sentences", "n_formulas",
    "n_figures", "max_depth", "seconds", "status", "error_type",
)

# File đánh dấu "publication này đã xong". Được ghi CUỐI CÙNG, xem write_outputs().
DONE_MARKER = "elements.jsonl"
#: Đủ ba file này mới coi là xong. Chỉ xét DONE_MARKER thì bài có elements.jsonl
#: nhưng mất hierarchy/bibtex (xoá tay, copy thiếu) sẽ không bao giờ được parse lại,
#: trong khi export_hf bỏ qua chính bài đó vì thiếu file.
OUTPUT_FILES = ("hierarchy.jsonl", "bibtex.jsonl", DONE_MARKER)


# --------------------------------------------------------------------------- #
# Tuần 2
# --------------------------------------------------------------------------- #
def parse_one(arxiv_id: str, out_root: Path) -> list[dict[str, Any]]:
    """Xử lý trọn một publication theo đúng thứ tự ở schema_m2.md mục 5.

        1. gather()                       — đường biên dịch từng version
        2. clean_latex + normalize_math   — chuẩn hoá
        3-4. unify_publication()          — dựng rename_map rồi đổi \\cite
        5. build_tree + build_store       — dựng cây và BĂM (chỉ băm ở đây)
        6. write_outputs()                — ghi 3 bảng, elements.jsonl ghi sau cùng

    Việc bỏ qua bài đã xong do run() lo, hàm này không cần kiểm tra lại.

    Returns:
        Danh sách dòng log, MỘT dòng cho mỗi version, khoá theo PARSE_LOG_FIELDS
        (thiếu khoá nào thì run() điền 0 / rỗng; có `arxiv_id` cũng được, run() ghi
        đè bằng ID của chính nó). Version rỗng: status="empty".

    Lỗi khoanh vùng:
      - Bước theo TỪNG version (đọc, chuẩn hoá, collect_bib, build_tree) lỗi -> chỉ
        version đó có status="fail" và bị loại khỏi các bước sau; version khác chạy tiếp.
      - Bước theo CẢ BÀI (unify_publication, build_store, write_outputs) lỗi -> ném ra,
        run() ghi một dòng fail cho cả bài.
      - NotImplementedError luôn ném ra: đó là code chưa viết, không phải lỗi dữ liệu.
      - Không version nào dùng được (mọi version đều fail) -> KHÔNG ghi file, để lần
        chạy sau thử lại thay vì đánh dấu "đã xong" bằng một elements.jsonl rỗng.

    `seconds` của mỗi version chỉ tính các bước riêng của version đó; các bước chung
    (unify_publication, build_store, ghi file) không chia vào version nào.
    """
    pub_key = config.pub_key(arxiv_id)
    rows: dict[int, dict[str, Any]] = {}       # dòng log theo version
    secs: dict[int, float] = {}
    norm_text: dict[int, str] = {}
    bib_entries: dict[int, list[dict[str, Any]]] = {}
    empty: list[int] = []

    def fail(v: int, exc: Exception) -> None:
        rows[v] = {"version": v, "status": "fail", "error_type": type(exc).__name__}

    # Bước 1: các thư mục version của bài này.
    for vdir in version_dirs(config.pub_dir(arxiv_id)):
        v = int(vdir.name[1:])
        t0 = time.perf_counter()
        try:
            # Bước 2: đường biên dịch, đọc và nối .tex theo thứ tự biên dịch.
            g = gather_detail(vdir, arxiv_id)
            if g.status == "empty":
                # Không bỏ qua: đề yêu cầu ghi nhận cả version rỗng (schema mục 6).
                empty.append(v)
                rows[v] = {"version": v, "status": "empty", "error_type": "",
                           "n_elements": 1}
                continue
            if not g.compile_path:
                rows[v] = {"version": v, "status": "fail",
                           "error_type": g.error_type or "no_root"}
                continue
            raw_text = read_compile_path(g.compile_path, vdir)
            # Bước 3: chuẩn hoá — ĐÚNG thứ tự clean_latex rồi mới normalize_math.
            norm_text[v] = normalize_math(clean_latex(raw_text))
            # Bước 4: reference của version này. Gắn version để merge_group chọn
            # key chuẩn tất định ("version nhỏ nhất trước").
            bib_entries[v] = [{**e, "version": e.get("version", v)}
                              for e in collect_bib(vdir)]
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 — lỗi một version không giết cả bài
            norm_text.pop(v, None)
            bib_entries.pop(v, None)
            fail(v, exc)
        finally:
            secs[v] = time.perf_counter() - t0

    # Bước 5: hai lượt, trên MỌI version cùng lúc — rename_map cần thấy hết các version.
    renamed_text: dict[int, str] = {}
    bibtex_rows: list[dict[str, Any]] = []
    if norm_text:
        renamed_text, bibtex_rows, _ = unify_publication(norm_text, bib_entries)

    # Bước 6: dựng cây từng version.
    trees: dict[int, Node] = {v: Node("document", "") for v in empty}
    for v in sorted(norm_text):
        t0 = time.perf_counter()
        try:
            # ⚠️ PHẢI là renamed_text, KHÔNG phải norm_text. Hai biến chỉ khác nhau ở
            # citation key nên truyền nhầm vẫn chạy trơn, không báo lỗi gì; triệu chứng
            # duy nhất là dedup_ratio ~ 0 ở bài nhiều version (cùng một câu ở v1/v2 trỏ
            # \cite tới hai key khác nhau -> băm ra hai element_id).
            # Cũng nhờ vậy mà `content` trong elements chính là chuỗi đã đem đi băm
            # (build_store băm và lưu cùng một node.content) — validation có kiểm.
            trees[v] = build_tree(renamed_text[v])
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001
            fail(v, exc)
        finally:
            secs[v] += time.perf_counter() - t0

    if not trees:
        # Mọi version đều fail: không ghi gì để lần sau còn thử lại.
        return [_with_seconds(rows[v], secs.get(v, 0.0)) for v in sorted(rows)]

    # Bước 7: băm + dedup xuyên version.
    elements, hierarchy = build_store(pub_key, arxiv_id, trees)

    # Bước 8: ghi 3 bảng, elements.jsonl sau cùng (write_outputs lo).
    write_outputs(pub_key, out_root, elements, hierarchy,
                  [_bibtex_row(arxiv_id, r) for r in bibtex_rows])

    kind_of = {e["element_id"]: e["kind"] for e in elements}
    per_version: dict[int, set[str]] = {v: set() for v in trees}
    for h in hierarchy:
        per_version[h["version"]].add(h["element_id"])
    for v, tree in trees.items():
        if v in empty:
            continue
        ids = per_version[v]
        kinds = [kind_of[i] for i in ids]
        rows[v] = {
            "version": v, "status": "ok", "error_type": "",
            "n_elements": len(ids) + 1,                  # + node gốc
            "n_sentences": kinds.count("sentence"),
            "n_formulas": kinds.count("formula"),
            "n_figures": kinds.count("figure"),
            "max_depth": _depth(tree),
        }
    return [_with_seconds(rows[v], secs.get(v, 0.0)) for v in sorted(rows)]


# Cột của bảng bibtex — schema_m2.md mục 1.3.
BIBTEX_FIELDS = ("arxiv_id", "citation_key", "entry_type", "title", "authors",
                 "year", "doi", "journal", "url")


def _bibtex_row(arxiv_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Chiếu entry về đúng các cột của schema mục 1.3.

    ⚠️ Entry của bib.py có khoá `arxiv_id` là arXiv ID của BÀI ĐƯỢC TRÍCH DẪN, còn cột
    `arxiv_id` của bảng bibtex là bài ĐANG PARSE — nên luôn ghi đè. Các khoá phụ
    (raw, version...) bị bỏ.
    """
    row = {f: entry.get(f) for f in BIBTEX_FIELDS}
    row["arxiv_id"] = arxiv_id
    return row


def _with_seconds(row: dict[str, Any], seconds: float) -> dict[str, Any]:
    return {**row, "seconds": seconds}


def _depth(node: Node) -> int:
    """Độ sâu của cây, gốc = 0. Duyệt bằng stack để không chạm giới hạn đệ quy."""
    best = 0
    stack = [(node, 0)]
    while stack:
        n, d = stack.pop()
        best = max(best, d)
        stack.extend((c, d + 1) for c in n.children)
    return best


def read_compile_path(compile_path: list[Path], vdir: Path) -> str:
    """Đọc root rồi THAY từng \\input/\\include bằng nội dung file con, đệ quy.

    Không được nối các file liên tiếp: nội dung file con sẽ rơi ra SAU
    \\end{document} của root và bị extract_body() cắt mất, hoặc sai thứ tự section.
    Chỉ thay những file nằm trong đường biên dịch gather đã chọn; mỗi file thay đúng
    một lần (chống vòng lặp, giống gather). Comment được bỏ trước để \\input bị comment
    không bị thay — cùng quy ước với gather.
    """
    root = compile_path[0]
    allowed = set(compile_path)
    used: set[Path] = {root}

    def expand(path: Path) -> str:
        text = clean_tex_comments(read_text_safe(path))

        def repl(m: re.Match[str]) -> str:
            raw = m.group(1) or m.group(2)               # dạng {…} hoặc dạng trần
            child = resolve_path(path.parent, raw, vdir, root.parent)
            if child is None or child not in allowed or child in used:
                return " "
            used.add(child)
            return "\n" + expand(child) + "\n"

        return _INCLUDE_ANY.sub(repl, text)

    return expand(root)


# \input{a}, \include{a}, \subfile{a} và \input a — cùng hai mẫu gather dùng.
_INCLUDE_ANY = re.compile(INCLUDE_PATTERN.pattern + "|" + INPUT_BARE_PATTERN.pattern)


# --------------------------------------------------------------------------- #
# Chạy lại được từ giữa chừng
# --------------------------------------------------------------------------- #
def already_done(pub_key: str, out_root: Path) -> bool:
    pub_dir = out_root / pub_key
    return all((pub_dir / name).is_file() for name in OUTPUT_FILES)


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Ghi ra file tạm rồi đổi tên — đứt giữa chừng thì file đích không tồn tại.

    os.replace là thao tác nguyên tử trên cùng một ổ đĩa (cả Windows lẫn POSIX).
    """
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write_outputs(
    pub_key: str,
    out_root: Path,
    elements: list[dict[str, Any]],
    hierarchy: list[dict[str, Any]],
    bibtex: list[dict[str, Any]],
) -> Path:
    """Ghi 3 bảng của một publication vào parsed/<pub_key>/.

    ⚠️ elements.jsonl là file cuối mà already_done() cần thấy, nên nó được ghi
    SAU CÙNG và ghi nguyên tử. Nếu ghi nó trước hoặc ghi thẳng, mất điện lúc đang
    ghi dở sẽ để lại một elements.jsonl cụt — lần chạy sau tưởng bài đã xong và bỏ
    qua, đúng kiểu lỗi "archive cụt đuôi" đã gặp ở M1.
    """
    pub_dir = out_root / pub_key
    pub_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(pub_dir / "hierarchy.jsonl", hierarchy)
    _write_jsonl_atomic(pub_dir / "bibtex.jsonl", bibtex)
    _write_jsonl_atomic(pub_dir / DONE_MARKER, elements)
    return pub_dir


def _log_row(arxiv_id: str, fields: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    """Dựng một dòng parse.csv đủ cột. Nhận dict (không bung **) để dòng do parse_one
    trả về có chứa `arxiv_id` cũng không đụng tham số — arxiv_id của run() luôn thắng.
    Khoá lạ bị bỏ qua thay vì làm DictWriter ném lỗi."""
    row: dict[str, Any] = {f: 0 for f in PARSE_LOG_FIELDS}
    row.update(version="", status="ok", error_type="")
    merged = {**(fields or {}), **kw}
    row.update({k: v for k, v in merged.items() if k in row})
    row["arxiv_id"] = arxiv_id
    if isinstance(row["seconds"], (int, float)):
        row["seconds"] = f"{row['seconds']:.2f}"
    return row


def _timed_call(
    parse_fn: Callable[[str, Path], list[dict[str, Any]]],
    arxiv_id: str,
    out_root: Path,
) -> tuple[Any, float, str | None, bool]:
    """Chạy parse_fn trong TIẾN TRÌNH CON và bắt mọi lỗi tại chỗ.

    Trả (kết quả, số giây, tên lớp lỗi hoặc None, có phải NotImplementedError không).
    Không ném lỗi qua ranh giới tiến trình: một số lớp lỗi không pickle được, và
    tiến trình chính chỉ cần TÊN lớp lỗi để ghi error_type.
    """
    t0 = time.perf_counter()
    try:
        result = parse_fn(arxiv_id, out_root)
        return result, time.perf_counter() - t0, None, False
    except NotImplementedError:
        return None, time.perf_counter() - t0, "NotImplementedError", True
    except Exception as exc:  # noqa: BLE001
        return None, time.perf_counter() - t0, type(exc).__name__, False


def run(
    ids: list[str],
    out_root: Path,
    overwrite: bool = False,
    verbose: bool = True,
    log_path: Path | None = None,
    parse_fn: Callable[[str, Path], list[dict[str, Any]]] | None = None,
    workers: int = 1,
) -> dict[str, int]:
    """Parse lần lượt từng publication, ghi logs/parse.csv, trả về số đếm theo status.

    - Đã có đủ 3 file (xem OUTPUT_FILES) và không --overwrite -> một dòng `skipped` (version để
      rỗng vì không mở lại bài đó), không đụng tới file cũ.
    - parse_fn ném lỗi -> một dòng `fail`, error_type = tên lớp lỗi, chạy tiếp bài sau.
      Riêng NotImplementedError được ném lại: đó là code chưa viết, không phải lỗi dữ liệu.
    - Log được flush sau mỗi bài để đứt giữa chừng vẫn còn.

    parse_fn mặc định là parse_one; tham số này để test thay bằng hàm giả.

    workers > 1 — parse song song bằng ProcessPoolExecutor:
      - Lọc already_done() TRƯỚC khi đưa vào pool, nên cơ chế chạy lại giữ nguyên.
      - Chỉ parse_fn chạy ở tiến trình con; mỗi bài ghi vào parsed/<pub_key>/ riêng
        nên các tiến trình không giẫm file nhau.
      - parse.csv chỉ do TIẾN TRÌNH CHÍNH ghi, khi từng bài xong (as_completed),
        nên các dòng không bao giờ lẫn vào nhau. Thứ tự dòng là thứ tự XONG, không
        phải thứ tự trong file ID — so sánh với workers=1 thì sort trước.
      - parse_fn phải pickle được (hàm cấp module, không lambda/closure), vì tiến
        trình con nhận nó qua pickle. Windows và Colab đều chạy được.
    """
    if workers < 1:
        raise ValueError("workers phải >= 1")
    parse_fn = parse_fn or parse_one
    log_path = log_path or (config.LOGS_ROOT / "parse.csv")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    counts = {"ok": 0, "empty": 0, "fail": 0, "skipped": 0}
    new_file = not log_path.exists() or log_path.stat().st_size == 0
    total = len(ids)

    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PARSE_LOG_FIELDS)
        if new_file:
            writer.writeheader()

        def record(i: int, arxiv_id: str, result: Any, secs: float, err: str | None) -> None:
            """Ghi log của MỘT bài — dùng chung cho cả tuần tự lẫn song song."""
            if err is None:
                try:
                    # Dựng dòng log trong try: parse_fn trả sai dạng (None, thiếu
                    # khoá...) chỉ làm fail bài này, không giết cả mẻ.
                    rows = [_log_row(arxiv_id, r) for r in result]
                except Exception as exc:  # noqa: BLE001
                    err = type(exc).__name__
            if err is not None:
                writer.writerow(_log_row(arxiv_id, seconds=secs,
                                         status="fail", error_type=err))
                counts["fail"] += 1
                if verbose:
                    print(f"[{i}/{total}] {arxiv_id}  LỖI: {err}")
            else:
                for row in rows:
                    writer.writerow(row)
                    counts[row["status"]] = counts.get(row["status"], 0) + 1
                if verbose:
                    print(f"[{i}/{total}] {arxiv_id}  {len(rows)} version  {secs:5.2f}s")
            fh.flush()

        # 1. Lọc bài đã xong ở tiến trình chính, trước khi chia việc.
        todo: list[str] = []
        for i, raw_id in enumerate(ids, 1):
            arxiv_id = config.strip_version(raw_id)
            if already_done(config.pub_key(arxiv_id), out_root) and not overwrite:
                writer.writerow(_log_row(arxiv_id, status="skipped"))
                counts["skipped"] += 1
                if verbose:
                    print(f"[{i}/{total}] {arxiv_id}  bỏ qua (đã có đủ output)")
                fh.flush()
            else:
                todo.append(arxiv_id)

        # 2a. Tuần tự — mặc định, kết quả tất định.
        if workers == 1:
            for i, arxiv_id in enumerate(todo, 1):
                result, secs, err, not_impl = _timed_call(parse_fn, arxiv_id, out_root)
                if not_impl:
                    raise NotImplementedError
                record(i, arxiv_id, result, secs, err)
            return counts

        # 2b. Song song.
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_timed_call, parse_fn, a, out_root): a for a in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                arxiv_id = futures[fut]
                try:
                    result, secs, err, not_impl = fut.result()
                except Exception as exc:  # noqa: BLE001 — lỗi pickle / tiến trình con chết
                    result, secs, err, not_impl = None, 0.0, type(exc).__name__, False
                if not_impl:
                    for f in futures:
                        f.cancel()
                    raise NotImplementedError
                record(i, arxiv_id, result, secs, err)

    return counts


def main() -> None:
    p = argparse.ArgumentParser(description="Hierarchical parser cho Milestone 2")
    p.add_argument("--ids", required=True, help="File ID (1 ID/dòng) hoặc danh sách ngăn bởi dấu phẩy")
    p.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N publication đầu (để test)")
    p.add_argument("--overwrite", action="store_true", help="Parse lại cả publication đã xong")
    p.add_argument("--workers", type=int, default=1,
                   help="Số tiến trình song song (mặc định 1; >1 do Minh Thư viết ở tuần 2)")
    p.add_argument("--out", type=Path, default=config.PROJECT_ROOT / "parsed")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    # Bỏ version và ID trùng giống src/main.py — một publication chỉ parse một lần.
    ids = list(dict.fromkeys(config.strip_version(i) for i in config.load_ids(args.ids)))
    ids = ids[:args.limit] if args.limit else ids
    if not ids:
        sys.exit("Không đọc được ID nào.")

    started = time.perf_counter()
    counts = run(ids, args.out, overwrite=args.overwrite, verbose=not args.quiet,
                 workers=args.workers)
    print(f"\n{'=' * 60}")
    print(f"Publication     : {len(ids)}")
    print("Version theo status: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Thời gian       : {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
    