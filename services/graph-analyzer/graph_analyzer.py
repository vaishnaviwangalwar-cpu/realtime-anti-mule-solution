#!/usr/bin/env python3
"""Graph Analyzer Service

* Consumes transactions from Kafka (topic ``transactions.raw`` or ``transactions.enriched``).
* Persists accounts and transaction relationships in Neo4j.
* Periodically (default every 15 s) builds an in‑memory NetworkX graph from Neo4j and runs Louvain community detection.
* For each discovered community ("cluster") it stores a morphic memory signature in Redis.
* Publishes cluster summary to Kafka topic ``graph.updates`` for real-time dashboard display.
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
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
INPUT_TOPICS = [os.getenv("INPUT_TOPIC", "transactions.raw"), "transactions.enriched"]
GRAPH_UPDATES_TOPIC = "graph.updates"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

CLUSTER_INTERVAL = int(os.getenv("CLUSTERING_INTERVAL", "15"))
MORPHIC_PREFIX = "morphic:"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
log = logging.getLogger("graph-analyzer")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
log.addHandler(handler)

def get_redis_client():
    try:
        return Redis.from_url(REDIS_URL)
    except Exception as e:
        log.warning(f"Redis connection error: {e}")
        return None

def get_neo4j_driver():
    try:
        return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception as e:
        log.warning(f"Neo4j driver error: {e}")
        return None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def persist_transaction(driver, txn: dict):
    sender = txn.get("account_id")
    receiver = txn.get("counterparty_id")
    if not sender or not receiver or sender == receiver:
        return
    ts = txn.get("timestamp", datetime.utcnow().isoformat() + "Z")
    amount = float(txn.get("amount", 0.0))
    try:
        with driver.session() as session:
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
    except Exception as e:
        log.warning(f"Failed to persist transaction to Neo4j: {e}")

def run_clustering(driver, redis_client, producer):
    if not driver:
        return
    log.info("Running Louvain community clustering on Neo4j transaction graph...")
    query = """
    MATCH (a:Account)-[r:SENT_TO]->(b:Account)
    RETURN a.id AS src, b.id AS dst, r.amount AS amount
    LIMIT 1000
    """
    edges: List[Tuple[str, str, float]] = []
    try:
        with driver.session() as session:
            for record in session.run(query):
                edges.append((record["src"], record["dst"], float(record["amount"])))
    except Exception as exc:
        log.error(f"Error querying Neo4j for clustering: {exc}")
        return

    if not edges:
        log.info("No transaction edges found yet for clustering")
        return

    G = nx.DiGraph()
    for src, dst, amt in edges:
        G.add_edge(src, dst, weight=amt)

    UG = G.to_undirected()
    try:
        communities = list(nx.community.louvain_communities(UG, weight="weight", seed=42))
    except Exception as exc:
        log.error(f"Louvain clustering failed: {exc}")
        return

    if redis_client:
        try:
            pipeline = redis_client.pipeline()
            for idx, community in enumerate(communities):
                cluster_key = f"{MORPHIC_PREFIX}cluster_{idx}"
                signature = {
                    "members": list(community),
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
                pipeline.set(cluster_key, json.dumps(signature))
                pipeline.expire(cluster_key, 86_400)
            pipeline.execute()
        except Exception as e:
            log.warning(f"Redis pipeline error in clustering: {e}")

    update_msg = {
        "type": "clustering",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "clusters": [{
            "cluster_id": f"cluster_{i}",
            "size": len(c),
            "members": list(c)[:10]
        } for i, c in enumerate(communities)],
    }
    if producer:
        try:
            producer.produce(GRAPH_UPDATES_TOPIC, json.dumps(update_msg).encode("utf-8"))
            producer.poll(0)
        except Exception as exc:
            log.error(f"Failed to publish graph update: {exc}")

    log.info("Clustering completed – %d clusters detected and saved", len(communities))

# ---------------------------------------------------------------------------
# Background loops
# ---------------------------------------------------------------------------
async def kafka_consumer_loop(driver):
    await asyncio.sleep(5)
    consumer_conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": "graph-analyzer-group",
        "auto.offset.reset": "earliest",
    }
    try:
        consumer = Consumer(consumer_conf)
        consumer.subscribe(INPUT_TOPICS)
        log.info("Graph Analyzer subscribed to Kafka topics: %s", INPUT_TOPICS)
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                await asyncio.sleep(0.05)
                continue
            if msg.error():
                await asyncio.sleep(0.5)
                continue
            try:
                txn = json.loads(msg.value().decode("utf-8"))
                persist_transaction(driver, txn)
            except Exception as exc:
                log.exception("Failed to process transaction: %s", exc)
    except Exception as e:
        log.error(f"Kafka consumer error in graph analyzer: {e}")

async def clustering_loop(driver, redis_client, producer):
    await asyncio.sleep(10)
    while True:
        try:
            run_clustering(driver, redis_client, producer)
        except Exception as e:
            log.error(f"Clustering loop iteration error: {e}")
        await asyncio.sleep(CLUSTER_INTERVAL)

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
async def main():
    driver = get_neo4j_driver()
    redis_client = get_redis_client()
    try:
        producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})
    except Exception:
        producer = None

    await asyncio.gather(
        kafka_consumer_loop(driver),
        clustering_loop(driver, redis_client, producer)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Graph analyzer stopped by user")
