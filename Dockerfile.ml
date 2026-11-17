FROM python:3.11-slim

WORKDIR /usr/app

RUN pip install --no-cache-dir \
    clickhouse-connect \
    polars xgboost scikit-learn pyarrow shap mlflow optuna evidently \
    confluent-kafka redis pandas numpy pyyaml plotly \
    psycopg2-binary duckdb

CMD ["/bin/sh"]
