#!/usr/bin/env python3
"""Synthetic transaction generator.

The generator reads environment variables (set in the docker‑compose file)
to control the rate and composition of the stream.
It creates JSON records following the transaction schema and pushes them to
the Kafka topic `transactions.raw`.
"""

import os
import json
import time
import random
import logging
from typing import List

from confluent_kafka import Producer
from faker import Faker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
TRANSACTION_RATE = int(os.getenv("TRANSACTION_RATE", "20"))
FRAUD_INJECTION_RATE = float(os.getenv("FRAUD_INJECTION_RATE", "0.05"))
FRAUD_TYPES = json.loads(os.getenv("FRAUD_TYPES", '["GAT","DMR","RBF","CAL","AEV"]'))
TOPIC = "transactions.raw"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
log = logging.getLogger("generator")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
log.addHandler(handler)

fake = Faker()

def delivery_report(err, msg):
    if err is not None:
        log.warning(f"Message delivery report: {err}")

def make_transaction(is_fraud: bool = False) -> dict:
    amount = round(random.uniform(10, 5000), 2)
    txn = {
        "transaction_id": f"TXN-{int(time.time()*1000)}-{random.randint(1000, 9999)}",
        "account_id": f"ACC-{random.randint(1, 1000):06d}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "amount": amount,
        "currency": "USD",
        "type": random.choice(["transfer", "payment", "withdrawal"]),
        "counterparty_id": f"ACC-{random.randint(1, 1000):06d}",
        "channel": random.choice(["mobile", "web", "atm"]),
        "location": {
            "country": "US",
            "region": random.choice(["northeast", "midwest", "southwest", "west"]),
            "city": fake.city(),
        },
        "metadata": {
            "device_id": f"DEV-{random.randint(1000, 9999)}",
            "ip_address": fake.ipv4_public(),
            "session_id": f"SESS-{random.randint(100000, 999999)}",
        },
        "is_fraud": is_fraud,
        "fraud_type": random.choice(FRAUD_TYPES) if is_fraud else None,
    }
    return txn

def run():
    log.info("Waiting 5s for Kafka broker to be ready...")
    time.sleep(5)
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})
    interval = 1.0 / max(1, TRANSACTION_RATE)
    log.info("Starting generator – %.1f TPS, %.2f%% fraud", TRANSACTION_RATE, FRAUD_INJECTION_RATE * 100)
    while True:
        try:
            is_fraud = random.random() < FRAUD_INJECTION_RATE
            txn = make_transaction(is_fraud)
            payload = json.dumps(txn).encode("utf-8")
            producer.produce(TOPIC, payload, callback=delivery_report)
            producer.poll(0)
        except Exception as e:
            log.warning(f"Error producing message: {e}")
        time.sleep(interval)

if __name__ == "__main__":
    run()
