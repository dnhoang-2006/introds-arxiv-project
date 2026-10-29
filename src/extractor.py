"""extractor.py - Giải nén archive arXiv và chỉ giữ lại file .tex / .bib.

Nguyên tắc:
  * KHÔNG sửa nội dung file TeX. Figure bị loại chỉ vì ta không extract file ảnh,
    còn `\\begin{figure}` và `\\includegraphics` trong .tex vẫn nguyên vẹn
    (Milestone 2 cần chúng).
  * Đo dung lượng archive TRƯỚC khi lọc và tổng dung lượng SAU khi lọc, ghi vào log.
  * Ghi lại mọi ca lạ (archive không phải tar, .tex trong thư mục con, tên trùng...)
    để tuần 2 biến thành test case.
"""

from __future__ import annotations

import gzip
import io
import logging
import os
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List

try:  # import như package (from src.extractor import ...)
    from .config import EMPTY_REASONS, KEEP_EXTENSIONS
except ImportError:  # chạy trực tiếp: python src/extractor.py
    from config import EMPTY_REASONS, KEEP_EXTENSIONS  # hằng số dùng chung (schema.md)

logger = logging.getLogger("extractor")

# Đầu file PDF -> version chỉ có PDF, không có source
PDF_MAGIC = b"%PDF"


@dataclass
class ExtractionResult:
    """Kết quả giải nén một archive (tương ứng một version)."""

    archive_path: str
    archive_format: str = "unknown"      # tar | tar.gz | gzip-single | zip | pdf | unknown
    size_before: int = 0                  # dung lượng file archive (bytes), đo TRƯỚC lọc
    size_after: int = 0                   # tổng dung lượng file giữ lại (bytes), SAU lọc
    members_total: int = 0                # số member trong archive
    kept_files: List[str] = field(default_factory=list)      # đường dẫn tương đối đã ghi
    skipped_files: List[str] = field(default_factory=list)   # member bị loại
    anomalies: List[str] = field(default_factory=list)       # ca lạ -> test case tuần 2
    empty_reason: str | None = None       # mã lý do theo schema.md §2 (None nếu có nội dung)
    empty_detail: str | None = None       # mô tả chi tiết cho _EMPTY.json

    @property
    def is_empty(self) -> bool:
        return not self.kept_files

    @property
    def n_tex(self) -> int:
        return sum(1 for f in self.kept_files if f.lower().endswith(".tex"))

    @property
    def n_bib(self) -> int:
        return sum(1 for f in self.kept_files if f.lower().endswith(".bib"))

    @property
    def status(self) -> str:
        """status của logs/extract.csv: ok | fail | empty."""
        if not self.is_empty:
            return "ok"
        return "fail" if self.empty_reason in ("corrupt_archive", "other") else "empty"

    @property
    def error_type(self) -> str:
        """error_type của logs/extract.csv: rỗng khi status = ok."""
        return "" if self.status == "ok" else (self.empty_reason or "other")


def _set_empty(result: "ExtractionResult", reason: str, detail: str) -> None:
    assert reason in EMPTY_REASONS, reason
    result.empty_reason = reason
    result.empty_detail = detail


# --------------------------------------------------------------------------- #
# Hàm tiện ích
# --------------------------------------------------------------------------- #
def _should_keep(member_name: str) -> bool:
    """Chỉ giữ .tex và .bib (không phân biệt hoa thường)."""
    return PurePosixPath(member_name.replace("\\", "/")).suffix.lower() in KEEP_EXTENSIONS


def _is_safe_member(name: str) -> bool:
    """Chặn path traversal (../, đường dẫn tuyệt đối, backslashes, ổ đĩa Windows)."""
    norm = name.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", norm):  # ổ đĩa kiểu C:/...
        return False
    p = PurePosixPath(norm)
    return not p.is_absolute() and ".." not in p.parts


def _unique_path(dest_dir: Path, rel_name: str, result: ExtractionResult, seen: set[str]) -> Path:
    """Tránh ghi đè khi cùng archive có 2 member trùng tên (không phân biệt hoa/thường,
    vì macOS/Windows coi `Main.tex` và `main.tex` là một file)."""
    norm = rel_name.replace("\\", "/")
    target = dest_dir / norm
    key = target.as_posix().lower()
    if key not in seen:
        seen.add(key)
        return target
    stem, suffix = target.stem, target.suffix
    i = 1
    while True:
        candidate = target.with_name(f"{stem}__dup{i}{suffix}")
        ckey = candidate.as_posix().lower()
        if ckey not in seen:
            seen.add(ckey)
            result.anomalies.append(f"DUPLICATE_NAME: {rel_name} -> {candidate.name}")
            return candidate
        i += 1


def _write_kept(dest_dir: Path, rel_name: str, data: bytes, result: ExtractionResult, seen: set[str]) -> None:
    target = _unique_path(dest_dir, rel_name, result, seen)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)  # ghi nguyên byte, không đụng nội dung
    result.kept_files.append(target.relative_to(dest_dir).as_posix())
    result.size_after += len(data)
    norm = rel_name.replace("\\", "/")
    if "/" in norm:
        result.anomalies.append(f"NESTED_FILE: {norm} nằm trong thư mục con")


# --------------------------------------------------------------------------- #
# Các định dạng archive
# --------------------------------------------------------------------------- #
def _extract_tar(path: Path, dest_dir: Path, result: ExtractionResult, seen: set[str]) -> None:
    with tarfile.open(path, mode="r:*") as tf:  # r:* tự nhận gz/bz2/xz/không nén
        members = tf.getmembers()
        result.members_total = len(members)
        for m in members:
            if not m.isfile():
                continue
            if not _is_safe_member(m.name):
                result.anomalies.append(f"UNSAFE_PATH: {m.name}")
                result.skipped_files.append(m.name)
                continue
            if not _should_keep(m.name):
                result.skipped_files.append(m.name)
                continue
            fobj = tf.extractfile(m)
            if fobj is None:
                result.anomalies.append(f"UNREADABLE_MEMBER: {m.name}")
                continue
            _write_kept(dest_dir, m.name, fobj.read(), result, seen)


def _extract_zip(path: Path, dest_dir: Path, result: ExtractionResult, seen: set[str]) -> None:
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        result.members_total = len(infos)
        for info in infos:
            if not _is_safe_member(info.filename):
                result.anomalies.append(f"UNSAFE_PATH: {info.filename}")
                result.skipped_files.append(info.filename)
                continue
            if not _should_keep(info.filename):
                result.skipped_files.append(info.filename)
                continue
            _write_kept(dest_dir, info.filename, zf.read(info), result, seen)


def _extract_gzip_single(path: Path, dest_dir: Path, result: ExtractionResult, seen: set[str]) -> None:
    """arXiv đôi khi trả về một file .tex đơn được gzip (không phải tar).

    Trường hợp gzip chứa tar đã được `_detect_format` nhận là "tar.gz" và xử lý
    ở `_extract_tar`, nên ở đây chỉ còn: gzip của PDF hoặc gzip của một file text.
    """
    raw = gzip.decompress(path.read_bytes())
    result.members_total = 1

    if raw[:4] == PDF_MAGIC:
        _set_empty(result, "pdf_only", "Archive gzip chứa 1 file PDF, không có .tex")
        result.skipped_files.append("<pdf inside gzip>")
        return

    # Nội dung đơn là text -> coi là một file .tex duy nhất
    result.anomalies.append("SINGLE_GZIP_TEX: archive là gzip của một file đơn, không phải tar")
    _write_kept(dest_dir, "main.tex", raw, result, seen)


def _detect_format(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:4] == PDF_MAGIC:
        return "pdf"
    if zipfile.is_zipfile(path):
        return "zip"
    if head[:2] == b"\x1f\x8b":
        return "tar.gz" if tarfile.is_tarfile(path) else "gzip-single"
    if tarfile.is_tarfile(path):
        return "tar"
    return "unknown"


# --------------------------------------------------------------------------- #
# API chính
# --------------------------------------------------------------------------- #
def extract_archive(archive_path: str | os.PathLike, dest_dir: str | os.PathLike) -> ExtractionResult:
    """Giải nén `archive_path` vào `dest_dir`, chỉ giữ .tex/.bib.

    Luôn đo `size_before` (dung lượng archive) trước khi lọc.
    """
    archive_path = Path(archive_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    result = ExtractionResult(archive_path=str(archive_path))
    result.size_before = archive_path.stat().st_size  # <-- đo TRƯỚC khi lọc (bắt buộc)

    fmt = _detect_format(archive_path)
    result.archive_format = fmt
    seen: set[str] = set()

    try:
        if fmt == "pdf":
            _set_empty(result, "pdf_only", "Archive chứa 1 file PDF, không có .tex")
            result.members_total = 1
            result.skipped_files.append(archive_path.name)
        elif fmt == "zip":
            result.anomalies.append("NON_TAR_ARCHIVE: zip")
            _extract_zip(archive_path, dest_dir, result, seen)
        elif fmt in ("tar", "tar.gz"):
            _extract_tar(archive_path, dest_dir, result, seen)
        elif fmt == "gzip-single":
            result.anomalies.append("NON_TAR_ARCHIVE: gzip đơn")
            _extract_gzip_single(archive_path, dest_dir, result, seen)
        else:
            result.anomalies.append("UNKNOWN_FORMAT: không nhận dạng được archive")
            _set_empty(result, "corrupt_archive", "Định dạng archive không nhận dạng được")
    except (tarfile.TarError, zipfile.BadZipFile, gzip.BadGzipFile, EOFError, OSError) as exc:
        result.anomalies.append(f"EXTRACT_ERROR: {type(exc).__name__}: {exc}")
        if result.is_empty:
            _set_empty(result, "corrupt_archive", f"Lỗi khi giải nén: {type(exc).__name__}: {exc}")
        else:
            # Đã ghi được một phần file -> giữ lại, chỉ đánh dấu để rà soát sau
            result.anomalies.append(
                f"PARTIAL_EXTRACT: giữ {len(result.kept_files)} file trước khi lỗi"
            )

    if result.is_empty and result.empty_reason is None:
        if any(s.lower().endswith((".docx", ".doc")) for s in result.skipped_files):
            _set_empty(result, "docx_only", "Archive chỉ có file Word, không có .tex")
        else:
            _set_empty(result, "no_tex_in_archive", "Archive không chứa file .tex hoặc .bib nào")

    logger.info(
        "[%s] format=%s | size_before=%d B | size_after=%d B | kept=%d/%d | empty=%s",
        archive_path.name, result.archive_format, result.size_before, result.size_after,
        len(result.kept_files), result.members_total, result.is_empty,
    )
    for a in result.anomalies:
        logger.warning("[%s] ANOMALY %s", archive_path.name, a)
    return result


def summarize_sizes(results: Dict[str, ExtractionResult]) -> str:
    """Bảng dung lượng trước/sau cho báo cáo."""
    lines = [f"{'version':<28}{'before(B)':>12}{'after(B)':>12}{'ratio':>8}"]
    tb = ta = 0
    for key, r in results.items():
        ratio = f"{r.size_after / r.size_before:.2f}" if r.size_before else "n/a"
        lines.append(f"{key:<28}{r.size_before:>12}{r.size_after:>12}{ratio:>8}")
        tb += r.size_before
        ta += r.size_after
    ratio = f"{ta / tb:.2f}" if tb else "n/a"
    lines.append(f"{'TOTAL':<28}{tb:>12}{ta:>12}{ratio:>8}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Giải nén archive arXiv và chỉ giữ lại .tex/.bib")
    parser.add_argument("archive", nargs="?", help="Đường dẫn file archive cần giải nén")
    parser.add_argument("dest", nargs="?", default="extracted", help="Thư mục đích (mặc định: extracted)")
    args = parser.parse_args()

    if not args.archive:
        print("Sử dụng: python src/extractor.py <file_archive> [thu_muc_dich]")
        print("Ví dụ:   python src/extractor.py downloads/1706.03762v1.tar.gz corpus/1706-03762/v1")
        sys.exit(0)

    res = extract_archive(args.archive, args.dest)
    print(f"\n--- Kết quả giải nén [{res.archive_path}] ---")
    print(f"Format      : {res.archive_format}")
    print(f"Size trước  : {res.size_before:,} bytes")
    if res.size_before:
        print(f"Size sau    : {res.size_after:,} bytes (tỉ lệ: {res.size_after / res.size_before:.2%})")
    else:
        print(f"Size sau    : {res.size_after:,} bytes")
    print(f"File giữ lại: {len(res.kept_files)} (.tex: {res.n_tex}, .bib: {res.n_bib})")
    print(f"File bỏ qua : {len(res.skipped_files)}")
    print(f"Trạng thái  : {res.status}" + (f" ({res.empty_reason})" if res.empty_reason else ""))
    if res.anomalies:
        print(f"Bất thường  : {len(res.anomalies)}")
        for a in res.anomalies:
            print(f"  - {a}")