"""tests/test_upload_hf.py — Kiểm các chốt an toàn của scripts/upload_hf.py.

Script này đẩy dữ liệu lên Internet nên phần đáng kiểm nhất là nó TỪ CHỐI đẩy
khi thư mục export chưa hoàn chỉnh. Đẩy nhầm bản dở lên Hub rồi mới phát hiện
thì phải xoá repo, mất công hơn nhiều.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import upload_hf  # noqa: E402

MSSV = "24120053"
TABLES = ("papers", "references", "elements", "hierarchy", "bibtex")


def _make_export(root: Path) -> Path:
    folder = root / "hf_export" / MSSV
    (folder / "metadata").mkdir(parents=True)
    (folder / "README.md").write_text(
        "---\nconfigs:\n  - config_name: papers\n---\n", encoding="utf-8"
    )
    for name in TABLES:
        d = folder / "data" / name
        d.mkdir(parents=True)
        (d / f"train-{MSSV}-00000.parquet").write_bytes(b"PAR1")
    (folder / "metadata" / f"export-manifest-{MSSV}.json").write_text(
        json.dumps({"n_publications": 2, "n_requested_publications": 2}), encoding="utf-8"
    )
    return folder


def test_accepts_a_complete_export(tmp_path, capsys):
    folder = _make_export(tmp_path)
    assert upload_hf.main(["--mssv", MSSV, "--folder", str(folder), "--dry-run"]) == 0
    assert "chưa đẩy gì" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("break_it", "msg"),
    [
        (lambda f: f.rename(f.with_name("gone")), "Chạy src/export_hf.py trước"),
        (lambda f: (f / "README.md").unlink(), "không phải bản export hoàn chỉnh"),
        (lambda f: (f / "README.md").write_text("# no yaml\n", encoding="utf-8"),
         "thiếu khối YAML"),
        (lambda f: (f / "metadata" / f"export-manifest-{MSSV}.json").unlink(),
         "Chạy lại src/export_hf.py"),
        (lambda f: __import__("shutil").rmtree(f / "data" / "bibtex"), "Thiếu bảng bibtex"),
        (lambda f: (f / "data" / "papers" / "x.tmp").write_bytes(b""),
         "bị cắt giữa chừng"),
    ],
)
def test_refuses_an_incomplete_export(tmp_path, capsys, break_it, msg):
    folder = _make_export(tmp_path)
    break_it(folder)
    with pytest.raises(SystemExit) as exc:
        upload_hf.main(["--mssv", MSSV, "--folder", str(folder), "--dry-run"])
    assert exc.value.code == 1
    assert msg in capsys.readouterr().err


def test_mssv_must_be_digits(tmp_path):
    with pytest.raises(SystemExit):
        upload_hf.main(["--mssv", "abc", "--dry-run"])
