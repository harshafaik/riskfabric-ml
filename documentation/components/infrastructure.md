# Infrastructure & Local Service Stack

## Overview

The local service stack (`docker-compose.yml`) provisions 9 services on `riskfabric_default`: ClickHouse, Redpanda, Redis, OLTP Postgres, scorer (`scorer.py`), monitor (`monitor.py`), Grafana, MLflow UI, and Django case-admin. The `replay` profile adds a one-shot producer (`replay.py`). The Python ML services and case-management UI depend on this stack; the Rust feature ETL does not. Simulation and world building live in `scrip`, so this stack runs no world-building Postgres.

## Schema

<div style="max-width: 400px; margin: 0 auto;">

```mermaid
flowchart TB
    classDef script fill:#22252a,stroke:#4d535b,stroke-width:1px,rx:5px,ry:5px,color:#cfd2d9;
    classDef store fill:#1b2a3a,stroke:#304e70,stroke-width:1px,rx:5px,ry:5px,color:#cfd2d9;
    classDef ui fill:#251e36,stroke:#483a68,stroke-width:1px,rx:5px,ry:5px,color:#cfd2d9;
    subgraph Host["Host Machine"]
        REPLAY["replay.py\n(host or compose profile)"]:::script
    end
    subgraph Stack["Docker Compose (riskfabric_default)"]
        RP[(Redpanda\n:9092 :29092)]:::store
        RD[(Redis\n:6379)]:::store
        CH[(ClickHouse\n:8123 :9000)]:::store
        PG[(oltp-postgres\n:5433)]:::store
        scorer[scorer.py]:::script
        monitor[monitor.py]:::script
        grafana[Grafana\n:3001]:::ui
        caseadmin[case_admin\nDjango :8001]:::ui
        mlflow[MLflow UI\n:5000]:::ui
    end
    REPLAY -->|"raw_transactions"| RP
    RP -->|"raw_transactions"| scorer
    scorer -->|"fraud_scores"| CH
    scorer -->|"cases"| caseadmin
    caseadmin --> PG
    RD <-.->|"feature state"| scorer
    CH --> grafana
    CH --> monitor
    mlflow -.->|"model registry"| scorer

    style Host fill:#1e232e,stroke:#333e54,stroke-width:1px,stroke-dasharray: 3 3,color:#cfd2d9
    style Stack fill:#1c241e,stroke:#304033,stroke-width:1px,stroke-dasharray: 3 3,color:#cfd2d9
```
</div>

**<a id="fig-8"></a>Figure 8:** Infrastructure Service Stack

| Service | Image | Ports | Persistence |
| :--- | :--- | :--- | :--- |
| `clickhouse` | `clickhouse/clickhouse-server:latest` | `8123`, `9000` | `clickhouse_data`, `clickhouse_logs` |
| `redpanda` | `redpandadata/redpanda:v23.2.1` | `9092` (ext), `29092` (int) | None (ephemeral) |
| `redis` | `redis:7-alpine` | `6379` | None (ephemeral) |
| `scorer` | `localhost/riskfabric_ml` (built from `Dockerfile.ml`) | — | Workspace mount `/usr/app` |
| `monitor` | `localhost/riskfabric_ml` (built from `Dockerfile.ml`) | — | Workspace mount `/usr/app` |
| `replay` | `localhost/riskfabric_ml` (profile: `replay`) | — | Workspace mount `/usr/app` |
| `grafana` | `grafana/grafana-oss:latest` | `3001` | `grafana_data` |
| `oltp-postgres` | `postgres:15-alpine` | `5433`→host | `oltp_postgres_data` |
| `case-admin` | built from `case_admin/Dockerfile` | `8001`→host | `case_admin/` mount |
| `mlflow-ui` | `ghcr.io/mlflow/mlflow:v3.14.0` | `5000` | `./mlruns` mount |

## Architecture

### Multi-Model Database Strategy
ClickHouse for append-heavy analytical queries (fraud scores), Redpanda for Kafka-compatible streaming, Redis for sub-millisecond per-card/customer state (verified: p50 120–261 µs, p99 ≤509 µs across all operations) [[See benchmarks](../performance.md)], Postgres for OLTP case management.

### Health-Check Gating
All data services health-checked (ClickHouse via `wget`, Redpanda via `rpk`, Redis via `redis-cli`, Postgres via `pg_isready`). `scorer`, `grafana`, and `case-admin` wait for `service_healthy` before startup. 5s interval, 5 retries.

### Dual Kafka Listener
Redpanda exposes port `29092` for container-to-container traffic and `9092` for host access (`replay.py`). `scorer` connects via `KAFKA_BOOTSTRAP_SERVERS=redpanda:29092`.

### Workspace Volume Mounts
`scorer`, `monitor` and `replay` mount the project at `/usr/app`; `case-admin` mounts `case_admin/` at `/usr/app`. Source changes take effect on container restart without an image rebuild. The ML image is built from `Dockerfile.ml` by the compose `build:` directive on first run.

## Current Limitations

Redpanda is ephemeral — all topic data lost on restart, preventing replay testing. Passwords hardcoded in `docker-compose.yml` and repeated across Python scripts with no `.env` support. Model artifacts (`models/`) and `data/config/runtime_thresholds.json` are generated and not committed; train the model and compute thresholds before starting the scorer.
