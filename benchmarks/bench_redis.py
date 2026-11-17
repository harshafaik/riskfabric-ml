#!/usr/bin/env python3
"""
bench_redis.py — Redis lookup latency benchmark (p50/p99).

Measures per-operation latency for the Redis commands used by scorer.py.
Dependencies: Redis (docker compose), seeded data from seed_redis.py
"""

import json
import os
import time
from datetime import datetime

from common import (
    check_dependency,
    get_hardware_info,
    md_table,
    percentiles,
    print_hardware_info,
)


def bench_redis_operations(host: str = "localhost", port: int = 6379, n: int = 10000):
    """Benchmark individual Redis operations used by scorer.py."""
    import redis
    r = redis.Redis(host=host, port=port, db=0, decode_responses=True)
    r.ping()

    # Pre-populate test keys
    test_card = "bench_card_test_123"
    test_cust = "bench_cust_test_456"
    test_merch = "bench_merch_test_789"

    r.hset(f"cust:{test_cust}:stats", mapping={"count": 50, "mean": 2500.0, "M2": 12500.0})
    r.hset(f"cust:{test_cust}:agg", mapping={"fraud_rate": 0.02, "mean_hour": 14.5})
    r.hset(f"merch:{test_merch}:agg", mapping={"fraud_rate": 0.01})
    for i in range(10):
        r.rpush(f"card:{test_card}:history", json.dumps({
            "transaction_id": f"tx_test_{i}",
            "amount": 100.0 + i * 10,
            "merchant_category": "GROCERY",
        }))
    r.set(f"card:{test_card}:last_ts", time.time())
    r.hset(f"card:{test_card}:loc", mapping={"lat": 12.9716, "lon": 77.5946})
    r.set(f"card:{test_card}:seq", 50)
    # Burst window
    for i in range(5):
        r.zadd(f"card:{test_card}:burst", {f"tx_burst_{i}": time.time()})

    operations = {
        "HGETALL (customer stats)": lambda: r.hgetall(f"cust:{test_cust}:stats"),
        "HGETALL (customer agg)": lambda: r.hgetall(f"cust:{test_cust}:agg"),
        "HGETALL (merchant agg)": lambda: r.hgetall(f"merch:{test_merch}:agg"),
        "HGETALL (card location)": lambda: r.hgetall(f"card:{test_card}:loc"),
        "HSET (save stats)": lambda: r.hset(
            f"cust:{test_cust}:stats",
            mapping={"count": 51, "mean": 2520.0, "M2": 12600.0},
        ),
        "GET (last timestamp)": lambda: r.get(f"card:{test_card}:last_ts"),
        "SET (update timestamp)": lambda: r.set(f"card:{test_card}:last_ts", time.time()),
        "ZADD (burst add)": lambda: r.zadd(
            f"card:{test_card}:burst", {f"tx_burst_new": time.time()}
        ),
        "ZREMRANGEBYSCORE (burst evict)": lambda: r.zremrangebyscore(
            f"card:{test_card}:burst", 0, time.time() - 60
        ),
        "ZCARD (burst count)": lambda: r.zcard(f"card:{test_card}:burst"),
        "LINDEX (peek history)": lambda: r.lindex(f"card:{test_card}:history", 0),
        "LPUSH + LTRIM (push history)": lambda: (
            r.lpush(f"card:{test_card}:history", json.dumps({"test": "data"})),
            r.ltrim(f"card:{test_card}:history", 0, 9),
        ),
        "INCR (sequence)": lambda: r.incr(f"card:{test_card}:seq"),
    }

    results = {}
    for op_name, op_fn in operations.items():
        times = []
        for _ in range(n):
            start = time.perf_counter()
            op_fn()
            elapsed = (time.perf_counter() - start) * 1_000_000  # microseconds
            times.append(elapsed)
        pcts = percentiles(times)
        results[op_name] = {
            "p50_us": pcts["p50"],
            "p99_us": pcts["p99"],
            "mean_us": sum(times) / len(times),
        }

    # Cleanup
    r.delete(f"cust:{test_cust}:stats")
    r.delete(f"cust:{test_cust}:agg")
    r.delete(f"merch:{test_merch}:agg")
    r.delete(f"card:{test_card}:history")
    r.delete(f"card:{test_card}:last_ts")
    r.delete(f"card:{test_card}:loc")
    r.delete(f"card:{test_card}:seq")
    r.delete(f"card:{test_card}:burst")

    return results


def main():
    print_hardware_info()

    if not check_dependency("Redis", "localhost", 6379):
        print("ERROR: Redis not running.")
        print("Start with: docker compose up -d redis")
        sys.exit(1)

    print("Benchmarking Redis operations (10,000 iterations each)...")
    results = bench_redis_operations(n=10000)

    print("\nRedis Operation Latency (microseconds)")
    print()
    headers = ["Operation", "p50 (µs)", "p99 (µs)", "Mean (µs)"]
    rows = []
    for op_name, stats in results.items():
        rows.append([
            op_name,
            f"{stats['p50_us']:.1f}",
            f"{stats['p99_us']:.1f}",
            f"{stats['mean_us']:.1f}",
        ])

    print(md_table(headers, rows))

    # Check sub-millisecond claim
    max_p50 = max(s["p50_us"] for s in results.values())
    max_p99 = max(s["p99_us"] for s in results.values())
    print()
    if max_p50 < 1000:
        print(f"✅ All operations p50 < 1ms (max: {max_p50:.0f} µs)")
    else:
        print(f"⚠ Some operations p50 > 1ms (max: {max_p50:.0f} µs)")
    if max_p99 < 1000:
        print(f"✅ All operations p99 < 1ms (max: {max_p99:.0f} µs)")
    else:
        print(f"⚠ Some operations p99 > 1ms (max: {max_p99:.0f} µs)")

    # Per-transaction Redis overhead (11 ops per scorer tx)
    total_mean = sum(s["mean_us"] for s in results.values())
    print(f"\n  Per-transaction Redis overhead: {total_mean:.0f} µs ({total_mean/1000:.2f} ms)")

    # Write results
    out = {
        "hardware": get_hardware_info(),
        "timestamp": datetime.now().isoformat(),
        "operations": results,
        "per_transaction_overhead_us": total_mean,
    }
    os.makedirs("benchmarks", exist_ok=True)
    with open("benchmarks/redis_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults written to benchmarks/redis_results.json")


if __name__ == "__main__":
    import sys
    main()
