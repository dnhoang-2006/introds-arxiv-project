"""Tests cho ca archive cụt đuôi / hỏng — đảm bảo extract_archive
không ném exception ra ngoài mà trả ExtractionResult với empty_reason."""

from __future__ import annotations

import gzip
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from extractor import ExtractionResult, extract_archive


def _make_truncated_tar_gz(path: Path) -> None:
    """Tạo một file .tar.gz hợp lệ rồi cắt cụt 80% phần cuối."""
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n"
        import tarfile as _tf
        info = _tf.TarInfo(name="main.tex")
        info.size = len(data)
        tf.addfile(info, BytesIO(data))
    raw = buf.getvalue()
    # Cắt 80% — chắc chắn hỏng
    path.write_bytes(raw[: len(raw) // 5])


def _make_random_garbage(path: Path) -> None:
    """File rác hoàn toàn, không phải tar/gz/zip/pdf."""
    path.write_bytes(b"\x00\xde\xad\xbe\xef" * 20)


def _make_truncated_gzip(path: Path) -> None:
    """File gzip hợp lệ header nhưng data bị cụt."""
    full = gzip.compress(b"\\documentclass{article}\n" * 100)
    path.write_bytes(full[: len(full) // 3])


class TestTruncatedArchive:
    """extract_archive KHÔNG được ném exception cho archive hỏng."""

    def test_truncated_tar_gz_returns_result(self, tmp_path: Path) -> None:
        archive = tmp_path / "broken.tar.gz"
        dest = tmp_path / "out"
        _make_truncated_tar_gz(archive)

        result = extract_archive(archive, dest)

        assert isinstance(result, ExtractionResult)
        assert result.empty_reason is not None, "phải đánh dấu empty_reason"
        assert any("ERROR" in a or "UNKNOWN" in a for a in result.anomalies), \
            f"anomalies phải ghi nhận lỗi: {result.anomalies}"

    def test_random_garbage_returns_result(self, tmp_path: Path) -> None:
        archive = tmp_path / "garbage.tar.gz"
        dest = tmp_path / "out"
        _make_random_garbage(archive)

        result = extract_archive(archive, dest)

        assert isinstance(result, ExtractionResult)
        assert result.empty_reason is not None

    def test_truncated_gzip_returns_result(self, tmp_path: Path) -> None:
        archive = tmp_path / "cut.gz"
        dest = tmp_path / "out"
        _make_truncated_gzip(archive)

        result = extract_archive(archive, dest)

        assert isinstance(result, ExtractionResult)
        # Không crash là đủ, empty_reason có thể là corrupt_archive
        assert result.empty_reason is not None

    def test_zero_byte_file(self, tmp_path: Path) -> None:
        archive = tmp_path / "empty.tar.gz"
        dest = tmp_path / "out"
        archive.write_bytes(b"")

        result = extract_archive(archive, dest)

        assert isinstance(result, ExtractionResult)

