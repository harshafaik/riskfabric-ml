#!/usr/bin/env python3
"""
bench_scoring.py — Scoring latency and throughput benchmark.

Measures end-to-end pipeline latency (kafka_received_at → scored_at) via ClickHouse
and sustained throughput (tx/s). Also compares batch=1 vs batch=50.

Dependencies: Redpanda, ClickHouse, Redis (docker compose up)
Guard: checks all three services are healthy before starting
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

from common import (
    check_dependency,
    get_hardware_info,
    is_container_runtime_running,
    md_table,
    percentiles,
    print_hardware_info,
)


def check_services() -> bool:
    ok = True
    if not is_container_runtime_running():
        print("ERROR: Container runtime (docker/podman) not running")
        return False
    for svc, host, port in [
        ("Redpanda", "localhost", 9092),
        ("ClickHouse", "localhost", 9000),
        ("Redis", "localhost", 6379),
    ]:
        if not check_dependency(svc, host, port):
            ok = False
    return ok


def query_clickhouse_latency() -> list:
    """Query p50/p95/p99 pipeline latency from ClickHouse fraud_scores."""
    import clickhouse_connect
    ch = clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        username="riskfabric_user",
        password="123",
        database="riskfabric",
    )

    # Get all latencies in ms
    result = ch.query(
        "SELECT dateDiff('millisecond', kafka_received_at, scored_at) AS latency "
        "FROM fraud_scores "
        "WHERE scored_at >= now() - INTERVAL 10 MINUTE "
        "ORDER BY scored_at"
    )

    latencies = [row[0] for row in result.result_rows if row[0] is not None]
    return latencies


def query_clickhouse_count() -> int:
    """Count rows scored in the last 10 minutes."""
    import clickhouse_connect
    ch = clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        username="riskfabric_user",
        password="123",
        database="riskfabric",
    )
    result = ch.query(
        "SELECT count() FROM fraud_scores "
        "WHERE scored_at >= now() - INTERVAL 10 MINUTE"
    )
    return result.result_rows[0][0]


def make_scorer_copy(batch_size: int) -> str:
    """Create a temp copy of scorer.py with batch_size modified."""
    import shutil
    import importlib

    src = "src/ml/scorer.py"
    with open(src) as f:
        content = f.read()

    # Replace batch_size = 50 with requested value
    new_content = content.replace("batch_size = 50", f"batch_size = {batch_size}")

    tmpdir = tempfile.mkdtemp(prefix="bench_scorer_")
    dest = os.path.join(tmpdir, "scorer.py")
    with open(dest, "w") as f:
        f.write(new_content)

    # Also copy model_utils.py
    shutil.copy("src/ml/model_utils.py", os.path.join(tmpdir, "model_utils.py"))
    shutil.copy("src/ml/ml_utils.py", os.path.join(tmpdir, "ml_utils.py"))

    return dest


def run_scorer_duration(scorer_path: str, duration: int = 60) -> None:
    """Run the scorer for a given duration."""
    cwd = os.path.dirname(scorer_path)
    env = os.environ.copy()
    env["KAFKA_BOOTSTRAP_SERVERS"] = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    env["REDIS_HOST"] = os.getenv("REDIS_HOST", "localhost")
    env["CLICKHOUSE_HOST"] = os.getenv("CLICKHOUSE_HOST", "localhost")

    # Run scorer as subprocess
    proc = subprocess.Popen(
        [sys.executable, scorer_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        proc.wait(timeout=duration)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)

    return proc.stdout


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        if check_services():
            print("All services healthy")
            sys.exit(0)
        else:
            print("Services not ready")
            sys.exit(1)

    print_hardware_info()

    if not check_services():
        print()
        print("ERROR: Required services not running.")
        print()
        print("Start all services:")
        print("  docker compose up -d")
        print()
        print("Then build the scorer image (first time only):")
        print("  podman build -t localhost/riskfabric_dlt -f Dockerfile.dlt .")
        print()
        print("Then re-run:")
        print("  python benchmarks/bench_scoring.py")
        sys.exit(1)

    print("All services healthy. Starting benchmarks...")

    # ── Batch=50 benchmark ───────────────────────────────────────────────
    print("\n--- Benchmark: batch_size=50 (default) ---")
    print("  Starting streaming generator + scorer...")
    print("  (This is a skeleton — streaming must be started manually)")
    print()

    # Query current latency if scorer has been running
    print("  Querying ClickHouse for pipeline latency...")
    try:
        latencies = query_clickhouse_latency()
        if latencies:
            pcts = percentiles(latencies)
            count = len(latencies)
            print(f"  Found {count} scored rows in last 10 min")
            print(f"  p50: {pcts['p50']:.1f} ms")
            print(f"  p95: {pcts['p95']:.1f} ms")
            print(f"  p99: {pcts['p99']:.1f} ms")

            # Query total for throughput
            total = query_clickhouse_count()
            print(f"  Total scored in last 10 min: {total}")
        else:
            print("  No scored rows found in last 10 min.")
            print()
            print("  To run this benchmark:")
            print("    1. Ensure docker compose is up and services are healthy")
            print("    2. Publish transactions to Redpanda (stream producer pending extraction)")
            print("    3. Start scorer: python src/ml/scorer.py")
            print("    4. Let it run for 5+ minutes, then re-run this script")
            print()
            print("  The batch=50 vs batch=1 comparison will:")
            print("    - Run scorer at batch=50 for 5 min, measure latency/tx")
            print("    - Run scorer at batch=1 for 5 min, measure latency/tx")
            print("    - Report the amortization benefit of micro-batching")
            print()
            print("  | Metric | batch=50 | batch=1 | Improvement |")
            print("  | :--- | ---: | ---: | ---: |")
            print("  | p50 latency (ms) | TODO | TODO | TODO |")
            print("  | p95 latency (ms) | TODO | TODO | TODO |")
            print("  | p99 latency (ms) | TODO | TODO | TODO |")
            print("  | Throughput (tx/s) | TODO | TODO | TODO |")
    except ImportError:
        print("  clickhouse_connect not available — install with: pip install clickhouse-connect")
    except Exception as e:
        print(f"  ClickHouse query failed: {e}")
        print("  Make sure the scorer has been running and producing data.")


if __name__ == "__main__":
    main()
