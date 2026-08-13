#!/usr/bin/env python3
"""Synthetic transaction generator.

The generator reads a handful of environment variables (set in the
docker‑compose file) to control the rate and composition of the stream.
It creates JSON records that roughly follow the schema described in the
PRD (see Appendix C) and pushes them to the Kafka topic
`transactions.raw`.

Key environment variables:
    TRANSACTION_RATE          – desired TPS (default 100)
    FRAUD_INJECTION_RATE      – fraction of transactions that are fraudulent
    FRAUD_TYPES               – JSON list of fraud codes e.g. ["GAT","DMR"]
    KAFKA_BOOTSTRAP_SERVERS   – broker address (default: kafka:29092)

The implementation is intentionally lightweight – the heavy‑weight ML
logic lives in the detector service.  This script merely provides a
continuous stream of realistic‑looking data for the rest of the system.
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
# Configuration via environment variables
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
TRANSACTION_RATE = int(os.getenv("TRANSACTION_RATE", "100"))          # TPS
FRAUD_INJECTION_RATE = float(os.getenv("FRAUD_INJECTION_RATE", "0.03"))
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

# ---------------------------------------------------------------------------
# Initialise Faker and Kafka producer
# ---------------------------------------------------------------------------
fake = Faker()
producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})


def delivery_report(err, msg):
    """Kafka async delivery callback – logs failures only."""
    if err is not None:
        log.error(f"Failed to deliver message: {err}")


def make_transaction(is_fraud: bool = False) -> dict:
    """Create a single transaction dict.

    The fields loosely follow the PRD's synthetic schema.  When ``is_fraud``
    is ``True`` we add a ``fraud_type`` chosen from ``FRAUD_TYPES``.
    """
    amount = round(random.uniform(5, 5000), 2)
    txn = {
        "transaction_id": f"TXN-{int(time.time()*1000)}-{random.randint(0, 9999)}",
        "account_id": f"ACC-{random.randint(1, 10000):06d}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "amount": amount,
        "currency": "USD",
        "type": random.choice(["transfer", "payment", "withdrawal"]),
        "counterparty_id": f"ACC-{random.randint(1, 10000):06d}",
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
    interval = 1.0 / TRANSACTION_RATE
    log.info("Starting generator – %.1f TPS, %.2f%% fraud", TRANSACTION_RATE, FRAUD_INJECTION_RATE * 100)
    while True:
        is_fraud = random.random() < FRAUD_INJECTION_RATE
        txn = make_transaction(is_fraud)
        payload = json.dumps(txn).encode("utf-8")
        producer.produce(TOPIC, payload, callback=delivery_report)
        producer.poll(0)
        time.sleep(interval)

if __name__ == "__main__":
    run()
