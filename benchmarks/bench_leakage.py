#!/usr/bin/env python3
"""bench_leakage.py — Leakage AUC benchmark (ablation study).

Part 1 (PRIMARY): Documented history from feature_leakage_issues.md
Part 2 (SECONDARY): Controlled ablation at seed=42, reintroducing leaks individually.

Every variant is clearly labeled — ablation numbers are NEVER presented as historical
measurements. Labels match methods.
"""

import json
import os
import sys
import time
from datetime import datetime

import duckdb
import numpy as np
import polars as pl
import xgboost as xgb
import yaml
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

# Add project root for ml_utils import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ml"))
from ml_utils import find_gold_snapshot, split_by_timestamp

from common import get_hardware_info, md_table, percentiles, print_hardware_info

DEFAULT_TUNING_PATH = "data/config/ml_tuning.yaml"


def load_gold(gold_path: str) -> pl.DataFrame:
    conn = duckdb.connect()
    df = pl.from_arrow(conn.execute(f"SELECT * FROM '{gold_path}'").arrow())
    conn.close()
    return df


def get_xgb_params(scale_pos_weight: float) -> dict:
    if os.path.exists(DEFAULT_TUNING_PATH):
        with open(DEFAULT_TUNING_PATH) as f:
            tuning = yaml.safe_load(f) or {}
    else:
        tuning = {}
    return {
        "n_estimators": tuning.get("n_estimators", 100),
        "max_depth": tuning.get("max_depth", 6),
        "learning_rate": tuning.get("learning_rate", 0.1),
        "objective": tuning.get("objective", "binary:logistic"),
        "tree_method": tuning.get("tree_method", "hist"),
        "enable_categorical": tuning.get("enable_categorical", True),
        "random_state": 42,
        "scale_pos_weight": scale_pos_weight,
        "eval_metric": tuning.get("eval_metric", "aucpr"),
    }


def train_and_evaluate(df: pl.DataFrame, feature_cols: list,
                       use_chronological: bool = True) -> float:
    """Train XGBoost and return ROC AUC. Handles categorical features automatically."""
    target_col = "is_fraud"
    available = [c for c in feature_cols if c in df.columns]

    if use_chronological:
        train_df, test_df = split_by_timestamp(df, test_size=0.2)
    else:
        X = df.select(available).to_pandas()
        y = df[target_col].to_numpy()
        idx = np.arange(len(df))
        train_idx, test_idx = train_test_split(idx, test_size=0.2, random_state=42)
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        # Build train_df/test_df for consistent column access
        train_df = df[train_idx.tolist()]
        test_df = df[test_idx.tolist()]

    if not use_chronological:
        # Variable already set above
        pass

    X_train = train_df.select(available).to_pandas()
    y_train = train_df[target_col].to_numpy()
    X_test = test_df.select(available).to_pandas()
    y_test = test_df[target_col].to_numpy()

    categorical_cols = [c for c in available if train_df[c].dtype == pl.String]
    for c in categorical_cols:
        X_train[c] = X_train[c].astype("category")
        X_test[c] = X_test[c].astype("category")

    fraud_count = y_train.sum()
    scale_pos_weight = (len(y_train) - fraud_count) / fraud_count
    params = get_xgb_params(scale_pos_weight)

    model = xgb.XGBClassifier(**params)
    model.fit(X_train, y_train)
    y_prob = model.predict_proba(X_test)[:, 1]
    return roc_auc_score(y_test, y_prob)


def main():
    print_hardware_info()

    gold_path = find_gold_snapshot(None)
    print(f"Gold snapshot: {gold_path}")
    df = load_gold(gold_path)
    print(f"Rows: {len(df):,}, Fraud rate: {df['is_fraud'].mean():.4f}")

    # Honest baseline features (as used in train_xgboost.py)
    honest_features = [
        "time_since_last_transaction",
        "transaction_sequence_number",
        "spatial_velocity",
        "hour_deviation_from_norm",
        "amount_deviation_z_score",
        "rapid_fire_transaction_flag",
        "escalating_amounts_flag",
        "merchant_category_switch_flag",
        "transaction_channel",
        "card_present",
    ]

    # ── Part 1: Documented History ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("  PART 1 — Documented History (from feature_leakage_issues.md)")
    print("=" * 60)
    print()
    print("| Stage | AUC | What changed | Provenance |")
    print("| :--- | ---: | :--- | :--- |")
    print("| Leak 1: amount as shortcut | 0.9079 | Raw `amount` had 96.3% feature importance | Development log |")
    print("| Leak 3: tuned amount, weak behavioral | 0.7960 | Amount retuned but behavioral signals missing | Development log |")
    print("| Leak 4: target encoding leak | 0.925 | `mf_fraud_rate`, `cf_fraud_rate` leaked from full batch | Development log |")
    print("| Leak 5: join destroys sort | — | 70% corrupted sequence features (AUC estimated ~0.70) | Development log |")
    print("| Leak 6: random split | 0.786 | Random split inflates AUC vs chronological 0.7622 | Development log |")
    print("| **FINAL (honest)** | **0.7622** | All fixes, chronological split | Reproducible seed=5555 |")
    print()

    # ── Part 2: Controlled Ablation (seed=42) ────────────────────────────
    print("=" * 60)
    print("  PART 2 — Controlled Ablation (seed=42, N=5)")
    print("  Labels: \"Ablation study — leak impact (reproducible at seed=42)\"")
    print("=" * 60)
    print()

    results = []
    n = 5

    for run in range(n):
        print(f"  Run {run+1}/{n}...")
        run_results = {}

        # Baseline
        auc_honest = train_and_evaluate(df, honest_features, use_chronological=True)
        run_results["Honest baseline (chronological split)"] = auc_honest
        print(f"    Honest baseline:            {auc_honest:.4f}")

        # + amount
        auc_amount = train_and_evaluate(
            df, honest_features + ["amount"], use_chronological=True
        )
        run_results["  + amount feature"] = auc_amount
        print(f"    + amount feature:           {auc_amount:.4f}")

        # + target encoding
        leak_features = honest_features + ["cf_fraud_rate", "mf_fraud_rate"]
        auc_target = train_and_evaluate(
            df, leak_features, use_chronological=True
        )
        run_results["  + target encoding (mf/cf_fraud_rate)"] = auc_target
        print(f"    + target encoding:          {auc_target:.4f}")

        # + random split
        auc_random = train_and_evaluate(df, honest_features, use_chronological=False)
        run_results["  + random split"] = auc_random
        print(f"    + random split:             {auc_random:.4f}")

        results.append(run_results)

    # Aggregate
    print(f"\n  Aggregated over {n} runs:\n")
    print("| Variant | Mean AUC | Std |")
    print("| :--- | ---: | ---: |")
    for variant in results[0].keys():
        vals = [r[variant] for r in results]
        mean = np.mean(vals)
        std = np.std(vals)
        print(f"| {variant} | {mean:.4f} | {std:.4f} |")

    # Write JSON for script consumers
    out = {
        "hardware": get_hardware_info(),
        "gold_snapshot": gold_path,
        "timestamp": datetime.now().isoformat(),
        "documented_history": {
            "leak1_amount_shortcut": 0.9079,
            "leak3_tuned_amount_no_behavioral": 0.7960,
            "leak4_target_encoding": 0.925,
            "leak6_random_split": 0.786,
            "final_honest": 0.7622,
        },
        "ablation_results": {k: float(np.mean([r[k] for r in results])) for k in results[0]},
    }
    os.makedirs("benchmarks", exist_ok=True)
    with open("benchmarks/leakage_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results written to benchmarks/leakage_results.json")


if __name__ == "__main__":
    main()
