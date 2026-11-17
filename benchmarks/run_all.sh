#!/usr/bin/env bash
# run_all.sh — Combined benchmark runner
#
# Runs all feasible benchmarks, skips ones with unavailable dependencies,
# and emits a single benchmarks/report.md.
#
# Usage: bash benchmarks/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

REPORT="benchmarks/report.md"
RUST_BINARIES=0
DOCKER_SERVICES=0

cleanup() {
    echo
    echo "Benchmark run interrupted. Partial results in $REPORT"
    exit 1
}
trap cleanup INT TERM

# ── Report header ───────────────────────────────────────────────────────
cat > "$REPORT" << 'HEADER'
# RiskFabric Performance Benchmarks

## Hardware

HEADER

# Append hardware info
{
    echo "- **Hostname**: $(hostname)"
    echo "- **OS**: $(uname -sr)"
    echo "- **CPU**: $(lscpu 2>/dev/null | grep 'Model name' | cut -d: -f2 | xargs || echo unknown)"
    echo "- **Logical cores**: $(nproc)"
    echo "- **RAM**: $(free -h 2>/dev/null | awk '/Mem:/ {print $2}' || echo unknown)"
    echo "- **Disk**: $(df -h / 2>/dev/null | awk 'NR==2 {print $1, $2}' || echo unknown)"
    echo "- **Python**: $(python3 --version 2>/dev/null || echo not found)"
    echo "- **Rust**: $(rustc --version 2>/dev/null || echo not found)"
    echo ""
    echo "## Methodology"
    echo ""
    echo "All benchmarks use **seed=42**, **N=5 repetitions** (unless noted), and report"
    echo "**mean ± std**. Latency percentiles are **p50/p95/p99** — never averages alone."
    echo ""
    echo "---"
    echo ""
} >> "$REPORT"

# ── Check available dependencies ────────────────────────────────────────
echo "==> Checking dependencies..."

if command -v cargo >/dev/null 2>&1; then
    RUST_BINARIES=1
    echo "    ✓ Rust toolchain"
else
    echo "    ✗ Rust toolchain (skipping generation/ETL benchmarks)"
fi

# Check Docker
if docker info >/dev/null 2>&1; then
    echo "    ✓ Docker"
    DOCKER_SERVICES=1
else
    # Try podman
    if podman info >/dev/null 2>&1; then
        echo "    ✓ Podman"
        DOCKER_SERVICES=1
    else
        echo "    ✗ Docker/Podman (skipping service-dependent benchmarks)"
    fi
fi

# Check individual services
REDIS_OK=0
CLICKHOUSE_OK=0
REDPANDA_OK=0

if [ $DOCKER_SERVICES -eq 1 ]; then
    timeout 2 bash -c "echo > /dev/tcp/localhost/6379" 2>/dev/null && { echo "    ✓ Redis"; REDIS_OK=1; } || echo "    ✗ Redis (start: docker compose up -d redis)"
    timeout 2 bash -c "echo > /dev/tcp/localhost/9000" 2>/dev/null && { echo "    ✓ ClickHouse"; CLICKHOUSE_OK=1; } || echo "    ✗ ClickHouse (start: docker compose up -d clickhouse)"
    timeout 2 bash -c "echo > /dev/tcp/localhost/9092" 2>/dev/null && { echo "    ✓ Redpanda"; REDPANDA_OK=1; } || echo "    ✗ Redpanda (start: docker compose up -d redpanda)"
fi

# ── HERO BENCHMARKS ─────────────────────────────────────────────────────
echo ""
echo "==> Running Hero Benchmarks..."
echo ""

# 2a: Scoring latency
{
    echo "## 2a. Scoring Latency & Throughput"
    echo ""
} >> "$REPORT"

if [ $REDPANDA_OK -eq 1 ] && [ $CLICKHOUSE_OK -eq 1 ] && [ $REDIS_OK -eq 1 ]; then
    echo "    Running bench_scoring.py..."
    if python3 "$SCRIPT_DIR/bench_scoring.py" --check 2>/dev/null; then
        python3 "$SCRIPT_DIR/bench_scoring.py" 2>&1 | tee -a "$REPORT"
    else
        echo "    ⚠ bench_scoring.py requires the scorer to have been running prior"
        echo "    Run: docker compose up -d && python src/ml/scorer.py"
    fi
else
    echo "    ⚠ Skipping — requires Redpanda, ClickHouse, and Redis"
    echo ""
    {
        echo "**Dependencies:** Redpanda + ClickHouse + Redis (docker compose up)"
        echo ""
        echo "| Metric | batch=50 | batch=1 | Improvement |"
        echo "| :--- | ---: | ---: | ---: |"
        echo "| p50 latency (ms) | TODO | TODO | TODO |"
        echo "| p95 latency (ms) | TODO | TODO | TODO |"
        echo "| p99 latency (ms) | TODO | TODO | TODO |"
        echo "| Throughput (tx/s) | TODO | TODO | TODO |"
        echo ""
        echo "**How to run:**"
        echo '```bash'
        echo 'docker compose up -d                          # start services'
        echo '# NOTE: the stream producer is pending extraction to a separate service'
        echo 'python src/ml/scorer.py &                     # start scoring'
        echo '# Wait 5 min, then:'
        echo 'python benchmarks/bench_scoring.py            # query ClickHouse for latencies'
        echo '```'
        echo ""
    } >> "$REPORT"
fi

# 2c: DuckDB vs ClickHouse
{
    echo "## 2c. DuckDB vs ClickHouse"
    echo ""
} >> "$REPORT"

if [ $CLICKHOUSE_OK -eq 1 ] && command -v python3 >/dev/null 2>&1; then
    echo "    Running bench_storage.py..."
    python3 "$SCRIPT_DIR/bench_storage.py" 2>&1 | tee -a "$REPORT"
else
    echo "    ⚠ Skipping — requires ClickHouse + Gold snapshot"
    {
        echo "**Dependencies:** ClickHouse (docker compose up -d clickhouse) + Gold Parquet snapshot"
        echo ""
        echo "| Engine | Query time p50 | p95 | p99 | Infra |"
        echo "| :--- | ---: | ---: | ---: | :--- |"
        echo "| DuckDB | TODO | TODO | TODO | in-process, 0 servers |"
        echo "| ClickHouse | TODO | TODO | TODO | 1 server, port 9000 |"
        echo ""
        echo "**How to run:**"
        echo '```bash'
        echo 'docker compose up -d clickhouse'
        echo 'python benchmarks/bench_storage.py'
        echo '```'
        echo ""
    } >> "$REPORT"
fi

# 2d: Leakage AUC
{
    echo "## 2d. Leakage AUC"
    echo ""
} >> "$REPORT"

if command -v python3 >/dev/null 2>&1; then
    echo "    Running bench_leakage.py..."
    python3 "$SCRIPT_DIR/bench_leakage.py" 2>&1 | tee -a "$REPORT"
else
    {
        echo "**Dependencies:** Python + Gold Parquet snapshot"
        echo ""
        echo "| Variant | AUC |"
        echo "| :--- | ---: |"
        echo "| Honest baseline (chronological) | TODO |"
        echo "| + amount feature | TODO |"
        echo "| + target encoding | TODO |"
        echo "| + random split | TODO |"
        echo ""
        echo "**How to run:**"
        echo '```bash'
        echo 'python benchmarks/bench_leakage.py'
        echo '```'
        echo ""
    } >> "$REPORT"
fi

# ── TIER-2 BENCHMARKS ───────────────────────────────────────────────────
echo ""
echo "==> Running Tier-2 Benchmarks..."
echo ""

# 3a: ETL throughput
{
    echo "## 3a. ETL Throughput"
    echo ""
} >> "$REPORT"

if [ $RUST_BINARIES -eq 1 ]; then
    echo "    Running bench_etl.sh..."
    bash "$SCRIPT_DIR/bench_etl.sh" 2>&1 | tee -a "$REPORT"
else
    {
        echo "**Dependencies:** Rust toolchain + generated Parquet"
        echo ""
        echo "| Stage | Rows/sec |"
        echo "| :--- | ---: |"
        echo "| Silver-all | TODO |"
        echo "| Gold-master | TODO |"
        echo ""
        echo "**How to run:**"
        echo '```bash'
        echo 'bash benchmarks/bench_etl.sh'
        echo '```'
        echo ""
    } >> "$REPORT"
fi

# 3b: Redis latency
{
    echo "## 3b. Redis Lookup Latency"
    echo ""
} >> "$REPORT"

if [ $REDIS_OK -eq 1 ] && command -v python3 >/dev/null 2>&1; then
    echo "    Running bench_redis.py..."
    python3 "$SCRIPT_DIR/bench_redis.py" 2>&1 | tee -a "$REPORT"
else
    {
        echo "**Dependencies:** Redis (docker compose up -d redis)"
        echo ""
        echo "| Operation | p50 (µs) | p99 (µs) |"
        echo "| :--- | ---: | ---: |"
        echo "| HGETALL (customer stats) | TODO | TODO |"
        echo "| GET (last timestamp) | TODO | TODO |"
        echo "| ZADD (burst add) | TODO | TODO |"
        echo "| ... | TODO | TODO |"
        echo ""
        echo "**How to run:**"
        echo '```bash'
        echo 'docker compose up -d redis'
        echo 'python benchmarks/bench_redis.py'
        echo '```'
        echo ""
    } >> "$REPORT"
fi

# 3c: Rate-limiter
{
    echo "## 3c. Streaming Rate-Limiter Accuracy"
    echo ""
} >> "$REPORT"

if [ $REDPANDA_OK -eq 1 ] && [ $RUST_BINARIES -eq 1 ]; then
    echo "    Running bench_ratelimit.sh..."
    bash "$SCRIPT_DIR/bench_ratelimit.sh" 2>&1 | tee -a "$REPORT"
else
    {
        echo "**Dependencies:** Redpanda (docker compose up -d redpanda)"
        echo ""
        echo "| Target | Measured | Error |"
        echo "| ---: | ---: | ---: |"
        echo "| 100 tx/s | TODO | TODO |"
        echo ""
        echo "**How to run:**"
        echo '```bash'
        echo 'docker compose up -d redpanda'
        echo 'bash benchmarks/bench_ratelimit.sh'
        echo '```'
        echo ""
    } >> "$REPORT"
fi

echo ""
echo "==> Done!"
echo "Report written to: $REPORT"
echo ""
echo "Quick summary:"
echo "  cd $(pwd)"
echo "  cat $REPORT"
