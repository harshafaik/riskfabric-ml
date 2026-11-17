#!/usr/bin/env bash
# bench_etl.sh — ETL throughput benchmark (rows/sec Bronze→Silver→Gold)
#
# Dependencies: Rust toolchain, Parquet output from generate.rs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "==> Hardware"
echo "    CPU: $(lscpu 2>/dev/null | grep 'Model name' | cut -d: -f2 | xargs || echo unknown)"
echo "    Cores: $(nproc) logical"
echo

command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo not found"; exit 1; }

# Check prerequisites exist
if [ ! -f data/bronze/transactions.parquet ]; then
    echo "ERROR: data/bronze/transactions.parquet not found"
    echo "Run first: scrip generate --out-dir data/bronze"
    exit 1
fi

echo "==> Building ETL release binary..."
cargo build --release --bin etl 2>&1 | tail -1

echo
echo "==> ETL Throughput"
echo

N_RUNS=3

# Silver-all
echo "--- Silver (all stages) ---"
for i in $(seq 1 $N_RUNS); do
    echo -n "  Run ${i}/${N_RUNS}... "
    /usr/bin/time -f "%e" cargo run --release --bin etl -- silver-all 2>&1 | tail -5
done

# Gold
echo
echo "--- Gold master ---"
for i in $(seq 1 $N_RUNS); do
    echo -n "  Run ${i}/${N_RUNS}... "
    /usr/bin/time -f "%e" cargo run --release --bin etl -- gold-master 2>&1 | tail -5
done

echo
echo "Manual summary: Check output above for timing."
echo "Rows/sec will depend on the generated dataset size."
echo
echo "| Stage | Wall Time (s) | Rows | Rows/sec |"
echo "| :--- | ---: | ---: | ---: |"
echo "| Silver-all | TODO | TODO | TODO |"
echo "| Gold-master | TODO | TODO | TODO |"
