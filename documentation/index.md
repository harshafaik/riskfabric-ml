# riskfabric-ml

![Rust](https://img.shields.io/badge/language-Rust-orange.svg)
![Python](https://img.shields.io/badge/language-Python-blue.svg)
![Polars](https://img.shields.io/badge/engine-Polars%200.51.0-blue.svg)
![XGBoost](https://img.shields.io/badge/ML-XGBoost-36A0A0.svg)
![ClickHouse](https://img.shields.io/badge/analytics-ClickHouse-yellow.svg)
![Redpanda](https://img.shields.io/badge/streaming-Redpanda-red.svg)
![Grafana](https://img.shields.io/badge/monitoring-Grafana-F46800.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

`riskfabric-ml` is the model and serving layer of the RiskFabric system. It consumes
analytical tables built from `scrip`'s deterministic synthetic feed and covers feature
engineering, training, calibration, real-time scoring, monitoring and analyst case review.
It does not generate data.

## Repositories

| Repository | Responsibility | Contract it emits |
| :--- | :--- | :--- |
| [`scrip`](https://github.com/harshafaik/scrip) | OpenStreetMap world building and deterministic agent simulation | dataset — five Parquet tables |
| [`riskfabric-pipelines`](https://github.com/harshafaik/riskfabric-pipelines) | Contract-validated ingestion, star schema, orchestration | validated Bronze and analytical marts |
| **riskfabric-ml** (this repository) | Feature engineering, training, calibration, scoring, monitoring, case review | model artifact and fraud scores |
| [`RiskFabric`](https://github.com/harshafaik/RiskFabric) (archived) | Original end-to-end monolith | — |

The Rust feature ETL described below still runs here. It is being replaced by
`riskfabric-pipelines`; until that migration lands, this repository is the only place
Bronze → Silver → Gold runs.

## System Pipeline

```mermaid
flowchart LR
    classDef external fill:#2a1b1b,stroke:#AD5A5A,stroke-width:1.5px,rx:8px,ry:8px,color:#FBE6E6,font-size:16px;
    classDef stage fill:#1b2a3a,stroke:#378ADD,stroke-width:1.5px,rx:8px,ry:8px,color:#E6F1FB,font-size:16px;

    A["World building<br/>OSM · H3 → Parquet<br/>scrip"]:::external
    B["Simulation Engine<br/>Rust<br/>scrip"]:::external
    C["Validated ingestion<br/>contracts · quarantine<br/>riskfabric-pipelines"]:::external
    D["Feature ETL<br/>Bronze → Silver → Gold<br/>migrating out"]:::stage
    E["Training · Calibration · Scoring<br/>XGBoost · SHAP · Monitoring"]:::stage
    F["Case Management<br/>ClickHouse → Postgres → Django"]:::stage

    A --> B --> C --> D --> E --> F
```

**<a id="fig-1"></a>Figure 1:** World building, simulation and validated ingestion are
provided by the two sibling repositories. The feature ETL still lives here and is being
retired. Everything from feature engineering onward is this repository's responsibility.

## Features

- **Real-time Scoring**: Kafka/Redpanda consumer with Redis feature store, XGBoost
  inference, and ClickHouse persistence.
- **Model Explainability**: SHAP global and per-profile analysis, calibration
  (Platt/Isotonic), drift simulation, and a Grafana monitoring dashboard.
- **Case Management**: Django admin panel backed by a dedicated PostgreSQL OLTP store for
  investigator review workflows.
- **Feature Engineering**: No-leak expanding-window features over Bronze/Silver/Gold
  Parquet. This layer is migrating to `riskfabric-pipelines`; the models consume whatever
  that pipeline produces.

## Tech Stack

- **Core Engine**: Rust (feature ETL)
- **Real-time Streaming**: Redpanda (Kafka-compatible) with a Python replay producer and
  scoring consumer
- **Data Processing**: Polars (batch feature engineering)
- **Data Warehouse**: Parquet (medallion ETL via Polars) → DuckDB (embedded training query
  engine)
- **Analytical Store**: ClickHouse (fraud scores, Grafana dashboards)
- **Operational Store**: PostgreSQL (case management OLTP)
- **Feature Store**: Redis (real-time feature serving)
- **Machine Learning**: XGBoost (training, inference), SHAP (explainability), Scikit-learn
  (calibration)
- **Infrastructure**: Podman/Docker Compose, Terraform (GCP deployment)
- **Docs**: mdBook (published via GitHub Actions)

## Quick Start

```bash
cargo build --release

scrip fixtures --out-dir references
scrip generate --customers 3400 --seed 42 --days 365 \
  --base-date 2026-01-01T00:00:00Z \
  --input-dir references --out-dir data/bronze

cargo run --bin riskfabric-etl silver-all
cargo run --bin riskfabric-etl gold-master

python src/ml/train_xgboost.py
python src/ml/test_model.py

podman compose up --build -d
podman compose --profile replay run --rm replay
```

The scorer loads `data/config/runtime_thresholds.json` when present and falls back to
`0.85` otherwise.

## Project Structure

```
📁 riskfabric-ml
 │
 ├─ ⚙️ Engine
 │   ├─ src/ — Rust feature ETL (Polars): bronze → silver → gold
 │   └─ Cargo.toml
 │
 ├─ 🧠 ML & Data
 │   ├─ src/ml/ — Python ML (training, calibration, scoring, monitoring)
 │   ├─ models/ — trained model artifacts (generated)
 │   ├─ reports/ — SHAP analysis outputs
 │   └─ data/ — configs, Parquet inputs/outputs
 │
 ├─ ☁️ Ops & Infra
 │   ├─ case_admin/ — Django admin (case management)
 │   ├─ deploy/ — Terraform (GCP deployment)
 │   ├─ docker/ — ClickHouse init, Grafana provisioning
 │   └─ docker-compose.yml
 │
 └─ 📖 Docs
```

## Modules

- [Data & Engineering](engineering_index.md)
- [Machine Learning Systems](ml_systems_index.md)
- [Infrastructure & Operations](infrastructure_index.md)
- [Conceptual Explanations](concepts_index.md)
- [Results & Monitoring](results_index.md)
- [Decisions](decisions_index.md)
- [Defunct Implementations](defunct_index.md)
- [Codebase Components](components/index.md)
