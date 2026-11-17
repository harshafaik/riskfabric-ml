CREATE TABLE IF NOT EXISTS fraud_scores (
    transaction_id String,
    card_id String,
    customer_id String,
    amount Float64,
    timestamp DateTime,
    kafka_received_at DateTime64(3),
    fraud_probability Float64,
    flagged UInt8,
    scored_at DateTime64(3)
) ENGINE = MergeTree()
ORDER BY (timestamp, card_id);

CREATE TABLE IF NOT EXISTS monitoring_metrics (
    report_time  DateTime64(3),
    metric_name  String,
    metric_value Float64,
    metric_label String DEFAULT '',
    report_type  String
) ENGINE = MergeTree()
ORDER BY (report_time, report_type, metric_name);

CREATE TABLE IF NOT EXISTS ground_truth (
    transaction_id String,
    is_fraud       UInt8,
    fraud_target   UInt8,
    label_noise    String,
    generated_at   DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY transaction_id;
