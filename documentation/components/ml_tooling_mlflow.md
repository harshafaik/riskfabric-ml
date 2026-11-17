# MLflow Experiment Tracking & Model Registry

## Overview

MLflow records every training and calibration run and packages the deployed fraud model as a portable pyfunc artifact. `mlflow_logging.py` centralizes tracking-URI and experiment setup; `mlflow_wrapper.py` defines the `CalibratedFraudModel` pyfunc wrapper plus a `LocalScoringWrapper` adapter for local-file fallback; `model_utils.load_model_for_scoring()` prefers the registry via the `MLFLOW_MODEL_URI` env var, then falls back to the local isotonic calibrator pickle, then to the raw XGBoost JSON. `train_xgboost.py` and `calibrate_model.py` consume the Gold Parquet snapshot via DuckDB and produce MLflow runs under the `Fraud Detection Pipeline` experiment, with the calibrator registered as `RiskFabric-Fraud`. The MLflow UI runs as an optional Docker service (`mlflow-ui` on port 5000) backed by the `./mlruns` file store.

## Tracking Configuration

| Setting | Value | Notes |
| :--- | :--- | :--- |
| Tracking URI | `MLFLOW_TRACKING_URI` env, default `file:./mlruns` | File store requires `MLFLOW_ALLOW_FILE_STORE=true` |
| Experiment (train/calibrate) | `Fraud Detection Pipeline` | Set by `setup_mlflow()` |
| Experiment (tuning) | `Fraud Detection Tuning` | Trials logged via Optuna callback |
| UI port | `5000` | `mlflow-ui` compose service, mounts `./mlruns` |

## What Gets Logged

### Training run (`train_xgboost.py`)

| Category | Content |
| :--- | :--- |
| Params | `n_estimators`, `max_depth`, `learning_rate`, `min_child_weight`, `gamma`, `reg_alpha`, `reg_lambda`, `subsample`, `colsample_bytree`, `colsample_bylevel`, `max_delta_step`, `objective`, `tree_method`, `scale_pos_weight`, `random_state`, `eval_metric`, `feature_count`, `tuning_source` |
| Metrics | `roc_auc`, `train_size`, `test_size`, `feature_importance.{feature}` |
| Tags | `script=train_xgboost`, `snapshot`, `feature_count` |
| Artifacts | Model JSON under `model/`, manual tuning config under `config/` |

### Calibration run (`calibrate_model.py`)

| Category | Content |
| :--- | :--- |
| Params | `calibration_method`, `calibration_split` (0.5), `snapshot`, `n_cal_samples`, `n_eval_samples` |
| Metrics | Per-method (raw/Platt/isotonic): `roc_auc`, `pr_auc`, `brier_loss`, `ece` |
| Tags | `script=calibrate_model`, `calibration_method`, `snapshot` |
| Model | `mlflow.pyfunc.log_model()` as `fraud_scorer`, registered name `RiskFabric-Fraud` |

## pyfunc Wrapper (`CalibratedFraudModel`)

The wrapper self-contains inference preprocessing. `load_context()` reads the calibrator pickle plus `feature_names.json`/`feature_types.json` sidecars. `predict()` reorders columns to the model's feature order, fills any missing column with `0.0`, and casts each column to its expected dtype (`c`→`category`, `float`→`float32`, `int`→`int32`) before returning the calibrated fraud probability. The caller gets correct predictions from `model.predict(df)` without knowing the model's expected schema.

## Model Loading Fallback Chain

`model_utils.load_model_for_scoring()` resolves the production inference model in three steps:

1. **MLflow registry** — if `MLFLOW_MODEL_URI` is set and loadable, return the pyfunc model.
2. **Local calibrator** — load `models/calibrated_fraud_model_isotonic.pkl` wrapped in `LocalScoringWrapper`.
3. **Raw XGBoost** — load the latest `models/fraud_model_*.json` via `load_model(enable_categorical=True)`, also wrapped.

Every step returns the same `predict(df) -> calibrated_probability` interface, so `scorer.py` is agnostic to which source provided the model. The scorer calls `load_model_for_scoring()` at startup and does not branch on the source.

## Pipeline Position

MLflow sits between training and serving. `train_xgboost.py` logs the raw model run, `calibrate_model.py` registers the deployable pyfunc artifact, and the real-time scorer (`scorer.py`) consumes that artifact through the `model_utils` fallback chain. `tune_xgboost.py` additionally logs each Optuna trial into MLflow via `optuna_integration.mlflow.MLflowCallback`, so the tuning experiment and the production run share the same tracking backend.

Both `train_xgboost.py` and `calibrate_model.py` accept a `--mlflow-strict` flag that elevates tracking failures to hard errors — useful in CI to enforce that every run has a registry record rather than silently falling back to a local model with no trace.
