"""
app/main.py

MineGuard Backend API Service (§3.3, §10, §11).
Integrates:
- 17 REST endpoints for Health, Live Snapshot, Sites, Nodes, Alerts, Downlink, Provisioning, Ingest
- WebSocket /ws/live broadcasting full real-time snapshots coalesced to ≤4 Hz
- Embedded Knothe physics simulation loop feeding live frames into the ingest pipeline
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db, async_session_factory
from .hub import hub
from .broadcaster import broadcaster
from .api import router as api_router
from .auth.router import router as auth_router
from .state import build_snapshot
from .ingest import ingest_frames
from simulator.virtual_gateway import VirtualGatewayRunner


async def _simulation_worker():
    """
    Background worker that runs Knothe physics simulations and ingests frames
    periodically if SIMULATOR_ENABLED is True.
    """
    runner = VirtualGatewayRunner()
    while True:
        try:
            frames = runner.generate_batch()
            async with async_session_factory() as session:
                await ingest_frames(session, frames, site_slug="jharia", gateway_slug="gw-01")
        except Exception as e:
            print(f"[Simulator Worker Error] {e}")
        await asyncio.sleep(settings.SIMULATOR_TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Database & seed bootstrap
    await init_db()

    # 2. Start WebSocket state broadcaster
    await broadcaster.start()

    # 3. Optional MQTT bridge
    from .mqtt import start_mqtt_bridge, stop_mqtt_bridge
    await start_mqtt_bridge()

    # 4. Optional embedded physics simulator loop
    sim_task = None
    if settings.SIMULATOR_ENABLED:
        sim_task = asyncio.create_task(_simulation_worker())

    yield

    # Teardown
    if sim_task:
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass

    await stop_mqtt_bridge()
    await broadcaster.stop()


app = FastAPI(
    title="MineGuard Backend Service",
    description="AI-enabled mine subsidence monitoring & early warning backend API.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include REST endpoints
app.include_router(auth_router)
app.include_router(api_router)


# -------------------------------------------------------------------------
# WebSocket /ws/live (§5.3, §11)
# -------------------------------------------------------------------------

@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await hub.connect(websocket)

    # Immediately push full snapshot upon connect (§5.3)
    try:
        async with async_session_factory() as session:
            initial_snapshot = await build_snapshot(session)
        await websocket.send_json(initial_snapshot)
    except Exception as e:
        print(f"[WS Initial Snapshot Error] {e}")

    # Listen until client disconnects
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(websocket)
    except Exception:
        await hub.disconnect(websocket)
