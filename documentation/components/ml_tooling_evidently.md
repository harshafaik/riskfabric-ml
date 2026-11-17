# Evidently Model Monitoring

## Overview

`monitor.py` — the RiskFabric model monitor — produces Evidently classification and data-drift reports against scored transactions joined to ground truth. It queries ClickHouse for transactions scored in a **lagged window** (default 120–180 seconds ago), joins them to the `riskfabric.ground_truth` table, and passes the result to Evidently's `ClassificationPreset` and `DataDriftPreset`. Reports render as both HTML and JSON into `data/monitor/reports/`, and per-cycle scalar metrics are written to the ClickHouse `monitoring_metrics` table for Grafana. The monitor runs as the `monitor` Docker service alongside the scorer.

## Report Configuration (`monitor_config.yaml`)

| Section | Key | Default | Notes |
| :--- | :--- | :--- | :--- |
| `monitor` | `interval_seconds` | `60` | Loop cadence |
| `monitor` | `min_samples` | `10` | Minimum joined rows required |
| `monitor` | `reports_dir` | `data/monitor/reports` | HTML/JSON output |
| `monitor` | `max_reports` | `50` | Prune threshold per format |
| `monitor` | `score_window_offset_seconds` | `120` | Lag: query scores 120–180s old |
| `monitor` | `score_window_duration_seconds` | `60` | Window width |
| `evidently` | `report_format` | `["html", "json"]` | Emitted formats |
| `evidently` | `reference_sample_size` | `10000` | Rows sampled for reference |
| `evidently` | `reference_refresh_seconds` | `3600` | Seconds between reference re-sampling |

## Report Generation (`generate_evidently_report`)

Evidently is imported lazily inside the function. When the library is missing and `MONITOR_STRICT` is unset, the failure is non-blocking — the monitor continues with ClickHouse scalar metrics alone. When `MONITOR_STRICT=true`, the failure raises, crashing the monitor. The function returns `True` on success and `False` on failure, and the caller writes an `evidently_healthy` metric to ClickHouse each cycle.

The function builds:

| Component | Preset | Purpose |
| :--- | :--- | :--- |
| Classification | `ClassificationPreset` | Quality metrics and confusion behavior |
| Drift | `DataDriftPreset(columns=["fraud_probability"])` | PSI-style shift in the score distribution |

The reference distribution is sampled at startup and re-sampled every `reference_refresh_seconds` (default 3600) to prevent the drift baseline from aging. Each cycle's joined rows are renamed so `is_fraud` → `target` and `flagged` → `prediction`, then run against the reference. Because the dual-label contract gives two fraud labels, the monitor emits **two reports per cycle** — one against the noisy operational label (`is_fraud`, suffix `operational`) and one against clean ground truth (`fraud_target`, suffix `true`). Reports are timestamped `monitoring_{YYYYMMDD_HHMMSS}_{suffix}.{html,json}` and pruned oldest-first down to `max_reports`.

## Scalar Metrics Written to ClickHouse

The `monitoring_metrics` table (created idempotently at startup) receives:

| `report_type` | Metrics |
| :--- | :--- |
| `classification` | Dual-label precision/recall/F1/AUC plus noise-gap deltas (from `compute_dual_metrics`), `join_rate` |
| `prediction_drift` | `psi`, `ref_mean_prob`, `cur_mean_prob`, `ref_std_prob`, `cur_std_prob`, `mean_shift` |
| `monitoring_health` | `evidently_healthy` (1.0 = both operational and true reports succeeded, 0.0 = at least one failed) |

This is the same `monitoring_metrics` table Grafana reads, so Evidently's HTML reports are the human-facing deep-dive while ClickHouse rows feed the operational dashboards.

## Pipeline Position

The monitor is the deployment-time counterpart to the offline training evaluation. It consumes `fraud_scores` (written by `scorer.py`) and `ground_truth` (written by the generator sidecar), and its reports land on disk while its scalar metrics land in ClickHouse for Grafana. The lagged window structurally eliminates the write-before-read race between ground-truth ingestion and scorer processing, matching the project's documented monitoring pattern.

Setting `MONITOR_STRICT=true` elevates Evidently report failures to hard errors — the monitor exits rather than continuing silently when the Evidently library is broken or missing. For development and CI, this surfaces integration failures as process crashes instead of buried warnings.
