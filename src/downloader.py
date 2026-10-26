"""
downloader.py - tải full-text source của MỌI version.

Đầu vào : corpus/<pub_key>/paper_meta.json do discovery.py ghi (lấy n_versions).
Đầu ra  : raw/<pub_key>/v<n>.<ext>             archive thô, extractor.py đọc tiếp
          corpus/<pub_key>/v<n>/                  thư mục version (luôn được tạo)
          corpus/<pub_key>/v<n>/_EMPTY.json       khi version không có TeX source
          logs/download.csv                       mỗi dòng = một lần tải thật

Luồng cho mỗi (bài, version):

    fetch_version()   [I/O-bound]   GET export.arxiv.org/src/<id>v<n>
          |
          v
    process_version() [CPU/disk]    nhận diện bằng magic bytes -> lưu archive / ghi _EMPTY.json

Hai stage là hai hàm độc lập, không chia sẻ state: tuần 2 chỉ cần đẩy
process_version() sang thread pool trong lúc luồng chính tải version kế tiếp.

Phải chạy discovery.py TRƯỚC. Downloader không tự gọi API: discovery và
downloader cùng gọi export.arxiv.org, hai bộ đếm 3 giây riêng có thể bắn sát nhau.

Chạy:
    python src/downloader.py --ids ids/24120144.txt
    python src/downloader.py --ids 2505.00666,2505.00672 --limit 5
    python src/downloader.py --ids ids/24120144.txt --force   # tải lại cả version đã có
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import tarfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import config
from discovery import load_ids
from http_utils import FetchResult, PoliteSession

# Archive thô tải từ /src/ (extractor.py đọc tiếp). Ưu tiên config.RAW_ROOT nếu nhóm đã
# khai báo; chưa có thì dùng <repo>/raw, ghi đè được bằng biến môi trường RAW_ROOT.
RAW_ROOT = getattr(
    config, "RAW_ROOT", Path(os.environ.get("RAW_ROOT", config.PROJECT_ROOT / "raw"))
)
LOG_PATH = config.LOGS_ROOT / "download.csv"
LOG_HEADER = ("arxiv_id", "version", "bytes", "seconds", "status", "error_type")
EMPTY_FILE = "_EMPTY.json"
PART_SUFFIX = ".part"

# Version không có TeX source -> ghi _EMPTY.json, không tải lại nữa
NO_SOURCE_KINDS = frozenset({"pdf_only", "docx_only", "corrupt_archive", "other"})
# HTTP 404: version chắc chắn không tồn tại -> ghi _EMPTY.json.
# HTTP 403 KHÔNG nằm ở đây: với arXiv, 403 thường là bị chặn tạm thời, không phải thiếu source.
PERMANENT_HTTP_ERRORS = frozenset({"http_404"})
# Gặp liên tiếp ngần này lần 403/429 thì dừng cả mẻ để bảo vệ IP
MAX_CONSECUTIVE_BLOCKS = 3
BLOCK_ERRORS = frozenset({"http_403", "http_429"})

# Chữ ký nhận diện file
GZIP_MAGIC = b"\x1f\x8b"
PDF_MAGIC = b"%PDF"
ZIP_MAGIC = b"PK\x03\x04"
TAR_MAGIC = b"ustar"
TAR_MAGIC_OFFSET = 257  # "ustar" nằm ở byte 257


# ----------------------------------------------------------------------
# Kiểu dữ liệu
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class DownloadRecord:
    """Một dòng của logs/download.csv"""

    arxiv_id: str
    version: int
    bytes: int
    seconds: float
    status: str  # ok | empty | fail | skipped
    error_type: str = ""  # rỗng khi status = ok

    def row(self) -> tuple:
        return (
            self.arxiv_id,
            self.version,
            self.bytes,
            f"{self.seconds:.2f}",
            self.status,
            self.error_type,
        )


# ----------------------------------------------------------------------
# Đường dẫn
# ----------------------------------------------------------------------
def raw_dir(arxiv_id: str) -> Path:
    return RAW_ROOT / config.pub_key(arxiv_id)


def find_archive(arxiv_id: str, version: int) -> Path | None:
    """Archive đã tải đầy đủ của version này"""
    folder = raw_dir(arxiv_id)
    if not folder.is_dir():
        return None
    for path in folder.glob(f"v{int(version)}.*"):
        if path.suffix != PART_SUFFIX and path.stat().st_size > 0:
            return path
    return None


def empty_marker(arxiv_id: str, version: int) -> Path:
    return config.version_dir(arxiv_id, version) / EMPTY_FILE


def is_done(arxiv_id: str, version: int) -> bool:
    return find_archive(arxiv_id, version) is not None or empty_marker(arxiv_id, version).exists()


# ----------------------------------------------------------------------
# Nhận diện loại file bằng magic bytes
# ----------------------------------------------------------------------
def _is_tar(blob: bytes) -> bool:
    end = TAR_MAGIC_OFFSET + len(TAR_MAGIC)
    return blob[TAR_MAGIC_OFFSET:end] == TAR_MAGIC


def _sniff_gzip(data: bytes) -> tuple[str, str]:
    """Phân loại nội dung bên trong một file gzip."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            head = gz.read(1024)
    except (OSError, EOFError):
        return "corrupt_archive", ""
    if head.startswith(PDF_MAGIC):
        return "pdf_only", ""
    if _is_tar(head) or _opens_as_tar(data):
        return "tar_gz", ".tar.gz"
    return "tex_gz", ".tex.gz"  # một file .tex đơn, bị gzip


def _opens_as_tar(data: bytes) -> bool:
    """Tar kiểu cũ không có chữ ký ustar"""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            return tf.next() is not None
    except (tarfile.TarError, OSError, EOFError):
        return False


def sniff(data: bytes) -> tuple[str, str]:
    """Phân loại nội dung trả về từ /src/.

    Trả (kind, ext). `ext` rỗng nghĩa là không lưu archive.
    kind thuộc tar_gz | tex_gz | tar | tex | zip | pdf_only | docx_only | corrupt_archive | other
    """
    if data.startswith(GZIP_MAGIC):
        return _sniff_gzip(data)
    if data.startswith(PDF_MAGIC):
        return "pdf_only", ""
    if data.startswith(ZIP_MAGIC):  # .docx cũng là zip, chứa thư mục word/
        return ("docx_only", "") if b"word/" in data[:4096] else ("zip", ".zip")
    if _is_tar(data):
        return "tar", ".tar"
    if data.lstrip()[:1] in (b"\\", b"%") or b"\\documentclass" in data[:8192]:
        return "tex", ".tex"
    return "other", ""


# ----------------------------------------------------------------------
# Ghi kết quả ra đĩa
# ----------------------------------------------------------------------
def write_empty(
    arxiv_id: str, version: int, reason: str, detail: str, http_status: int | None
) -> None:
    """Ghi corpus/<pub_key>/v<n>/_EMPTY.json."""
    marker = empty_marker(arxiv_id, version)
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "arxiv_id": arxiv_id,
        "version": int(version),
        "reason": reason if reason in config.EMPTY_REASONS else "other",
        "detail": detail,
        "http_status": http_status,
        "fetched_at": config.now_iso(),
    }
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    stale = find_archive(arxiv_id, version)
    if stale:  # chạy --force: version giờ rỗng
        stale.unlink()


def save_archive(arxiv_id: str, version: int, data: bytes, ext: str) -> Path:
    """Lưu archive .part rồi đổi tên và tạo sẵn thư mục version."""
    out = raw_dir(arxiv_id) / f"v{int(version)}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + PART_SUFFIX)
    tmp.write_bytes(data)
    tmp.replace(out)
    config.version_dir(arxiv_id, version).mkdir(parents=True, exist_ok=True)
    empty_marker(arxiv_id, version).unlink(missing_ok=True)  # chạy --force: giờ đã có source
    return out


# ----------------------------------------------------------------------
# Hai stage của pipeline
# ----------------------------------------------------------------------
def fetch_version(http: PoliteSession, arxiv_id: str, version: int) -> FetchResult:
    """Stage 1 — I/O-bound: chỉ chờ mạng."""
    return http.get(config.src_url(arxiv_id, version))


def process_version(arxiv_id: str, version: int, res: FetchResult) -> DownloadRecord:
    """Stage 2 — CPU/disk-bound: phân loại và ghi ra đĩa. Không gọi mạng."""
    if not res.ok:
        if res.error_type in PERMANENT_HTTP_ERRORS:
            write_empty(
                arxiv_id,
                version,
                res.error_type,
                f"/src/ trả HTTP {res.status} sau {res.attempts} lần thử",
                res.status,
            )
        return DownloadRecord(arxiv_id, version, 0, res.seconds, "fail", res.error_type)

    kind, ext = sniff(res.content)
    size = len(res.content)

    if kind in NO_SOURCE_KINDS:
        write_empty(
            arxiv_id,
            version,
            kind,
            f"Phản hồi {size} bytes, nhận diện là {kind} qua magic bytes",
            res.status,
        )
        return DownloadRecord(arxiv_id, version, size, res.seconds, "empty", kind)

    save_archive(arxiv_id, version, res.content, ext)
    return DownloadRecord(arxiv_id, version, size, res.seconds, "ok")


def download_source(http: PoliteSession, arxiv_id: str, version: int) -> DownloadRecord:
    """Tải và xử lý một version (chế độ tuần tự)."""
    return process_version(arxiv_id, version, fetch_version(http, arxiv_id, version))


# ----------------------------------------------------------------------
# Đọc số version do discovery.py ghi
# ----------------------------------------------------------------------
def read_n_versions(arxiv_id: str) -> tuple[str, int] | None:
    """Trả (arxiv_id chuẩn, n_versions) từ paper_meta.json, hoặc None nếu chưa có."""
    meta_path = config.pub_dir(arxiv_id) / "paper_meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta["arxiv_id"], max(1, int(meta["n_versions"]))


# ----------------------------------------------------------------------
# Điều phối
# ----------------------------------------------------------------------
class SourceDownloader:
    """Tải source mọi version cho một danh sách ID.

    Ví dụ (notebook):
        dl = SourceDownloader()
        records = dl.run(["2505.00666", "2505.00672"])
        dl.summary
    """

    def __init__(self, force: bool = False, verbose: bool = True) -> None:
        self.force = force
        self.verbose = verbose
        self.summary: Counter[str] = Counter()
        config.ensure_dirs()
        RAW_ROOT.mkdir(parents=True, exist_ok=True)

    def plan(self, ids: list[str]) -> tuple[list[tuple[str, int]], list[DownloadRecord]]:
        """Liệt kê các (id, version) cần tải và các bài chưa qua discovery."""
        tasks: list[tuple[str, int]] = []
        missing: list[DownloadRecord] = []
        for raw_id in ids:
            found = read_n_versions(raw_id)
            if found is None:
                missing.append(
                    DownloadRecord(
                        config.strip_version(raw_id), 0, 0, 0.0, "skipped", "no_paper_meta"
                    )
                )
                continue
            base_id, n_versions = found
            for version in range(1, n_versions + 1):
                if self.force or not is_done(base_id, version):
                    tasks.append((base_id, version))
                else:
                    self.summary["already_done"] += 1
        return tasks, missing

    def run(self, ids: list[str]) -> list[DownloadRecord]:
        self.summary.clear()
        tasks, records = self.plan(ids)
        if records and self.verbose:
            print(
                f"Bỏ qua {len(records)} bài chưa có paper_meta.json — hãy chạy discovery.py trước."
            )

        new_log = not LOG_PATH.exists()
        progress = _Progress(len(tasks), self.verbose)
        consecutive_blocks = 0

        with LOG_PATH.open("a", newline="", encoding="utf-8") as fh, PoliteSession() as http:
            writer = csv.writer(fh)
            if new_log:
                writer.writerow(LOG_HEADER)
            writer.writerows(r.row() for r in records)

            for arxiv_id, version in tasks:
                try:
                    rec = download_source(http, arxiv_id, version)
                except OSError as exc:  # lỗi ghi đĩa: ghi log, không dừng cả mẻ
                    rec = DownloadRecord(arxiv_id, version, 0, 0.0, "fail", type(exc).__name__)
                records.append(rec)
                writer.writerow(rec.row())
                fh.flush()
                progress.update(f"{arxiv_id}v{version} {rec.status}")

                consecutive_blocks = consecutive_blocks + 1 if rec.error_type in BLOCK_ERRORS else 0
                if consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                    print(
                        f"\nDỪNG: {consecutive_blocks} lần liên tiếp bị 403/429 — có thể đã "
                        f"bị arXiv chặn. Kiểm tra User-Agent và chờ vài giờ rồi chạy lại."
                    )
                    break

        progress.close()
        self.summary.update(r.status for r in records)
        return records


class _Progress:
    """Thanh tiến trình: dùng tqdm nếu đã cài, không thì in từng dòng."""

    def __init__(self, total: int, enabled: bool) -> None:
        self.enabled = enabled
        try:  # tqdm là tuỳ chọn: thiếu thì vẫn chạy, chỉ in từng dòng
            from tqdm.auto import tqdm  # noqa: PLC0415

            self._bar = tqdm(total=total, unit="ver", disable=not enabled)
        except ImportError:
            self._bar = None

    def update(self, label: str) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(label)
            self._bar.update(1)
        elif self.enabled:
            print(label)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tải full-text source mọi version (Milestone 1)")
    parser.add_argument("--ids", required=True, help="File ID hoặc danh sách ngăn bởi dấu phẩy")
    parser.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N bài đầu")
    parser.add_argument("--force", action="store_true", help="Tải lại cả version đã có")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    ids = load_ids(args.ids, args.limit)
    if not ids:
        sys.exit("Không đọc được ID nào.")

    started = time.perf_counter()
    downloader = SourceDownloader(force=args.force, verbose=not args.quiet)
    records = downloader.run(ids)
    downloaded = sum(r.bytes for r in records if r.status == "ok")

    print(f"\n{'=' * 60}")
    print(f"Kết quả       : {dict(downloader.summary)}")
    print(f"Dung lượng tải: {downloaded / 1e6:.1f} MB")
    print(f"Thời gian     : {time.perf_counter() - started:.1f}s")
    print(f"Archive       : {RAW_ROOT}")
    print(f"Log           : {LOG_PATH}")


if __name__ == "__main__":
    main()