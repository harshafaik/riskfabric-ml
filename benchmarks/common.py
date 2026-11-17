#!/usr/bin/env python3
"""Shared utilities for RiskFabric benchmark harnesses."""

import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


def get_hardware_info() -> dict:
    """Return CPU model, core count, RAM, disk type."""
    info: Dict[str, Any] = {}
    info["hostname"] = platform.node()
    info["os"] = f"{platform.system()} {platform.release()}"
    info["python"] = sys.version.split()[0]

    try:
        import psutil
        info["cpu_model"] = platform.processor() or "unknown"
        info["logical_cores"] = psutil.cpu_count(logical=True)
        info["physical_cores"] = psutil.cpu_count(logical=False)
        mem = psutil.virtual_memory()
        info["ram_gb"] = round(mem.total / (1024**3), 1)
        info["ram_available_gb"] = round(mem.available / (1024**3), 1)
    except ImportError:
        info["cpu_model"] = platform.processor() or "unknown"
        info["logical_cores"] = os.cpu_count()
        info["physical_cores"] = os.cpu_count()
        info["ram_gb"] = "psutil not available"
        info["ram_available_gb"] = "psutil not available"

    try:
        import psutil
        partitions = psutil.disk_partitions()
        root_part = next((p for p in partitions if p.mountpoint == "/"), None)
        if root_part:
            usage = psutil.disk_usage("/")
            info["disk_type"] = root_part.fstype
            info["disk_total_gb"] = round(usage.total / (1024**3), 1)
    except Exception:
        info["disk_type"] = "unknown"
        info["disk_total_gb"] = "unknown"

    return info


def print_hardware_info(info: Optional[dict] = None) -> None:
    """Print hardware info block for a benchmark report."""
    if info is None:
        info = get_hardware_info()
    print("---")
    print("### Hardware")
    for key, val in info.items():
        print(f"- **{key}**: {val}")
    print()


def percentiles(values: List[float]) -> Dict[str, float]:
    """Return p50, p95, p99 for a list of values."""
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    s = sorted(values)
    n = len(s)

    def _pct(p: float) -> float:
        idx = p * (n - 1) / 100.0
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return s[lo] + frac * (s[hi] - s[lo])

    return {
        "p50": _pct(50),
        "p95": _pct(95),
        "p99": _pct(99),
    }


def md_table(headers: List[str], rows: List[List[str]]) -> str:
    """Format a markdown table string."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---:" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def fmt_mean_std(values: List[float], unit: str = "", precision: int = 2) -> str:
    """Format mean ± std."""
    if not values:
        return "N/A"
    m = statistics.mean(values)
    s = statistics.stdev(values) if len(values) > 1 else 0.0
    if unit:
        return f"{m:.{precision}f} ± {s:.{precision}f} {unit}"
    return f"{m:.{precision}f} ± {s:.{precision}f}"


def check_dependency(name: str, host: str, port: int) -> bool:
    """Check if a TCP service is reachable."""
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        print(f"  ⚠ {name} not reachable at {host}:{port} — skipping benchmark")
        return False


def run_command(cmd: List[str], cwd: Optional[str] = None, timeout: int = 600,
                capture: bool = True) -> Tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=capture,
        text=True, timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def time_command(cmd: List[str], cwd: Optional[str] = None,
                 timeout: int = 600) -> float:
    """Run a command and return wall-clock time in seconds."""
    start = time.perf_counter()
    rc, _, stderr = run_command(cmd, cwd=cwd, timeout=timeout)
    elapsed = time.perf_counter() - start
    if rc != 0:
        print(f"  Command failed (exit {rc}): {' '.join(cmd)}")
        if stderr:
            print(f"  stderr: {stderr[:500]}")
        return float("nan")
    return elapsed


def bench_runner(name: str, n: int = 5, seed: int = 42) -> Callable:
    """Decorator for benchmark functions. Calls func() N times, prints results.

    The decorated function should accept an integer run_index (0..N-1) and
    return a Dict[str, float] of measured metrics.
    """
    def decorator(func: Callable[[int], Dict[str, float]]):
        def wrapper():
            print(f"\n{'='*60}")
            print(f"  {name}  (N={n}, seed={seed})")
            print(f"{'='*60}")
            print_hardware_info()

            all_metrics: Dict[str, List[float]] = {}
            for i in range(n):
                print(f"  Run {i+1}/{n}...", end=" ", flush=True)
                os.environ["BENCHMARK_SEED"] = str(seed)
                try:
                    metrics = func(i)
                except Exception as e:
                    print(f"FAILED: {e}")
                    continue
                for k, v in metrics.items():
                    all_metrics.setdefault(k, []).append(v)
                vals = ", ".join(f"{k}={v:.3f}" for k, v in metrics.items())
                print(f"{vals}")

            if not all_metrics:
                print("\n  No successful runs.\n")
                return

            print(f"\n  Results (mean ± std over {len(next(iter(all_metrics.values())))} runs):")
            table_headers = ["Metric"] + [f"Run {i+1}" for i in range(n)] + ["Mean ± Std"]
            table_rows = []
            for metric, vals in all_metrics.items():
                row = [metric] + [f"{v:.3f}" for v in vals] + [fmt_mean_std(vals)]
                table_rows.append(row)
                print(f"    {metric}: {fmt_mean_std(vals)}")
            print(f"\n{md_table(table_headers, table_rows)}")
            print()
            return all_metrics
        return wrapper
    return decorator


def is_container_runtime_running() -> bool:
    """Check if Docker or Podman is accessible."""
    for cmd in ["docker", "podman"]:
        try:
            result = subprocess.run(
                [cmd, "info"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


def get_peak_rss_mb() -> float:
    """Return current process peak RSS in MB, or 0 if psutil unavailable."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0
