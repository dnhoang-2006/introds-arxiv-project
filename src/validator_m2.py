"""validator_m2.py - Data Validation Suite cho Milestone 2 (bảng `elements` và `hierarchy`).

Kiểm đầu ra của parser theo docs/schema_m2.md. Lõi là hàm thuần nhận list dict, nên test được
bằng fixture tự dựng (tests/fixtures_m2.py) mà không cần chờ dữ liệu parse thật.

Sáu phép kiểm
    V1 one_root        mỗi version có ĐÚNG MỘT gốc, kind `document`
                       (gốc = set(parent_id) - set(element_id), schema_m2.md mục 1.2)
    V2 no_orphan       mọi element_id và parent_id trong hierarchy đều có trong elements
    V3 acyclic         không chu trình; mọi node đi lên được tới gốc
    V4 edges_kinds     kind hợp lệ; cạnh không trùng; lá không làm cha; `document` chỉ là gốc;
                       node không phải lá chỉ có MỘT cha trong một version
    V5 elements        file đọc được; element_id duy nhất, đúng tiền tố `pub_key#`;
                       arxiv_id là bản gốc; không có hai hàng cùng (kind, content);
                       dedup hiệu quả giữa các version
    V6 version_cover   mọi version 1..n_versions có cây, hoặc là bản ghi rỗng đúng mục 6

Một element LÁ (sentence, formula, figure) được phép dùng lại dưới nhiều cha trong cùng một
version: cùng một câu xuất hiện hai lần thì cùng element_id (dedup theo nội dung). Việc đó
chỉ bị báo là cảnh báo.

Chạy:
    python src/validator_m2.py --ids ids/24120152.txt --limit 20
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from validator import Issue, write_report  # noqa: E402  (dùng lại Issue và ghi báo cáo của M1)

VALIDATOR_M2_VERSION = "1.0"

# docs/schema_m2.md mục 3: đúng 10 giá trị, không thêm không bớt
KINDS = frozenset({
    "document", "section", "subsection", "subsubsection", "paragraph",
    "itemize", "item", "sentence", "formula", "figure",
})
LEAF_KINDS = frozenset({"sentence", "formula", "figure"})

# Dạng id do elements.element_uid() sinh ra: 2310-12345#snt_a3f9c201
_ID_SHAPE = re.compile(r"^[^#\s]+#(?:doc|sec|sub|ssb|par|itz|itm|snt|eqn|fig)_[0-9a-f]{8}$")

CHECKS: dict[str, tuple[str, str, str]] = {
    "V1": ("one_root", "Mỗi version có đúng một gốc, kind document",
           "schema_m2 mục 1.2: gốc = set(parent_id) - set(element_id)"),
    "V2": ("no_orphan", "Mọi element_id và parent_id trong hierarchy đều có trong elements",
           "hierarchy tham chiếu tới elements"),
    "V3": ("acyclic", "Không có chu trình; mọi node đi lên được tới gốc", "cây phân cấp"),
    "V4": ("edges_kinds", "kind hợp lệ, cạnh không trùng, lá không làm cha, document chỉ là gốc, "
                          "node không phải lá chỉ có một cha trong một version",
           "schema_m2 mục 3: 10 giá trị kind; đề: lá là sentence, formula, figure"),
    "V5": ("elements", "File đọc được; element_id duy nhất, đúng tiền tố pub_key#, arxiv_id bản gốc, "
                       "không có hai hàng cùng (kind, content)",
           "đề: nội dung khớp giữa các version chiếm một hàng duy nhất"),
    "V6": ("version_cover", "Mọi version 1..n_versions có cây hoặc là bản ghi rỗng đúng quy ước",
           "đề: ghi version rỗng, không bỏ qua; schema_m2 mục 6"),
}


def _sample(items: Iterable[Any], n: int = 3) -> str:
    items = [str(i) for i in items]
    head = ", ".join(items[:n])
    return head + (f" ... (+{len(items) - n} nữa)" if len(items) > n else "")


def read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """Đọc JSON Lines. Trả (các dòng đọc được, danh sách lỗi); dòng hỏng không làm sập cả file."""
    rows: list[dict] = []
    errors: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"dòng {n}: JSON hỏng ({exc.msg})")
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                errors.append(f"dòng {n}: không phải object JSON")
    return rows, errors


def arxiv_id_from_folder(folder: str) -> str:
    """Đoán arxiv_id từ tên thư mục (ngược của config.pub_key); chỉ dùng khi dữ liệu không có."""
    if re.fullmatch(r"\d{4}-\d{4,5}", folder):
        return folder.replace("-", ".")
    return folder.replace("_", "/", 1)


class ValidatorM2:
    def __init__(self) -> None:
        self.issues: list[Issue] = []
        self.checked: dict[str, set] = {c: set() for c in CHECKS}
        self.stats: Counter = Counter()
        self.dedup_ratios: list[float] = []

    # ---- ghi nhận ------------------------------------------------------- #
    def _add(self, sev: str, check: str, arxiv_id: str, version: int | None,
             message: str, owner: str, path: str) -> None:
        self.issues.append(Issue(check=check, severity=sev, arxiv_id=arxiv_id, version=version,
                                 message=message, owner=owner, path=path))

    # ---- lõi: một publication -------------------------------------------- #
    def validate(
        self,
        elements: list[dict],
        hierarchy: list[dict],
        arxiv_id: str,
        pub_key: str | None = None,
        n_versions: int | None = None,
        owner: str = "",
        path: str = "",
    ) -> list[Issue]:
        """Kiểm một publication; trả về các vấn đề của riêng publication này."""
        start = len(self.issues)
        pub_key = pub_key or config.pub_key(arxiv_id)

        def err(check: str, version: int | None, msg: str) -> None:
            self._add("error", check, arxiv_id, version, msg, owner, path)

        def warn(check: str, version: int | None, msg: str) -> None:
            self._add("warning", check, arxiv_id, version, msg, owner, path)

        def touch(check: str, version: int | None = None) -> None:
            self.checked[check].add((arxiv_id, version))

        # ---------------- bảng elements (V4 kind, V5) ---------------------- #
        for c in ("V4", "V5"):
            touch(c)
        elem: dict[str, dict] = {}
        bad_shape: list[str] = []
        bad_arxiv = missing_arxiv = 0
        for row in elements:
            eid, kind, content = row.get("element_id"), row.get("kind"), row.get("content")
            if not isinstance(eid, str) or not eid:
                err("V5", None, "hàng elements thiếu element_id (null hoặc rỗng)")
                continue
            if not isinstance(content, str):
                err("V5", None, f"{eid}: content phải là chuỗi, không được null")
            if not isinstance(kind, str) or kind not in KINDS:   # kiểm kiểu trước: list/dict không băm được
                err("V4", None, f"{eid}: kind không hợp lệ {kind!r}; chỉ nhận {sorted(KINDS)}")
                row = {**row, "kind": None}   # các bước sau dùng kind làm khóa/so sánh, nên chuẩn hóa về None
            if eid in elem:
                err("V5", None, f"element_id lặp trong elements: {eid}")
                continue
            elem[eid] = row
            if not eid.startswith(pub_key + "#"):
                err("V5", None, f"{eid}: không bắt đầu bằng '{pub_key}#'")
            elif not _ID_SHAPE.match(eid):
                bad_shape.append(eid)
            if row.get("arxiv_id") != arxiv_id:
                if row.get("arxiv_id") in (None, ""):
                    missing_arxiv += 1
                else:
                    bad_arxiv += 1
        if missing_arxiv:
            err("V5", None, f"{missing_arxiv} hàng elements thiếu arxiv_id (null hoặc không có trường); "
                            f"schema yêu cầu không null")
        if bad_shape:
            warn("V5", None, f"{len(bad_shape)} element_id không đúng dạng <mã>_<8 hex> của "
                             f"element_uid(): {_sample(bad_shape)}")
        if bad_arxiv:
            err("V5", None, f"{bad_arxiv} hàng elements có arxiv_id khác '{arxiv_id}' "
                            f"(phải là bản gốc, chưa đổi dấu)")

        by_content: dict[tuple, list[str]] = defaultdict(list)
        for eid, row in elem.items():
            if isinstance(row.get("content"), str):
                by_content[(row.get("kind"), row["content"])].append(eid)
        for (kind, content), ids in by_content.items():
            if len(ids) > 1:
                err("V5", None, f"{len(ids)} hàng elements cùng (kind={kind}, content="
                                f"{content[:40]!r}): {_sample(ids)}. Nội dung khớp phải chiếm một hàng")

        # ---------------- bảng hierarchy ----------------------------------- #
        by_version: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for row in hierarchy:
            v, child, parent = row.get("version"), row.get("element_id"), row.get("parent_id")
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                err("V6", None, f"cạnh có version không hợp lệ: {v!r}")
                continue
            if not (isinstance(child, str) and child and isinstance(parent, str) and parent):
                err("V2", v, f"cạnh thiếu element_id hoặc parent_id (null/rỗng): {child!r} -> {parent!r}")
                continue
            if row.get("arxiv_id") in (None, ""):
                err("V5", v, f"cạnh {child} -> {parent} thiếu arxiv_id (null hoặc không có trường)")
            elif row.get("arxiv_id") != arxiv_id:
                err("V5", v, f"cạnh có arxiv_id {row.get('arxiv_id')!r}, phải là '{arxiv_id}' (bản gốc)")
            by_version[v].append((child, parent))

        # ---------------- V5: dedup hiệu quả giữa các version --------------- #
        if len(by_version) > 1:
            all_children = [child for edges in by_version.values() for child, _ in edges]
            n_nodes = len(all_children)
            n_unique = len(set(all_children))
            ratio = 1.0 - (n_unique / n_nodes) if n_nodes > 0 else 0.0
            self.dedup_ratios.append(ratio)
            if ratio <= 0.0 and n_nodes > 0:
                warn("V5", None, f"bài có {len(by_version)} version nhưng dedup_ratio = 0.0 "
                                 f"(không có element nào dùng lại giữa các version)")

        # ---------------- V6: phủ version ---------------------------------- #
        touch("V6")
        root_text = {v: f"{arxiv_id}v{v}" for v in range(1, (n_versions or 0) + 1)}
        doc_versions: set[int] = set()
        for row in elem.values():
            if row.get("kind") == "document" and isinstance(row.get("content"), str):
                m = re.fullmatch(re.escape(arxiv_id) + r"v(\d+)", row["content"])
                if m:
                    doc_versions.add(int(m.group(1)))
        with_tree = set(by_version)
        empty_versions = doc_versions - with_tree
        if n_versions is None:
            expected = with_tree | doc_versions
            if not expected:
                err("V6", None, "không có version nào (không cây, không bản ghi rỗng)")
        else:
            expected = set(range(1, n_versions + 1))
            for v in sorted(with_tree - expected):
                err("V6", v, f"version {v} không tồn tại (bài chỉ có {n_versions} version)")
            for v in sorted(expected - with_tree - empty_versions):
                err("V6", v, f"version {v} không có cây và cũng không có bản ghi rỗng "
                             f"(document với content '{root_text[v]}')")
        self.stats["versions"] += len(expected)
        self.stats["empty_versions"] += len(empty_versions & expected)
        self.stats["elements"] += len(elem)
        self.stats["edges"] += sum(len(e) for e in by_version.values())

        # ---------------- từng version có cây ------------------------------ #
        for v in sorted(by_version):
            edges = by_version[v]
            for c in ("V1", "V2", "V3", "V4"):
                touch(c, v)
            parents_of: dict[str, list[str]] = defaultdict(list)
            for child, parent in edges:
                parents_of[child].append(parent)
            children = {c for c, _ in edges}
            parents = {p for _, p in edges}
            nodes = children | parents

            # V4: cạnh trùng
            dup = [e for e, n in Counter(edges).items() if n > 1]
            if dup:
                err("V4", v, f"{len(dup)} cạnh trùng dòng (version, element_id, parent_id): "
                             f"{_sample(f'{c}->{p}' for c, p in dup)}")

            # V1: đúng một gốc, kind document
            roots = sorted(parents - children)
            if len(roots) != 1:
                err("V1", v, ("không có gốc nào (mọi node đều có cha, có thể do chu trình)" if not roots
                              else f"có {len(roots)} gốc, phải đúng 1: {_sample(roots)}"))
            else:
                root = roots[0]
                r = elem.get(root)
                if r is not None and r.get("kind") != "document":
                    err("V1", v, f"gốc {root} có kind {r.get('kind')!r}, phải là 'document'")
                if r is not None and r.get("content") != root_text.get(v, f"{arxiv_id}v{v}"):
                    warn("V6", v, f"content của gốc nên là '{arxiv_id}v{v}' (schema_m2 mục 2), "
                                  f"đang là {r.get('content')!r}")

            # V2: mồ côi
            miss_child = sorted(c for c in children if c not in elem)
            miss_parent = sorted(p for p in parents if p not in elem)
            if miss_child:
                err("V2", v, f"{len(miss_child)} element_id trong hierarchy không có trong elements: "
                             f"{_sample(miss_child)}")
            if miss_parent:
                err("V2", v, f"{len(miss_parent)} parent_id trong hierarchy không có trong elements: "
                             f"{_sample(miss_parent)}")

            # V3: chu trình (DFS ba màu theo cạnh node -> cha)
            color: dict[str, int] = {}
            cycles: list[list[str]] = []
            for s in sorted(nodes):
                if color.get(s):
                    continue
                color[s] = 1
                path_stack = [s]
                stack = [(s, iter(parents_of.get(s, ())))]
                while stack:
                    node, it = stack[-1]
                    for nxt in it:
                        c = color.get(nxt, 0)
                        if c == 1:
                            cycles.append(path_stack[path_stack.index(nxt):] + [nxt])
                        elif c == 0:
                            color[nxt] = 1
                            path_stack.append(nxt)
                            stack.append((nxt, iter(parents_of.get(nxt, ()))))
                            break
                    else:
                        color[node] = 2
                        path_stack.pop()
                        stack.pop()
            for cyc in cycles[:3]:
                err("V3", v, "chu trình: " + " -> ".join(cyc))
            if len(cycles) > 3:
                err("V3", v, f"... và {len(cycles) - 3} chu trình khác")

            # V4: lá làm cha, document làm con, nhiều cha
            leaf_parents = sorted(p for p in parents if elem.get(p, {}).get("kind") in LEAF_KINDS)
            if leaf_parents:
                err("V4", v, f"{len(leaf_parents)} node lá làm cha (sentence/formula/figure không có "
                             f"con): {_sample(leaf_parents)}")
            doc_children = sorted(c for c in children if elem.get(c, {}).get("kind") == "document")
            if doc_children:
                err("V4", v, f"node document không phải gốc: {_sample(doc_children)}")
            multi = {c: set(ps) for c, ps in parents_of.items() if len(set(ps)) > 1}
            bad_multi = sorted(c for c in multi if elem.get(c, {}).get("kind") not in LEAF_KINDS)
            if bad_multi:
                err("V4", v, f"{len(bad_multi)} node không phải lá có nhiều hơn một cha trong cùng "
                             f"version: {_sample(bad_multi)}")
            shared_leaves = len(multi) - len(bad_multi)
            if shared_leaves > 0:
                warn("V4", v, f"{shared_leaves} element lá được dùng lại dưới nhiều cha trong cùng "
                              f"version (câu/công thức lặp, hợp lệ theo dedup nội dung)")

            # node tồn tại trong elements nhưng chưa nằm trong cây của version này không phải lỗi:
            # element của version khác vẫn nằm chung kho.

        # element không thuộc cây nào của bất kỳ version, và không phải bản ghi rỗng
        used = {n for edges in by_version.values() for e in edges for n in e}
        unused = sorted(e for e, r in elem.items() if e not in used and r.get("kind") != "document")
        if unused:
            warn("V5", None, f"{len(unused)} element không nằm trong cây của version nào: {_sample(unused)}")
        return self.issues[start:]

    # ---- đọc từ đĩa ------------------------------------------------------- #
    def validate_dir(self, pub_dir: Path, n_versions: int | None = None, owner: str = "") -> list[Issue]:
        folder = pub_dir.name
        elements, hierarchy, problems = [], [], []
        for name, sink in (("elements.jsonl", elements), ("hierarchy.jsonl", hierarchy)):
            f = pub_dir / name
            if not f.is_file():
                problems.append(f"thiếu file {name}")
                continue
            rows, errs = read_jsonl(f)
            sink.extend(rows)
            problems.extend(f"{name}: {e}" for e in errs)

        arxiv_id = next((r["arxiv_id"] for r in hierarchy + elements
                         if isinstance(r.get("arxiv_id"), str) and r["arxiv_id"]), None)
        arxiv_id = arxiv_id or arxiv_id_from_folder(folder)
        start = len(self.issues)
        self.checked["V5"].add((arxiv_id, None))
        for p in problems:
            self._add("error", "V5", arxiv_id, None, p, owner, str(pub_dir))
        if config.pub_key(arxiv_id) != folder:
            self._add("error", "V5", arxiv_id, None,
                      f"tên thư mục '{folder}' không khớp pub_key của arxiv_id '{arxiv_id}'", owner, str(pub_dir))
        self.validate(elements, hierarchy, arxiv_id, pub_key=folder, n_versions=n_versions,
                      owner=owner, path=str(pub_dir))
        return self.issues[start:]

    def missing_publication(self, folder: str, owner: str, path: str) -> None:
        aid = arxiv_id_from_folder(folder)
        self.checked["V6"].add((aid, None))
        self._add("error", "V6", aid, None, "chưa có thư mục parsed cho bài này", owner, path)
        self.stats["missing_papers"] += 1

    # ---- báo cáo ---------------------------------------------------------- #
    def build_report(self, elapsed: float, n_papers: int, parsed_root: Path | None = None) -> dict:
        issues = sorted(self.issues, key=lambda i: (i.owner, i.arxiv_id, -1 if i.version is None else i.version, i.check))
        checks = {}
        for cid, (name, desc, basis) in CHECKS.items():
            errs = [i for i in issues if i.check == cid and i.severity == "error"]
            warns = [i for i in issues if i.check == cid and i.severity == "warning"]
            checks[cid] = {
                "name": name, "description": desc, "basis": basis,
                "status": "fail" if errs else "pass",
                "n_checked": len(self.checked[cid]),
                "n_failed": len({(i.arxiv_id, i.version) for i in errs}),
                "n_errors": len(errs), "n_warnings": len(warns),
            }
        by_owner: dict[str, dict] = {}
        for i in issues:
            o = by_owner.setdefault(i.owner or "(không rõ)", {"errors": 0, "warnings": 0, "_papers": set()})
            o["errors" if i.severity == "error" else "warnings"] += 1
            if i.severity == "error":
                o["_papers"].add(i.arxiv_id)
        for o in by_owner.values():
            o["papers_with_errors"] = len(o.pop("_papers"))
        n_err = sum(1 for i in issues if i.severity == "error")

        if self.dedup_ratios:
            dedup_stats = {
                "mean": round(float(statistics.mean(self.dedup_ratios)), 4),
                "median": round(float(statistics.median(self.dedup_ratios)), 4),
                "max": round(float(max(self.dedup_ratios)), 4),
                "min": round(float(min(self.dedup_ratios)), 4),
            }
        else:
            dedup_stats = {"mean": 0.0, "median": 0.0, "max": 0.0, "min": 0.0}

        named_checks = {
            "single_root": "pass" if checks["V1"]["status"] == "pass" else "fail",
            "no_orphan": "pass" if checks["V2"]["status"] == "pass" else "fail",
            "no_cycle": "pass" if checks["V3"]["status"] == "pass" else "fail",
            "unique_element_id": "pass" if (checks["V4"]["status"] == "pass" and checks["V5"]["status"] == "pass") else "fail",
            "dedup_effective": "pass" if not any(i.check == "V5" and "dedup" in i.message for i in issues if i.severity == "error") else "fail",
            "version_coverage": "pass" if checks["V6"]["status"] == "pass" else "fail",
        }

        return {
            "n_publications": n_papers,
            "n_versions": self.stats["versions"],
            "checks": named_checks,
            "detailed_checks": checks,
            "dedup_ratio": dedup_stats,
            "failures": [asdict(i) for i in issues if i.severity == "error"],
            "validator_version": VALIDATOR_M2_VERSION,
            "generated_at": config.now_iso(),
            "parsed_root": str(parsed_root) if parsed_root else None,
            "summary": {
                "passed": n_err == 0, "n_papers": n_papers,
                "n_versions": self.stats["versions"], "n_errors": n_err,
                "n_warnings": len(issues) - n_err, "elapsed_seconds": round(elapsed, 2),
            },
            "stats": {k: self.stats[k] for k in ("versions", "empty_versions", "elements", "edges", "missing_papers")},
            "by_owner": dict(sorted(by_owner.items())),
            "errors": [asdict(i) for i in issues],
        }


def validate_publication(elements: list[dict], hierarchy: list[dict], arxiv_id: str,
                         pub_key: str | None = None, n_versions: int | None = None) -> list[Issue]:
    """Tiện ích cho test: kiểm một publication, trả về danh sách vấn đề."""
    return ValidatorM2().validate(elements, hierarchy, arxiv_id, pub_key, n_versions)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def read_ids(path: Path) -> list[str]:
    if path.is_dir():
        all_ids: list[str] = []
        for f in sorted(path.glob("*.txt")):
            all_ids.extend(read_ids(f))
        return sorted(set(all_ids))
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    ids = [config.strip_version(s.strip()) for s in lines]
    return [i for i in ids if i and not i.startswith("#")]


def n_versions_from_corpus(corpus_root: Path, folder: str) -> int | None:
    meta = corpus_root / folder / "paper_meta.json"
    try:
        n = json.loads(meta.read_text(encoding="utf-8")).get("n_versions")
    except (OSError, ValueError):
        return None
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 1 else None


def print_summary(report: dict, out: Path, max_lines: int) -> None:
    s = report["summary"]
    bar = "=" * 64
    print(f"\n{bar}\nM2 VALIDATION  -  {'PASS' if s['passed'] else 'FAIL'}\n{bar}")
    print(f"Bài: {s['n_papers']}   Version: {s['n_versions']}   "
          f"Lỗi: {s['n_errors']}   Cảnh báo: {s['n_warnings']}   ({s['elapsed_seconds']}s)")
    if "dedup_ratio" in report:
        dr = report["dedup_ratio"]
        print(f"Dedup ratio: mean={dr['mean']:.4f}, median={dr['median']:.4f}, max={dr['max']:.4f}")
    detailed = report.get("detailed_checks", report.get("checks", {}))
    for cid, c in detailed.items():
        if isinstance(c, dict):
            mark = "PASS" if c.get("status") == "pass" else "FAIL"
            print(f"  {cid} {mark}  {c.get('name', cid):<14} kiểm {c.get('n_checked', 0):>5}  lỗi {c.get('n_errors', 0):>4}  cảnh báo {c.get('n_warnings', 0):>4}")
        else:
            mark = "PASS" if c == "pass" else "FAIL"
            print(f"  {cid:<20} {mark}")
    errors = [e for e in report.get("failures", [e for e in report.get("errors", []) if e.get("severity") == "error"])]
    for e in errors[:max_lines]:
        ver = f"v{e['version']}" if e.get("version") is not None else "-"
        print(f"  {e.get('check', '')} {e.get('arxiv_id', '')} {ver}: {e.get('message', '')}")
    if len(errors) > max_lines:
        print(f"  ... còn {len(errors) - max_lines} lỗi, xem đầy đủ trong file báo cáo")
    print(f"Báo cáo: {out}")


def default_parsed_root() -> Path:
    return Path(os.environ.get("PARSED_ROOT", config.PROJECT_ROOT / "parsed"))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Data Validation Suite cho đầu ra parser Milestone 2")
    ap.add_argument("--parsed", type=Path, default=default_parsed_root(), help="Thư mục parsed/ (mặc định: parsed/)")
    ap.add_argument("--corpus", type=Path, default=config.CORPUS_ROOT,
                    help="corpus/ của M1, đọc n_versions trong paper_meta.json (không có thì suy từ dữ liệu)")
    ap.add_argument("--ids", "--ids-file", dest="ids_file", type=Path, default=None,
                    help="ids/<mssv>.txt (hoặc thư mục ids/): chỉ kiểm các bài này, báo bài thiếu và gán người phụ trách")
    ap.add_argument("--limit", type=int, default=None, help="Giới hạn số bài kiểm tra (vd: --limit 20)")
    ap.add_argument("--out", type=Path, default=config.REPORTS_ROOT / "validation_m2.json")
    ap.add_argument("--strict", action="store_true", help="Coi cảnh báo như lỗi khi tính exit code")
    ap.add_argument("--max-print", type=int, default=40, help="Số lỗi in ra console")
    args = ap.parse_args(argv)

    if not args.parsed.is_dir():
        args.parsed.mkdir(parents=True, exist_ok=True)
    if args.ids_file is not None and not args.ids_file.exists():
        ap.error(f"không thấy file hoặc thư mục ID: {args.ids_file}")

    started = time.perf_counter()
    v = ValidatorM2()
    owner = args.ids_file.stem if (args.ids_file and args.ids_file.is_file()) else ""
    if args.ids_file:
        folders = [config.pub_key(i) for i in read_ids(args.ids_file)]
    else:
        folders = sorted(d.name for d in args.parsed.iterdir() if d.is_dir())
    if args.limit and args.limit > 0:
        folders = folders[:args.limit]
    for n, folder in enumerate(folders, 1):
        pub_dir = args.parsed / folder
        if not pub_dir.is_dir():
            v.missing_publication(folder, owner, str(pub_dir))
            continue
        v.validate_dir(pub_dir, n_versions_from_corpus(args.corpus, folder), owner)
        if n % 500 == 0:
            print(f"  [{n}/{len(folders)}] {len(v.issues)} vấn đề tới giờ", flush=True)

    report = v.build_report(time.perf_counter() - started, len(folders), args.parsed)
    out = write_report(report, args.out)
    print_summary(report, out, args.max_print)
    s = report["summary"]
    return 1 if (s["n_errors"] or (args.strict and s["n_warnings"])) else 0


if __name__ == "__main__":
    sys.exit(main())