"""Replay a Parquet file or directory into the raw_transactions topic."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import polars as pl
from confluent_kafka import Producer

TOPIC = "raw_transactions"


def _frame(path: Path) -> pl.DataFrame:
    if path.is_dir():
        files = sorted(path.rglob("*.parquet"))
        if not files:
            raise SystemExit(f"no Parquet files under {path}")
        return pl.concat([pl.read_parquet(file) for file in files])
    return pl.read_parquet(path)


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/bronze/transactions.parquet"),
    )
    parser.add_argument("--topic", default=TOPIC)
    parser.add_argument(
        "--bootstrap",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=0.0,
        help="rows per second; 0 sends as fast as possible",
    )
    parser.add_argument("--limit", type=int, default=0, help="stop after N rows; 0 sends all")
    args = parser.parse_args()

    frame = _frame(args.input)
    if args.limit:
        frame = frame.head(args.limit)

    producer = Producer({"bootstrap.servers": args.bootstrap})
    sent = 0
    for row in frame.iter_rows(named=True):
        payload = {key: _jsonable(value) for key, value in row.items()}
        producer.produce(
            args.topic,
            key=str(row.get("card_id", "")).encode("utf-8"),
            value=json.dumps(payload).encode("utf-8"),
        )
        producer.poll(0)
        sent += 1
        if args.rate > 0:
            time.sleep(1.0 / args.rate)
        if sent % 1000 == 0:
            print(f"sent {sent:,}")
    producer.flush()
    print(f"sent {sent:,} rows to {args.topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
