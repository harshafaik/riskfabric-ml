import os
import glob
import duckdb
import numpy as np
import polars as pl


def find_gold_snapshot(snapshot=None):
    if snapshot:
        path = f"data/gold/{snapshot}/fact_transactions_gold.parquet"
        if os.path.exists(path):
            return path
        raise FileNotFoundError(f"Snapshot not found: {path}")

    snapshots = sorted(glob.glob("data/gold/*/fact_transactions_gold.parquet"), reverse=True)
    if not snapshots:
        raise FileNotFoundError("No Gold snapshots found. Run `cargo run --bin etl -- gold-master` first.")
    return snapshots[0]


def load_gold_dataframe(snapshot=None):
    gold_path = find_gold_snapshot(snapshot)
    conn = duckdb.connect()
    df = pl.from_arrow(conn.execute(f"SELECT * FROM '{gold_path}'").arrow())
    conn.close()
    return df


def calculate_ece(y_true, y_prob, n_bins=10):
    """Expected Calibration Error over uniform probability bins."""
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    total_samples = len(y_prob)

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        in_bin = (y_prob >= lo) & (y_prob < hi) if i < n_bins - 1 else (y_prob >= lo) & (y_prob <= hi)
        bin_count = np.sum(in_bin)
        if bin_count > 0:
            bin_error = abs(np.mean(y_prob[in_bin]) - np.mean(y_true[in_bin]))
            ece += (bin_count / total_samples) * bin_error

    return ece


def split_by_timestamp(df, test_size=0.2):
    """Split a Polars DataFrame chronologically by its `timestamp` column.

    Rows are sorted by timestamp ascending. The first (1-test_size) fraction
    goes to the training set, and the last test_size fraction goes to the test
    set. This prevents future data from leaking into training and avoids the
    optimistically biased metrics that a random split produces on time-series
    fraud data.
    """
    df_sorted = df.sort("timestamp")
    n = len(df_sorted)
    split_idx = int(n * (1 - test_size))
    train_df = df_sorted[:split_idx]
    test_df = df_sorted[split_idx:]
    return train_df, test_df
