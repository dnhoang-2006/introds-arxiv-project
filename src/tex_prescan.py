"""Tiền xử lý TeX (prescan) bắc cầu từ Milestone 1 sang Milestone 2/3.

Duyệt các file .tex trong corpus/<pub_key>/<version>/, ghi nhận:
1. File gốc (root file): file .tex chứa \\documentclass hoặc \\documentstyle
2. Danh sách \\input và \\include trong từng file (chưa resolve đệ quy)
3. Đếm số lượng \\bibitem trong mỗi version
4. Tỉ lệ version có file .bib riêng vs chỉ có \\bibitem inline
5. Kích thước matching pool M3: số references có mã arXiv từ references.json

Output được ghi vào:
- corpus/<pub_key>/<version>/prescan.json
- corpus/<pub_key>/prescan.json
- reports/prescan_summary.json (thống kê toàn bộ)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import config

DOC_CLASS_PATTERN = re.compile(r"\\(?:documentclass|documentstyle)\b", re.IGNORECASE)
INCLUDE_PATTERN = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
INPUT_BARE_PATTERN = re.compile(r"\\input\s+([^\s%{}]+)")
BIBITEM_PATTERN = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
COMMENT_PATTERN = re.compile(r"(?<!\\)%.*")


def clean_tex_comments(text: str) -> str:
    """Loại bỏ comment LaTeX (%...) nhưng giữ nguyên ký tự thoát \\%."""
    lines = [COMMENT_PATTERN.sub("", line) for line in text.splitlines()]
    return "\n".join(lines)


def read_text_safe(path: Path) -> str:
    """Đọc file text với utf-8, fallback sang latin-1 nếu gặp lỗi encoding."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="replace")
        except Exception:
            return ""


def extract_includes(clean_text: str) -> list[str]:
    """Trích xuất danh sách file được include/input từ nội dung TeX."""
    targets: list[str] = []
    # \\input{...}, \\include{...}, \\subfile{...}
    for match in INCLUDE_PATTERN.findall(clean_text):
        target = match.strip().strip('"\'')
        if target and target not in targets:
            targets.append(target)
    # \\input bare_path
    for match in INPUT_BARE_PATTERN.findall(clean_text):
        target = match.strip().strip('"\'')
        if target and target not in targets:
            targets.append(target)
    return targets


def score_root_candidate(rel_path: str, has_includes: bool, arxiv_id: str) -> int:
    """Chấm điểm ưu tiên để chọn root file chính xác nhất khi có nhiều file chứa \\documentclass."""
    score = 0
    name_lower = Path(rel_path).name.lower()
    parts = Path(rel_path).parts

    # Ưu tiên file nằm ở thư mục gốc của version (không nằm trong folder con)
    if len(parts) == 1:
        score += 20

    # Ưu tiên các tên file phổ biến thường là file chính
    if name_lower in ("main.tex", "ms.tex", "paper.tex", "article.tex", "manuscript.tex"):
        score += 30
    elif name_lower.startswith("main") or name_lower.startswith("paper"):
        score += 15

    # Ưu tiên nếu tên file chứa mã arXiv
    clean_id = config.strip_version(arxiv_id).replace(".", "").replace("-", "")
    if clean_id and clean_id in name_lower:
        score += 25

    # File có include các file con khác có khả năng cao là file chính
    if has_includes:
        score += 10

    # Trừ điểm các file mẫu, template, appendix hoặc slide
    if any(k in name_lower for k in ("sample", "template", "authordraft", "appendix", "supp", "poster", "slide")):
        score -= 25

    return score


def prescan_version(
    version_dir: Path,
    arxiv_id: str,
    matching_pool_size: int,
) -> dict[str, Any]:
    """Quét một thư mục version (v1, v2...) và trả về metadata prescan."""
    version_name = version_dir.name
    empty_file = version_dir / "_EMPTY.json"

    # Trường hợp 1: Version không có source TeX (được đánh dấu bằng _EMPTY.json)
    if empty_file.is_file():
        reason = "empty_version"
        try:
            empty_data = json.loads(empty_file.read_text(encoding="utf-8"))
            reason = empty_data.get("reason", reason)
        except Exception:
            pass

        return {
            "arxiv_id": arxiv_id,
            "version": version_name,
            "has_tex": False,
            "is_empty": True,
            "empty_reason": reason,
            "root_file": None,
            "candidate_roots": [],
            "tex_files": [],
            "includes": {},
            "n_bibitem": 0,
            "has_bib_file": False,
            "bib_files": [],
            "bib_style": "none",
            "matching_pool_size": matching_pool_size,
            "prescanned_at": config.now_iso(),
        }

    # Trường hợp 2: Quét tất cả file .tex và .bib
    tex_paths = sorted(version_dir.glob("**/*.tex"))
    bib_paths = sorted(version_dir.glob("**/*.bib"))

    tex_rel_files = [p.relative_to(version_dir).as_posix() for p in tex_paths]
    bib_rel_files = [p.relative_to(version_dir).as_posix() for p in bib_paths]

    if not tex_paths:
        return {
            "arxiv_id": arxiv_id,
            "version": version_name,
            "has_tex": False,
            "is_empty": True,
            "empty_reason": "no_tex_in_folder",
            "root_file": None,
            "candidate_roots": [],
            "tex_files": [],
            "includes": {},
            "n_bibitem": 0,
            "has_bib_file": bool(bib_paths),
            "bib_files": bib_rel_files,
            "bib_style": "bib_file_only" if bib_paths else "none",
            "matching_pool_size": matching_pool_size,
            "prescanned_at": config.now_iso(),
        }

    candidate_roots: list[str] = []
    candidate_scores: dict[str, int] = {}
    includes_map: dict[str, list[str]] = {}
    total_bibitem = 0

    for tex_path, rel_str in zip(tex_paths, tex_rel_files):
        raw_text = read_text_safe(tex_path)
        clean_text = clean_tex_comments(raw_text)

        # 1. Kiểm tra \documentclass
        if DOC_CLASS_PATTERN.search(clean_text):
            candidate_roots.append(rel_str)

        # 2. Liệt kê \input, \include (chưa resolve đệ quy)
        inc_list = extract_includes(clean_text)
        if inc_list:
            includes_map[rel_str] = inc_list

        # 3. Đếm \bibitem
        bibitems = BIBITEM_PATTERN.findall(clean_text)
        total_bibitem += len(bibitems)

    # Xác định root_file ưu tiên nhất
    root_file: str | None = None
    if len(candidate_roots) == 1:
        root_file = candidate_roots[0]
    elif len(candidate_roots) > 1:
        for c in candidate_roots:
            candidate_scores[c] = score_root_candidate(
                c, has_includes=(c in includes_map), arxiv_id=arxiv_id,
            )
        root_file = max(candidate_roots, key=lambda c: candidate_scores[c])

    # 4. Xác định phong cách trích dẫn (bib_style)
    has_bib = len(bib_paths) > 0
    has_inline = total_bibitem > 0
    if has_bib and not has_inline:
        bib_style = "bib_file_only"
    elif not has_bib and has_inline:
        bib_style = "inline_bibitem_only"
    elif has_bib and has_inline:
        bib_style = "both"
    else:
        bib_style = "none"

    return {
        "arxiv_id": arxiv_id,
        "version": version_name,
        "has_tex": True,
        "is_empty": False,
        "empty_reason": None,
        "root_file": root_file,
        "candidate_roots": candidate_roots,
        "tex_files": tex_rel_files,
        "includes": includes_map,
        "n_bibitem": total_bibitem,
        "has_bib_file": has_bib,
        "bib_files": bib_rel_files,
        "bib_style": bib_style,
        "matching_pool_size": matching_pool_size,
        "prescanned_at": config.now_iso(),
    }


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Ghi file JSON an toàn thông qua file tạm .tmp để tránh lỗi ngắt giữa chừng."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def prescan_publication(pub_dir: Path, force: bool = False) -> dict[str, Any] | None:
    """Prescan toàn bộ các version của một publication."""
    if not pub_dir.is_dir():
        return None

    # Tìm các thư mục version (v1, v2...)
    version_dirs = sorted(
        [d for d in pub_dir.iterdir() if d.is_dir() and re.match(r"^v\d+$", d.name)],
        key=lambda d: int(d.name[1:]),
    )
    if not version_dirs:
        return None

    # Đọc arxiv_id và matching pool size từ references.json hoặc paper_meta.json
    arxiv_id = pub_dir.name.replace("-", ".").replace("_", "/")
    matching_pool_size = 0

    ref_file = pub_dir / "references.json"
    if ref_file.is_file():
        try:
            ref_data = json.loads(ref_file.read_text(encoding="utf-8"))
            arxiv_id = ref_data.get("arxiv_id", arxiv_id)
            matching_pool_size = int(ref_data.get("n_with_arxiv", 0))
        except Exception:
            pass
    else:
        meta_file = pub_dir / "paper_meta.json"
        if meta_file.is_file():
            try:
                meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                arxiv_id = meta_data.get("arxiv_id", arxiv_id)
            except Exception:
                pass

    pub_prescan_path = pub_dir / "prescan.json"
    if not force and pub_prescan_path.is_file():
        # Kiểm tra nếu đã prescan đầy đủ thì đọc kết quả
        try:
            return json.loads(pub_prescan_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    versions_data: dict[str, Any] = {}
    for vdir in version_dirs:
        v_prescan = prescan_version(vdir, arxiv_id, matching_pool_size)
        versions_data[vdir.name] = v_prescan
        # Ghi prescan.json cho từng version
        write_json_atomic(vdir / "prescan.json", v_prescan)

    pub_summary = {
        "arxiv_id": arxiv_id,
        "pub_key": pub_dir.name,
        "prescanned_at": config.now_iso(),
        "matching_pool_size": matching_pool_size,
        "n_versions": len(version_dirs),
        "versions": versions_data,
    }
    # Ghi prescan.json cấp publication
    write_json_atomic(pub_prescan_path, pub_summary)
    return pub_summary


def prescan_corpus(
    ids_path: Path | None = None,
    limit: int | None = None,
    force: bool = False,
    quiet: bool = False,
) -> dict[str, Any]:
    """Quét toàn bộ corpus và trả về thống kê tổng hợp phục vụ báo cáo."""
    config.ensure_dirs()

    if ids_path and ids_path.is_file():
        target_ids = []
        for line in ids_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                target_ids.append(config.strip_version(line))
        pub_dirs = [config.pub_dir(aid) for aid in target_ids]
    else:
        pub_dirs = sorted(
            [d for d in config.CORPUS_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda d: d.name,
        )

    if limit is not None:
        pub_dirs = pub_dirs[:limit]

    total_pubs = len(pub_dirs)
    if not quiet:
        print(f"Bắt đầu prescan cho {total_pubs} publications trong corpus...")

    summary_stats = {
        "total_publications": 0,
        "total_versions": 0,
        "empty_versions": 0,
        "tex_versions": 0,
        "root_detected_versions": 0,
        "root_detection_rate": 0.0,
        "bib_styles": {
            "bib_file_only": 0,
            "inline_bibitem_only": 0,
            "both": 0,
            "none": 0,
        },
        "total_bibitems": 0,
        "total_matching_pool": 0,
        "matching_pool_distribution": {
            "mean": 0.0,
            "has_arxiv_ratio": 0.0,
        },
    }

    start_time = time.monotonic()
    processed_pubs = 0

    for pub_dir in pub_dirs:
        res = prescan_publication(pub_dir, force=force)
        if not res:
            continue

        processed_pubs += 1
        summary_stats["total_publications"] += 1
        summary_stats["total_matching_pool"] += res.get("matching_pool_size", 0)

        for v_name, v_info in res.get("versions", {}).items():
            summary_stats["total_versions"] += 1
            if v_info.get("is_empty"):
                summary_stats["empty_versions"] += 1
            else:
                summary_stats["tex_versions"] += 1
                if v_info.get("root_file"):
                    summary_stats["root_detected_versions"] += 1
                summary_stats["total_bibitems"] += v_info.get("n_bibitem", 0)

            style = v_info.get("bib_style", "none")
            if style in summary_stats["bib_styles"]:
                summary_stats["bib_styles"][style] += 1

        if not quiet and processed_pubs % 500 == 0:
            elapsed = time.monotonic() - start_time
            print(f"  Đã prescan {processed_pubs}/{total_pubs} publications ({elapsed:.1f}s)")

    # Tính toán các tỉ lệ phần trăm
    tex_v = summary_stats["tex_versions"]
    if tex_v > 0:
        summary_stats["root_detection_rate"] = round(
            (summary_stats["root_detected_versions"] / tex_v) * 100, 2,
        )

    if summary_stats["total_publications"] > 0:
        summary_stats["matching_pool_distribution"]["mean"] = round(
            summary_stats["total_matching_pool"] / summary_stats["total_publications"], 2,
        )

    # Ghi báo cáo tổng hợp ra reports/prescan_summary.json
    summary_path = config.REPORTS_ROOT / "prescan_summary.json"
    write_json_atomic(summary_path, summary_stats)

    elapsed_total = time.monotonic() - start_time
    if not quiet:
        print("\n" + "=" * 60)
        print("HOÀN THÀNH PRESCAN CORPUS")
        print(f"Thời gian thực hiện: {elapsed_total:.2f} giây")
        print(f"Tổng số publications: {summary_stats['total_publications']}")
        print(f"Tổng số versions: {summary_stats['total_versions']}")
        print(f"Versions rỗng (chỉ PDF/không TeX): {summary_stats['empty_versions']}")
        print(f"Versions có TeX source: {summary_stats['tex_versions']}")
        print(f"Phát hiện file root: {summary_stats['root_detected_versions']}/{tex_v} ({summary_stats['root_detection_rate']}%)")
        print("\nPhân bổ phong cách Bibliography:")
        for k, v in summary_stats["bib_styles"].items():
            pct = round(v / summary_stats["total_versions"] * 100, 1) if summary_stats["total_versions"] else 0
            print(f"  - {k:<20}: {v:>5} ({pct}%)")
        print(f"\nTổng số \\bibitem đếm được: {summary_stats['total_bibitems']}")
        print(f"Tổng kích thước matching pool: {summary_stats['total_matching_pool']} candidates")
        print(f"Trung bình candidate arXiv/bài: {summary_stats['matching_pool_distribution']['mean']}")
        print(f"Báo cáo tổng hợp: {summary_path}")
        print("=" * 60)

    return summary_stats


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Tien xu ly TeX (prescan) corpus bac cau M2/M3")
    parser.add_argument("--ids", type=Path, default=None, help="File chua danh sach arXiv ID")
    parser.add_argument("--limit", type=int, default=None, help="Gioi han so publication can prescan")
    parser.add_argument("--force", action="store_true", help="Ghi de prescan.json da ton tai")
    parser.add_argument("--quiet", action="store_true", help="Khong in tien trinh chi tiet")
    args = parser.parse_args()

    prescan_corpus(ids_path=args.ids, limit=args.limit, force=args.force, quiet=args.quiet)


if __name__ == "__main__":
    main()
