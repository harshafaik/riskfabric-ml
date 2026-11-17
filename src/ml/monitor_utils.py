# ── Dual-Label Contract ──────────────────────────────────────────────────
# ground_truth (ClickHouse table / Parquet chunks) contains TWO fraud labels:
#   is_fraud       → noisy operational label (3% FN / 5% FP noise applied)
#   fraud_target   → clean ground truth (before label noise)
#   label_noise    → "none" | "fn" | "fp"
#
# is_fraud != truth.  is_fraud is what the model was trained ON.
# fraud_target is what the model should ACTUALLY catch.
# The GAP between metrics computed against each is the noise cost.
#
# Any code that treats is_fraud AS ground truth without explicit intent
# is a conceptual regression.  If you're changing how these labels are used,
# re-read the noisy-label documentation first.
# ─────────────────────────────────────────────────────────────────────────

import os
import math
import glob
from datetime import datetime, timezone

import numpy as np
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    accuracy_score,
)

# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------

def compute_classification_metrics(
    y_true: np.ndarray, y_prob: np.ndarray, y_pred: np.ndarray
) -> dict:
    n = len(y_true)
    tp = int((y_true & y_pred).sum())
    tn = int((~y_true & ~y_pred).sum())
    fp = int((~y_true & y_pred).sum())
    fn = int((y_true & ~y_pred).sum())

    metrics = {
        "sample_count": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "actual_fraud_rate": float(y_true.mean()),
        "flagged_rate": float(y_pred.mean()),
    }

    has_pos = int(y_true.sum()) > 0
    has_neg = int((~y_true).sum()) > 0

    if has_pos and has_neg:
        metrics["roc_auc"] = roc_auc_score(y_true, y_prob)

    metrics["pr_auc"] = average_precision_score(y_true, y_prob)
    metrics["precision"] = precision_score(y_true, y_pred, zero_division=0)
    metrics["recall"] = recall_score(y_true, y_pred, zero_division=0)
    metrics["f1"] = f1_score(y_true, y_pred, zero_division=0)
    metrics["accuracy"] = accuracy_score(y_true, y_pred)

    return metrics


def compute_dual_metrics(
    y_operational: np.ndarray,
    y_clean: np.ndarray,
    y_prob: np.ndarray,
    y_pred: np.ndarray,
) -> dict:
    """
    Compute metrics against both labels and the noise gap between them.

    Returns a flat dict with keys like:
      precision_operational, precision_true, precision_noise_gap, ...
    """
    op = compute_classification_metrics(y_operational.astype(bool), y_prob, y_pred)
    true = compute_classification_metrics(y_clean.astype(bool), y_prob, y_pred)

    result = {}
    for key, val in op.items():
        result[f"{key}_operational"] = val
    for key, val in true.items():
        result[f"{key}_true"] = val

    # Noise gap: positive value means the operational label overstates performance
    for key in ["recall", "precision", "pr_auc", "f1", "actual_fraud_rate",
                "tp", "fn", "fp", "tn"]:
        if key in op and key in true:
            result[f"{key}_noise_gap"] = op[key] - true[key]

    return result


# ---------------------------------------------------------------------------
# Prediction drift – PSI between reference and current probability distributions
# ---------------------------------------------------------------------------

def compute_prediction_drift(
    reference_probs: np.ndarray,
    current_probs: np.ndarray,
    bins: int = 10,
) -> dict:
    bin_edges = np.linspace(0, 1, bins + 1)

    ref_hist, _ = np.histogram(reference_probs, bins=bin_edges)
    cur_hist, _ = np.histogram(current_probs, bins=bin_edges)

    ref_dist = ref_hist / ref_hist.sum()
    cur_dist = cur_hist / cur_hist.sum()

    epsilon = 1e-10
    psi_values = (cur_dist - ref_dist) * np.log(
        (cur_dist + epsilon) / (ref_dist + epsilon)
    )
    psi = float(psi_values.sum())

    ref_mean = float(reference_probs.mean())
    cur_mean = float(current_probs.mean())
    ref_std = float(reference_probs.std())
    cur_std = float(current_probs.std())

    return {
        "psi": psi,
        "ref_mean_prob": ref_mean,
        "cur_mean_prob": cur_mean,
        "ref_std_prob": ref_std,
        "cur_std_prob": cur_std,
        "mean_shift": cur_mean - ref_mean,
    }


# ---------------------------------------------------------------------------
# ClickHouse metric writer
# ---------------------------------------------------------------------------

def write_metrics_to_clickhouse(
    client,
    report_time: datetime,
    metrics: dict,
    report_type: str,
    label: str = "",
):
    rows = []
    for name, value in metrics.items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        rows.append([report_time, name, float(value), label, report_type])

    if not rows:
        return

    client.insert(
        "monitoring_metrics",
        rows,
        column_names=[
            "report_time", "metric_name", "metric_value",
            "metric_label", "report_type",
        ],
    )


# ---------------------------------------------------------------------------
# Report pruning
# ---------------------------------------------------------------------------

def prune_old_reports(reports_dir: str, max_reports: int):
    html_files = sorted(
        glob.glob(os.path.join(reports_dir, "*.html")),
        key=os.path.getmtime,
    )
    json_files = sorted(
        glob.glob(os.path.join(reports_dir, "*.json")),
        key=os.path.getmtime,
    )

    for flist in [html_files, json_files]:
        while len(flist) > max_reports:
            oldest = flist.pop(0)
            os.remove(oldest)
