"""SUBSIDENCE-NET API.

Serves the live view over REST and WebSocket, ingests gateway frames over HTTP
and (optionally) MQTT, and pushes node configuration back down to the mesh.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import broadcaster, mqtt
from .api import router
from .config import get_settings
from .db import dispose_db, get_sessionmaker, init_db
from .hub import hub
from .state import build_snapshot

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("subnet")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await broadcaster.start()
    await mqtt.start()
    log.info("SUBSIDENCE-NET API ready")
    try:
        yield
    finally:
        await mqtt.stop()
        await broadcaster.stop()
        await dispose_db()


app = FastAPI(
    title="SUBSIDENCE-NET API",
    version="1.0.0",
    summary="Mine subsidence monitoring, prediction and early warning",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    """Push the snapshot on connect, then on every change.

    The first message is a full snapshot rather than a delta, so a client that
    reconnects after a dropped link is immediately correct instead of applying
    updates to stale state -- which matters on a mine site where connectivity
    comes and goes.
    """
    await websocket.accept()
    queue = await hub.subscribe()
    try:
        async with get_sessionmaker()() as session:
            await websocket.send_json(await build_snapshot(session, settings))

        while True:
            try:
                snapshot = await asyncio.wait_for(queue.get(), timeout=25)
            except asyncio.TimeoutError:
                # Keep-alive: idle proxies drop silent WebSockets.
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(snapshot)
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover
        log.exception("websocket closed unexpectedly")
    finally:
        await hub.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "subsidence-net", "docs": "/docs", "live": "/ws/live"}
