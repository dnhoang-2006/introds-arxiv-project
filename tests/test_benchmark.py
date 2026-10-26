"""
Unit and integration tests for src/benchmark.py.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from benchmark import (
    SCHEMA_COLUMNS,
    BenchmarkResult,
    append_to_csv,
    calculate_dir_size_bytes,
    run_benchmark,
    save_to_json,
)


def test_successful_command():
    """Verify short successful command records all 4 metrics."""
    cmd = [sys.executable, "-c", "import time; time.sleep(0.1); print('done')"]
    result, proc = run_benchmark(command=cmd, stage="unit_test")

    assert result.status == "success"
    assert result.exit_code == 0
    assert result.wall_time_seconds >= 0.08
    assert result.peak_ram_mb is not None and result.peak_ram_mb > 0
    assert result.average_ram_mb is not None and result.average_ram_mb > 0
    assert result.started_at_utc.endswith("+00:00") or result.started_at_utc.endswith("Z")
    assert result.ended_at_utc.endswith("+00:00") or result.ended_at_utc.endswith("Z")
    assert result.stage == "unit_test"
    assert proc is not None
    assert proc.returncode == 0


def test_failing_command():
    """Verify failing command captures non-zero exit code and failed status."""
    cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
    result, proc = run_benchmark(command=cmd, stage="test_fail")

    assert result.status == "failed"
    assert result.exit_code == 42
    assert result.wall_time_seconds >= 0.0
    assert result.peak_ram_mb is not None
    assert proc is not None
    assert proc.returncode == 42


def test_invalid_command():
    """Verify non-existent command handles error gracefully without raising."""
    cmd = ["non_existent_executable_12345"]
    result, proc = run_benchmark(command=cmd, stage="test_invalid")

    assert result.status == "error"
    assert result.exit_code == 127
    assert "not found" in (result.notes or "").lower()
    assert result.wall_time_seconds >= 0.0


def test_timeout_command():
    """Verify command exceeding timeout is terminated with timeout status."""
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    result, proc = run_benchmark(command=cmd, timeout=0.3, stage="test_timeout")

    assert result.status == "timeout"
    assert result.exit_code == -1
    assert "timed out" in (result.notes or "").lower()


def test_disk_delta_measurement(tmp_path):
    """Verify disk measurement accurately tracks size delta in MB."""
    target_dir = tmp_path / "measured_dir"
    target_dir.mkdir()

    # Pre-populate with 100KB file
    file1 = target_dir / "existing.dat"
    file1.write_bytes(b"0" * 102400)
    initial_bytes = calculate_dir_size_bytes(target_dir)
    assert initial_bytes == 102400

    # Run command that writes a 200KB file
    file2 = target_dir / "new.dat"
    cmd = [
        sys.executable,
        "-c",
        f"with open(r'{file2}', 'wb') as f: f.write(b'X' * 204800)",
    ]

    result, _ = run_benchmark(command=cmd, disk_path=target_dir)

    assert result.status == "success"
    assert result.disk_scope == "delta:measured_dir"
    assert result.disk_usage_mb is not None
    # 204800 bytes / (1024*1024) = 0.1953125 MB ~ 0.1953 MB
    expected_mb = round(204800 / (1024 * 1024), 4)
    assert abs(result.disk_usage_mb - expected_mb) < 0.005


def test_csv_export_schema(tmp_path):
    """Verify CSV export writes valid header matching team schema and correct values."""
    csv_file = tmp_path / "test_benchmark.csv"
    cmd = [sys.executable, "-c", "print('csv_test')"]
    result, _ = run_benchmark(
        command=cmd,
        stage="discovery",
        paper_id="2310.12345",
        notes="sample test run",
    )

    append_to_csv(result, csv_file)
    assert csv_file.exists()

    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == SCHEMA_COLUMNS
        rows = list(reader)
        assert len(rows) == 1
        row = rows[0]
        assert row["stage"] == "discovery"
        assert row["paper_id"] == "2310.12345"
        assert row["status"] == "success"
        assert row["exit_code"] == "0"
        assert float(row["wall_time_seconds"]) >= 0.0
        assert float(row["peak_ram_mb"]) > 0
        assert row["notes"] == "sample test run"

    # Append a second result
    append_to_csv(result, csv_file)
    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 2


def test_json_export_schema(tmp_path):
    """Verify JSON export stores valid array of benchmark records."""
    json_file = tmp_path / "test_benchmark.json"
    cmd = [sys.executable, "-c", "print('json_test')"]
    result, _ = run_benchmark(command=cmd, stage="download", paper_id="1706.03762")

    save_to_json(result, json_file)
    assert json_file.exists()

    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["stage"] == "download"
    assert data[0]["paper_id"] == "1706.03762"
    assert data[0]["status"] == "success"
    assert "wall_time_seconds" in data[0]
    assert "peak_ram_mb" in data[0]
    assert "average_ram_mb" in data[0]
    assert "disk_usage_mb" in data[0]


def test_child_process_ram_sampling():
    """Verify memory of spawned child processes is captured in tree RSS."""
    # Spawn a python child that creates a grandchild that allocates memory
    script = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; a = bytearray(20*1024*1024); time.sleep(0.3)'])\n"
        "p.wait()\n"
    )
    cmd = [sys.executable, "-c", script]
    result, _ = run_benchmark(command=cmd, sampling_interval=0.05)

    assert result.status == "success"
    assert result.peak_ram_mb is not None
    # 20MB buffer + python base runtime should yield peak RAM >= 15 MB
    assert result.peak_ram_mb >= 15.0
