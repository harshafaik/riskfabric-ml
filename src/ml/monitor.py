#!/usr/bin/env python3
"""
RiskFabric Model Monitor

Queries ClickHouse for scored transactions in a **lagged time window**
(default: transactions scored 120–180 seconds ago), then joins against
an in-memory accumulator built from ground_truth.csv.

The lagged window eliminates the race between ground-truth writes and
scorer processing — by the time we query, the scorer has had ≥2 minutes
to finish its work.  (Quantifying the actual join rate is a required
follow-up benchmark; see the plan for details.)
"""
import os
import re
import sys
import time
import json
import yaml
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from clickhouse_connect import get_client

from monitor_utils import (
    compute_dual_metrics,
    compute_prediction_drift,
    write_metrics_to_clickhouse,
    prune_old_reports,
)

# ---------------------------------------------------------------------------
# Config loading (YAML + env-var interpolation)
# ---------------------------------------------------------------------------

def _expand_env(value):
    if not isinstance(value, str):
        return value
    def _repl(m):
        expr = m.group(1)
        if ":-" in expr:
            var, default = expr.split(":-", 1)
            return os.environ.get(var.strip(), default.strip())
        return os.environ.get(expr, "")
    return re.sub(r"\$\{([^}]+)\}", _repl, value)

def load_config(path: str) -> dict:
    config_path = Path(__file__).parent / path
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return _expand_env(obj)
    return _walk(raw)


# ---------------------------------------------------------------------------
# One-time reference distribution sampling from ClickHouse
# ---------------------------------------------------------------------------

def sample_reference_distribution(ch_client, sample_size: int) -> np.ndarray:
    print(f"   -> Sampling reference distribution ({sample_size} rows) from ClickHouse ...")
    result = ch_client.query_df(
        "SELECT fraud_probability FROM riskfabric.fraud_scores ORDER BY rand() LIMIT {limit}".format(limit=int(sample_size))
    )
    probs = result["fraud_probability"].to_numpy(dtype=np.float64)
    print(f"   -> Reference: μ={probs.mean():.4f}, σ={probs.std():.4f}, n={len(probs)}")
    return probs


# ---------------------------------------------------------------------------
# Evidently report generation (best-effort — failure does not block the loop)
# ---------------------------------------------------------------------------

def generate_evidently_report(
    reference_probs: np.ndarray,
    current_df: pd.DataFrame,
    reports_dir: str,
    report_time: datetime,
    label_col: str,
    label_suffix: str,
    strict: bool = False,
):
    try:
        from evidently.report import Report
        from evidently.metric_preset import ClassificationPreset, DataDriftPreset

        ref_df = pd.DataFrame({"fraud_probability": reference_probs})
        cur_df = current_df.rename(columns={label_col: "target", "flagged": "prediction"})
        cur_df["prediction"] = cur_df["prediction"].astype(int)
        cur_df["target"] = cur_df["target"].astype(int)

        report = Report(metrics=[ClassificationPreset(), DataDriftPreset(columns=["fraud_probability"])])
        report.run(reference_data=ref_df, current_data=cur_df)

        ts = report_time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(reports_dir, exist_ok=True)

        html_path = os.path.join(reports_dir, f"monitoring_{ts}_{label_suffix}.html")
        json_path = os.path.join(reports_dir, f"monitoring_{ts}_{label_suffix}.json")

        report.save_html(html_path)
        report.save_json(json_path)

        print(f"   -> Evidently report ({label_suffix}): {html_path}")
        return True
    except Exception:
        if strict:
            raise
        print(f"   ⚠️ Evidently report ({label_suffix}) generation failed")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    config = load_config("monitor_config.yaml")

    interval = int(config["monitor"]["interval_seconds"])
    min_samples = int(config["monitor"]["min_samples"])
    reports_dir = config["monitor"]["reports_dir"]
    max_reports = int(config["monitor"]["max_reports"])
    window_offset_s = int(config["monitor"]["score_window_offset_seconds"])
    window_duration_s = int(config["monitor"]["score_window_duration_seconds"])
    ref_sample_size = int(config["evidently"]["reference_sample_size"])
    ref_refresh_s = int(config["evidently"].get("reference_refresh_seconds", 3600))
    strict = os.environ.get("MONITOR_STRICT", "").lower() in ("1", "true", "yes")

    # ClickHouse
    ch_cfg = config["clickhouse"]
    print(f"   -> Connecting to ClickHouse at {ch_cfg['host']}:{ch_cfg['port']} ...")
    ch_client = get_client(
        host=ch_cfg["host"],
        port=int(ch_cfg["port"]),
        username=ch_cfg["user"],
        password=ch_cfg["password"],
        database=ch_cfg["database"],
    )

    # Ensure monitoring_metrics table exists
    ch_client.command("""
        CREATE TABLE IF NOT EXISTS monitoring_metrics (
            report_time  DateTime64(3),
            metric_name  String,
            metric_value Float64,
            metric_label String DEFAULT '',
            report_type  String
        ) ENGINE = MergeTree()
        ORDER BY (report_time, report_type, metric_name)
    """)
    print("   -> monitoring_metrics table ready")

    # Reference distribution — refreshed on a timer
    ref_probs = sample_reference_distribution(ch_client, ref_sample_size)
    last_ref_refresh = datetime.now(timezone.utc)

    print(f"   -> Score window: {window_offset_s}s–{window_offset_s + window_duration_s}s ago")
    print(f"   -> Monitor entering loop (interval={interval}s, min_samples={min_samples})")
    print("---")

    JOIN_QUERY = """
        SELECT fs.transaction_id, fs.fraud_probability, fs.flagged,
               gt.is_fraud, gt.fraud_target, gt.label_noise
        FROM riskfabric.fraud_scores fs
        JOIN riskfabric.ground_truth gt
          ON fs.transaction_id = gt.transaction_id
        WHERE fs.scored_at >= {start:DateTime64(3)}
          AND fs.scored_at <  {end:DateTime64(3)}
    """

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Refresh reference distribution periodically
            if (now - last_ref_refresh).total_seconds() >= ref_refresh_s:
                print(f"   -> Refreshing reference distribution ({ref_refresh_s}s elapsed)")
                ref_probs = sample_reference_distribution(ch_client, ref_sample_size)
                last_ref_refresh = now

            window_start = now - timedelta(seconds=window_offset_s + window_duration_s)
            window_end   = now - timedelta(seconds=window_offset_s)

            joined = ch_client.query_df(
                JOIN_QUERY,
                parameters={"start": window_start, "end": window_end},
            )

            ts_now = now.strftime("%H:%M:%S")
            n_total = len(joined)
            if n_total == 0:
                print(f"[{ts_now}] No joined rows in lagged window — sleeping {interval}s")
                time.sleep(interval)
                continue

            # --- Step 2: Compute metrics on joined rows ---
            y_operational = joined["is_fraud"].values.astype(np.int64)
            y_clean       = joined["fraud_target"].values.astype(np.int64)
            y_prob        = joined["fraud_probability"].values.astype(np.float64)
            y_pred        = joined["flagged"].values.astype(bool)

            dual_metrics = compute_dual_metrics(y_operational, y_clean, y_prob, y_pred)
            dual_metrics["join_rate"] = 1.0

            n_fn = int((y_operational == 0) & (y_clean == 1)).sum()
            n_fp = int((y_operational == 1) & (y_clean == 0)).sum()
            n_noisy = n_fn + n_fp

            print(
                f"   -> Operational (vs is_fraud): "
                f"precision={dual_metrics.get('precision_operational', 'N/A'):.4f}, "
                f"recall={dual_metrics['recall_operational']:.4f}"
                f"\n   -> Clean truth (vs fraud_target):  "
                f"precision={dual_metrics.get('precision_true', 'N/A'):.4f}, "
                f"recall={dual_metrics['recall_true']:.4f}"
                f"\n   -> Noise gap: recall={dual_metrics['recall_noise_gap']:.4f}, "
                f"precision={dual_metrics['precision_noise_gap']:.4f}"
                f" (noisy={n_noisy}: {n_fn} FN, {n_fp} FP)"
            )

            # --- Step 4: Prediction drift ---
            drift_metrics = compute_prediction_drift(ref_probs, y_prob)
            print(
                f"   -> Drift: PSI={drift_metrics['psi']:.4f}, "
                f"mean_shift={drift_metrics['mean_shift']:.4f}"
            )

            # --- Step 5: Write to ClickHouse ---
            report_time = datetime.now(timezone.utc)
            write_metrics_to_clickhouse(ch_client, report_time, dual_metrics, "classification")
            write_metrics_to_clickhouse(ch_client, report_time, drift_metrics, "prediction_drift")

            # --- Step 6: Evidently reports (dual-label) ---
            op_report_ok = generate_evidently_report(ref_probs, joined, reports_dir, report_time,
                                      label_col="is_fraud", label_suffix="operational", strict=strict)
            true_report_ok = generate_evidently_report(ref_probs, joined, reports_dir, report_time,
                                      label_col="fraud_target", label_suffix="true", strict=strict)

            # Surface Evidently health as a metric in ClickHouse
            write_metrics_to_clickhouse(ch_client, report_time,
                                        {"evidently_healthy": 1.0 if (op_report_ok and true_report_ok) else 0.0},
                                        "monitoring_health")

            # --- Step 7: Prune old reports ---
            prune_old_reports(reports_dir, max_reports)

            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n   -> Monitor stopped by user")
            break
        except Exception:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ⚠️ Cycle error — will retry after {interval}s")
            traceback.print_exc()
            time.sleep(interval)


if __name__ == "__main__":
    main()
