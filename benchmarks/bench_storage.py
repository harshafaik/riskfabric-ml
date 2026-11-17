#!/usr/bin/env python3
"""
bench_storage.py — DuckDB vs ClickHouse query comparison.

Benchmarks the ACTUAL DuckDB training-data extraction query (load_gold_dataframe)
against a reconstructed ClickHouse equivalent (bulk-load Gold Parquet into a
scratch table). Does NOT benchmark the Gold join — that's Rust/Polars, not DuckDB/ClickHouse.

Label: "ClickHouse numbers obtained by reconstructing the defunct Gold path for
benchmarking only. ClickHouse is streaming-only in production; this scaffold exists
solely to validate the Storage Architecture Split decision."
"""

import os
import sys
import time
from datetime import datetime

import duckdb
import polars as pl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ml"))
from ml_utils import find_gold_snapshot

from common import (
    check_dependency,
    get_hardware_info,
    is_container_runtime_running,
    md_table,
    percentiles,
    print_hardware_info,
)

N_RUNS = 5
SCRATCH_TABLE = "bench_gold_snapshot"


def check_clickhouse() -> bool:
    return check_dependency("ClickHouse", "localhost", 9000)


def bench_duckdb(gold_path: str) -> list:
    """Time the real training-data load via DuckDB."""
    times = []
    for i in range(N_RUNS):
        start = time.perf_counter()
        conn = duckdb.connect()
        df = pl.from_arrow(
            conn.execute(f"SELECT * FROM '{gold_path}'").arrow()
        )
        conn.close()
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)
        print(f"    DuckDB run {i+1}/{N_RUNS}: {elapsed*1000:.1f} ms ({len(df)} rows)")
    return times


def bench_clickhouse(gold_path: str) -> list:
    """Bulk-load Gold Parquet into a scratch ClickHouse table, time the extraction query."""
    import clickhouse_connect
    import pandas as pd

    ch = clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        username="riskfabric_user",
        password="123",
        database="riskfabric",
    )

    ch.command(f"DROP TABLE IF EXISTS {SCRATCH_TABLE}")
    print(f"    Loading Gold Parquet into ClickHouse scratch table {SCRATCH_TABLE}...")

    conn = duckdb.connect()
    gold_df = pl.from_arrow(conn.execute(f"SELECT * FROM '{gold_path}'").arrow())
    conn.close()

    # Map Polars → ClickHouse types
    def map_type(dt) -> str:
        s = str(dt)
        if "Float" in s:
            return "Float64"
        if "UInt32" in s or "Int32" in s or "Int64" in s:
            return "Int64"
        if s == "Boolean":
            return "UInt8"
        if "Datetime" in s:
            return "DateTime64(3)"
        return "String"

    cols = [f"`{c}` {map_type(d)}" for c, d in zip(gold_df.columns, gold_df.dtypes)]
    ddl = f"CREATE TABLE {SCRATCH_TABLE} ({', '.join(cols)}) ENGINE = MergeTree() ORDER BY tuple()"
    ch.command(ddl)

    # Use Arrow-based insert for reliable type handling
    conn2 = duckdb.connect()
    arrow_table = conn2.execute(f"SELECT * FROM '{gold_path}'").fetch_arrow_table()
    conn2.close()
    ch.insert_arrow(SCRATCH_TABLE, arrow_table)
    total_count = ch.command(f"SELECT count() FROM {SCRATCH_TABLE}")
    print(f"    Loaded {total_count} rows into ClickHouse")

    # Benchmark: equivalent extraction query
    # Select all columns (the real DuckDB query does SELECT *)
    col_names = ", ".join(f"`{c}`" for c in gold_df.columns)
    query = f"SELECT {col_names} FROM {SCRATCH_TABLE}"

    times = []
    for i in range(N_RUNS):
        start = time.perf_counter()
        result = ch.query(query)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)
        print(f"    ClickHouse run {i+1}/{N_RUNS}: {elapsed*1000:.1f} ms ({result.result_rows} rows)")

    # Cleanup
    ch.command(f"DROP TABLE IF EXISTS {SCRATCH_TABLE}")
    return times


def main():
    print_hardware_info()

    try:
        gold_path = find_gold_snapshot(None)
    except FileNotFoundError:
        print("ERROR: No Gold snapshot found. Run `cargo run --release --bin etl -- gold-master` first.")
        print("After ETL, re-run: python benchmarks/bench_storage.py")
        sys.exit(1)

    print(f"Gold snapshot: {gold_path}")
    size_mb = os.path.getsize(gold_path) / (1024 * 1024)
    print(f"Gold Parquet size: {size_mb:.1f} MB")

    # ── DuckDB ──────────────────────────────────────────────────────────
    print("\n--- DuckDB (in-process, 0 servers) ---")
    duckdb_times = bench_duckdb(gold_path)

    # ── ClickHouse ──────────────────────────────────────────────────────
    print("\n--- ClickHouse (1 server, port 9000) ---")
    if not is_container_runtime_running():
        print("  ⚠ Container runtime not available — skipping ClickHouse")
        clickhouse_times = None
    elif not check_clickhouse():
        print("  ⚠ ClickHouse not reachable")
        print("  Start with: docker compose up -d clickhouse")
        clickhouse_times = None
    else:
        clickhouse_times = bench_clickhouse(gold_path)

    # ── Report ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  DuckDB vs ClickHouse — Query Time Comparison")
    print("  Extraction query: SELECT * FROM Gold Parquet")
    print("=" * 60)
    print()
    print("> ClickHouse numbers obtained by reconstructing the defunct Gold path")
    print("> for benchmarking only. ClickHouse is streaming-only in production;")
    print("> this scaffold exists solely to validate the Storage Architecture Split decision.")
    print()

    headers = ["Engine", "Query time p50", "p95", "p99", "Infra"]
    rows = []

    dp = percentiles(duckdb_times)
    rows.append([
        "DuckDB",
        f"{dp['p50']:.1f} ms",
        f"{dp['p95']:.1f} ms",
        f"{dp['p99']:.1f} ms",
        "in-process, 0 servers, 0 ports, 0 containers",
    ])

    if clickhouse_times:
        cp = percentiles(clickhouse_times)
        rows.append([
            "ClickHouse",
            f"{cp['p50']:.1f} ms",
            f"{cp['p95']:.1f} ms",
            f"{cp['p99']:.1f} ms",
            "1 server, 1 port, 1 container",
        ])

    print(md_table(headers, rows))
    print()
    print("### Infra Overhead Note")
    print()
    print("The old batch pipeline ingested Parquet into ClickHouse, read it back for")
    print("feature computation, then wrote it back — a round-trip that existed only")
    print("because ClickHouse was the default store. DuckDB reads the same Parquet directly")
    print("with zero servers — no daemon to run, no port to expose, no container to maintain.")
    print()

    # Write results
    import json
    out = {
        "hardware": get_hardware_info(),
        "gold_snapshot": gold_path,
        "gold_size_mb": size_mb,
        "timestamp": datetime.now().isoformat(),
        "duckdb": {
            "p50": dp["p50"],
            "p95": dp["p95"],
            "p99": dp["p99"],
            "mean_ms": sum(duckdb_times) / len(duckdb_times),
        },
    }
    if clickhouse_times:
        out["clickhouse"] = {
            "p50": cp["p50"],
            "p95": cp["p95"],
            "p99": cp["p99"],
            "mean_ms": sum(clickhouse_times) / len(clickhouse_times),
        }
    with open("benchmarks/storage_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"Results written to benchmarks/storage_results.json")


if __name__ == "__main__":
    main()
