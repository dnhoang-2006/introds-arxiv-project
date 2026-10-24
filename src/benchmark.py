"""
benchmark.py — Reusable performance benchmarking tool for pipeline execution.

Measures:
  1. End-to-end wall-clock time (high-precision perf_counter, UTC timestamps).
  2. Peak RAM usage (including recursive child processes, in MB).
  3. Average RAM usage (periodic background sampling, in MB).
  4. Disk usage (configurable scope: directory size delta in MB).

Compatible with Python >= 3.9 (tested on Python 3.9, 3.10, 3.11+).
Handles process tree monitoring across Windows and POSIX systems.
Outputs structured metrics to CSV and/or JSON conforming to the proposed team schema.

Usage examples:
  # Benchmark a shell command and print summary:
  python src/benchmark.py -- python src/discovery.py --ids ids/example.txt --limit 1

  # Benchmark with stage and paper tags, recording to CSV:
  python src/benchmark.py --stage discovery --paper-id 2310.12345 --csv logs/benchmark_runs.csv -- python src/discovery.py --ids 2310.12345

  # Track disk usage delta on corpus directory:
  python src/benchmark.py --stage download --disk-path corpus --csv logs/benchmark_runs.csv --json logs/latest_run.json -- python -c "print('test')"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    import psutil
except ImportError:
    sys.exit("Error: 'psutil' is required for benchmark.py. Install via: pip install psutil")

# Tool metadata
TOOL_VERSION = "1.0.0"
DEFAULT_SAMPLING_INTERVAL = 0.1  # seconds
BYTES_PER_MB = 1024 * 1024


@dataclass
class BenchmarkResult:
    """Structured benchmark log entry matching the proposed team schema."""

    run_id: str
    stage: str
    paper_id: str | None
    command: str
    started_at_utc: str
    ended_at_utc: str
    exit_code: int | None
    status: str  # "success", "failed", "timeout", "error"
    wall_time_seconds: float
    peak_ram_mb: float | None
    average_ram_mb: float | None
    ram_sampling_interval_seconds: float
    disk_usage_mb: float | None
    disk_scope: str  # e.g., "delta:<path>", "none"
    testbed: str
    tool_version: str
    notes: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return asdict(self)


def get_default_testbed() -> str:
    """Return a descriptive string of the host environment."""
    os_name = platform.system()
    os_release = platform.release()
    cpu_arch = platform.machine()
    py_ver = platform.python_version()
    try:
        mem_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        mem_info = f"{mem_gb}GB"
    except Exception:
        mem_info = "unknown_mem"
    return f"{os_name}-{os_release}-{cpu_arch} (Python {py_ver}, RAM {mem_info})"


def calculate_dir_size_bytes(target_path: Path) -> int:
    """Recursively calculate the total size in bytes of all files in a directory or file.

    Returns 0 if the path does not exist.
    """
    if not target_path.exists():
        return 0
    if target_path.is_file():
        try:
            return target_path.stat().st_size
        except OSError:
            return 0

    total_size = 0
    for root, _, files in os.walk(target_path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                # Follow symlinks only if regular file
                total_size += os.path.getsize(fp)
            except OSError:
                continue
    return total_size


def get_tree_rss_bytes(root_pid: int) -> int:
    """Calculate the sum of RSS memory (bytes) across the root process and all child processes.

    Platform note:
      - On Windows and Linux, `children(recursive=True)` traverses the active process tree.
      - Handles processes that terminate between enumeration and inspection (`NoSuchProcess`).
      - Handles security restrictions (`AccessDenied`).
    """
    total_rss = 0
    try:
        parent = psutil.Process(root_pid)
        procs = [parent]
        try:
            procs.extend(parent.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        for p in procs:
            try:
                if p.is_running():
                    total_rss += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return total_rss


def run_benchmark(
    command: Sequence[str] | str,
    stage: str = "pipeline",
    paper_id: str | None = None,
    disk_path: str | Path | None = None,
    sampling_interval: float = DEFAULT_SAMPLING_INTERVAL,
    timeout: float | None = None,
    testbed: str | None = None,
    notes: str | None = None,
    cwd: str | Path | None = None,
    capture_output: bool = False,
) -> tuple[BenchmarkResult, subprocess.CompletedProcess | None]:
    """Execute a command, monitor resource consumption, and return structured metrics.

    Args:
        command: Command to execute (as a list of tokens or shell string).
        stage: Pipeline stage name (e.g., 'discovery', 'download', 'extract').
        paper_id: Optional arXiv ID or paper identifier.
        disk_path: Directory or file path to measure disk usage delta for.
        sampling_interval: Seconds between RAM sampling ticks.
        timeout: Optional timeout in seconds.
        testbed: Host platform identifier (auto-detected if None).
        notes: Additional context or notes.
        cwd: Working directory for process execution.
        capture_output: Whether to capture stdout/stderr in memory.

    Returns:
        Tuple of (BenchmarkResult, CompletedProcess or None)
    """
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    command_str = " ".join(command) if isinstance(command, (list, tuple)) else str(command)
    active_testbed = testbed or get_default_testbed()

    # Determine disk scope and initial size
    disk_target: Path | None = Path(disk_path).resolve() if disk_path else None
    initial_disk_bytes: int = 0
    disk_scope: str = "none"
    if disk_target is not None:
        disk_scope = f"delta:{disk_target.name}"
        initial_disk_bytes = calculate_dir_size_bytes(disk_target)

    # Prepare RAM sampling data
    ram_samples: list[float] = []
    stop_event = threading.Event()
    process_holder: list[subprocess.Popen | None] = [None]

    def monitor_ram() -> None:
        """Background thread polling memory usage of the process tree."""
        while not stop_event.is_set():
            proc = process_holder[0]
            if proc is not None and proc.poll() is None:
                rss_bytes = get_tree_rss_bytes(proc.pid)
                if rss_bytes > 0:
                    rss_mb = round(rss_bytes / BYTES_PER_MB, 2)
                    ram_samples.append(rss_mb)
            stop_event.wait(sampling_interval)

    started_at_dt = datetime.now(timezone.utc)
    started_at_utc = started_at_dt.isoformat()
    t_start = time.perf_counter()

    monitor_thread = threading.Thread(target=monitor_ram, name="RAMMonitor", daemon=True)
    exit_code: int | None = None
    status: str = "error"
    completed_proc: subprocess.CompletedProcess | None = None
    stdout_data: str | None = None
    stderr_data: str | None = None

    try:
        use_shell = isinstance(command, str)
        proc = subprocess.Popen(
            command,
            shell=use_shell,
            cwd=cwd,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True if capture_output else False,
        )
        process_holder[0] = proc
        monitor_thread.start()

        # Immediate first sample to capture initial memory
        initial_rss = get_tree_rss_bytes(proc.pid)
        if initial_rss > 0:
            ram_samples.append(round(initial_rss / BYTES_PER_MB, 2))

        try:
            out, err = proc.communicate(timeout=timeout)
            if capture_output:
                stdout_data = out
                stderr_data = err
            exit_code = proc.returncode
            status = "success" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            if capture_output:
                stdout_data = out
                stderr_data = err
            exit_code = -1
            status = "timeout"
            err_msg = f"Command timed out after {timeout} seconds"
            notes = f"{notes}; {err_msg}" if notes else err_msg

    except FileNotFoundError as fnf_err:
        exit_code = 127
        status = "error"
        notes = f"{notes}; Command not found: {fnf_err}" if notes else f"Command not found: {fnf_err}"
    except Exception as exc:
        exit_code = 1
        status = "error"
        notes = f"{notes}; Execution error: {exc}" if notes else f"Execution error: {exc}"
    finally:
        t_end = time.perf_counter()
        ended_at_dt = datetime.now(timezone.utc)
        ended_at_utc = ended_at_dt.isoformat()
        stop_event.set()
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=1.0)

    wall_time_seconds = round(max(0.0, t_end - t_start), 4)

    # Calculate RAM metrics
    peak_ram_mb: float | None = max(ram_samples) if ram_samples else None
    average_ram_mb: float | None = (
        round(sum(ram_samples) / len(ram_samples), 2) if ram_samples else None
    )

    # Calculate Disk metrics
    disk_usage_mb: float | None = None
    if disk_target is not None:
        final_disk_bytes = calculate_dir_size_bytes(disk_target)
        delta_bytes = final_disk_bytes - initial_disk_bytes
        # Store delta in MB (can be 0.0 or positive/negative if files removed)
        disk_usage_mb = round(delta_bytes / BYTES_PER_MB, 4)

    result = BenchmarkResult(
        run_id=run_id,
        stage=stage,
        paper_id=paper_id,
        command=command_str,
        started_at_utc=started_at_utc,
        ended_at_utc=ended_at_utc,
        exit_code=exit_code,
        status=status,
        wall_time_seconds=wall_time_seconds,
        peak_ram_mb=peak_ram_mb,
        average_ram_mb=average_ram_mb,
        ram_sampling_interval_seconds=sampling_interval,
        disk_usage_mb=disk_usage_mb,
        disk_scope=disk_scope,
        testbed=active_testbed,
        tool_version=TOOL_VERSION,
        notes=notes,
    )

    if exit_code is not None:
        completed_proc = subprocess.CompletedProcess(
            args=command,
            returncode=exit_code,
            stdout=stdout_data,
            stderr=stderr_data,
        )

    return result, completed_proc


# CSV Column order matching the proposed benchmark schema
SCHEMA_COLUMNS: list[str] = [
    "run_id",
    "stage",
    "paper_id",
    "command",
    "started_at_utc",
    "ended_at_utc",
    "exit_code",
    "status",
    "wall_time_seconds",
    "peak_ram_mb",
    "average_ram_mb",
    "ram_sampling_interval_seconds",
    "disk_usage_mb",
    "disk_scope",
    "testbed",
    "tool_version",
    "notes",
]


def append_to_csv(result: BenchmarkResult, csv_path: str | Path) -> Path:
    """Append a benchmark record to a CSV file, writing header if the file is new."""
    path = Path(csv_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_COLUMNS)
        if write_header:
            writer.writeheader()
        row = result.to_dict()
        # Clean null values to empty string for clean CSV representation
        clean_row = {k: ("" if row[k] is None else row[k]) for k in SCHEMA_COLUMNS}
        writer.writerow(clean_row)
    return path


def save_to_json(result: BenchmarkResult, json_path: str | Path) -> Path:
    """Save or append a benchmark record to a JSON file."""
    path = Path(json_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    if path.exists() and path.stat().st_size > 0:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                records = existing
            elif isinstance(existing, dict):
                records = [existing]
        except Exception:
            records = []

    records.append(result.to_dict())
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def print_summary(res: BenchmarkResult) -> None:
    """Print a clean human-readable summary of the benchmark metrics to console."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"BENCHMARK REPORT — {res.run_id}")
    print(f"{sep}")
    print(f"Command          : {res.command}")
    print(f"Stage            : {res.stage}")
    print(f"Paper ID         : {res.paper_id or 'N/A'}")
    print(f"Status           : {res.status.upper()} (Exit code: {res.exit_code})")
    print(f"Wall-clock Time  : {res.wall_time_seconds:.4f} s")
    print(
        f"Peak RAM         : {f'{res.peak_ram_mb:.2f} MB' if res.peak_ram_mb is not None else 'N/A'}"
    )
    print(
        f"Average RAM      : {f'{res.average_ram_mb:.2f} MB' if res.average_ram_mb is not None else 'N/A'}"
    )
    print(f"RAM Interval     : {res.ram_sampling_interval_seconds:.2f} s")
    print(
        f"Disk Usage       : {f'{res.disk_usage_mb:+.4f} MB' if res.disk_usage_mb is not None else 'N/A'} (Scope: {res.disk_scope})"
    )
    print(f"Timestamps (UTC) : {res.started_at_utc} -> {res.ended_at_utc}")
    print(f"Testbed          : {res.testbed}")
    if res.notes:
        print(f"Notes            : {res.notes}")
    print(f"{sep}\n")


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for CLI usage."""
    parser = argparse.ArgumentParser(
        prog="benchmark.py",
        description="Performance benchmarking utility for crawling and parsing pipelines.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Measure a quick command:
  python src/benchmark.py -- python -c "import time; time.sleep(1)"

  # Benchmark discovery module on sample IDs, append to logs/benchmark_runs.csv:
  python src/benchmark.py --stage discovery --ids ids/example.txt --csv logs/benchmark_runs.csv -- python src/discovery.py --ids ids/example.txt --limit 2

  # Track disk output on corpus folder:
  python src/benchmark.py --stage download --disk-path corpus --csv logs/benchmark_runs.csv -- python src/downloader.py --ids ids/example.txt

  # Save JSON metrics and set custom sampling interval:
  python src/benchmark.py --interval 0.05 --json logs/benchmark.json -- python script.py
""",
    )

    parser.add_argument(
        "--stage",
        type=str,
        default="pipeline",
        help="Pipeline stage identifier (e.g., discovery, download, extract, references). Default: 'pipeline'.",
    )
    parser.add_argument(
        "--paper-id",
        type=str,
        default=None,
        help="Optional paper arXiv ID or identifier associated with this benchmark run.",
    )
    parser.add_argument(
        "--disk-path",
        type=str,
        default=None,
        help="Directory or file path to monitor for disk size change (calculates pre/post size delta).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_SAMPLING_INTERVAL,
        help=f"RAM polling sampling interval in seconds (default: {DEFAULT_SAMPLING_INTERVAL}s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Optional maximum execution time before process termination.",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV file where results will be appended conforming to the team schema.",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Path to JSON file where results will be appended or saved.",
    )
    parser.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Optional descriptive notes or experiment tag.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress terminal summary output.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to benchmark. Precede with '-- ' to separate flags from command arguments.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cmd = args.command
    # Strip leading '--' if present in remainder
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    if not cmd:
        parser.print_help(sys.stderr)
        print("\nError: No command provided to benchmark.", file=sys.stderr)
        return 2

    result, proc = run_benchmark(
        command=cmd,
        stage=args.stage,
        paper_id=args.paper_id,
        disk_path=args.disk_path,
        sampling_interval=args.interval,
        timeout=args.timeout,
        notes=args.notes,
    )

    if args.csv:
        csv_path = append_to_csv(result, args.csv)
        if not args.quiet:
            print(f"[benchmark] Logged to CSV: {csv_path}")

    if args.json:
        json_path = save_to_json(result, args.json)
        if not args.quiet:
            print(f"[benchmark] Logged to JSON: {json_path}")

    if not args.quiet:
        print_summary(result)

    # Return child exit code, or 1 if failed
    return result.exit_code if result.exit_code is not None else 1


if __name__ == "__main__":
    sys.exit(main())
