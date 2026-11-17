#!/usr/bin/env bash
# bench_ratelimit.sh — Streaming rate-limiter accuracy benchmark
#
# Measures actual throughput vs target (100 tx/s) from stream.rs.
# Dependencies: Redpanda (docker compose up -d redpanda)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "==> Hardware"
echo "    CPU: $(lscpu 2>/dev/null | grep 'Model name' | cut -d: -f2 | xargs || echo unknown)"
echo

command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo not found"; exit 1; }

# Check Redpanda
if ! timeout 2 bash -c "echo > /dev/tcp/localhost/9092" 2>/dev/null; then
    echo "ERROR: Redpanda not reachable at localhost:9092"
    echo "Start with: docker compose up -d redpanda"
    exit 1
fi

echo "==> Building stream release binary..."
cargo build --release --bin stream 2>&1 | tail -1

DURATION=120
TARGET_RATE=100

echo
echo "==> Streaming rate-limiter test: target ${TARGET_RATE} tx/s, duration ${DURATION}s"
echo "    Starting stream.rs and capturing output..."

# Run stream for DURATION seconds, capture output
timeout $((DURATION + 5)) cargo run --release --bin stream 2>&1 | tee /tmp/stream_output.txt &
PID=$!

# Wait for duration
sleep $DURATION
kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# Parse output for throughput events
echo
echo "==> Parsing throughput events..."

# Stream.rs emits progress events: "StreamTick" with records_per_sec
# Try to find throughput lines
if [ -f /tmp/stream_output.txt ]; then
    total_lines=$(wc -l < /tmp/stream_output.txt)
    echo "    Captured ${total_lines} lines of output"

    # Look for records_per_sec in output
    rates=$(grep -oP 'records_per_sec[:\s]*\K[\d.]+' /tmp/stream_output.txt 2>/dev/null || echo "")
    if [ -n "$rates" ]; then
        echo "    Found throughput samples:"
        echo "$rates" | head -20
        echo "    ..."
        echo

        # Compute stats
        if command -v python3 >/dev/null 2>&1; then
            echo "$rates" | python3 -c "
import sys
rates = [float(line.strip()) for line in sys.stdin if line.strip()]
if rates:
    print(f'Samples: {len(rates)}')
    print(f'Mean: {sum(rates)/len(rates):.1f} tx/s')
    print(f'Target: ${TARGET_RATE} tx/s')
    print(f'Error: {sum(rates)/len(rates) - ${TARGET_RATE}:.1f} tx/s')
    print(f'Min: {min(rates):.1f}, Max: {max(rates):.1f}')
    s = sorted(rates)
    n = len(s)
    print(f'p50: {s[n//2]:.1f}, p95: {s[int(n*0.95)]:.1f}, p99: {s[int(n*0.99)]:.1f}')
"
        fi
    else
        echo "    No throughput metrics found in output."
        echo "    The stream.rs binary may not emit records_per_sec in human-readable form."
        echo

        # Fallback: show last 30 lines for manual inspection
        echo "    Last 30 lines of output:"
        tail -30 /tmp/stream_output.txt
    fi
fi

echo
echo "| Metric | Value |"
echo "| :--- | ---: |"
echo "| Target rate | ${TARGET_RATE} tx/s |"
echo "| Duration | ${DURATION}s |"
echo "| Measured rate | TODO (see above) |"
