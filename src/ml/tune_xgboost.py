import polars as pl
import xgboost as xgb
import duckdb
import numpy as np
import yaml
import os
from sklearn.metrics import roc_auc_score, average_precision_score
from argparse import ArgumentParser
from ml_utils import split_by_timestamp, find_gold_snapshot

OPTUNA_OUTPUT_PATH = "data/config/ml_tuning_optuna.yaml"


def _build_storage_url():
    host = os.environ.get("OLTP_POSTGRES_HOST", "localhost")
    port = os.environ.get("OLTP_POSTGRES_PORT", "5433")
    user = os.environ.get("OLTP_POSTGRES_USER", "riskfabric_oltp_user")
    password = os.environ.get("OLTP_POSTGRES_PASSWORD", "123")
    db = os.environ.get("OPTUNA_POSTGRES_DB", "riskfabric_optuna")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"

FEATURE_COLS = [
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


def load_data(gold_path):
    conn = duckdb.connect()
    query = f"SELECT * FROM '{gold_path}'"
    df = pl.from_arrow(conn.execute(query).arrow())
    conn.close()
    return df


def prepare_features(df):
    available_cols = df.columns
    feature_cols = [c for c in FEATURE_COLS if c in available_cols]
    missing = set(FEATURE_COLS) - set(available_cols)
    if missing:
        print(f"   Missing from Gold: {missing}")

    train_df, test_df = split_by_timestamp(df, test_size=0.2)

    X_train = train_df.select(feature_cols).to_pandas()
    y_train = train_df["is_fraud"].to_numpy()
    X_test = test_df.select(feature_cols).to_pandas()
    y_test = test_df["is_fraud"].to_numpy()

    categorical_cols = [c for c in feature_cols if train_df[c].dtype == pl.String]
    for c in categorical_cols:
        X_train[c] = X_train[c].astype("category")
        X_test[c] = X_test[c].astype("category")

    fraud_count = y_train.sum()
    legitimate_count = len(y_train) - fraud_count
    scale_pos_weight = legitimate_count / fraud_count

    return X_train, y_train, X_test, y_test, feature_cols, scale_pos_weight


def objective(trial, X_train, y_train, X_test, y_test, scale_pos_weight):
    swm = trial.suggest_float("scale_pos_weight_multiplier", 0.5, 2.0)
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 50, 500),
        "max_depth": trial.suggest_int("max_depth", 3, 12),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
        "gamma": trial.suggest_float("gamma", 0.001, 5.0, log=True),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.001, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.001, 10.0, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "colsample_bylevel": trial.suggest_float("colsample_bylevel", 0.5, 1.0),
        "max_delta_step": trial.suggest_int("max_delta_step", 0, 10),
        "scale_pos_weight_multiplier": swm,
        "objective": "binary:logistic",
        "tree_method": "hist",
        "enable_categorical": True,
        "random_state": 42,
        "eval_metric": "aucpr",
        "scale_pos_weight": scale_pos_weight * swm,
    }
    del params["scale_pos_weight_multiplier"]

    model = xgb.XGBClassifier(**params)
    model.fit(X_train, y_train)

    y_prob = model.predict_proba(X_test)[:, 1]
    pr_auc = average_precision_score(y_test, y_prob)
    roc_auc = roc_auc_score(y_test, y_prob)

    trial.set_user_attr("roc_auc", float(roc_auc))

    return pr_auc


def tune():
    import optuna

    parser = ArgumentParser(description="Optuna hyperparameter tuning for XGBoost fraud detection")
    parser.add_argument("--snapshot", type=str, default=None, help="Specific snapshot directory")
    parser.add_argument("--trials", type=int, default=100, help="Number of Optuna trials (default: 100)")
    parser.add_argument("--study-name", type=str, default="xgboost-fraud-tuning", help="Optuna study name")
    parser.add_argument("--storage-url", type=str, default=None, help="DB URL for Optuna storage (overrides env)")
    parser.add_argument("--require-storage", action="store_true", help="Abort instead of falling back to in-memory")
    args = parser.parse_args()

    storage_url = args.storage_url or os.environ.get("OPTUNA_STORAGE_URL") or _build_storage_url()

    gold_path = find_gold_snapshot(args.snapshot)
    print(f"Loading Gold snapshot: {gold_path}")
    df = load_data(gold_path)
    X_train, y_train, X_test, y_test, feature_cols, scale_pos_weight = prepare_features(df)

    print(f"   Train: {len(y_train):,} rows")
    print(f"   Test:  {len(y_test):,} rows")
    print(f"   Features ({len(feature_cols)}): {feature_cols}")
    print(f"   Scale positive weight: {scale_pos_weight:.4f}")

    callbacks = []

    try:
        import mlflow
        from mlflow_logging import setup_mlflow
        setup_mlflow("Fraud Detection Tuning")

        from optuna_integration.mlflow import MLflowCallback  # optuna 4.x

        mlflow_callback = MLflowCallback(
            tracking_uri=mlflow.get_tracking_uri(),
            metric_name="pr_auc",
        )
        callbacks.append(mlflow_callback)
        print("   MLflow callback registered")
    except Exception as e:
        print(f"   MLflow callback unavailable (non-fatal): {e}")

    try:
        study = optuna.create_study(
            study_name=args.study_name,
            storage=storage_url,
            direction="maximize",
            load_if_exists=True,
            sampler=optuna.samplers.TPESampler(multivariate=True, seed=42),
        )
        storage_label = "PostgreSQL"
    except Exception:
        if args.require_storage:
            print(f"ERROR: PostgreSQL storage unavailable and --require-storage is set")
            raise
        print(f"   PostgreSQL unavailable, falling back to in-memory")
        study = optuna.create_study(
            study_name=args.study_name,
            direction="maximize",
            sampler=optuna.samplers.TPESampler(multivariate=True, seed=42),
        )
        storage_label = "in-memory"

    print(f"\nStarting Optuna study '{args.study_name}' — {args.trials} trials")
    print(f"   Storage: {storage_label}")
    print(f"   Sampler: TPESampler(multivariate=True)")
    print(f"   Direction: maximize PR-AUC\n")

    def wrapped_objective(trial):
        return objective(trial, X_train, y_train, X_test, y_test, scale_pos_weight)

    study.optimize(wrapped_objective, n_trials=args.trials, callbacks=callbacks)

    print("\n" + "=" * 60)
    print("OPTUNA TUNING RESULTS")
    print("=" * 60)
    print(f"   Best trial:  #{study.best_trial.number}")
    print(f"   Best PR-AUC:  {study.best_value:.6f}")
    print(f"   Best ROC-AUC: {study.best_trial.user_attrs.get('roc_auc', 'N/A'):.6f}")

    best_params = study.best_params.copy()
    best_params.pop("scale_pos_weight_multiplier", None)
    best_params["objective"] = "binary:logistic"
    best_params["tree_method"] = "hist"
    best_params["enable_categorical"] = True
    best_params["random_state"] = 42
    best_params["eval_metric"] = "aucpr"
    best_params["scale_pos_weight"] = float(
        scale_pos_weight * study.best_params.get("scale_pos_weight_multiplier", 1.0)
    )

    print("\n   Best parameters:")
    for k, v in sorted(best_params.items()):
        if isinstance(v, float):
            print(f"     {k}: {v:.6f}")
        else:
            print(f"     {k}: {v}")

    output = {
        "study_name": args.study_name,
        "study_direction": "maximize",
        "target_metric": "pr_auc",
        "best_pr_auc": float(study.best_value),
        "best_roc_auc": study.best_trial.user_attrs.get("roc_auc"),
        "best_trial_number": study.best_trial.number,
        "n_trials": args.trials,
        "hyperparameters": best_params,
    }

    os.makedirs(os.path.dirname(OPTUNA_OUTPUT_PATH), exist_ok=True)
    with open(OPTUNA_OUTPUT_PATH, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False)
    print(f"\nSaved: {OPTUNA_OUTPUT_PATH}")


if __name__ == "__main__":
    tune()
