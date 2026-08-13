#!/usr/bin/env python3
"""Graph Analyzer Service

* Consumes enriched transactions from Kafka (topic ``transactions.enriched``).
* Persists accounts and transaction relationships in Neo4j.
* Periodically (default every 30 s) builds an in‑memory NetworkX graph from Neo4j and runs the Louvain community‑detection algorithm.
* For each discovered community ("cluster") it stores a lightweight *morphic memory* signature in Redis – this enables the detector to recognise dormant‑resurrection patterns.
* Optionally publishes a compact cluster summary to a Kafka topic ``graph.updates`` so that the dashboard can receive real‑time topology changes.

The implementation below is intentionally lightweight – it focuses on correctness and observability rather than raw performance. Production‑grade deployments would add proper batching, back‑pressure handling, and more sophisticated feature extraction.
"""

import os
import json
import time
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Tuple

from confluent_kafka import Consumer, Producer, KafkaException
from neo4j import GraphDatabase
from redis import Redis
import networkx as nx

# ---------------------------------------------------------------------------
# Configuration (environment variables – all defined in docker‑compose)
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
ENRICHED_TOPIC = "transactions.enriched"
GRAPH_UPDATES_TOPIC = "graph.updates"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# How often (seconds) we run the clustering step
CLUSTER_INTERVAL = int(os.getenv("CLUSTERING_INTERVAL", "30"))
# Redis key prefix for stored cluster signatures
MORPHIC_PREFIX = "morphic:"  # e.g. morphic:cluster_id -> JSON signature

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
log = logging.getLogger("graph-analyzer")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
log.addHandler(handler)

# ---------------------------------------------------------------------------
# Initialise external services (singletons reused across async loops)
# ---------------------------------------------------------------------------
redis_client = Redis.from_url(REDIS_URL)
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})

# ---------------------------------------------------------------------------
# Helper: publish a JSON message to the ``graph.updates`` topic
# ---------------------------------------------------------------------------
def publish_graph_update(message: dict):
    try:
        producer.produce(GRAPH_UPDATES_TOPIC, json.dumps(message).encode("utf-8"))
        producer.poll(0)
    except Exception as exc:
        log.error(f"Failed to publish graph update: {exc}")

# ---------------------------------------------------------------------------
# Neo4j persistence helpers – each enriched transaction is turned into a
# simple directed edge ``(sender)-[:SENT_TO {amount, timestamp}]->(receiver)``.
# ---------------------------------------------------------------------------
def persist_transaction(txn: dict):
    sender = txn.get("account_id")
    receiver = txn.get("counterparty_id")
    if not sender or not receiver:
        return
    ts = txn.get("timestamp", datetime.utcnow().isoformat() + "Z")
    amount = txn.get("amount", 0)
    with neo4j_driver.session() as session:
        session.run(
            """
            MERGE (a:Account {id: $sender})
            MERGE (b:Account {id: $receiver})
            CREATE (a)-[:SENT_TO {amount: $amt, timestamp: $ts}]->(b)
            """,
            sender=sender,
            receiver=receiver,
            amt=amount,
            ts=ts,
        )

# ---------------------------------------------------------------------------
# Clustering routine – builds a NetworkX graph from Neo4j, runs Louvain
# community detection, stores a concise signature in Redis, and emits an
# update message for the dashboard.
# ---------------------------------------------------------------------------
def run_clustering():
    log.info("Running Louvain clustering …")
    # Pull a minimal edge list from Neo4j – this is fine for demo sizes.
    query = """
    MATCH (a:Account)-[r:SENT_TO]->(b:Account)
    RETURN a.id AS src, b.id AS dst, r.amount AS amount
    """
    edges: List[Tuple[str, str, float]] = []
    with neo4j_driver.session() as session:
        for record in session.run(query):
            edges.append((record["src"], record["dst"], record["amount"]))

    G = nx.DiGraph()
    for src, dst, amt in edges:
        G.add_edge(src, dst, weight=amt)

    # Louvain works on undirected graphs – we convert.
    UG = G.to_undirected()
    try:
        communities = list(nx.community.louvain_communities(UG, weight="weight", seed=42))
    except Exception as exc:
        log.error(f"Louvain clustering failed: {exc}")
        return

    # Build a mapping: node -> community_id
    node_to_cluster: Dict[str, str] = {}
    for idx, community in enumerate(communities):
        cluster_id = f"cluster_{idx}"
        for node in community:
            node_to_cluster[node] = cluster_id

    # Store a simple signature per cluster in Redis – for the demo we store
    # the list of member account IDs (could be replaced by a vector hash).
    pipeline = redis_client.pipeline()
    for idx, community in enumerate(communities):
        cluster_key = f"{MORPHIC_PREFIX}cluster_{idx}"
        signature = {
            "members": list(community),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        pipeline.set(cluster_key, json.dumps(signature))
        # Optional TTL – keep for a day (adjust as needed)
        pipeline.expire(cluster_key, 86_400)
    pipeline.execute()

    # Publish a concise update for the dashboard – only cluster IDs and sizes.
    update_msg = {
        "type": "clustering",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "clusters": [{
            "cluster_id": f"cluster_{i}",
            "size": len(c),
        } for i, c in enumerate(communities)],
    }
    publish_graph_update(update_msg)
    log.info("Clustering completed – %d clusters emitted", len(communities))

# ---------------------------------------------------------------------------
# Async background loops – one for Kafka consumption, one for periodic clustering.
# ---------------------------------------------------------------------------
async def kafka_consumer_loop():
    consumer_conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": "graph-analyzer",
        "auto.offset.reset": "earliest",
    }
    consumer = Consumer(consumer_conf)
    consumer.subscribe([ENRICHED_TOPIC])
    log.info("Subscribed to Kafka topic %s", ENRICHED_TOPIC)
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            await asyncio.sleep(0.1)
            continue
        if msg.error():
            log.error("Kafka error: %s", msg.error())
            continue
        try:
            txn = json.loads(msg.value().decode("utf-8"))
            persist_transaction(txn)
        except Exception as exc:
            log.exception("Failed to process transaction message: %s", exc)
    # consumer.close() – unreachable because loop runs forever

async def clustering_loop():
    while True:
        run_clustering()
        await asyncio.sleep(CLUSTER_INTERVAL)

# ---------------------------------------------------------------------------
# Entrypoint – run both loops concurrently.
# ---------------------------------------------------------------------------
async def main():
    await asyncio.gather(kafka_consumer_loop(), clustering_loop())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Graph analyzer stopped by user")
