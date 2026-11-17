# Optuna Hyperparameter Tuning

## Overview

`tune_xgboost.py` searches the XGBoost hyperparameter space with Optuna's multivariate TPE sampler, optimizing PR-AUC on a held-out chronological test split. The study persists to PostgreSQL (`riskfabric_optuna` database, created by `docker/postgres-init/init-optuna.sql`); the storage URL is constructed from `OLTP_POSTGRES_HOST`/`PORT`/`USER`/`PASSWORD` environment variables (matching the rest of the stack). When PostgreSQL is unreachable, the tuner falls back to in-memory storage — unless `--require-storage` is passed, which makes the fallback a hard error. The best parameters are written to `data/config/ml_tuning_optuna.yaml` (and a parallel `.json`), which `train_xgboost.py` reads at startup, taking precedence over the manually-maintained `data/config/ml_tuning.yaml`. Each trial is optionally streamed to MLflow through `optuna_integration.mlflow.MLflowCallback`.

## Study Configuration

| Setting | Value | Notes |
| :--- | :--- | :--- |
| Study name | `xgboost-fraud-tuning` | Default; overridable via `--study-name` |
| Storage URL | `postgresql+psycopg2://{user}:{pw}@{host}:{port}/riskfabric_optuna` | Built from `OLTP_POSTGRES_*` env vars; `--storage-url` override |
| Direction | Maximize PR-AUC | `average_precision_score` on the test split |
| Sampler | `TPESampler(multivariate=True, seed=42)` | Deterministic, joint hyperparameter search |
| Trials | 100 default | `--trials` CLI override |
| Persistence | `load_if_exists=True` | Resumes an existing study by name |

## Search Space

| Hyperparameter | Range | Scale |
| :--- | :--- | :--- |
| `n_estimators` | 50–500 | int |
| `max_depth` | 3–12 | int |
| `learning_rate` | 0.01–0.3 | log |
| `min_child_weight` | 1–20 | int |
| `gamma` | 0.001–5.0 | log |
| `reg_alpha` | 0.001–10.0 | log |
| `reg_lambda` | 0.001–10.0 | log |
| `subsample` | 0.5–1.0 | uniform |
| `colsample_bytree` | 0.5–1.0 | uniform |
| `colsample_bylevel` | 0.5–1.0 | uniform |
| `max_delta_step` | 0–10 | int |
| `scale_pos_weight_multiplier` | 0.5–2.0 | uniform — multiplies the data-derived `scale_pos_weight` |

Fixed per trial: `objective=binary:logistic`, `tree_method=hist`, `enable_categorical=True`, `eval_metric=aucpr`, `random_state=42`. The trial reports its `roc_auc` as a user attribute and returns PR-AUC as the objective. The multiplier is removed from the final saved parameter dict and folded into a single `scale_pos_weight` value before writing output.

## Config Consumption Path

`train_xgboost.py` resolves hyperparameters in this order:

1. If `data/config/ml_tuning_optuna.yaml` exists, load its `hyperparameters` block (including the tuned `scale_pos_weight`) — tagged `tuning_source: optuna` in the MLflow run.
2. Else if `data/config/ml_tuning.yaml` exists, use it.
3. Else use hardcoded defaults.

This precedence ensures the auto-generated Optuna output wins when present while the manual config remains untouched for human editing, per the project's config convention.

## Output Files

| File | Content |
| :--- | :--- |
| `data/config/ml_tuning_optuna.yaml` | `study_name`, `study_direction`, `target_metric`, `best_pr_auc`, `best_roc_auc`, `best_trial_number`, `n_trials`, `hyperparameters` |

## Pipeline Position

Optuna is a pre-training optimization stage. It reads the Gold Parquet snapshot (via `find_gold_snapshot()` and DuckDB), splits chronologically with `split_by_timestamp(test_size=0.2)` — the same split the trainer uses — and hands the tuned hyperparameters down to `train_xgboost.py` through the config file. When PostgreSQL is up, the study resumes across sessions; when MLflow is available, trials log to the `Fraud Detection Tuning` experiment.

The `--require-storage` flag aborts with an error rather than silently falling back to in-memory when PostgreSQL is unreachable — useful for CI jobs and long searches where trial persistence matters. The storage URL is built from the same `OLTP_POSTGRES_HOST`/`OLTP_POSTGRES_PORT`/`OLTP_POSTGRES_USER`/`OLTP_POSTGRES_PASSWORD` environment variables used by the rest of the stack, with the `OPTUNA_POSTGRES_DB` variable defaulting to `riskfabric_optuna`. A `--storage-url` CLI override still takes precedence for custom setups.
