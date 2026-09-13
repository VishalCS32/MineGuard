"""SUBSIDENCE-NET telemetry receiver -- one file, two dependencies.

Takes the JSON a field gateway pushes, stores it in a SQLite file, and serves
it back both as JSON and as a flat CSV table that pandas can read straight
off the URL.

Run it:      uvicorn app:app --host 0.0.0.0 --port 8020
Deploy it:   the same command, anywhere that runs Python.

Why SQLite and the standard library: this has to run on a laptop next to the
gateway, on a free container, and on whatever the demo machine turns out to
be, without anyone installing a database first. One file, one dependency that
matters, nothing to configure.

The handlers are plain `def`, not `async def`. SQLite is blocking, and a
blocking call inside an async handler stalls every other request on the
server -- FastAPI runs sync handlers in a thread pool instead, which is
exactly right here and costs nothing at this volume.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

DB_PATH = os.getenv("DB_PATH", "telemetry.db")
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "").strip()
MAX_BATCH = 500

app = FastAPI(title="MineGuard telemetry receiver", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# One flat table. Every field the gateway can send gets its own column, so
# `pandas.read_csv(".../readings.csv")` is a usable dataframe with no
# unpacking -- which is the whole point of keeping it flat rather than
# storing documents and making the ML side dig them out.
COLUMNS = [
    "node_id", "ts", "received_at",
    "gyro_x", "gyro_y", "gyro_z",
    "accel_x", "accel_y", "accel_z",
    "roll_deg", "pitch_deg",
    "vib_x", "vib_y", "vib_z", "vib_rms",
    "temperature_c", "battery_mv",
    "latitude", "longitude", "altitude", "satellites", "hdop",
    "rssi_dbm", "snr_db", "flags",
]

_lock = threading.Lock()


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    cols = ",\n  ".join(f"{c} {'TEXT' if c in ('node_id','ts','received_at') else 'REAL'}"
                        for c in COLUMNS)
    with db() as c:
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS readings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              {cols},
              raw TEXT NOT NULL
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_node_id ON readings(node_id, id)")
        # WAL so a reader -- a dashboard polling, or a training job pulling
        # the whole table -- never blocks the gateway writing.
        c.execute("PRAGMA journal_mode=WAL")


init()


def check_token(authorization: str | None) -> None:
    """Bearer token on writes only; reads stay open so a dashboard just works.

    Unset means open, which is right on a laptop and wrong on the internet:
    an unauthenticated ingest endpoint is a database anyone can fill, and
    fabricated telemetry is worse than none because it still draws a line.
    """
    if INGEST_TOKEN and authorization != f"Bearer {INGEST_TOKEN}":
        raise HTTPException(401, "bad or missing ingest token")


def num(v: Any) -> float | None:
    """Anything unparseable becomes NULL rather than an error.

    A node that cannot measure something sends null, and one odd field must
    never cost the whole reading -- this receives from hardware that is
    partly broken, in a field, at night.
    """
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def flatten(d: dict) -> dict[str, Any]:
    s = d.get("sensor_data") or {}
    g = s.get("gyro") or {}
    a = s.get("accelerometer") or {}
    o = s.get("orientation") or {}
    v = s.get("vibration") or {}
    p = d.get("gps") or {}
    c = d.get("communication") or {}
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "node_id": str(d["node_id"])[:64],
        # The node's own clock if it had one, else arrival. Kept apart from
        # received_at on purpose: the gap between them is how you spot a
        # gateway draining a spool after an outage.
        "ts": d.get("timestamp") or now,
        "received_at": now,
        "gyro_x": num(g.get("x")), "gyro_y": num(g.get("y")), "gyro_z": num(g.get("z")),
        "accel_x": num(a.get("x")), "accel_y": num(a.get("y")), "accel_z": num(a.get("z")),
        "roll_deg": num(o.get("roll")), "pitch_deg": num(o.get("pitch")),
        "vib_x": num(v.get("x")), "vib_y": num(v.get("y")), "vib_z": num(v.get("z")),
        "vib_rms": num(v.get("rms")),
        "temperature_c": num(s.get("temperature_c")),
        "battery_mv": num(s.get("battery_mv")),
        "latitude": num(p.get("latitude")), "longitude": num(p.get("longitude")),
        "altitude": num(p.get("altitude")), "satellites": num(p.get("satellites")),
        "hdop": num(p.get("hdop")),
        "rssi_dbm": num(c.get("rssi_dbm")), "snr_db": num(c.get("snr_db")),
        "flags": num(d.get("flags")) or 0,
    }


# ------------------------------------------------------------------ write
@app.post("/api/v1/telemetry", status_code=202)
def ingest(body: Any = Body(...),
           authorization: str | None = Header(default=None)) -> dict:
    """One reading, or a list of them.

    A batch matters: a gateway coming back from an outage has a spool to
    drain, and one POST per reading would take longer than the outage did.
    """
    check_token(authorization)
    docs = body if isinstance(body, list) else [body]
    if not docs:
        return {"accepted": 0}
    if len(docs) > MAX_BATCH:
        raise HTTPException(413, f"at most {MAX_BATCH} readings per request")
    for d in docs:
        if not isinstance(d, dict) or not d.get("node_id"):
            raise HTTPException(422, "every reading needs a node_id")

    rows = [(flatten(d), json.dumps(d)) for d in docs]
    sql = (f"INSERT INTO readings ({','.join(COLUMNS)},raw) "
           f"VALUES ({','.join('?' * len(COLUMNS))},?)")
    with _lock, db() as c:
        c.executemany(sql, [tuple(f[k] for k in COLUMNS) + (raw,) for f, raw in rows])
    return {"accepted": len(docs)}


# ------------------------------------------------------------------- read
@app.get("/health")
def health() -> dict:
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    return {"status": "ok", "readings": n, "db": DB_PATH,
            "auth": "token" if INGEST_TOKEN else "open",
            "time": datetime.now(tz=timezone.utc).isoformat()}


@app.get("/api/v1/nodes")
def nodes() -> list[dict]:
    """Every node, with its latest reading."""
    with db() as c:
        rows = c.execute(
            "SELECT r.* FROM readings r JOIN "
            "(SELECT node_id, MAX(id) m FROM readings GROUP BY node_id) t "
            "ON r.id = t.m ORDER BY r.node_id").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/v1/nodes/{node_id}/latest")
def latest(node_id: str) -> dict:
    with db() as c:
        r = c.execute("SELECT * FROM readings WHERE node_id=? ORDER BY id DESC LIMIT 1",
                      (node_id,)).fetchone()
    if r is None:
        raise HTTPException(404, f"no readings for {node_id!r}")
    return dict(r)


def _select(node_id: str | None, since_id: int, limit: int) -> list[sqlite3.Row]:
    q = "SELECT * FROM readings WHERE id > ?"
    args: list[Any] = [since_id]
    if node_id:
        q += " AND node_id = ?"
        args.append(node_id)
    q += " ORDER BY id LIMIT ?"
    args.append(limit)
    with db() as c:
        return c.execute(q, args).fetchall()


@app.get("/api/v1/readings")
def readings(node_id: str | None = None,
             since_id: int = Query(0, ge=0),
             limit: int = Query(1000, ge=1, le=50000)) -> list[dict]:
    """Flat rows, oldest first, for a dashboard or a training set.

    `since_id` is the cursor: keep the largest `id` you have seen and ask for
    what came after it. Cheaper and more reliable than paging by timestamp,
    which repeats or skips rows whenever two readings share a second -- and
    at a five-second interval across twenty-one nodes, they do.
    """
    return [dict(r) for r in _select(node_id, since_id, limit)]


@app.get("/api/v1/readings.csv")
def readings_csv(node_id: str | None = None,
                 since_id: int = Query(0, ge=0),
                 limit: int = Query(50000, ge=1, le=500000)) -> StreamingResponse:
    """The same rows as CSV, so the ML side is one line:

        df = pandas.read_csv("http://host:8020/api/v1/readings.csv")
    """
    rows = _select(node_id, since_id, limit)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id"] + COLUMNS)
    for r in rows:
        w.writerow([r["id"]] + [r[c] for c in COLUMNS])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      'attachment; filename="readings.csv"'})
