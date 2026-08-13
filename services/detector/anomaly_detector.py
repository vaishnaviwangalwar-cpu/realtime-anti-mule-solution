"""Anomaly detector service

- Consumes enriched transactions from Kafka (`transactions.enriched`).
- Extracts a 64‑dim feature vector (placeholder implementation).
- Encodes the vector with a Temporal VAE implemented in PyTorch.
- Computes a cosine‑distance drift score against the historic baseline stored in Redis.
- Publishes alerts to Kafka topic `alerts.generated` when the score exceeds the dynamic 95th‑percentile threshold.

The code is intentionally lightweight – heavy‑weight model training is performed offline and the exported TorchScript model is mounted at `/models/vae/model.pt`.
"""

import os
import json
import asyncio
import logging
from typing import List

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from redis import Redis
from confluent_kafka import Consumer, Producer

# ---------------------------------------------------------------------------
# Configuration (environment variables are injected by Docker Compose)
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_GROUP = os.getenv("KAFKA_GROUP_ID", "anomaly-detector")
ENRICHED_TOPIC = "transactions.enriched"
ALERT_TOPIC = "alerts.generated"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
VAE_MODEL_PATH = os.getenv("VAE_MODEL_PATH", "/models/vae/model.pt")
DRIFT_THRESHOLD_PERCENTILE = int(os.getenv("DRIFT_THRESHOLD_PERCENTILE", "95"))

log = logging.getLogger("anomaly_detector")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
log.addHandler(handler)

# ---------------------------------------------------------------------------
# Simple feature extractor – in a real system this would be much richer.
# ---------------------------------------------------------------------------
def extract_features(transaction: dict) -> np.ndarray:
    """Return a 64‑dim float vector from a raw transaction dict.
    For demo purposes we hash a few numeric fields and pad/truncate.
    """
    # Example fields – adjust to match the schema in the PRD.
    amount = transaction.get("amount", 0.0)
    hour = int(transaction.get("timestamp", "00:00").split("T")[1].split(":")[0])
    day_of_week = int(transaction.get("timestamp", "1970-01-01T00:00").split("T")[0].split('-')[2]) % 7
    # Create a small vector and pad to 64 dims.
    base = np.array([amount, hour, day_of_week], dtype=np.float32)
    padded = np.pad(base, (0, 64 - base.shape[0]), constant_values=0.0)
    return padded

# ---------------------------------------------------------------------------
# Temporal VAE – very minimal skeleton. The actual trained model is loaded
# from disk; the class definition must match the saved TorchScript.
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
        # x: (batch, seq_len, dim)
        _, (h_n, _) = self.encoder(x)
        h = torch.cat([h_n[-2], h_n[-1]], dim=-1)  # bidirectional concat
        mu = self.fc_mu(h)
        logvar = self.fc_logvar(h)
        return mu, logvar

    def reparameterize(self, mu, logvar):
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z, seq_len: int):
        # repeat latent vector for each timestep
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
    a_norm = a / np.linalg.norm(a)
    b_norm = b / np.linalg.norm(b)
    return 1.0 - float(np.dot(a_norm, b_norm))

# ---------------------------------------------------------------------------
# Main async loop
# ---------------------------------------------------------------------------
async def main():
    # Initialise Redis client
    redis_client = Redis.from_url(REDIS_URL)

    # Load the TorchScript model (exported from training script)
    device = torch.device("cpu")
    model = torch.jit.load(VAE_MODEL_PATH, map_location=device)
    model.eval()

    # Initialise Kafka consumer & producer
    consumer_conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": KAFKA_GROUP,
        "auto.offset.reset": "earliest",
    }
    producer_conf = {"bootstrap.servers": KAFKA_BOOTSTRAP}
    consumer = Consumer(consumer_conf)
    producer = Producer(producer_conf)
    consumer.subscribe([ENRICHED_TOPIC])
    log.info("Anomaly detector started – listening to %s", ENRICHED_TOPIC)

    # Simple sliding‑window cache for dynamic thresholding
    drift_history: List[float] = []

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            if msg.error():
                log.error("Kafka error: %s", msg.error())
                continue
            transaction = json.loads(msg.value().decode("utf-8"))
            # 1. Feature extraction
            feats = extract_features(transaction)
            feats_tensor = torch.from_numpy(feats).unsqueeze(0).unsqueeze(0)  # (1,1,64)

            # 2. Encode with VAE – we only need the latent mean (mu)
            with torch.no_grad():
                mu, _ = model.encode(feats_tensor)
            latent = mu.squeeze(0).numpy()  # (latent_dim,)

            # 3. Retrieve historic baseline embedding for the account
            account_id = transaction.get("account_id")
            baseline_key = f"baseline:{account_id}"
            baseline_bytes = redis_client.get(baseline_key)
            if baseline_bytes is None:
                # First observation – store as baseline and skip alerting
                redis_client.set(baseline_key, latent.tobytes())
                continue
            baseline = np.frombuffer(baseline_bytes, dtype=np.float32)

            # 4. Compute drift score
            drift = cosine_distance(latent, baseline)
            drift_history.append(drift)
            # Update baseline with exponential moving average (simple decay)
            decay = 0.9
            new_baseline = decay * baseline + (1 - decay) * latent
            redis_client.set(baseline_key, new_baseline.tobytes())

            # 5. Dynamic threshold – compute 95th percentile on the fly (simple window)
            if len(drift_history) > 1000:
                drift_history = drift_history[-1000:]
            threshold = np.percentile(drift_history, DRIFT_THRESHOLD_PERCENTILE)

            if drift > threshold:
                alert = {
                    "account_id": account_id,
                    "drift_score": drift,
                    "threshold": float(threshold),
                    "timestamp": transaction.get("timestamp"),
                    "type": "behavioral_drift",
                }
                producer.produce(ALERT_TOPIC, json.dumps(alert).encode("utf-8"))
                producer.flush()
                log.info("Alert emitted for %s (score %.3f > %.3f)", account_id, drift, threshold)
    finally:
        consumer.close()

if __name__ == "__main__":
    asyncio.run(main())
