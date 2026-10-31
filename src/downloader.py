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

Hai stage là hai hàm độc lập, không chia sẻ state.

Các tối ưu TẮT mặc định, bật bằng cờ để đo before/after:
  --workers N  process_version() chạy trong N luồng nền; luồng chính chỉ lo tải.
               Mạng vẫn đi qua MỘT PoliteSession duy nhất (1 connection, 3 giây)
               -> pacing không đổi, chỉ phần CPU/đĩa được chồng lên thời gian chờ mạng.
  --stream     Giải nén ngay sau khi tải (dùng extractor.py của nhóm), chỉ ghi
               .tex/.bib vào corpus/, KHÔNG giữ archive trong raw/. Ghi luôn
               logs/extract.csv nên không cần chạy corpus_builder cho phần tải.

Phải chạy discovery.py TRƯỚC. Downloader không tự gọi API: discovery và
downloader cùng gọi export.arxiv.org, hai bộ đếm 3 giây riêng có thể bắn sát nhau.

Mã thoát: 0 = chạy hết danh sách; 2 = dừng giữa chừng (đĩa đầy / bị chặn 403-429).

Chạy:
    python src/downloader.py --ids ids/24120144.txt
    python src/downloader.py --ids 2505.00666,2505.00672 --limit 5
    python src/downloader.py --ids ids/24120144.txt --force   # tải lại cả version đã có
    python src/downloader.py --ids ids/24120144.txt --max-raw-gb 6
    python src/downloader.py --ids ids/24120144.txt --cleanup-after-extract
    python src/downloader.py --ids ids/24120144.txt --stream --workers 2   # bản tối ưu
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import shutil
import sys
import tarfile
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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

# Bảo vệ dung lượng đĩa
GB = 1024**3
RAW_WARN_RATIO = 0.8  # vượt 80% ngưỡng --max-raw-gb thì cảnh báo trước
MIN_FREE_GB = 1.0  # ổ chứa raw/ còn dưới ngần này thì luôn dừng, có cờ hay không

# Chế độ --stream
STREAM_TMP_DIR = ".stream_tmp"  # file archive tạm, nằm trong RAW_ROOT, xoá ngay sau khi giải nén
EXIT_STOPPED = 2  # mã thoát khi dừng giữa chừng -> benchmark.py ghi "failed", không phải "success"
_extract_log_lock = threading.Lock()  # nhiều luồng cùng ghi logs/extract.csv


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


def is_extracted(arxiv_id: str, version: int) -> bool:
    """corpus/<pub_key>/v<n>/ đã có ít nhất một file .tex/.bib (corpus_builder đã giải nén)."""
    folder = config.version_dir(arxiv_id, version)
    if not folder.is_dir():
        return False
    return any(
        p.is_file() and p.suffix.lower() in config.KEEP_EXTENSIONS for p in folder.rglob("*")
    )


def is_done(arxiv_id: str, version: int) -> bool:
    # is_extracted: archive đã bị --cleanup-after-extract xoá nhưng version vẫn xong,
    # không được tải lại.
    return (
        find_archive(arxiv_id, version) is not None
        or empty_marker(arxiv_id, version).exists()
        or is_extracted(arxiv_id, version)
    )


# ----------------------------------------------------------------------
# Dung lượng đĩa
# ----------------------------------------------------------------------
def dir_size_bytes(root: Path) -> int:
    """Tổng dung lượng file trong một thư mục (bỏ qua file đang bị xoá giữa chừng)."""
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def free_disk_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def cleanup_extracted(arxiv_id: str, version: int) -> int:
    """Xoá archive thô của version ĐÃ giải nén xong. Trả số byte giải phóng.

    Chỉ xoá khi corpus/<pub_key>/v<n>/ đã có .tex/.bib hoặc _EMPTY.json — chưa giải nén
    thì giữ nguyên, để corpus_builder còn đọc được.
    """
    archive = find_archive(arxiv_id, version)
    if archive is None:
        return 0
    if not (is_extracted(arxiv_id, version) or empty_marker(arxiv_id, version).exists()):
        return 0
    size = archive.stat().st_size
    archive.unlink()
    try:
        archive.parent.rmdir()  # chỉ xoá được khi thư mục bài đã rỗng
    except OSError:
        pass
    return size


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


def stream_extract(arxiv_id: str, version: int, data: bytes, ext: str) -> None:
    """--stream: giải nén `data` thẳng vào corpus/<pub_key>/v<n>/, không giữ archive.

    Dùng lại extractor.py + corpus_builder.py của nhóm (không viết lại luật lọc), nên
    kết quả và logs/extract.csv giống hệt luồng tải -> corpus_builder.
    Giải nén vào thư mục v<n>.part rồi mới đổi tên -> bị ngắt giữa chừng thì version
    không bị tính là "đã xong" nửa vời.
    """
    from corpus_builder import append_extract_log, write_empty_marker  # noqa: PLC0415
    from extractor import extract_archive  # noqa: PLC0415

    final_dir = config.version_dir(arxiv_id, version)
    part_dir = final_dir.with_name(final_dir.name + PART_SUFFIX)
    tmp_dir = RAW_ROOT / STREAM_TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / f"{config.pub_key(arxiv_id)}_v{int(version)}{ext}"
    shutil.rmtree(part_dir, ignore_errors=True)
    try:
        tmp_file.write_bytes(data)
        result = extract_archive(tmp_file, part_dir)
        if result.is_empty:
            write_empty_marker(part_dir, arxiv_id, int(version), result=result)
        if final_dir.exists():  # thư mục rỗng tạo sẵn, hoặc bản cũ khi chạy --force
            shutil.rmtree(final_dir)
        part_dir.replace(final_dir)
        with _extract_log_lock:
            append_extract_log(config.LOGS_ROOT / "extract.csv", arxiv_id, int(version), result)
    finally:
        tmp_file.unlink(missing_ok=True)
        shutil.rmtree(part_dir, ignore_errors=True)
    stale = find_archive(arxiv_id, version)
    if stale:  # archive cũ từ lần chạy không --stream: đã có .tex/.bib rồi thì bỏ
        stale.unlink()


def process_version(
    arxiv_id: str, version: int, res: FetchResult, stream: bool = False
) -> DownloadRecord:
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
            # Đã có _EMPTY.json -> log là "empty" cho khớp, không phải "fail" cần chạy lại
            return DownloadRecord(arxiv_id, version, 0, res.seconds, "empty", res.error_type)
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

    if stream:
        stream_extract(arxiv_id, version, res.content, ext)
    else:
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

    def __init__(
        self,
        force: bool = False,
        verbose: bool = True,
        max_raw_gb: float | None = None,
        cleanup_after_extract: bool = False,
        stream: bool = False,
        workers: int = 0,
    ) -> None:
        if max_raw_gb is not None and max_raw_gb <= 0:
            raise ValueError("--max-raw-gb phải > 0")
        if workers < 0:
            raise ValueError("--workers phải >= 0")
        self.force = force
        self.verbose = verbose
        self.max_raw_bytes = int(max_raw_gb * GB) if max_raw_gb else None
        self.cleanup_after_extract = cleanup_after_extract
        self.stream = stream
        self.workers = workers
        self.stopped = False  # True khi dừng giữa chừng (đĩa / bị chặn)
        self.freed_bytes = 0
        self._warned = False
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
                if self.cleanup_after_extract:
                    self.freed_bytes += cleanup_extracted(base_id, version)
                if self.force or not is_done(base_id, version):
                    tasks.append((base_id, version))
                else:
                    self.summary["already_done"] += 1
        return tasks, missing

    def disk_guard(self, raw_bytes: int) -> str | None:
        """Trả lý do phải dừng, hoặc None nếu còn chạy tiếp được. In cảnh báo 80% một lần."""
        free = free_disk_bytes(RAW_ROOT)
        if free < MIN_FREE_GB * GB:
            return f"ổ chứa {RAW_ROOT} chỉ còn {free / GB:.2f} GB trống (< {MIN_FREE_GB} GB)"
        if self.max_raw_bytes is None:
            return None
        if raw_bytes >= self.max_raw_bytes:
            return (
                f"raw/ đã {raw_bytes / GB:.2f} GB, vượt ngưỡng "
                f"--max-raw-gb {self.max_raw_bytes / GB:.2f} GB"
            )
        if not self._warned and raw_bytes >= RAW_WARN_RATIO * self.max_raw_bytes:
            self._warned = True
            print(
                f"\nCẢNH BÁO: raw/ đã {raw_bytes / GB:.2f} GB "
                f"(≥ {RAW_WARN_RATIO:.0%} ngưỡng {self.max_raw_bytes / GB:.2f} GB). "
                f"Ổ còn trống {free / GB:.1f} GB."
            )
        return None

    def _process(self, arxiv_id: str, version: int, res: FetchResult) -> DownloadRecord:
        """Stage 2 cho một version; lỗi ghi đĩa/giải nén thành dòng fail, không làm sập mẻ."""
        try:
            return process_version(arxiv_id, version, res, stream=self.stream)
        except Exception as exc:  # noqa: BLE001 - mọi lỗi stage 2 đều ghi log rồi chạy tiếp
            return DownloadRecord(arxiv_id, version, 0, res.seconds, "fail", type(exc).__name__)

    def run(self, ids: list[str]) -> list[DownloadRecord]:
        self.summary.clear()
        self.freed_bytes = 0
        self._warned = False
        self.stopped = False
        tasks, records = self.plan(ids)
        if records and self.verbose:
            print(
                f"Bỏ qua {len(records)} bài chưa có paper_meta.json — hãy chạy discovery.py trước."
            )
        if self.freed_bytes and self.verbose:
            print(f"Đã dọn {self.freed_bytes / 1e6:.1f} MB archive của các version đã giải nén.")

        # Đo raw/ MỘT lần, sau đó cộng dồn theo từng archive mới -> không quét lại đĩa mỗi vòng
        raw_bytes = dir_size_bytes(RAW_ROOT)
        if self.verbose:
            limit = f" / ngưỡng {self.max_raw_bytes / GB:.2f} GB" if self.max_raw_bytes else ""
            print(
                f"raw/ hiện tại: {raw_bytes / GB:.2f} GB{limit} · "
                f"ổ còn trống {free_disk_bytes(RAW_ROOT) / GB:.1f} GB"
            )

        if self.verbose and (self.stream or self.workers):
            print(
                f"Chế độ tối ưu: stream={'bật' if self.stream else 'tắt'}, "
                f"workers={self.workers} (pacing arXiv vẫn 1 connection / {config.REQUEST_DELAY}s)"
            )

        new_log = not LOG_PATH.exists()
        progress = _Progress(len(tasks), self.verbose)
        consecutive_blocks = 0
        pending: set[Future[DownloadRecord]] = set()
        # Giới hạn số version tải xong mà chưa xử lý -> RAM không phình (mỗi cái giữ cả archive)
        max_pending = max(1, self.workers) * 2
        pool = ThreadPoolExecutor(max_workers=self.workers) if self.workers else None

        with LOG_PATH.open("a", newline="", encoding="utf-8") as fh, PoliteSession() as http:
            writer = csv.writer(fh)
            if new_log:
                writer.writerow(LOG_HEADER)
            writer.writerows(r.row() for r in records)

            def collect(rec: DownloadRecord) -> None:
                """Ghi kết quả ở luồng chính -> CSV không bị nhiều luồng ghi chồng."""
                nonlocal raw_bytes
                records.append(rec)
                if rec.status == "ok" and not self.stream:
                    raw_bytes += rec.bytes
                writer.writerow(rec.row())
                fh.flush()
                progress.update(f"{rec.arxiv_id}v{rec.version} {rec.status}")

            def drain(block_until: int) -> None:
                """Lấy kết quả các luồng nền cho tới khi còn <= block_until việc đang chờ."""
                nonlocal pending
                while len(pending) > block_until:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for fut in done:
                        collect(fut.result())

            try:
                for arxiv_id, version in tasks:
                    stop_reason = self.disk_guard(raw_bytes)
                    if stop_reason:
                        self.summary["stopped_disk"] += 1
                        self.stopped = True
                        print(
                            f"\nDỪNG ĐỂ BẢO VỆ ĐĨA: {stop_reason}.\n"
                            f"Còn khoảng {len(tasks) - progress.done - len(pending)} version "
                            f"chưa tải. Giải phóng chỗ (hoặc đặt RAW_ROOT sang ổ khác, hoặc "
                            f"dùng --stream) rồi chạy lại cùng lệnh — version đã xong tự bỏ qua."
                        )
                        break

                    res = fetch_version(http, arxiv_id, version)  # luôn ở luồng chính
                    if pool is None:
                        collect(self._process(arxiv_id, version, res))
                    else:
                        pending.add(pool.submit(self._process, arxiv_id, version, res))
                        drain(max_pending - 1)

                    blocked = res.error_type in BLOCK_ERRORS
                    consecutive_blocks = consecutive_blocks + 1 if blocked else 0
                    if consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                        self.summary["stopped_blocked"] += 1
                        self.stopped = True
                        print(
                            f"\nDỪNG: {consecutive_blocks} lần liên tiếp bị 403/429 — có thể đã "
                            f"bị arXiv chặn. Kiểm tra User-Agent và chờ vài giờ rồi chạy lại."
                        )
                        break
            finally:
                drain(0)  # kể cả khi Ctrl+C: ghi nốt các version đã tải xong
                if pool is not None:
                    pool.shutdown(wait=True)

        progress.close()
        self.summary.update(r.status for r in records)
        return records


class _Progress:
    """Thanh tiến trình: dùng tqdm nếu đã cài, không thì in từng dòng."""

    def __init__(self, total: int, enabled: bool) -> None:
        self.enabled = enabled
        self.done = 0
        try:  # tqdm là tuỳ chọn: thiếu thì vẫn chạy, chỉ in từng dòng
            from tqdm.auto import tqdm  # noqa: PLC0415

            self._bar = tqdm(total=total, unit="ver", disable=not enabled)
        except ImportError:
            self._bar = None

    def update(self, label: str) -> None:
        self.done += 1
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
    parser.add_argument(
        "--max-raw-gb",
        type=float,
        default=None,
        help="Dừng và cảnh báo khi raw/ vượt ngưỡng này (GB). Cảnh báo sớm ở 80%%.",
    )
    parser.add_argument(
        "--cleanup-after-extract",
        action="store_true",
        help="Xoá raw/<pub_key>/v<n>.* của version ĐÃ giải nén (corpus có .tex/.bib "
        "hoặc _EMPTY.json). Mặc định tắt.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Giải nén ngay sau khi tải, chỉ ghi .tex/.bib vào corpus/, không giữ "
        "archive trong raw/ (ghi luôn logs/extract.csv). Mặc định tắt.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Số luồng nền xử lý/giải nén trong lúc luồng chính tải tiếp. "
        "0 = tuần tự như tuần 1 (mặc định). Không ảnh hưởng pacing 3 giây.",
    )
    args = parser.parse_args()
    if args.workers < 0:
        parser.error("--workers phải >= 0")

    ids = load_ids(args.ids, args.limit)
    if not ids:
        sys.exit("Không đọc được ID nào.")

    if args.stream:
        # extractor.py in WARNING cho mỗi ca lạ (vd .tex trong thư mục con) -> hàng nghìn dòng
        # đè lên thanh tiến trình. Ca lạ vẫn phản ánh trong logs/extract.csv.
        import logging  # noqa: PLC0415

        logging.getLogger("extractor").setLevel(logging.ERROR)

    started = time.perf_counter()
    downloader = SourceDownloader(
        force=args.force,
        verbose=not args.quiet,
        max_raw_gb=args.max_raw_gb,
        cleanup_after_extract=args.cleanup_after_extract,
        stream=args.stream,
        workers=args.workers,
    )
    records = downloader.run(ids)
    downloaded = sum(r.bytes for r in records if r.status == "ok")

    print(f"\n{'=' * 60}")
    print(f"Kết quả       : {dict(downloader.summary)}")
    print(f"Dung lượng tải: {downloaded / 1e6:.1f} MB")
    if downloader.freed_bytes:
        print(f"Đã dọn        : {downloader.freed_bytes / 1e6:.1f} MB archive")
    print(f"Thời gian     : {time.perf_counter() - started:.1f}s")
    print(f"Archive       : {'(không giữ — chế độ --stream)' if args.stream else RAW_ROOT}")
    print(f"Log           : {LOG_PATH}")
    if downloader.stopped:
        sys.exit(EXIT_STOPPED)  # để benchmark.py / script ghi nhận là CHƯA xong


if __name__ == "__main__":
    main()