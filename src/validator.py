"""validator.py - A2: Data Validation Suite cho corpus Milestone 1.

Chạy 7 nhóm kiểm tra trên một hoặc nhiều thư mục corpus và ghi reports/validation.json.
Mỗi lỗi đều có `arxiv_id` + `version` + mô tả (+ `owner` nếu đọc được ids/<mssv>.txt)
để người phụ trách sửa được ngay.

  C1  Đủ số thư mục version = n_versions trong paper_meta.json
  C2  Mọi version có >=1 .tex HOẶC _EMPTY.json hợp lệ (có lý do thuộc config.EMPTY_REASONS)
  C3  Không có file lạ ngoài .tex / .bib / .json
  C4  \\includegraphics và \\begin{figure} còn nguyên (so byte với archive trong raw/ nếu có)
  C5  paper_meta.json đủ 6 trường bảng `papers`, đúng kiểu
  C6  references.json đủ trường của bảng `references`, đúng kiểu
  C7  ID cũ (hep-th/9901001) không bị biến dạng; tên thư mục khớp config.pub_key

Mức độ: "error" làm exit code = 1; "warning" chỉ ghi nhận (dùng --strict để coi là lỗi).

Chạy (từ thư mục gốc dự án):
    python src/validator.py --ids-file ids/<mssv>.txt        # corpus/ mặc định + kiểm tra bài thiếu
    python src/validator.py --corpus corpus_a corpus_b ...   # gộp corpus của cả nhóm
    python src/validator.py --no-reextract                   # bỏ bước so với archive (nhanh hơn)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import config

try:  # dùng lại extractor để so file trong corpus với archive gốc (C4)
    import extractor
except Exception:  # noqa: BLE001 - thiếu extractor thì chỉ bỏ bước so sánh
    extractor = None

VALIDATOR_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Schema (docs/schema.md + crawling.md)
# --------------------------------------------------------------------------- #
PAPERS_FIELDS = ("arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue")
INTERNAL_FIELDS = ("n_versions", "latest_versioned_id", "discovered_at")

# Bảng `references`: arxiv_id là khóa nối với bài trích dẫn, 5 trường còn lại là nội dung
REF_KEY = "arxiv_id"
REF_FIELDS = ("ref_arxiv_id", "ref_title", "ref_authors", "ref_submission_date", "ref_s2_id")
REF_TOP_FIELDS = ("arxiv_id", "crawled_at", "status", "n_total", "n_with_arxiv", "references")
REF_STATUS_OK = "ok"
REF_STATUS_WARN = {"not_indexed"}                 # Semantic Scholar không có bài: hợp lệ nhưng cần biết
REF_STATUS_RERUN = {"rate_limited", "error"}      # lần crawl hỏng: phải chạy lại

EMPTY_FIELDS = ("arxiv_id", "version", "reason", "detail", "http_status", "fetched_at")

ALLOWED_EXT = {".tex", ".bib", ".json"}
VERSION_DIR = re.compile(r"^v(\d+)$")
NEW_ID = re.compile(r"^\d{4}\.\d{4,5}$")
OLD_ID = re.compile(r"^[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{7}$")
VERSION_SUFFIX = re.compile(r"v\d+$")

CHECKS: dict[str, tuple[str, str, str]] = {
    "C1": ("version_count", "Đủ số thư mục version bằng n_versions API báo",
           "all available versions must be crawled"),
    "C2": ("version_content", "Mọi version có >=1 .tex hoặc _EMPTY.json hợp lệ có ghi lý do",
           "keep an empty record rather than dropping"),
    "C3": ("stray_files", "Không có file lạ ngoài .tex/.bib/.json",
           "extract only the .tex and .bib files"),
    "C4": ("latex_intact", r"\includegraphics và \begin{figure} còn nguyên",
           "keep the LaTeX commands untouched"),
    "C5": ("paper_meta", "paper_meta.json đủ 6 trường bảng papers, đúng kiểu", "bảng `papers`"),
    "C6": ("references", "references.json đủ trường bảng references, đúng kiểu", "bảng `references`"),
    "C7": ("id_integrity", "ID cũ như hep-th/9901001 không bị biến dạng",
           "retain the original identifiers"),
}


# --------------------------------------------------------------------------- #
# Kiểu dữ liệu
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    check: str
    severity: str            # error | warning
    arxiv_id: str
    version: int | None
    message: str
    owner: str = ""
    path: str = ""


@dataclass
class Paper:
    dir: Path
    label: str                                   # arxiv_id dùng để báo lỗi
    meta: dict | None = None
    n_versions: int | None = None
    version_dirs: dict[int, Path] = field(default_factory=dict)

    @property
    def folder(self) -> str:
        return self.dir.name


# --------------------------------------------------------------------------- #
# Tiện ích
# --------------------------------------------------------------------------- #
def read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except FileNotFoundError:
        return None, "không tồn tại"
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"không đọc được: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"JSON hỏng: {exc}"


def is_iso(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def id_problem(value: Any, allow_version: bool = False) -> str | None:
    """Mô tả vì sao một arXiv ID bị biến dạng; None nếu hợp lệ."""
    if not isinstance(value, str) or not value:
        return "rỗng hoặc không phải chuỗi"
    if value != value.strip():
        return "thừa khoảng trắng đầu/cuối"
    if value.lower().startswith("arxiv:"):
        return "còn tiền tố 'arXiv:'"
    base = value
    if VERSION_SUFFIX.search(value):
        base = VERSION_SUFFIX.sub("", value)
        if (NEW_ID.match(base) or OLD_ID.match(base)) and not allow_version:
            return "còn hậu tố version (arxiv_id phải là ID gốc, không có vN)"
    if NEW_ID.match(base) or OLD_ID.match(base):
        return None
    if re.match(r"^[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?_\d{7}$", base):
        return "dấu '/' bị đổi thành '_' (đúng phải là dạng hep-th/9901001)"
    if re.match(r"^\d{4}-\d{4,5}$", base):
        return "dấu '.' bị đổi thành '-' (đúng phải là dạng 2310.12345)"
    if re.match(r"^[A-Za-z]+(?:-[A-Za-z]+)*(?:\.[A-Za-z]{2})?/\d{7}$", base):
        return "sai hoa/thường (tên archive phải viết thường, vd hep-th)"
    return "không khớp định dạng arXiv ID"


def strip_comments(text: str) -> str:
    """Bỏ phần comment LaTeX (% không có \\ đứng trước) để đếm lệnh chính xác."""
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", ln) for ln in text.splitlines())


FIG_BEGIN = re.compile(r"\\begin\s*\{figure\*?\}")
FIG_END = re.compile(r"\\end\s*\{figure\*?\}")
INCLUDEGRAPHICS = re.compile(r"\\includegraphics\b")


def find_archive(raw_root: Path, folder: str, version: int) -> Path | None:
    """Archive hoàn chỉnh của một version trong raw/<pub_key>/v<n>.*"""
    d = raw_root / folder
    if not d.is_dir():
        return None
    for path in sorted(d.glob(f"v{version}.*")):
        if not path.name.endswith(".part") and path.is_file() and path.stat().st_size > 0:
            return path
    return None


def display_path(path: Path, anchor: Path) -> str:
    """Đường dẫn tương đối (không lộ thư mục cá nhân) để ghi vào báo cáo."""
    path = Path(path)
    for base in (config.PROJECT_ROOT, anchor):
        try:
            return path.resolve().relative_to(Path(base).resolve()).as_posix()
        except (ValueError, OSError):
            continue
    return path.name


def load_expected(ids_path: Path | None) -> dict[str, dict]:
    """Đọc ID mong đợi từ một thư mục ids/*.txt hoặc một file .txt cụ thể."""
    expected: dict[str, dict] = {}
    if not ids_path:
        return expected
    ids_path = Path(ids_path)
    files = sorted(ids_path.glob("*.txt")) if ids_path.is_dir() else [ids_path]
    for f in files:
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.lower().startswith("arxiv:"):
                s = s[6:].strip()
            s = config.strip_version(s)
            if s:
                e = expected.setdefault(config.pub_key(s), {"arxiv_id": s, "owners": set()})
                e["owners"].add(f.stem)
    return expected


# --------------------------------------------------------------------------- #
# Validator
# --------------------------------------------------------------------------- #
class Validator:
    def __init__(
        self,
        corpus_roots: list[Path],
        ids_dir: Path | None = None,
        raw_root: Path | None = None,
        reextract: bool = True,
        progress: bool = False,
    ) -> None:
        self.progress = progress
        self.corpus_roots = [Path(p) for p in corpus_roots]
        self.expected = load_expected(ids_dir)
        self.raw_root = Path(raw_root) if raw_root else None
        self.reextract = bool(reextract and extractor is not None and self.raw_root)
        self.issues: list[Issue] = []
        self.checked: dict[str, set] = {c: set() for c in CHECKS}
        self.stats: Counter = Counter()
        if extractor is not None:
            logging.getLogger("extractor").setLevel(logging.ERROR)

    # ---- ghi nhận ------------------------------------------------------- #
    def owner_of(self, folder: str) -> str:
        e = self.expected.get(folder)
        return ",".join(sorted(e["owners"])) if e else ""

    def add(self, p: Paper, check: str, severity: str, version: int | None, message: str,
            path: Path | None = None) -> None:
        self.issues.append(Issue(
            check=check, severity=severity, arxiv_id=p.label, version=version,
            message=message, owner=self.owner_of(p.folder),
            path=display_path(path or p.dir, p.dir.parent.parent),
        ))

    def touch(self, check: str, p: Paper, version: int | None = None) -> None:
        self.checked[check].add((p.label, version))

    def error(self, p: Paper, check: str, version: int | None, message: str, path: Path | None = None) -> None:
        self.add(p, check, "error", version, message, path)

    def warn(self, p: Paper, check: str, version: int | None, message: str, path: Path | None = None) -> None:
        self.add(p, check, "warning", version, message, path)

    # ---- C5: paper_meta.json -------------------------------------------- #
    def check_meta(self, p: Paper) -> None:
        c = "C5"
        self.touch(c, p)
        path = p.dir / "paper_meta.json"
        meta, err = read_json(path)
        if err:
            self.error(p, c, None, f"paper_meta.json {err}", path)
            return
        if not isinstance(meta, dict):
            self.error(p, c, None, "paper_meta.json phải là một object JSON", path)
            return
        p.meta = meta
        if isinstance(meta.get("arxiv_id"), str) and meta["arxiv_id"].strip():
            p.label = meta["arxiv_id"].strip()

        for f in PAPERS_FIELDS + INTERNAL_FIELDS:
            if f not in meta:
                self.error(p, c, None, f"thiếu trường '{f}'", path)

        def bad(msg: str) -> None:
            self.error(p, c, None, msg, path)

        if "arxiv_id" in meta and not (isinstance(meta["arxiv_id"], str) and meta["arxiv_id"].strip()):
            bad("arxiv_id phải là chuỗi không rỗng")
        if "title" in meta and not (isinstance(meta["title"], str) and meta["title"].strip()):
            bad("title phải là chuỗi không rỗng")
        if "authors" in meta:
            if not is_str_list(meta["authors"]):
                bad("authors phải là list[str]")
            elif not meta["authors"]:
                self.warn(p, c, None, "authors rỗng (API không trả tác giả?)", path)
        if "submission_date" in meta:
            sd = meta["submission_date"]
            if sd is None:
                self.warn(p, c, None, "submission_date = null", path)
            elif not is_iso(sd):
                bad(f"submission_date không phải chuỗi ISO 8601: {sd!r}")
        if "revised_dates" in meta:
            rd = meta["revised_dates"]
            if not is_str_list(rd):
                bad("revised_dates phải là list[str]")
            else:
                for d in rd:
                    if not is_iso(d):
                        bad(f"revised_dates chứa giá trị không phải ISO 8601: {d!r}")
        if "venue" in meta:
            v = meta["venue"]
            if v is not None and not isinstance(v, str):
                bad("venue phải là chuỗi hoặc null")
            elif isinstance(v, str) and (not v.strip() or v.strip() == "None"):
                bad(f'venue nullable: ghi null, không ghi {v!r}')
        if "n_versions" in meta:
            n = meta["n_versions"]
            if not is_int(n) or n < 1:
                bad(f"n_versions phải là số nguyên >= 1, đang là {n!r}")
            else:
                p.n_versions = n
        if "latest_versioned_id" in meta and not isinstance(meta["latest_versioned_id"], str):
            bad("latest_versioned_id phải là chuỗi")
        if "discovered_at" in meta and not is_iso(meta["discovered_at"]):
            bad(f"discovered_at không phải ISO 8601: {meta['discovered_at']!r}")
        if "revised_dates_complete" in meta and not isinstance(meta["revised_dates_complete"], bool):
            bad("revised_dates_complete phải là bool")

    # ---- C7: toàn vẹn ID -------------------------------------------------- #
    def check_ids(self, p: Paper) -> None:
        c = "C7"
        self.touch(c, p)
        meta = p.meta
        if meta is not None and "arxiv_id" in meta:
            prob = id_problem(meta["arxiv_id"])
            if prob:
                self.error(p, c, None, f"arxiv_id {meta['arxiv_id']!r} bị biến dạng: {prob}",
                           p.dir / "paper_meta.json")
            elif config.pub_key(meta["arxiv_id"]) != p.folder:
                self.error(p, c, None,
                           f"tên thư mục '{p.folder}' không khớp config.pub_key"
                           f"({meta['arxiv_id']!r}) = '{config.pub_key(meta['arxiv_id'])}'", p.dir)
            lid, n = meta.get("latest_versioned_id"), p.n_versions
            if isinstance(lid, str) and isinstance(meta["arxiv_id"], str) and n is not None:
                want = f"{meta['arxiv_id']}v{n}"
                if lid != want:
                    self.error(p, c, None, f"latest_versioned_id={lid!r} nhưng phải là {want!r}",
                               p.dir / "paper_meta.json")
        elif meta is None:
            # Không có meta: ít nhất tên thư mục phải trông giống một pub_key hợp lệ
            if not (re.match(r"^\d{4}-\d{4,5}$", p.folder) or re.match(r"^[a-z.\-A-Z]+_\d{7}$", p.folder)):
                self.error(p, c, None, f"tên thư mục '{p.folder}' không giống pub_key của ID nào", p.dir)

        if self.expected and p.folder not in self.expected:
            self.warn(p, c, None, f"thư mục '{p.folder}' không khớp ID nào trong ids/*.txt", p.dir)

    # ---- C1: số thư mục version ------------------------------------------ #
    def check_versions(self, p: Paper) -> None:
        c = "C1"
        self.touch(c, p)
        for e in sorted(p.dir.iterdir()):
            m = VERSION_DIR.match(e.name)
            if e.is_dir() and m and e.name == f"v{int(m.group(1))}":
                p.version_dirs[int(m.group(1))] = e
        if p.n_versions is None:
            return  # không biết n_versions (C5 đã báo lỗi)
        want, have = set(range(1, p.n_versions + 1)), set(p.version_dirs)
        for v in sorted(want - have):
            self.error(p, c, v, f"thiếu thư mục v{v} (paper_meta báo n_versions={p.n_versions}, "
                                f"corpus chỉ có {sorted(have) or 'không có version nào'})", p.dir / f"v{v}")
        for v in sorted(have - want):
            self.error(p, c, v, f"thừa thư mục v{v} (n_versions={p.n_versions})", p.version_dirs[v])

    # ---- C2 + C4: nội dung từng version ----------------------------------- #
    def check_version(self, p: Paper, v: int, vdir: Path) -> None:
        files = [f for f in vdir.rglob("*") if f.is_file()]
        tex = sorted(f for f in files if f.suffix.lower() == ".tex")
        bib = [f for f in files if f.suffix.lower() == ".bib"]
        marker = vdir / "_EMPTY.json"
        self.stats["versions"] += 1

        c = "C2"
        self.touch(c, p, v)
        marker_ok = False
        if marker.exists():
            problems = self.empty_marker_problems(p, v, marker)
            marker_ok = not problems
            if problems:
                self.error(p, c, v, "_EMPTY.json không hợp lệ: " + "; ".join(problems), marker)
            if tex:
                self.warn(p, c, v, f"vừa có _EMPTY.json vừa có {len(tex)} file .tex (mâu thuẫn)", marker)
        if not tex and not marker.exists():
            hint = " (chỉ có .bib)" if bib else ""
            self.error(p, c, v, f"không có file .tex và không có _EMPTY.json{hint}", vdir)
        if marker_ok and not tex:
            self.stats["empty_versions"] += 1
        if tex:
            self.stats["versions_with_tex"] += 1

        if tex:
            self.check_latex(p, v, vdir, tex)

    def empty_marker_problems(self, p: Paper, v: int, marker: Path) -> list[str]:
        data, err = read_json(marker)
        if err:
            return [err]
        if not isinstance(data, dict):
            return ["phải là một object JSON"]
        out = [f"thiếu trường '{f}'" for f in EMPTY_FIELDS if f not in data]
        reason = data.get("reason")
        if "reason" in data and reason not in config.EMPTY_REASONS:
            out.append(f"reason={reason!r} không thuộc {list(config.EMPTY_REASONS)}")
        if "version" in data and (not is_int(data["version"]) or data["version"] != v):
            out.append(f"version={data['version']!r} khác thư mục v{v}")
        if "arxiv_id" in data:
            prob = id_problem(data["arxiv_id"])
            if prob:
                out.append(f"arxiv_id {data['arxiv_id']!r} bị biến dạng: {prob}")
            elif p.meta and data["arxiv_id"] != p.meta.get("arxiv_id"):
                out.append(f"arxiv_id={data['arxiv_id']!r} khác paper_meta ({p.meta.get('arxiv_id')!r})")
        if "detail" in data and not isinstance(data["detail"], str):
            out.append("detail phải là chuỗi")
        if "http_status" in data and data["http_status"] is not None and not is_int(data["http_status"]):
            out.append("http_status phải là số nguyên hoặc null")
        if "fetched_at" in data and not is_iso(data["fetched_at"]):
            out.append(f"fetched_at không phải ISO 8601: {data['fetched_at']!r}")
        return out

    def check_latex(self, p: Paper, v: int, vdir: Path, tex: list[Path]) -> None:
        c = "C4"
        self.touch(c, p, v)
        begin = end = inc = 0
        for f in tex:
            text = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
            begin += len(FIG_BEGIN.findall(text))
            end += len(FIG_END.findall(text))
            inc += len(INCLUDEGRAPHICS.findall(text))
        self.stats["figure_envs"] += begin
        self.stats["includegraphics"] += inc
        if begin == 0 and inc == 0:
            self.stats["versions_without_figures"] += 1
        if begin != end:
            self.warn(p, c, v, rf"số \begin{{figure}} ({begin}) khác số \end{{figure}} ({end}): "
                               "figure có thể bị cắt cụt (bỏ qua nếu nằm trong verbatim/macro)", vdir)

        if not self.reextract:
            return
        archive = find_archive(self.raw_root, p.folder, v)
        if archive is None:
            self.stats["reextract_skipped"] += 1
            return
        self.stats["reextract_compared"] += 1
        with tempfile.TemporaryDirectory() as tmp:
            try:
                res = extractor.extract_archive(archive, tmp)
            except Exception as exc:  # noqa: BLE001
                self.warn(p, c, v, f"không giải nén lại được {archive.name} để so sánh: {exc}", archive)
                return
            for rel in res.kept_files:
                src, dst = Path(tmp) / rel, vdir / rel
                if not dst.is_file():
                    self.error(p, c, v, f"file '{rel}' có trong archive nhưng thiếu trong corpus", dst)
                elif src.read_bytes() != dst.read_bytes():
                    self.error(p, c, v, f"file '{rel}' khác archive gốc (nội dung bị sửa hoặc bị ghi đè)", dst)

    # ---- C3: file lạ ------------------------------------------------------ #
    def check_stray(self, p: Paper) -> None:
        c = "C3"
        self.touch(c, p)
        for e in sorted(p.dir.iterdir()):
            if e.is_file():
                if e.suffix.lower() not in ALLOWED_EXT:
                    self.error(p, c, None, f"file lạ ở thư mục bài: '{e.name}'", e)
            elif e.is_dir() and e.name not in {d.name for d in p.version_dirs.values()}:
                self.warn(p, c, None, f"thư mục lạ '{e.name}' (không phải vN hợp lệ)", e)
        for v, vdir in sorted(p.version_dirs.items()):
            self.touch(c, p, v)
            for f in sorted(vdir.rglob("*")):
                if f.is_file() and f.suffix.lower() not in ALLOWED_EXT:
                    rel = f.relative_to(vdir).as_posix()
                    self.error(p, c, v, f"file lạ '{rel}' (chỉ cho phép .tex/.bib/.json)", f)

    # ---- C6 (+ phần ID của C7): references.json ---------------------------- #
    def check_references(self, p: Paper) -> None:
        c = "C6"
        self.touch(c, p)
        path = p.dir / "references.json"
        data, err = read_json(path)
        if err:
            self.error(p, c, None, f"references.json {err}", path)
            return

        if isinstance(data, dict):
            for f in REF_TOP_FIELDS:
                if f not in data:
                    self.error(p, c, None, f"references.json thiếu trường '{f}'", path)
            refs, status = data.get("references"), data.get("status")
            if "arxiv_id" in data and data["arxiv_id"] != p.label:
                prob = id_problem(data["arxiv_id"])
                self.error(p, "C7", None,
                           f"references.json: arxiv_id={data['arxiv_id']!r} khác paper_meta ({p.label!r})"
                           + (f"; {prob}" if prob else ""), path)
            if status in REF_STATUS_RERUN:
                self.error(p, c, None, f"status='{status}': lần crawl hỏng, cần chạy lại "
                                       "reference_builder.py --overwrite", path)
            elif status in REF_STATUS_WARN:
                self.warn(p, c, None, f"status='{status}': Semantic Scholar không có bài này "
                                      "(references rỗng)", path)
            elif "status" in data and status != REF_STATUS_OK:
                self.error(p, c, None, f"status={status!r} không nhận ra được", path)
        elif isinstance(data, list):
            refs, status = data, REF_STATUS_OK
        else:
            self.error(p, c, None, "references.json phải là object hoặc list", path)
            return

        if not isinstance(refs, list):
            if isinstance(data, dict) and "references" in data:
                self.error(p, c, None, "'references' phải là list", path)
            return

        if isinstance(data, dict):
            if "n_total" in data and (not is_int(data["n_total"]) or data["n_total"] != len(refs)):
                self.error(p, c, None, f"n_total={data['n_total']!r} nhưng có {len(refs)} reference", path)
            if "n_with_arxiv" in data:
                actual = sum(1 for r in refs if isinstance(r, dict) and r.get("ref_arxiv_id"))
                if not is_int(data["n_with_arxiv"]) or data["n_with_arxiv"] != actual:
                    self.error(p, c, None, f"n_with_arxiv={data['n_with_arxiv']!r} nhưng đếm được {actual}", path)

        self.stats["references"] += len(refs)
        prob6: dict[str, list[int]] = defaultdict(list)
        prob7: dict[str, list[int]] = defaultdict(list)
        for i, ref in enumerate(refs):
            for msg in self.ref_problems(ref, p.label, prob7, i):
                prob6[msg].append(i)

        def emit(check: str, table: dict[str, list[int]]) -> None:
            for msg, idx in table.items():
                sample = ", ".join(f"#{k}" for k in idx[:3]) + (" ..." if len(idx) > 3 else "")
                self.error(p, check, None, f"{msg} ({len(idx)} reference, vd {sample})", path)

        emit(c, prob6)
        emit("C7", prob7)

    @staticmethod
    def ref_problems(ref: Any, label: str, prob7: dict[str, list[int]], i: int) -> list[str]:
        if not isinstance(ref, dict):
            return ["reference không phải object"]
        out = []
        missing = [f for f in (REF_KEY,) + REF_FIELDS if f not in ref]
        if missing:
            out.append("thiếu trường " + ", ".join(missing))
        if REF_KEY in ref and ref[REF_KEY] != label:
            out.append(f"arxiv_id={ref[REF_KEY]!r} khác ID bài trích dẫn ({label!r})")
        for f in ("ref_arxiv_id", "ref_title", "ref_submission_date", "ref_s2_id"):
            v = ref.get(f)
            if f in ref and v is not None and (not isinstance(v, str) or not v.strip()):
                out.append(f"{f} phải là chuỗi không rỗng hoặc null")
        if "ref_authors" in ref and not is_str_list(ref["ref_authors"]):
            out.append("ref_authors phải là list[str]")
        if "has_arxiv_id" in ref:
            if not isinstance(ref["has_arxiv_id"], bool):
                out.append("has_arxiv_id phải là bool")
            elif ref["has_arxiv_id"] != bool(ref.get("ref_arxiv_id")):
                out.append("has_arxiv_id không khớp với ref_arxiv_id")
        rid = ref.get("ref_arxiv_id")
        if isinstance(rid, str) and rid:
            prob = id_problem(rid, allow_version=True)
            if prob:
                prob7[f"ref_arxiv_id bị biến dạng ({prob})"].append(i)
        return out

    # ---- điều phối --------------------------------------------------------- #
    def run(self) -> dict:
        started = time.perf_counter()
        folders: dict[str, list[Path]] = defaultdict(list)
        for root in self.corpus_roots:
            for e in sorted(root.iterdir()):
                if e.is_dir() and not e.name.startswith("."):
                    folders[e.name].append(e)

        total = len(folders)
        if self.progress:
            mode = "có so với archive gốc (chậm hơn)" if self.reextract else "không so với archive gốc"
            print(f"Đang kiểm tra {total} bài, {mode}...", flush=True)
        for n, (name, dirs) in enumerate(sorted(folders.items()), 1):
            if len(dirs) > 1:
                p = Paper(dir=dirs[0], label=name)
                self.touch("C1", p)
                self.warn(p, "C1", None, "bài xuất hiện ở nhiều corpus: " + ", ".join(map(str, dirs)))
            p = Paper(dir=dirs[0], label=name)
            self.stats["papers"] += 1
            self.check_meta(p)
            self.check_ids(p)
            self.check_versions(p)
            for v, vdir in sorted(p.version_dirs.items()):
                self.check_version(p, v, vdir)
            self.check_stray(p)
            self.check_references(p)
            if self.progress and (n % 250 == 0 or n == total):
                print(f"  [{n}/{total}] {time.perf_counter() - started:.0f}s, "
                      f"{len(self.issues)} vấn đề tới giờ", flush=True)

        for key, e in sorted(self.expected.items()):
            if key not in folders:
                p = Paper(dir=self.corpus_roots[0] / key, label=e["arxiv_id"])
                self.touch("C1", p)
                self.error(p, "C1", None, f"không có thư mục bài trong corpus (ID có trong ids/ của "
                                          f"{','.join(sorted(e['owners']))})", p.dir)
                self.stats["missing_papers"] += 1
        return self.build_report(time.perf_counter() - started)

    # ---- báo cáo ------------------------------------------------------------ #
    def build_report(self, elapsed: float) -> dict:
        issues = sorted(self.issues, key=lambda i: (i.owner, i.arxiv_id, -1 if i.version is None else i.version, i.check))
        checks = {}
        for cid, (name, desc, basis) in CHECKS.items():
            errs = [i for i in issues if i.check == cid and i.severity == "error"]
            warns = [i for i in issues if i.check == cid and i.severity == "warning"]
            checks[cid] = {
                "name": name,
                "description": desc,
                "basis": basis,
                "status": "fail" if errs else "pass",
                "n_checked": len(self.checked[cid]),
                "n_failed": len({(i.arxiv_id, i.version) for i in errs}),
                "n_errors": len(errs),
                "n_warnings": len(warns),
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
        return {
            "validator_version": VALIDATOR_VERSION,
            "generated_at": config.now_iso(),
            "corpus_roots": [display_path(p, p.parent) for p in self.corpus_roots],
            "ids_checked_against": sorted({o for e in self.expected.values() for o in e["owners"]}),
            "reextract_against_raw": self.reextract,
            "summary": {
                "passed": n_err == 0,
                "n_papers": self.stats["papers"],
                "n_versions": self.stats["versions"],
                "n_errors": n_err,
                "n_warnings": len(issues) - n_err,
                "elapsed_seconds": round(elapsed, 2),
            },
            "checks": checks,
            "stats": {k: self.stats[k] for k in (
                "papers", "versions", "versions_with_tex", "empty_versions", "missing_papers",
                "figure_envs", "includegraphics", "versions_without_figures",
                "reextract_compared", "reextract_skipped", "references")},
            "by_owner": dict(sorted(by_owner.items())),
            "errors": [asdict(i) for i in issues],
        }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def default_raw_root() -> Path:
    import os
    return Path(os.environ.get("RAW_ROOT", config.PROJECT_ROOT / "raw"))


def write_report(report: dict, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out


def print_summary(report: dict, out: Path, max_lines: int) -> None:
    s = report["summary"]
    bar = "=" * 64
    print(f"\n{bar}\nDATA VALIDATION  -  {'PASS' if s['passed'] else 'FAIL'}\n{bar}")
    print(f"Bài: {s['n_papers']}   Version: {s['n_versions']}   "
          f"Lỗi: {s['n_errors']}   Cảnh báo: {s['n_warnings']}   ({s['elapsed_seconds']}s)")
    for cid, c in report["checks"].items():
        mark = "PASS" if c["status"] == "pass" else "FAIL"
        print(f"  {cid} {mark}  {c['name']:<16} kiểm {c['n_checked']:>5}  lỗi {c['n_errors']:>4}  cảnh báo {c['n_warnings']:>4}")
    if len(report["by_owner"]) > 1 or "(không rõ)" not in report["by_owner"]:
        print("Theo người phụ trách:")
        for o, v in report["by_owner"].items():
            print(f"  {o:<14} lỗi {v['errors']:>4}  cảnh báo {v['warnings']:>4}  ({v['papers_with_errors']} bài lỗi)")
    errors = [e for e in report["errors"] if e["severity"] == "error"]
    for e in errors[:max_lines]:
        ver = f"v{e['version']}" if e["version"] is not None else "-"
        who = f"[{e['owner']}] " if e["owner"] else ""
        print(f"  {e['check']} {who}{e['arxiv_id']} {ver}: {e['message']}")
    if len(errors) > max_lines:
        print(f"  ... còn {len(errors) - max_lines} lỗi, xem đầy đủ trong file báo cáo")
    print(f"Báo cáo: {out}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Data Validation Suite cho corpus Milestone 1")
    ap.add_argument("--corpus", nargs="+", type=Path, default=[config.CORPUS_ROOT],
                    help="Một hoặc nhiều thư mục corpus (mặc định: corpus/)")
    ap.add_argument("--ids-file", type=Path, default=None,
                    help="File ids/<mssv>.txt của bạn: kiểm tra bài thiếu và gán người phụ trách")
    ap.add_argument("--ids-dir", type=Path,
                    help="Đọc toàn bộ ids/*.txt thay cho --ids-file")
    ap.add_argument("--no-ids", action="store_true", help="Không đọc danh sách ID mong đợi")
    ap.add_argument("--raw-root", type=Path, default=default_raw_root(),
                    help="Thư mục raw/ chứa archive gốc để so với corpus (C4)")
    ap.add_argument("--no-reextract", action="store_true", help="Bỏ bước so file với archive gốc")
    ap.add_argument("--out", type=Path, default=config.REPORTS_ROOT / "validation.json")
    ap.add_argument("--strict", action="store_true", help="Coi cảnh báo như lỗi khi tính exit code")
    ap.add_argument("--max-print", type=int, default=40, help="Số lỗi in ra console")
    args = ap.parse_args(argv)

    for root in args.corpus:
        if not root.is_dir():
            ap.error(f"không thấy thư mục corpus: {root}")

    expected_ids = None if args.no_ids else (args.ids_dir or args.ids_file)
    if expected_ids is not None and not Path(expected_ids).exists():
        ap.error(f"không thấy file/thư mục ID: {expected_ids}")
    if expected_ids is None and not args.no_ids:
        print("Gợi ý: thêm --ids-file ids/<mssv>.txt để kiểm tra bài thiếu và gán người phụ trách.")
    v = Validator(args.corpus, expected_ids, args.raw_root,
                  reextract=not args.no_reextract and Path(args.raw_root).is_dir(), progress=True)
    if not args.no_reextract and not Path(args.raw_root).is_dir():
        print(f"Không thấy {args.raw_root}: bỏ bước so với archive gốc (C4 chỉ kiểm cấu trúc figure).")
    report = v.run()
    out = write_report(report, args.out)
    print_summary(report, out, args.max_print)
    s = report["summary"]
    return 1 if (s["n_errors"] or (args.strict and s["n_warnings"])) else 0


if __name__ == "__main__":
    sys.exit(main())