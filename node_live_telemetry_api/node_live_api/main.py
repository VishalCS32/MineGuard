import asyncio
import math
import random
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Node Live Telemetry API",
    version="1.0.0",
    description="Simulated real-time sensor API for a mobile app and web dashboard."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock this down to your app/dashboard domains in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NODE_ID = "NODE-001"
clients: set[WebSocket] = set()
start_time = asyncio.get_event_loop_policy().get_event_loop().time()


def clamp(value, low, high):
    return max(low, min(high, value))


def simulated_data():
    # Smooth signals + small noise make the stream look like realistic sensor data.
    t = asyncio.get_event_loop_policy().get_event_loop().time() - start_time

    roll = 0.55 * math.sin(t * 0.35) + random.gauss(0, 0.04)
    pitch = 0.45 * math.sin(t * 0.27 + 1.2) + random.gauss(0, 0.035)

    gyro = {
        "x": round(0.02 * math.sin(t * 1.7) + random.gauss(0, 0.006), 4),
        "y": round(0.018 * math.cos(t * 1.3) + random.gauss(0, 0.006), 4),
        "z": round(0.009 * math.sin(t * 1.9) + random.gauss(0, 0.004), 4),
    }

    accel = {
        "x": round(0.18 * math.sin(t * 0.8) + random.gauss(0, 0.025), 4),
        "y": round(0.15 * math.cos(t * 0.7) + random.gauss(0, 0.025), 4),
        "z": round(9.806 + 0.05 * math.sin(t * 0.9) + random.gauss(0, 0.015), 4),
    }

    vibration = {
        "x": round(abs(0.065 + 0.018 * math.sin(t * 1.2) + random.gauss(0, 0.012)), 4),
        "y": round(abs(0.058 + 0.015 * math.cos(t * 1.4) + random.gauss(0, 0.010)), 4),
        "z": round(abs(0.095 + 0.025 * math.sin(t * 1.05) + random.gauss(0, 0.016)), 4),
    }
    vibration["rms"] = round(
        math.sqrt((vibration["x"]**2 + vibration["y"]**2 + vibration["z"]**2) / 3),
        4
    )

    # Simulated stationary GPS around New Delhi with tiny drift.
    latitude = 28.613900 + 0.000020 * math.sin(t / 8) + random.gauss(0, 0.000003)
    longitude = 77.209000 + 0.000025 * math.cos(t / 9) + random.gauss(0, 0.000003)

    anomaly_score = round(
        clamp(
            0.08
            + vibration["rms"] * 0.35
            + abs(roll) * 0.015
            + abs(pitch) * 0.015
            + random.gauss(0, 0.012),
            0.0,
            1.0
        ),
        3
    )

    condition = (
        "critical" if anomaly_score >= 0.80
        else "warning" if anomaly_score >= 0.45
        else "normal"
    )

    return {
        "node_id": NODE_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "gyro": gyro,
        "accel": accel,
        "orientation": {
            "roll": round(roll, 3),
            "pitch": round(pitch, 3),
        },
        "vibration": vibration,
        "gps": {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "altitude": round(215.42 + 0.35 * math.sin(t / 5) + random.gauss(0, 0.04), 2),
            "satellites": random.randint(13, 16),
            "hdop": round(clamp(0.82 + random.gauss(0, 0.08), 0.55, 1.25), 2),
        },
        "ml": {
            "condition": condition,
            "anomaly": anomaly_score >= 0.45,
            "anomaly_score": anomaly_score,
        },
    }


@app.get("/")
async def root():
    return {
        "service": "Node Live Telemetry API",
        "status": "online",
        "node_id": NODE_ID,
        "rest_endpoint": "/api/v1/nodes/NODE-001/latest",
        "websocket_endpoint": "/ws/NODE-001",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/v1/nodes/{node_id}/latest")
async def latest(node_id: str):
    if node_id != NODE_ID:
        return {"error": "node_not_found", "node_id": node_id}
    return simulated_data()


@app.websocket("/ws/{node_id}")
async def websocket_endpoint(websocket: WebSocket, node_id: str):
    if node_id != NODE_ID:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    clients.add(websocket)

    try:
        while True:
            data = simulated_data()
            await websocket.send_json(data)
            await asyncio.sleep(1.0)  # 1 Hz live telemetry
    except WebSocketDisconnect:
        clients.discard(websocket)
    except Exception:
        clients.discard(websocket)
        try:
            await websocket.close()
        except Exception:
            pass
