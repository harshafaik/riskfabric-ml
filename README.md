# RiskFabric

[![Rust](https://img.shields.io/badge/language-Rust-orange.svg)](https://www.rust-lang.org/)
[![Python](https://img.shields.io/badge/language-Python-blue.svg)](https://www.python.org/)
[![Polars](https://img.shields.io/badge/engine-Polars%200.51.0-blue.svg)](https://pola.rs/)
[![XGBoost](https://img.shields.io/badge/ML-XGBoost-36A0A0.svg)](https://xgboost.readthedocs.io/)
[![ClickHouse](https://img.shields.io/badge/analytics-ClickHouse-yellow.svg)](https://clickhouse.com/)
[![Grafana](https://img.shields.io/badge/monitoring-Grafana-F46800.svg)](https://grafana.com/)
[![Redpanda](https://img.shields.io/badge/streaming-Redpanda-red.svg)](https://redpanda.com/)
[![Redis](https://img.shields.io/badge/store-Redis-red.svg)](https://redis.io/)
[![Podman](https://img.shields.io/badge/container-Podman-892CA0.svg)](https://podman.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy mdBook](https://github.com/harshafaik/riskfabric/actions/workflows/deploy_book.yml/badge.svg)](https://github.com/harshafaik/riskfabric/actions/workflows/deploy_book.yml)

RiskFabric is the model and serving layer of a fraud intelligence system. It consumes analytical tables built from **scrip**'s deterministic synthetic feed and covers training, calibration, real-time scoring, monitoring and analyst case review. It does not generate data, and its data-engineering layer is moving to a dedicated pipeline repository.

## Repositories

| Repository | Responsibility | Contract it emits |
| :--- | :--- | :--- |
| `scrip` | OpenStreetMap world building and deterministic agent simulation | dataset — five Parquet tables |
| `riskfabric-pipelines` | Contract-validated ingestion, star schema, orchestration | validated Bronze and analytical marts |
| **RiskFabric** (this repository) | Training, calibration, scoring, monitoring, case review | model artifact and fraud scores |

The Rust feature ETL described below still runs here. It is being replaced by `riskfabric-pipelines`; until that migration lands, this repository is the only place Bronze → Silver → Gold runs.

## System Pipeline

```mermaid
flowchart LR
    classDef stage fill:#1b2a3a,stroke:#378ADD,stroke-width:1.5px,rx:8px,ry:8px,color:#E6F1FB,font-size:16px;
    classDef external fill:#2a1b1b,stroke:#AD5A5A,stroke-width:1.5px,rx:8px,ry:8px,color:#FBE6E6,font-size:16px;

    A["World building<br/>OSM · H3 → Parquet<br/>scrip"]:::external
    B["Simulation Engine<br/>Rust<br/>scrip"]:::external
    C["Validated ingestion<br/>contracts · quarantine<br/>riskfabric-pipelines"]:::external
    D["Feature ETL<br/>Bronze → Silver → Gold<br/>migrating out"]:::stage
    E["Training · Calibration · Scoring<br/>XGBoost · SHAP · Monitoring"]:::stage
    F["Case Management<br/>ClickHouse → Postgres → Django"]:::stage

    A --> B --> C --> D --> E --> F
```

**Figure 1:** System Pipeline — world building, simulation and validated ingestion are provided by the two sibling repositories. The feature ETL still lives here and is being retired. Everything from training onward is this repository's responsibility.

## ✨ Features
- **Real-time Scoring**: Kafka/Redpanda consumer with Redis feature store, XGBoost inference, and ClickHouse persistence.
- **Model Explainability**: SHAP global and per-profile analysis, calibration (Platt/Isotonic), drift simulation, and a Grafana monitoring dashboard.
- **Case Management**: Django admin panel backed by a dedicated PostgreSQL OLTP store for investigator review workflows.
- **Feature Engineering**: No-leak expanding-window features over Bronze/Silver/Gold Parquet. This layer is migrating to `riskfabric-pipelines`; the models consume whatever that pipeline produces.

## 🛠️ Tech Stack
- **Core Engine**: Rust (ETL, feature engineering)
- **Real-time Streaming**: Redpanda (Kafka-compatible) with a Python scoring consumer
- **Data Processing**: Polars (batch feature engineering)
- **Data Warehouse**: Parquet (medallion ETL via Polars) → DuckDB (embedded training query engine)
- **Analytical Store**: ClickHouse (fraud scores, Grafana dashboards)
- **Operational Store**: PostgreSQL (case management OLTP)
- **Feature Store**: Redis (real-time feature serving)
- **Machine Learning**: XGBoost (training, inference), SHAP (explainability), Scikit-learn (calibration)
- **Infrastructure**: Podman/Docker Compose, Terraform (GCP deployment)
- **Docs**: mdBook (published via GitHub Actions)

## 🚀 Quick Start

```bash
# Build
cargo build --release

# 1. Generate synthetic data with scrip (separate project).
#    Its Parquet output is exactly what the ETL expects in data/bronze/.
#    Once riskfabric-pipelines owns ingestion, this step becomes `rfp run`.
scrip generate --customers 3400 --seed 42 --days 365 \
  --base-date 2026-01-01T00:00:00Z \
  --input-dir references --out-dir data/bronze

# 2. Run the Parquet-native ETL pipeline (bronze → silver → gold)
cargo run --bin riskfabric-etl silver-all
cargo run --bin riskfabric-etl gold-master

# 3. Train + evaluate the XGBoost model
python src/ml/train_xgboost.py
python src/ml/test_model.py

# 4. Start the full stack (ClickHouse, Redpanda, Redis, scorer, case-admin, Grafana)
podman compose up --build -d
```

## 📁 Project Structure

### Root Directory

```
📁 RiskFabric
 │
 ├─ ⚙️ Engine
 │   ├─ src/ — Rust ETL (Polars): bronze → silver → gold
 │   └─ Cargo.toml
 │
 ├─ 🧠 ML & Data
 │   ├─ src/ml/ — Python ML (training, scoring, explainability)
 │   ├─ models/ — XGBoost artifacts
 │   ├─ reports/ — SHAP analysis outputs
 │   └─ data/ — Parquet inputs/outputs
 │
 ├─ ☁️ Ops & Infra
 │   ├─ case_admin/ — Django admin (case management)
 │   ├─ deploy/ — Terraform (GCP deployment)
 │   ├─ docker/ — ClickHouse init, Grafana provisioning
 │   └─ docker-compose.yml
 │
 └─ 📖 Docs (documentation/ — mdBook)
```

## Modules

- [Data & Engineering](documentation/engineering_index.md)
- [Machine Learning Systems](documentation/ml_systems_index.md)
- [Infrastructure & Operations](documentation/infrastructure_index.md)
- [Conceptual Explanations](documentation/concepts_index.md)
- [Results & Monitoring](documentation/results_index.md)
- [Decisions](documentation/decisions_index.md)
- [Defunct Implementations](documentation/defunct_index.md)
- [Codebase Components](documentation/components/index.md)

---

*Developed by harshafaik*
