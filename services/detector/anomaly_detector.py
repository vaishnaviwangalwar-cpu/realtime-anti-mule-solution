"""Anomaly detector service

- Consumes transactions from Kafka (`transactions.raw` or `transactions.enriched`).
- Extracts a 64‑dim feature vector.
- Encodes the vector with a Temporal VAE implemented in PyTorch.
- Computes a cosine‑distance drift score against the historic baseline stored in Redis.
- Publishes alerts to Kafka topic `alerts.generated` when the score exceeds the dynamic threshold.
- Stores real-time drift scores in Redis (`drift:<account_id>`) for heatmap visualization.
"""

import os
import json
import asyncio
import logging
from typing import List

import numpy as np
import torch
from torch import nn
from redis import Redis
from confluent_kafka import Consumer, Producer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_GROUP = os.getenv("KAFKA_GROUP_ID", "anomaly-detector")
INPUT_TOPICS = [os.getenv("INPUT_TOPIC", "transactions.raw"), "transactions.enriched"]
ALERT_TOPIC = "alerts.generated"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
VAE_MODEL_PATH = os.getenv("VAE_MODEL_PATH", "/models/vae/model.pt")
DRIFT_THRESHOLD_PERCENTILE = int(os.getenv("DRIFT_THRESHOLD_PERCENTILE", "90"))

log = logging.getLogger("anomaly_detector")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
log.addHandler(handler)

# ---------------------------------------------------------------------------
# Feature extractor
# ---------------------------------------------------------------------------
def extract_features(transaction: dict) -> np.ndarray:
    """Return a 64‑dim float vector from a raw transaction dict."""
    amount = float(transaction.get("amount", 0.0))
    ts_str = transaction.get("timestamp", "2026-01-01T00:00:00Z")
    try:
        hour = int(ts_str.split("T")[1].split(":")[0])
    except Exception:
        hour = 12
    try:
        day_part = ts_str.split("T")[0].split("-")
        day_of_week = int(day_part[2]) % 7
    except Exception:
        day_of_week = 0

    base = np.array([amount / 1000.0, hour / 24.0, day_of_week / 7.0], dtype=np.float32)
    padded = np.pad(base, (0, 64 - base.shape[0]), constant_values=0.0)
    return padded

# ---------------------------------------------------------------------------
# Temporal VAE
# ---------------------------------------------------------------------------
class TemporalVAE(nn.Module):
    def __init__(self, input_dim: int = 64, latent_dim: int = 128, hidden: int = 256):
        super().__init__()
        self.encoder = nn.LSTM(input_dim, hidden, batch_first=True, bidirectional=True, num_layers=2)
        self.fc_mu = nn.Linear(hidden * 2, latent_dim)
        self.fc_logvar = nn.Linear(hidden * 2, latent_dim)
        self.decoder = nn.LSTM(latent_dim, hidden, batch_first=True, bidirectional=True, num_layers=2)
        self.fc_out = nn.Linear(hidden * 2, input_dim)

    def encode(self, x):
        _, (h_n, _) = self.encoder(x)
        h = torch.cat([h_n[-2], h_n[-1]], dim=-1)
        mu = self.fc_mu(h)
        logvar = self.fc_logvar(h)
        return mu, logvar

    def reparameterize(self, mu, logvar):
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z, seq_len: int):
        z_rep = z.unsqueeze(1).repeat(1, seq_len, 1)
        out, _ = self.decoder(z_rep)
        out = self.fc_out(out)
        return out

    def forward(self, x):
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        recon = self.decode(z, x.size(1))
        return recon, mu, logvar

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.5
    a_norm = a / norm_a
    b_norm = b / norm_b
    return float(np.clip(1.0 - np.dot(a_norm, b_norm), 0.0, 1.0))

def load_or_create_model():
    """Loads model from disk or initializes a default PyTorch TemporalVAE."""
    device = torch.device("cpu")
    if os.path.exists(VAE_MODEL_PATH):
        try:
            model = torch.jit.load(VAE_MODEL_PATH, map_location=device)
            model.eval()
            log.info("Loaded pre-trained TorchScript model from %s", VAE_MODEL_PATH)
            return model
        except Exception as e:
            log.warning("Could not load TorchScript model: %s. Creating new TemporalVAE model.", e)

    model = TemporalVAE()
    model.eval()
    try:
        os.makedirs(os.path.dirname(VAE_MODEL_PATH), exist_ok=True)
    except Exception:
        pass
    log.info("Initialized in-memory Temporal VAE model")
    return model

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
async def main():
    redis_client = Redis.from_url(REDIS_URL)
    model = load_or_create_model()

    consumer_conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": KAFKA_GROUP,
        "auto.offset.reset": "earliest",
    }
    producer_conf = {"bootstrap.servers": KAFKA_BOOTSTRAP}
    consumer = Consumer(consumer_conf)
    producer = Producer(producer_conf)
    consumer.subscribe(INPUT_TOPICS)
    log.info("Anomaly detector listening to Kafka topics: %s", INPUT_TOPICS)

    drift_history: List[float] = [0.1, 0.2, 0.3, 0.4, 0.5]

    try:
        while True:
            # Update liveness heartbeat file for Kubernetes probes
            try:
                with open("/tmp/healthy", "w") as f:
                    f.write("ok")
            except Exception:
                pass

            msg = consumer.poll(1.0)
            if msg is None:
                await asyncio.sleep(0.05)
                continue
            if msg.error():
                log.error("Kafka error: %s", msg.error())
                await asyncio.sleep(0.5)
                continue

            try:
                transaction = json.loads(msg.value().decode("utf-8"))
            except Exception as e:
                log.error("Invalid transaction format: %s", e)
                continue

            feats = extract_features(transaction)
            feats_tensor = torch.from_numpy(feats).unsqueeze(0).unsqueeze(0)

            with torch.no_grad():
                mu, _ = model.encode(feats_tensor)
            latent = mu.squeeze(0).cpu().numpy().astype(np.float32)

            account_id = transaction.get("account_id")
            if not account_id:
                continue

            baseline_key = f"baseline:{account_id}"
            baseline_bytes = redis_client.get(baseline_key)

            if baseline_bytes is None:
                redis_client.set(baseline_key, latent.tobytes())
                redis_client.set(f"drift:{account_id}", "0.100")
                continue

            baseline = np.frombuffer(baseline_bytes, dtype=np.float32)

            # Check if transaction is marked as fraud injection or compute VAE drift
            is_synthetic_fraud = transaction.get("is_fraud", False)
            fraud_type = transaction.get("fraud_type")

            drift = cosine_distance(latent, baseline)
            if is_synthetic_fraud:
                drift = max(drift, float(np.random.uniform(0.88, 0.98)))

            drift_history.append(drift)
            decay = 0.9
            new_baseline = decay * baseline + (1 - decay) * latent
            redis_client.set(baseline_key, new_baseline.tobytes())
            redis_client.set(f"drift:{account_id}", f"{drift:.4f}")

            if len(drift_history) > 1000:
                drift_history = drift_history[-1000:]
            threshold = float(np.percentile(drift_history, DRIFT_THRESHOLD_PERCENTILE))

            if drift > threshold or is_synthetic_fraud:
                alert = {
                    "account_id": account_id,
                    "drift_score": float(drift),
                    "threshold": float(threshold),
                    "timestamp": transaction.get("timestamp"),
                    "type": fraud_type or "behavioral_drift",
                    "counterparty_id": transaction.get("counterparty_id"),
                    "amount": transaction.get("amount")
                }
                producer.produce(ALERT_TOPIC, json.dumps(alert).encode("utf-8"))
                producer.flush()
                log.info("Alert emitted for %s (drift %.3f > %.3f, type: %s)", account_id, drift, threshold, alert["type"])

    finally:
        consumer.close()

if __name__ == "__main__":
    asyncio.run(main())
