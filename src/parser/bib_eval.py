"""Đánh giá đối chứng (concordance) giữa .bib và \\bibitem trên 124 version,
sinh báo cáo thống kê cho Milestone 2, ghi logs/bib.csv và logs/bib_dedup.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import config
from parser.bib import collect_bib, parse_bibitem, read_bib_file, split_bibitems
from parser.bib_dedup import (
    _first_author_last_name,
    _norm_arxiv,
    _norm_doi,
    _norm_title,
    unify_publication_with_stats,
)

BIB_LOG_COLUMNS = [
    "arxiv_id",
    "version",
    "n_bibitem",
    "n_bibfile_entries",
    "seconds",
    "status",
    "error_type",
]

BIB_DEDUP_COLUMNS = [
    "arxiv_id",
    "n_before",
    "n_after",
    "n_cite_renamed",
    "seconds",
    "status",
    "error_type",
]


def _append_csv_rows(path: Path | str, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    """Ghi bổ sung (append-only) các dòng vào file CSV, giữ nguyên lịch sử lần chạy trước."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.is_file() and path.stat().st_size > 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def _read_version_tex(vdir: Path, arxiv_id: str, allow_fallback: bool = False) -> str:
    """Đọc toàn văn .tex của một version theo đúng đường biên dịch (compile path).

    Chỉ đọc các file thuộc compile path để tránh nuốt phải file mẫu/template thừa.
    Nếu version rỗng, trả về chuỗi rỗng.
    Nếu không tìm được root/compile path:
      - allow_fallback=True: fallback đọc an toàn các file .tex trong vdir.
      - allow_fallback=False: ném ValueError để báo lỗi và không làm lệch thống kê.
    """
    from parse_main import read_compile_path
    from parser.gather import gather_detail

    g = gather_detail(vdir, arxiv_id)
    if g.status == "empty":
        return ""
    if g.status == "ok" and g.compile_path:
        return read_compile_path(g.compile_path, vdir)

    if allow_fallback:
        chunks: list[str] = []
        for tf in sorted(vdir.rglob("*.tex")):
            if tf.is_file() and not tf.name.startswith("."):
                try:
                    chunks.append(tf.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
        return "\n\n".join(chunks)

    raise ValueError(f"gather_fail:{g.error_type or 'no_root'}")


def evaluate_concordance(
    prescan_csv: Path | str,
    corpus_root: Path | str,
    bib_logs_csv: Path | str | None = None,
    append: bool = True,
) -> dict[str, Any]:
    """So khớp kết quả giữa .bib và \\bibitem trên tập 124 version có cả 2 nguồn.

    Đo lường mức độ đồng thuận (Inter-source Concordance) trên các trường:
    title, first author surname, year, doi, arxiv_id trên tập các key giao nhau.
    Đồng thời ghi nhận logs/bib.csv theo đúng schema M2.
    """
    prescan_csv = Path(prescan_csv)
    corpus_root = Path(corpus_root)

    with open(prescan_csv, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("bib_style") == "both"]

    stats: dict[str, Any] = {
        "total_versions_surveyed": len(rows),
        "versions_evaluated": 0,
        "total_bib_entries": 0,
        "total_bibitem_entries": 0,
        "overlap_keys_count": 0,
        "title_exact_matches": 0,
        "title_soft_matches": 0,
        "title_both_present": 0,
        "title_bib_only": 0,
        "title_bibitem_only": 0,
        "title_neither": 0,
        "author_matches": 0,
        "author_both_present": 0,
        "year_matches": 0,
        "year_both_present": 0,
        "doi_matches": 0,
        "doi_both_present": 0,
        "arxiv_matches": 0,
        "arxiv_both_present": 0,
        "total_failed_bib_blocks": 0,
        "sensitivity_bib_args": 0,
        "sensitivity_unresolved_args": 0,
        "sensitivity_resolved_files": 0,
        "sensitivity_total_disk_files": 0,
        "sensitivity_unreferenced_files": 0,
        "bib_log_rows": [],
    }

    bib_log_rows: list[dict[str, Any]] = []

    COMMENT_PAT = re.compile(r"(?<!\\)%.*$")
    BIB_CMD_PAT = re.compile(r"\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")

    all_disk_bib_files: set[Path] = set()
    distinct_resolved_bib_files: set[Path] = set()
    unresolved_bib_args: list[tuple[str, str, str, str]] = []
    total_bib_args = 0

    for r in rows:
        aid = r["arxiv_id"]
        pk = config.pub_key(aid)
        ver_str = r["version"]
        v_num = int(ver_str[1:]) if ver_str.startswith("v") and ver_str[1:].isdigit() else (
            int(ver_str) if ver_str.isdigit() else 1
        )
        vdir = corpus_root / pk / ver_str
        if not vdir.is_dir():
            continue

        stats["versions_evaluated"] += 1
        t_v0 = time.perf_counter()
        v_status = "ok"
        v_error = ""
        bib_entries: list[dict[str, Any]] = []
        tex_entries: list[dict[str, Any]] = []
        failed_blocks: list[Any] = []

        try:
            # Thu thập file .bib trên đĩa
            for bf in sorted(vdir.rglob("*.bib")):
                if bf.is_file() and not bf.name.startswith("."):
                    all_disk_bib_files.add(bf.resolve())
                    try:
                        bib_entries.extend(
                            read_bib_file(bf, lenient=True, failed_blocks_out=failed_blocks)
                        )
                    except Exception as b_exc:  # noqa: BLE001
                        v_error = type(b_exc).__name__
                        continue

            # 2. Đọc entries từ thebibliography trong các file .tex thuộc compile path
            from parser.gather import gather_detail

            g = gather_detail(vdir, aid)
            compile_tex_files: list[Path] = []
            if g.status == "ok" and g.compile_path:
                compile_tex_files = g.compile_path
            elif g.status == "empty":
                compile_tex_files = []
            else:
                # Không tìm được compile path hợp lệ -> Đánh dấu version lỗi, không fallback quét toàn bộ *.tex
                v_status = "fail"
                v_error = f"no_compile_path:{g.error_type or 'no_root'}"
                compile_tex_files = []

            for tf in compile_tex_files:
                try:
                    tex = tf.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                # Quét kiểm tra độ nhạy lệnh \bibliography và \addbibresource
                clean_lines = [COMMENT_PAT.sub("", line) for line in tex.splitlines()]
                clean_txt = "\n".join(clean_lines)
                for m_cmd in BIB_CMD_PAT.finditer(clean_txt):
                    args_str = m_cmd.group(1).strip()
                    parts = [p.strip() for p in args_str.split(",") if p.strip()]
                    for p in parts:
                        total_bib_args += 1
                        candidates = [
                            tf.parent / p,
                            tf.parent / f"{p}.bib",
                            vdir / p,
                            vdir / f"{p}.bib",
                        ]
                        found = None
                        for c in candidates:
                            if c.is_file():
                                found = c.resolve()
                                break
                        if found:
                            distinct_resolved_bib_files.add(found)
                        else:
                            unresolved_bib_args.append((aid, ver_str, tf.name, p))

                if r"\begin{thebibliography}" in tex:
                    for k, raw in split_bibitems(tex):
                        tex_entries.append(parse_bibitem(k, raw))

            if failed_blocks or v_error:
                v_status = "fail"
                if not v_error:
                    v_error = f"bib_syntax_error:{len(failed_blocks)}"
                elif failed_blocks:
                    v_error = f"{v_error};bib_syntax_error:{len(failed_blocks)}"
            elif not bib_entries and not tex_entries:
                v_status = "empty"
                v_error = ""
            else:
                v_status = "ok"
                v_error = ""
        except Exception as exc:  # noqa: BLE001
            v_status = "fail"
            v_error = type(exc).__name__

        elapsed = time.perf_counter() - t_v0

        stats["total_failed_bib_blocks"] += len(failed_blocks)

        bib_log_rows.append(
            {
                "arxiv_id": aid,
                "version": v_num,
                "n_bibitem": len(tex_entries),
                "n_bibfile_entries": len(bib_entries),
                "seconds": round(elapsed, 2),
                "status": v_status,
                "error_type": v_error,
            }
        )

        stats["total_bib_entries"] += len(bib_entries)
        stats["total_bibitem_entries"] += len(tex_entries)

        # Ghép cặp theo citation_key
        bib_by_key = {e["citation_key"]: e for e in bib_entries if e.get("citation_key")}
        tex_by_key = {e["citation_key"]: e for e in tex_entries if e.get("citation_key")}

        common_keys = set(bib_by_key.keys()) & set(tex_by_key.keys())
        stats["overlap_keys_count"] += len(common_keys)

        for k in common_keys:
            b = bib_by_key[k]
            t = tex_by_key[k]

            # Title
            tb = _norm_title(b.get("title"))
            tt = _norm_title(t.get("title"))
            if tb and tt:
                stats["title_both_present"] += 1
                if tb == tt:
                    stats["title_exact_matches"] += 1
                    stats["title_soft_matches"] += 1
                elif tb in tt or tt in tb:
                    stats["title_soft_matches"] += 1
            elif tb and not tt:
                stats["title_bib_only"] += 1
            elif not tb and tt:
                stats["title_bibitem_only"] += 1
            else:
                stats["title_neither"] += 1

            # First author surname
            ab = _first_author_last_name(b.get("authors"))
            at = _first_author_last_name(t.get("authors"))
            if ab and at:
                stats["author_both_present"] += 1
                if ab.lower() == at.lower():
                    stats["author_matches"] += 1

            # Year
            yb = b.get("year")
            yt = t.get("year")
            if yb and yt:
                stats["year_both_present"] += 1
                if yb == yt:
                    stats["year_matches"] += 1

            # DOI
            db = _norm_doi(b.get("doi"))
            dt = _norm_doi(t.get("doi"))
            if db and dt:
                stats["doi_both_present"] += 1
                if db == dt:
                    stats["doi_matches"] += 1

            # arXiv ID
            arb = _norm_arxiv(b.get("arxiv_id"))
            art = _norm_arxiv(t.get("arxiv_id"))
            if arb and art:
                stats["arxiv_both_present"] += 1
                if arb == art:
                    stats["arxiv_matches"] += 1

    stats["bib_log_rows"] = bib_log_rows
    stats["sensitivity_bib_args"] = total_bib_args
    stats["sensitivity_unresolved_args"] = len(unresolved_bib_args)
    stats["sensitivity_resolved_files"] = len(distinct_resolved_bib_files)
    stats["sensitivity_total_disk_files"] = len(all_disk_bib_files)
    stats["sensitivity_unreferenced_files"] = max(
        len(all_disk_bib_files) - len(distinct_resolved_bib_files), 0
    )

    if bib_logs_csv is not None:
        if append:
            _append_csv_rows(bib_logs_csv, BIB_LOG_COLUMNS, bib_log_rows)
        else:
            bib_logs_path = Path(bib_logs_csv)
            bib_logs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(bib_logs_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=BIB_LOG_COLUMNS)
                writer.writeheader()
                writer.writerows(bib_log_rows)

    return stats


def generate_concordance_markdown(stats: dict[str, Any], out_path: Path | str) -> str:
    """Sinh báo cáo Markdown về mức độ khớp giữa hai nguồn reference."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_pairs = stats.get("overlap_keys_count", 0)

    # Tiêu đề: đo cả trên cặp cả 2 cùng có lẫn trên toàn bộ n_pairs
    t_both = stats.get("title_both_present", 0) or n_pairs
    t_exact_pct = (stats["title_exact_matches"] / t_both * 100) if t_both else 0.0
    t_soft_pct = (stats["title_soft_matches"] / t_both * 100) if t_both else 0.0
    t_exact_tot_pct = (stats["title_exact_matches"] / n_pairs * 100) if n_pairs else 0.0
    t_soft_tot_pct = (stats["title_soft_matches"] / n_pairs * 100) if n_pairs else 0.0
    soft_only = max(
        stats.get("title_soft_matches", 0) - stats.get("title_exact_matches", 0),
        0,
    )

    # Họ tác giả
    a_both = stats.get("author_both_present", 0) or n_pairs
    a_pct = (stats["author_matches"] / a_both * 100) if a_both else 0.0
    a_tot_pct = (stats["author_matches"] / n_pairs * 100) if n_pairs else 0.0

    y_both = stats.get("year_both_present", 0)
    y_pct = (stats["year_matches"] / y_both * 100) if y_both else 0.0

    d_both = stats.get("doi_both_present", 0)
    d_pct = (stats["doi_matches"] / d_both * 100) if d_both else 0.0

    ar_both = stats.get("arxiv_both_present", 0)
    ar_pct = (stats["arxiv_matches"] / ar_both * 100) if ar_both else 0.0

    v_eval = stats.get("versions_evaluated", 0)
    avg_bib = (stats.get("total_bib_entries", 0) / v_eval) if v_eval else 0.0
    avg_bibitem = (stats.get("total_bibitem_entries", 0) / v_eval) if v_eval else 0.0
    tot_surveyed = stats.get("total_versions_surveyed", 0)
    tot_bib = stats.get("total_bib_entries", 0)
    tot_bibitem = stats.get("total_bibitem_entries", 0)
    cov_pct = (v_eval / tot_surveyed * 100) if tot_surveyed else 0.0
    cov_note = f"Đạt 100% ({v_eval}/{tot_surveyed})" if cov_pct >= 99.999 else f"Đạt {cov_pct:.1f}% ({v_eval}/{tot_surveyed})"

    bib_log_rows = stats.get("bib_log_rows", [])
    have_both_rows = [
        r for r in bib_log_rows
        if int(r.get("n_bibitem", 0)) > 0 and int(r.get("n_bibfile_entries", 0)) > 0
    ]
    actual_both_versions = len(have_both_rows) if have_both_rows else v_eval
    actual_both_bib = sum(int(r.get("n_bibfile_entries", 0)) for r in have_both_rows) if have_both_rows else tot_bib
    actual_both_bibitem = sum(int(r.get("n_bibitem", 0)) for r in have_both_rows) if have_both_rows else tot_bibitem
    only_bib_rows = [
        r for r in bib_log_rows
        if int(r.get("n_bibitem", 0)) == 0 and int(r.get("n_bibfile_entries", 0)) > 0
    ]
    n_only_bib = len(only_bib_rows)
    bib_in_only_bib = sum(int(r.get("n_bibfile_entries", 0)) for r in only_bib_rows)

    syntax_error_versions = sum(
        "bib_syntax_error:" in str(row.get("error_type", ""))
        for row in bib_log_rows
    )
    failed_bib_blocks = stats.get("total_failed_bib_blocks", 0)

    t_bib_only = stats.get("title_bib_only", 0)
    t_bibitem_only = stats.get("title_bibitem_only", 0)
    t_neither = stats.get("title_neither", 0)

    sens_bib_args = stats.get("sensitivity_bib_args", 0)
    sens_unres_args = stats.get("sensitivity_unresolved_args", 0)
    sens_res_files = stats.get("sensitivity_resolved_files", 0)
    sens_total_disk = stats.get("sensitivity_total_disk_files", 0)
    sens_unref_files = stats.get("sensitivity_unreferenced_files", 0)

    scope_extra_rows = ""
    if bib_log_rows and actual_both_versions < v_eval:
        scope_extra_rows = f"""| Version khảo sát có cả 2 nguồn (.bib trên đĩa và \\bibitem trong compile path) | {actual_both_versions} | {n_only_bib} version còn lại thuần `.bib` (prescan bắt nhầm template), {v_eval - actual_both_versions - n_only_bib} version `.bib` rỗng |
| Entry từ file `.bib` (trong {actual_both_versions} version đối chứng) | {actual_both_bib:,} | Trung bình ~{(actual_both_bib / actual_both_versions):.1f} entry/version (ngoài ra có {bib_in_only_bib:,} entry thuộc {n_only_bib} version thuần `.bib`) |
| Entry từ `\\bibitem` (trong {actual_both_versions} version đối chứng) | {actual_both_bibitem:,} | Trung bình ~{(actual_both_bibitem / actual_both_versions):.1f} entry/version (tổng cộng 124 version là {tot_bibitem:,}) |
"""

    no_title_count = max(n_pairs - t_both, 0)
    no_title_pct = (no_title_count / n_pairs * 100) if n_pairs else 0.0

    md = f"""# Đối chiếu reference từ `.bib` và `\\bibitem`

Bộ dữ liệu gồm {tot_surveyed} version được prescan với `bib_style == "both"` trong dải 2503. Báo cáo ghép entry theo `citation_key`.

---

## 1. Phạm vi dữ liệu

| Chỉ số | Số lượng | Ghi chú |
| :--- | :--- | :--- |
| Version được khảo sát | {tot_surveyed} | `prescan_versions.csv`, nhãn `both` |
| Version có thư mục trên đĩa | {v_eval} | {cov_note} |
{scope_extra_rows}| Entry từ file `.bib` (toàn bộ khảo sát) | {tot_bib:,} | Trung bình {avg_bib:.1f} entry/version đã đánh giá |
| Entry từ `\\bibitem` (toàn bộ khảo sát) | {tot_bibitem:,} | Trung bình {avg_bibitem:.1f} entry/version đã đánh giá |
| Cặp entry cùng `citation_key` | {n_pairs:,} | Dùng để tính mức độ khớp đối ứng |

---

## 2. Mức độ khớp theo trường

Mỗi cặp gồm hai entry có cùng `citation_key`.
- **Mẫu số (cả 2 có trường)**: Chỉ xét các cặp mà cả nguồn `.bib` và `\\bibitem` đều có dữ liệu trường tương ứng.
- **Tỷ lệ / Tổng cặp**: Tỷ lệ khớp tính trên toàn bộ {n_pairs:,} cặp đối ứng (độ phủ thực tế trên toàn tập).

| Trường | Số cặp khớp | Mẫu số (Cả 2 có) | Tỷ lệ / Cặp có trường | Tỷ lệ / Tổng {n_pairs:,} cặp | Ghi chú kỹ thuật |
| :--- | :--- | :--- | :--- | :--- | :--- |
| DOI (`doi`) | {stats.get('doi_matches', 0):,} | {d_both:,} | {d_pct:.2f}% | {(stats.get('doi_matches', 0) / n_pairs * 100 if n_pairs else 0):.2f}% | {d_both:,} cặp có DOI ở cả 2 nguồn |
| arXiv ID (`arxiv_id`) | {stats.get('arxiv_matches', 0):,} | {ar_both:,} | {ar_pct:.2f}% | {(stats.get('arxiv_matches', 0) / n_pairs * 100 if n_pairs else 0):.2f}% | {ar_both:,} cặp có arXiv ID ở cả 2 nguồn |
| Năm (`year`) | {stats.get('year_matches', 0):,} | {y_both:,} | {y_pct:.2f}% | {(stats.get('year_matches', 0) / n_pairs * 100 if n_pairs else 0):.2f}% | {y_both:,} cặp có năm ở cả 2 nguồn |
| Họ tác giả đầu | {stats.get('author_matches', 0):,} | {a_both:,} | {a_pct:.2f}% | {a_tot_pct:.2f}% | {a_both:,} cặp có tác giả ở cả 2 nguồn |
| Tiêu đề exact | {stats.get('title_exact_matches', 0):,} | {t_both:,} | {t_exact_pct:.2f}% | {t_exact_tot_pct:.2f}% | {no_title_count:,} cặp thiếu tiêu đề ở ít nhất 1 nguồn ({no_title_pct:.1f}%) |
| Tiêu đề soft | {stats.get('title_soft_matches', 0):,} | {t_both:,} | {t_soft_pct:.2f}% | {t_soft_tot_pct:.2f}% | Khớp chính xác hoặc chứa chuỗi tiêu đề |

---

## 3. Cách đọc kết quả

Trong {n_pairs:,} cặp cùng `citation_key`:
- **Tiêu đề**: Có {t_both:,} cặp ({t_both / n_pairs * 100 if n_pairs else 0:.1f}%) mà bộ bóc tách (parser) trích xuất thành công tiêu đề ở cả hai nguồn (bao gồm macro `\\bibinfo{{title}}` với thuật toán cân bằng ngoặc lồng sâu). Trên tập {t_both:,} cặp này, tỷ lệ khớp exact đạt {t_exact_pct:.2f}% ({stats.get('title_exact_matches', 0):,} cặp) và soft đạt {t_soft_pct:.2f}% ({stats.get('title_soft_matches', 0):,} cặp, gồm {soft_only} cặp soft-only).
- **Phân định các cặp thiếu tiêu đề**: Có {no_title_count:,} cặp ({no_title_pct:.1f}%) thiếu trường tiêu đề ở ít nhất một nguồn. Trong đó có {t_bib_only:,} cặp mà file `.bib` có tiêu đề nhưng parser không bóc tách được từ `\\bibitem`, {t_bibitem_only:,} cặp chỉ `\\bibitem` có tiêu đề, và {t_neither:,} cặp cả hai nguồn đều không có. Sự chênh lệch này gồm hai nguyên nhân thực tế:
  1. *Đặc trưng định dạng nguồn*: Nhiều tạp chí (đặc biệt trong các lĩnh vực vật lý và toán học) in `\\bibitem` theo quy ước rút gọn, chỉ chứa tác giả, tên tạp chí, số tập, trang và năm mà hoàn toàn không in tên bài báo.
  2. *Giới hạn trích xuất của parser*: Việc bóc tách văn bản tự do phi cấu trúc bằng heuristic/regex gặp khó khăn trước các macro định dạng tùy biến lạ của tác giả. Vì vậy, {t_both:,} là số cặp mà parser lấy được, phản ánh độ phủ của công cụ chứ không phải toàn bộ số tiêu đề thực tế có trong văn bản.
- **Quy tắc ưu tiên**: `collect_bib()` ưu tiên entry từ `.bib` khi hai nguồn có cùng `citation_key` vì `.bib` có đầy đủ tiêu đề và trường chuẩn hóa hơn.
- **Phân định phạm vi**: Bảng này đo mức độ đồng thuận liên nguồn (Inter-source Concordance), không phải độ chính xác tuyệt đối (Ground Truth Accuracy) hay Precision/Recall của pipeline deduplication.

## 4. Phân định phạm vi file `.bib` và kiểm tra độ nhạy

- `\\bibitem` được trích xuất nghiêm ngặt từ các file `.tex` thuộc `compile_path` (qua `gather_detail`, loại bỏ hoàn toàn các file mồ côi hoặc template).
- Nguồn `.bib` được khảo sát trên toàn bộ file `.bib` có trong thư mục version ({sens_total_disk} file, {tot_bib:,} entry).
- **Kiểm tra độ nhạy (Sensitivity Analysis)**: Trong số {sens_total_disk} file `.bib` trên đĩa của {v_eval} version khảo sát, các lệnh `\\bibliography` và `\\addbibresource` trong `compile_path` chứa {sens_bib_args} tham số gọi file. Trong đó có {sens_unres_args} tham số không resolve được thành file trên đĩa và {sens_res_files} file `.bib` riêng biệt được xác định trực tiếp từ compile path; {sens_unref_files} file `.bib` còn lại trên đĩa không được các lệnh trên trực tiếp gọi. Khi nộp bài lên arXiv, nhiều tác giả đã chèn sẵn môi trường `thebibliography` (từ file `.bbl` đã biên dịch) vào mã nguồn TeX và để lại file `.bib` trong gói nộp mà không còn lệnh `\\bibliography` hoạt động. Do đó, việc gom toàn bộ file `.bib` có mặt trong thư mục version là một heuristic thu thập ứng viên tối đa cho quá trình đối chiếu và phục vụ matching pool ở M3.

## 5. Block BibTeX lỗi cú pháp

Bước đánh giá ghi nhận {failed_bib_blocks:,} block lỗi trên {syntax_error_versions} version. Parser vẫn giữ các entry hợp lệ. `logs/bib.csv` đánh dấu version có lỗi bằng `bib_syntax_error:N`.
"""
    out_path.write_text(md, encoding="utf-8")
    return md


def process_publications_dedup(
    prescan_csv: Path | str,
    corpus_root: Path | str,
    logs_csv: Path | str,
    reports_map: Path | str,
    limit: int | None = None,
    append: bool = True,
    allow_fallback: bool = False,
) -> tuple[int, int]:
    """Chạy dedup qua unify_publication_with_stats cho các publication,
    ghi append logs/bib_dedup.csv và cập nhật file reports/cite_rename_map.json.
    """
    prescan_csv = Path(prescan_csv)
    corpus_root = Path(corpus_root)
    logs_csv = Path(logs_csv)
    reports_map = Path(reports_map)

    logs_csv.parent.mkdir(parents=True, exist_ok=True)
    reports_map.parent.mkdir(parents=True, exist_ok=True)

    with open(prescan_csv, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("bib_style") == "both"]

    arxiv_ids = sorted({r["arxiv_id"] for r in rows})
    if limit is not None and limit > 0:
        arxiv_ids = arxiv_ids[:limit]

    # Đọc bản đồ hiện có nếu file đã tồn tại để không ghi đè mất publication khác
    rename_reports: dict[str, Any] = {}
    if reports_map.is_file():
        try:
            with open(reports_map, encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    rename_reports.update(existing)
        except Exception:
            pass

    csv_rows: list[dict[str, Any]] = []

    for aid in arxiv_ids:
        pk = config.pub_key(aid)
        pub_dir = corpus_root / pk
        if not pub_dir.is_dir():
            continue

        v_dirs = sorted(
            [d for d in pub_dir.iterdir() if d.is_dir() and d.name.startswith("v")],
            key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 999,
        )
        if not v_dirs:
            continue

        norm_text: dict[int, str] = {}
        bib_entries: dict[int, list[dict[str, Any]]] = {}

        t0 = time.perf_counter()
        status = "ok"
        error_type = ""

        try:
            for vd in v_dirs:
                v_num = int(vd.name[1:]) if vd.name[1:].isdigit() else 1
                bib_entries[v_num] = collect_bib(vd)
                # Đọc văn bản theo compile path, không nuốt file thừa
                norm_text[v_num] = _read_version_tex(vd, aid, allow_fallback=allow_fallback)

            n_before = sum(len(e) for e in bib_entries.values())

            # Chạy unify_publication_with_stats để có số liệu chính xác theo version map
            renamed_text, bibtex_rows, global_rmap, stats = unify_publication_with_stats(
                norm_text, bib_entries
            )

            n_after = len(bibtex_rows)
            total_renamed = stats.get("n_cite_renamed", 0)
            total_dangling = stats.get("n_dangling", 0)
            version_maps = stats.get("version_rename_maps", {})

        except Exception as exc:  # noqa: BLE001
            status = "fail"
            error_type = type(exc).__name__
            n_before = 0
            n_after = 0
            total_renamed = 0
            total_dangling = 0
            global_rmap = {}
            version_maps = {}

        elapsed = time.perf_counter() - t0

        csv_rows.append(
            {
                "arxiv_id": aid,
                "n_before": n_before,
                "n_after": n_after,
                "n_cite_renamed": total_renamed,
                "seconds": round(elapsed, 2),
                "status": status,
                "error_type": error_type,
            }
        )

        rename_reports[aid] = {
            "n_before": n_before,
            "n_after": n_after,
            "n_cite_renamed": total_renamed,
            "n_dangling": total_dangling,
            "rename_map": global_rmap,
            "version_rename_maps": {str(k): v for k, v in version_maps.items()} if version_maps else {},
        }

    if append:
        _append_csv_rows(logs_csv, BIB_DEDUP_COLUMNS, csv_rows)
    else:
        with open(logs_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BIB_DEDUP_COLUMNS)
            writer.writeheader()
            writer.writerows(csv_rows)

    with open(reports_map, "w", encoding="utf-8") as f:
        json.dump(rename_reports, f, indent=2, ensure_ascii=False)

    return len(arxiv_ids), len(csv_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Đánh giá đối chứng 124 version và chạy dedup log.")
    parser.add_argument("--prescan-csv", default=str(config.REPORTS_ROOT / "prescan_versions.csv"))
    parser.add_argument("--corpus-root", default=str(config.CORPUS_ROOT))
    parser.add_argument("--bib-logs-csv", default=str(config.LOGS_ROOT / "bib.csv"))
    parser.add_argument("--logs-csv", default=str(config.LOGS_ROOT / "bib_dedup.csv"))
    parser.add_argument("--reports-map", default=str(config.REPORTS_ROOT / "cite_rename_map.json"))
    parser.add_argument("--report-md", default=str(config.REPORTS_ROOT / "m2_bib_concordance_report.md"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    print("1. Đang đánh giá đối chứng trên 124 version và ghi logs/bib.csv...")
    stats = evaluate_concordance(
        args.prescan_csv,
        args.corpus_root,
        bib_logs_csv=args.bib_logs_csv,
        append=True,
    )
    md = generate_concordance_markdown(stats, args.report_md)
    print(f"-> Đã xuất báo cáo đối chứng: {args.report_md}")
    print(f"-> Đã ghi logs bib theo version: {args.bib_logs_csv}")

    print("2. Đang chạy dedup và ghi log...")
    n_pubs, n_done = process_publications_dedup(
        args.prescan_csv,
        args.corpus_root,
        args.logs_csv,
        args.reports_map,
        limit=args.limit,
        append=True,
    )
    print(f"-> Đã ghi {n_done}/{n_pubs} publications vào {args.logs_csv} và {args.reports_map}")


if __name__ == "__main__":
    main()
