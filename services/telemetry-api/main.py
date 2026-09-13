"""SUBSIDENCE-NET telemetry receiver.

Accepts the decoded documents a field gateway pushes, stores them, serves
them back, and broadcasts them live to any dashboard that is watching.

Deliberately separate from `backend/`, which is the system of record and
speaks raw protocol frames. This one takes JSON from anything that can POST,
holds no opinion about the codec, and is safe to expose on the public
internet -- which the frame ingest is not.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from db import dispose_db, init_db, readings, session_factory
from models import Reading

log = logging.getLogger("telemetry")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

INGEST_TOKEN = os.getenv("INGEST_TOKEN", "").strip()
MAX_BATCH = 200


# ----------------------------------------------------------------- auth
def require_token(authorization: str | None = Header(default=None)) -> None:
    """Bearer token on the write path only.

    Reads stay open because a dashboard is the point of this service. Writes
    do not, because an unauthenticated ingest endpoint on the public internet
    is a database anyone can fill -- and telemetry nobody can trust is worse
    than no telemetry, since it still draws a line on a chart.

    Unset means open, so a bench deployment needs no ceremony. The startup
    log says so loudly, because "I forgot" is the normal way this ends up
    open in production.
    """
    if not INGEST_TOKEN:
        return
    expected = f"Bearer {INGEST_TOKEN}"
    if authorization != expected:
        raise HTTPException(401, "bad or missing ingest token")


# ------------------------------------------------------------ live fan-out
class Hub:
    """Every connected dashboard, and a fire-and-forget broadcast.

    A slow or dead socket must never hold up ingest -- the gateway is on a
    2G-era budget and will not wait -- so a send that fails just drops the
    listener.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def leave(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def publish(self, doc: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._clients)
        for ws in targets:
            try:
                await ws.send_json(doc)
            except Exception:
                await self.leave(ws)


hub = Hub()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if not INGEST_TOKEN:
        log.warning("INGEST_TOKEN is unset -- POST /api/v1/telemetry is OPEN. "
                    "Set it before this is reachable from the internet.")
    yield
    await dispose_db()


app = FastAPI(title="SUBSIDENCE-NET telemetry receiver", version="1.0.0",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.getenv("CORS_ORIGINS", "*").split(",") if o],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _row(doc: Reading) -> dict[str, Any]:
    sd, gps, comm = doc.sensor_data, doc.gps, doc.communication
    now = datetime.now(tz=timezone.utc)
    return {
        "node_id": doc.node_id,
        # A document with no timestamp is stamped on arrival rather than
        # rejected: the reading is good, only its clock is missing.
        "ts": doc.timestamp or now,
        "received_at": now,
        "roll_deg": sd.orientation.roll,
        "pitch_deg": sd.orientation.pitch,
        "vib_rms": sd.vibration.rms,
        "temperature_c": sd.temperature_c,
        "battery_mv": sd.battery_mv,
        "latitude": gps.latitude,
        "longitude": gps.longitude,
        "altitude": gps.altitude,
        "satellites": gps.satellites,
        "rssi_dbm": comm.rssi_dbm,
        "snr_db": comm.snr_db,
        "flags": doc.flags,
        "raw": doc.model_dump(mode="json"),
    }


# --------------------------------------------------------------- ingest
@app.post("/api/v1/telemetry", status_code=202,
          dependencies=[Depends(require_token)])
async def ingest(body: Reading | list[Reading]) -> dict[str, Any]:
    """One reading, or a batch.

    A batch is accepted because a gateway coming back from an outage has a
    spool to drain and one POST per reading would take longer than the outage
    did.
    """
    docs = body if isinstance(body, list) else [body]
    if not docs:
        return {"accepted": 0}
    if len(docs) > MAX_BATCH:
        raise HTTPException(413, f"at most {MAX_BATCH} readings per request")

    rows = [_row(d) for d in docs]
    async with session_factory()() as s:
        await s.execute(sa.insert(readings), rows)
        await s.commit()

    for d in docs:
        await hub.publish(d.model_dump(mode="json"))

    log.info("accepted %d reading(s) from %s", len(docs),
             ", ".join(sorted({d.node_id for d in docs})))
    return {"accepted": len(docs)}


# ---------------------------------------------------------------- reads
@app.get("/health")
async def health() -> dict[str, Any]:
    async with session_factory()() as s:
        await s.execute(sa.text("SELECT 1"))
        n = (await s.execute(sa.select(sa.func.count()).select_from(readings))).scalar_one()
    return {"status": "ok", "readings": n,
            "time": datetime.now(tz=timezone.utc).isoformat(),
            "auth": "token" if INGEST_TOKEN else "open"}


@app.get("/api/v1/nodes")
async def list_nodes() -> list[dict[str, Any]]:
    """Every node, with its most recent reading."""
    async with session_factory()() as s:
        newest = (
            sa.select(readings.c.node_id,
                      sa.func.max(readings.c.id).label("id"))
            .group_by(readings.c.node_id).subquery()
        )
        rows = (await s.execute(
            sa.select(readings).join(newest, readings.c.id == newest.c.id)
            .order_by(readings.c.node_id)
        )).mappings().all()
    return [_public(r) for r in rows]


@app.get("/api/v1/nodes/{node_id}/latest")
async def latest(node_id: str) -> dict[str, Any]:
    async with session_factory()() as s:
        row = (await s.execute(
            sa.select(readings).where(readings.c.node_id == node_id)
            .order_by(readings.c.id.desc()).limit(1)
        )).mappings().first()
    if row is None:
        raise HTTPException(404, f"no readings for {node_id!r}")
    return _public(row)


@app.get("/api/v1/nodes/{node_id}/history")
async def history(node_id: str,
                  limit: int = Query(200, ge=1, le=5000)) -> list[dict[str, Any]]:
    """Oldest first, as a chart wants it."""
    async with session_factory()() as s:
        rows = (await s.execute(
            sa.select(readings).where(readings.c.node_id == node_id)
            .order_by(readings.c.id.desc()).limit(limit)
        )).mappings().all()
    return [_public(r) for r in reversed(rows)]


def _public(r: sa.RowMapping) -> dict[str, Any]:
    d = dict(r)
    d.pop("id", None)
    for k in ("ts", "received_at"):
        if isinstance(d.get(k), datetime):
            v = d[k]
            d[k] = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return d


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    """Every reading, as it arrives."""
    await hub.join(sock)
    try:
        while True:
            await sock.receive_text()   # clients need send nothing; this parks
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(sock)
