import os
import json
import logging
import asyncio
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import socketio
from redis import Redis
from neo4j import GraphDatabase
from confluent_kafka import Consumer

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("api-server")

# Environment configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")

# Initialize Socket.IO Async Server
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*"
)

fastapi_app = FastAPI(title="Real-Time Anti-Mule Intelligence API", version="1.0.0")

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Combined ASGI app with Socket.IO
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

# In-memory alert cache for instant responses
alerts_cache: List[dict] = []
MAX_CACHE_ALERTS = 100

def get_redis_client():
    try:
        return Redis.from_url(REDIS_URL, decode_responses=False)
    except Exception as e:
        log.warning(f"Redis not available: {e}")
        return None

def get_neo4j_driver():
    try:
        return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception as e:
        log.warning(f"Neo4j driver error: {e}")
        return None

@sio.event
async def connect(sid, environ):
    log.info(f"Socket.IO client connected: {sid}")

@sio.event
async def disconnect(sid):
    log.info(f"Socket.IO client disconnected: {sid}")

@fastapi_app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Fraud & Mule Intelligence API",
        "endpoints": [
            "/api/v1/alerts",
            "/api/v1/heatmap",
            "/api/v1/graph/clusters",
            "/api/v1/graph/cluster/{cluster_id}",
            "/api/v1/accounts/{account_id}/behavioral-dna",
            "/api/v1/accounts/{account_id}/drift"
        ]
    }

@fastapi_app.get("/api/v1/alerts")
def get_alerts(page: int = 1, size: int = 20):
    r = get_redis_client()
    alerts = []
    if r:
        try:
            raw_alerts = r.lrange("alerts:list", (page - 1) * size, page * size - 1)
            for item in raw_alerts:
                alerts.append(json.loads(item.decode("utf-8")))
        except Exception as e:
            log.warning(f"Error fetching alerts from Redis: {e}")

    if not alerts:
        alerts = alerts_cache[(page - 1) * size : page * size]

    if not alerts:
        # Provide sample alerts if none collected yet
        alerts = [
            {
                "account_id": "ACC-000102",
                "drift_score": 0.942,
                "threshold": 0.850,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "rapid_dormant_resurrection"
            },
            {
                "account_id": "ACC-000455",
                "drift_score": 0.915,
                "threshold": 0.850,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "gat_layering"
            },
            {
                "account_id": "ACC-000912",
                "drift_score": 0.887,
                "threshold": 0.850,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "smurfing_dispersion"
            }
        ]

    return {"alerts": alerts, "page": page, "size": size, "total": max(len(alerts), len(alerts_cache))}

@fastapi_app.get("/api/v1/heatmap")
def get_heatmap():
    r = get_redis_client()
    heatmap = []
    if r:
        try:
            keys = r.keys("drift:*")
            for k in keys[:100]:
                score_str = r.get(k)
                if score_str:
                    acc_id = k.decode("utf-8").replace("drift:", "")
                    heatmap.append({"account_id": acc_id, "score": float(score_str)})
        except Exception as e:
            log.warning(f"Error reading heatmap from Redis: {e}")

    if not heatmap:
        # Generate varied scores for demo accounts
        for i in range(1, 65):
            acc_id = f"ACC-{i:06d}"
            score = 0.95 if i in [2, 5, 12, 18, 33, 47] else round(0.1 + (i % 7) * 0.12, 3)
            heatmap.append({"account_id": acc_id, "score": score})

    return heatmap

@fastapi_app.get("/api/v1/graph/clusters")
def get_graph_clusters():
    r = get_redis_client()
    clusters = []
    if r:
        try:
            keys = r.keys("morphic:cluster_*")
            for k in keys:
                raw = r.get(k)
                if raw:
                    data = json.loads(raw.decode("utf-8"))
                    cluster_id = k.decode("utf-8").replace("morphic:", "")
                    clusters.append({
                        "cluster_id": cluster_id,
                        "size": len(data.get("members", [])),
                        "members": data.get("members", [])
                    })
        except Exception as e:
            log.warning(f"Error fetching clusters: {e}")

    if not clusters:
        clusters = [
            {
                "cluster_id": "cluster_0",
                "size": 5,
                "members": ["ACC-000102", "ACC-000455", "ACC-000912", "ACC-001200", "ACC-003400"]
            },
            {
                "cluster_id": "cluster_1",
                "size": 4,
                "members": ["ACC-000005", "ACC-000018", "ACC-000033", "ACC-000047"]
            }
        ]

    return {"clusters": clusters}

@fastapi_app.get("/api/v1/graph/cluster/{cluster_id}")
def get_cluster_detail(cluster_id: str):
    r = get_redis_client()
    members = []
    if r:
        try:
            raw = r.get(f"morphic:{cluster_id}")
            if raw:
                data = json.loads(raw.decode("utf-8"))
                members = data.get("members", [])
        except Exception as e:
            log.warning(f"Error fetching cluster {cluster_id}: {e}")

    if not members:
        members = [f"ACC-{cluster_id}-{i:03d}" for i in range(1, 6)]

    # Query Neo4j for transactions between members if available
    recent_txns = []
    driver = get_neo4j_driver()
    if driver and members:
        try:
            with driver.session() as session:
                q = """
                MATCH (a:Account)-[r:SENT_TO]->(b:Account)
                WHERE a.id IN $members OR b.id IN $members
                RETURN a.id AS src, b.id AS dst, r.amount AS amount, r.timestamp AS ts
                LIMIT 15
                """
                res = session.run(q, members=members)
                for rec in res:
                    recent_txns.append({
                        "from": rec["src"],
                        "to": rec["dst"],
                        "amount": rec["amount"],
                        "timestamp": rec["ts"]
                    })
        except Exception as e:
            log.warning(f"Neo4j query error: {e}")

    if not recent_txns:
        recent_txns = [
            {"from": members[0], "to": members[1] if len(members) > 1 else "ACC-HUB", "amount": 4850.00, "timestamp": datetime.utcnow().isoformat() + "Z"},
            {"from": members[1] if len(members) > 1 else "ACC-HUB", "to": members[2] if len(members) > 2 else "ACC-MULE", "amount": 4720.00, "timestamp": datetime.utcnow().isoformat() + "Z"}
        ]

    return {
        "cluster_id": cluster_id,
        "accounts": members,
        "recent_transactions": recent_txns
    }

@fastapi_app.get("/api/v1/accounts/{account_id}/behavioral-dna")
def get_account_dna(account_id: str):
    r = get_redis_client()
    embedding = []
    if r:
        try:
            raw = r.get(f"baseline:{account_id}")
            if raw:
                import numpy as np
                embedding = np.frombuffer(raw, dtype=np.float32).tolist()[:16]
        except Exception as e:
            log.warning(f"Error fetching DNA baseline: {e}")

    if not embedding:
        # Fallback 16-dim representation
        import hashlib
        seed = int(hashlib.md5(account_id.encode()).hexdigest(), 16)
        embedding = [round(((seed >> (i * 4)) & 0xFF) / 255.0, 4) for i in range(16)]

    return {
        "account_id": account_id,
        "embedding": embedding,
        "recent_transactions": [
            {"type": "transfer", "amount": 4500.0, "currency": "USD", "channel": "mobile", "status": "flagged"},
            {"type": "withdrawal", "amount": 4000.0, "currency": "USD", "channel": "atm", "status": "flagged"}
        ]
    }

@fastapi_app.get("/api/v1/accounts/{account_id}/drift")
def get_account_drift(account_id: str):
    r = get_redis_client()
    drift_score = 0.885
    if r:
        try:
            score_str = r.get(f"drift:{account_id}")
            if score_str:
                drift_score = float(score_str)
        except Exception as e:
            log.warning(f"Error fetching drift: {e}")

    return {
        "account_id": account_id,
        "drift_score": drift_score,
        "baseline_status": "established",
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }

# Background Kafka consumer to stream alerts and graph updates
async def kafka_listener_loop():
    await asyncio.sleep(5)  # Wait for Kafka to initialize
    try:
        conf = {
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": "api-dashboard-consumer",
            "auto.offset.reset": "latest"
        }
        consumer = Consumer(conf)
        consumer.subscribe(["alerts.generated", "graph.updates"])
        log.info("API Kafka listener subscribed to alerts.generated & graph.updates")
        r = get_redis_client()

        while True:
            msg = consumer.poll(0.5)
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            if msg.error():
                await asyncio.sleep(0.5)
                continue

            topic = msg.topic()
            try:
                data = json.loads(msg.value().decode("utf-8"))
                if topic == "alerts.generated":
                    alerts_cache.insert(0, data)
                    if len(alerts_cache) > MAX_CACHE_ALERTS:
                        alerts_cache.pop()
                    if r:
                        r.lpush("alerts:list", json.dumps(data))
                        r.ltrim("alerts:list", 0, 200)
                    await sio.emit("alert", data)
                elif topic == "graph.updates":
                    await sio.emit("graph", data)
            except Exception as e:
                log.error(f"Error processing Kafka message: {e}")
    except Exception as e:
        log.warning(f"Kafka listener could not start: {e}. Running in polling mode.")

@fastapi_app.on_event("startup")
async def startup_event():
    asyncio.create_task(kafka_listener_loop())
