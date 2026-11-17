# RiskFabric Performance Benchmarks

## Hardware

- **Hostname**: fedora
- **OS**: Linux 7.0.11-200.fc44.x86_64
- **CPU**: AMD Ryzen 7 4800H with Radeon Graphics
- **Logical cores**: 16
- **RAM**: 15Gi
- **Disk**: /dev/nvme1n1p3 476G
- **Python**: Python 3.14.5
- **Rust**: rustc 1.95.0 (59807616e 2026-04-14)

## Methodology

All benchmarks use **seed=42**, **N=5 repetitions** (unless noted), and report
**mean ± std**. Latency percentiles are **p50/p95/p99** — never averages alone.

---

## 2a. Scoring Latency & Throughput

---
### Hardware
- **hostname**: fedora
- **os**: Linux 7.0.11-200.fc44.x86_64
- **python**: 3.14.5
- **cpu_model**: unknown
- **logical_cores**: 16
- **physical_cores**: 8
- **ram_gb**: 15.0
- **ram_available_gb**: 9.4
- **disk_type**: btrfs
- **disk_total_gb**: 475.4

All services healthy. Starting benchmarks...

--- Benchmark: batch_size=50 (default) ---
  Starting streaming generator + scorer...
  (This is a skeleton — streaming must be started manually)

  Querying ClickHouse for pipeline latency...
  Found 51750 scored rows in last 10 min
  p50: 177.0 ms
  p95: 509.0 ms
  p99: 550.0 ms
  Total scored in last 10 min: 51750
## 2b. Generation Throughput & Scaling

==> Hardware
    CPU:     AMD Ryzen 7 4800H with Radeon Graphics
    Cores:   16 logical
    RAM:     15Gi
    Disk:    /dev/nvme1n1p3 476G
    OS:      Linux 7.0.11-200.fc44.x86_64

==> Building release binary...
    Finished `release` profile [optimized] target(s) in 0.21s
