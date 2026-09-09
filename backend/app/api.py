"""REST surface consumed by the web dashboard and the Android app."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from subnet_proto import Config

from . import broadcaster
from .config import Settings, get_settings
from .db import session_dep
from .ingest import ingest_frames
from .risk import corrected_tilt_mdeg
from .models import alerts as alerts_t
from .models import node_configs, nodes as nodes_t, sites as sites_t, telemetry
from .state import build_snapshot

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(session_dep)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

#: Sample counts behind each range tab, at one sample per 15 simulated minutes.
RANGE_POINTS = {"1H": 4, "6H": 24, "24H": 96, "7D": 672}


# --------------------------------------------------------------------- health
@router.get("/health")
async def health(session: SessionDep) -> dict[str, Any]:
    await session.execute(sa.text("SELECT 1"))
    return {
        "status": "ok",
        "dialect": session.bind.dialect.name,
        "time": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------ snapshot
@router.get("/snapshot")
async def snapshot(session: SessionDep, settings: SettingsDep,
                   site: str | None = None) -> dict[str, Any]:
    """The whole live view in one document -- the same shape the WebSocket pushes."""
    return await build_snapshot(session, settings, site)


# --------------------------------------------------------------------- sites
@router.get("/sites")
async def list_sites(session: SessionDep) -> list[dict[str, Any]]:
    rows = (await session.execute(sa.select(sites_t))).mappings().all()
    return [dict(r) for r in rows]


class FaceUpdate(BaseModel):
    face_x_m: float = Field(ge=0, description="Where the working face has reached")


@router.patch("/sites/{slug}/face")
async def update_face(slug: str, body: FaceUpdate, session: SessionDep) -> dict[str, Any]:
    """Operator input: advancing the face re-drives the deformation model."""
    result = await session.execute(
        sites_t.update().where(sites_t.c.slug == slug).values(face_x_m=body.face_x_m))
    if result.rowcount == 0:
        raise HTTPException(404, f"no site {slug!r}")
    await session.commit()
    broadcaster.mark_dirty()
    return {"slug": slug, "face_x_m": body.face_x_m}


# --------------------------------------------------------------------- nodes
@router.get("/nodes")
async def list_nodes(session: SessionDep) -> list[dict[str, Any]]:
    rows = (await session.execute(
        sa.select(nodes_t).order_by(nodes_t.c.addr))).mappings().all()
    return [dict(r) for r in rows]


class NodePlacement(BaseModel):
    """Where an operator dropped the pin, plus what to call it."""

    label: str | None = None
    zone: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    x_m: float | None = None
    y_m: float | None = None


@router.patch("/nodes/{addr}")
async def place_node(addr: int, body: NodePlacement, session: SessionDep) -> dict[str, Any]:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if not values:
        raise HTTPException(400, "no fields to update")
    result = await session.execute(
        nodes_t.update().where(nodes_t.c.addr == addr).values(**values))
    if result.rowcount == 0:
        raise HTTPException(404, f"no node 0x{addr:04X}")
    await session.commit()
    broadcaster.mark_dirty()
    return {"addr": addr, **values}


@router.post("/nodes/{addr}/recalibrate")
async def recalibrate(addr: int, session: SessionDep) -> dict[str, Any]:
    """Re-zero a node against its current attitude.

    For use after a node is legitimately disturbed -- re-planted, knocked by
    plant, re-levelled. It clears the commissioning baseline so the next frame
    establishes a new one, which is the only correct way to resume: without it
    the node reports the disturbance as ground movement forever.
    """
    result = await session.execute(
        nodes_t.update().where(nodes_t.c.addr == addr)
        .values(baseline_pitch_mdeg=None, baseline_roll_mdeg=None,
                baseline_temp_c_x100=None))
    if result.rowcount == 0:
        raise HTTPException(404, f"no node 0x{addr:04X}")
    await session.commit()
    return {"addr": addr, "baseline": "cleared -- next frame re-establishes it"}


# ----------------------------------------------------------------- telemetry
@router.get("/nodes/{addr}/history")
async def node_history(addr: int, session: SessionDep, settings: SettingsDep,
                       range: str = Query("24H", pattern="^(1H|6H|24H|7D)$")) -> list[dict]:
    node = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.addr == addr))).mappings().first()
    if node is None:
        raise HTTPException(404, f"no node 0x{addr:04X}")

    # Plot deformation, not attitude. Nodes are hand-planted on uneven ground, so
    # raw pitch and roll mostly describe how the post was hammered in -- and a
    # chart of that would disagree with the gauges, which are baseline-corrected.
    base_pitch = node["baseline_pitch_mdeg"] or 0
    base_roll = node["baseline_roll_mdeg"] or 0
    base_temp = (node["baseline_temp_c_x100"] or 0) / 100.0

    limit = RANGE_POINTS[range]
    rows = (await session.execute(
        sa.select(telemetry.c.time, telemetry.c.pitch_mdeg, telemetry.c.roll_mdeg,
                  telemetry.c.vib_rms_mg, telemetry.c.temp_c_x100)
        .where(telemetry.c.node_id == node["id"])
        .order_by(telemetry.c.time.desc()).limit(limit)
    )).mappings().all()

    # Plotted temperature-corrected, for the same reason it is plotted
    # baseline-corrected: an uncorrected trace shows the daily thermal swing of
    # the post, which is larger than the movement being looked for and would
    # make every chart look like a sine wave with the signal buried in it.
    drift = settings.tilt_drift_mdeg_per_c
    out = []
    for r in reversed(rows):   # oldest first, as the chart expects
        t = r["time"]
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        temp = (r["temp_c_x100"] or 0) / 100.0
        out.append({
            "t": int(t.timestamp() * 1000),
            "pitch": corrected_tilt_mdeg(r["pitch_mdeg"] or 0, base_pitch,
                                         temp, base_temp, drift) / 1000.0,
            "roll": corrected_tilt_mdeg(r["roll_mdeg"] or 0, base_roll,
                                        temp, base_temp, drift) / 1000.0,
            "vib": r["vib_rms_mg"] or 0,
            "tempC": temp,
        })
    return out


# -------------------------------------------------------------------- alerts
@router.get("/alerts")
async def list_alerts(session: SessionDep, state: str | None = None,
                      limit: int = Query(50, le=500)) -> list[dict[str, Any]]:
    stmt = sa.select(alerts_t).order_by(alerts_t.c.raised_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(alerts_t.c.state == state)
    return [dict(r) for r in (await session.execute(stmt)).mappings().all()]


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: int, session: SessionDep,
                    by: str = Body("operator", embed=True)) -> dict[str, Any]:
    result = await session.execute(
        alerts_t.update().where(alerts_t.c.id == alert_id)
        .values(state="acked", acked_by=by, acked_at=datetime.now(timezone.utc)))
    if result.rowcount == 0:
        raise HTTPException(404, "no such alert")
    await session.commit()
    broadcaster.mark_dirty()
    return {"id": alert_id, "state": "acked"}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int, session: SessionDep) -> dict[str, Any]:
    result = await session.execute(
        alerts_t.update().where(alerts_t.c.id == alert_id)
        .values(state="resolved", resolved_at=datetime.now(timezone.utc)))
    if result.rowcount == 0:
        raise HTTPException(404, "no such alert")
    await session.commit()
    broadcaster.mark_dirty()
    return {"id": alert_id, "state": "resolved"}


# ------------------------------------------------------- node configuration
class ConfigPush(BaseModel):
    """Remote reconfiguration, as pushed from the dashboard's node admin panel."""

    sample_interval_s: int = Field(60, ge=5, le=3600)
    wor_period_ms: int = Field(2000, ge=250, le=10000)
    tx_power_dbm: int = Field(22, ge=10, le=22)
    tilt_alert_mdeg: int = Field(2000, ge=10, le=32000)
    vib_alert_mg: int = Field(500, ge=10, le=60000)
    tilt_rate_alert_mdeg_h: int = Field(150, ge=1, le=60000)
    tilt_offset_pitch: int = Field(0, ge=-32768, le=32767)
    tilt_offset_roll: int = Field(0, ge=-32768, le=32767)
    flags: int = Field(15, ge=0, le=255)
    created_by: str = "operator"


@router.get("/nodes/{addr}/config")
async def get_config(addr: int, session: SessionDep) -> list[dict[str, Any]]:
    node = (await session.execute(
        sa.select(nodes_t.c.id).where(nodes_t.c.addr == addr))).scalar_one_or_none()
    if node is None:
        raise HTTPException(404, f"no node 0x{addr:04X}")
    rows = (await session.execute(
        sa.select(node_configs).where(node_configs.c.node_id == node)
        .order_by(node_configs.c.cfg_version.desc()).limit(10))).mappings().all()
    return [dict(r) for r in rows]


@router.post("/nodes/{addr}/config", status_code=201)
async def push_config(addr: int, body: ConfigPush, session: SessionDep) -> dict[str, Any]:
    """Queue a configuration downlink.

    The row is created 'pending' and only becomes 'applied' when the node's ACK
    echoes the same config hash. That round trip is the whole point: a downlink
    that never reached a sleeping node must be visible as such, not assumed.
    """
    node = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.addr == addr))).mappings().first()
    if node is None:
        raise HTTPException(404, f"no node 0x{addr:04X}")

    current = (await session.execute(
        sa.select(sa.func.max(node_configs.c.cfg_version))
        .where(node_configs.c.node_id == node["id"]))).scalar() or 0
    version = current + 1

    # Hash with the same codec the node will verify against.
    frame_cfg = Config(cfg_version=version, **body.model_dump(exclude={"created_by"}))
    cfg_hash = frame_cfg.compute_hash()

    await session.execute(node_configs.insert().values(
        node_id=node["id"], cfg_version=version, cfg_hash=cfg_hash,
        status="pending", created_by=body.created_by,
        **body.model_dump(exclude={"created_by"}),
    ))
    await session.commit()

    from .mqtt import publish_downlink   # imported late: MQTT is optional
    delivered = await publish_downlink(addr, frame_cfg)

    return {
        "addr": addr, "cfg_version": version, "cfg_hash": cfg_hash,
        "status": "sent" if delivered else "pending",
        "transport": "mqtt" if delivered else "queued (no broker configured)",
    }


# ---------------------------------------------------------------- provision
class NodeSpecIn(BaseModel):
    addr: int = Field(ge=1, le=0xFFFE)
    label: str
    zone: str | None = None
    lat: float | None = None
    lon: float | None = None
    x_m: float | None = None
    y_m: float | None = None
    # Commissioning survey: the node's attitude on undisturbed ground, before
    # the face arrived. Deformation is measured against this, so supplying it
    # explicitly is how a real commissioning record enters the system.
    baseline_pitch_mdeg: int | None = None
    baseline_roll_mdeg: int | None = None
    #: The temperature the survey was taken at. Drift is only removable relative
    #: to a known reference, so a baseline without one is only half a baseline.
    baseline_temp_c_x100: int | None = None


class ProvisionRequest(BaseModel):
    """Commissioning payload: the panel and the nodes planted over it.

    Idempotent, so re-running a commissioning script is safe and a gateway can
    re-announce its field after a rebuild without duplicating anything.
    """

    slug: str
    name: str
    coalfield: str | None = None
    origin_lat: float
    origin_lon: float
    seam_depth_m: float = 150
    extraction_thickness_m: float = 3.0
    subsidence_factor: float = 0.65
    angle_of_draw_deg: float = 35
    face_x_m: float = 0
    face_advance_m_per_day: float = 12
    panel_x_start: float = 0
    panel_x_end: float = 600
    panel_y_min: float = -200
    panel_y_max: float = 200
    nodes: list[NodeSpecIn] = Field(default_factory=list)


@router.post("/provision", status_code=201)
async def provision(body: ProvisionRequest, session: SessionDep) -> dict[str, Any]:
    site_values = body.model_dump(exclude={"nodes"})
    existing = (await session.execute(
        sa.select(sites_t).where(sites_t.c.slug == body.slug))).mappings().first()
    if existing:
        await session.execute(
            sites_t.update().where(sites_t.c.id == existing["id"]).values(**site_values))
        site_id = existing["id"]
    else:
        site_id = (await session.execute(
            sites_t.insert().values(**site_values).returning(sites_t.c.id))).scalar_one()

    created = updated = 0
    for spec in body.nodes:
        values = spec.model_dump()
        found = (await session.execute(
            sa.select(nodes_t.c.id)
            .where(nodes_t.c.site_id == site_id, nodes_t.c.addr == spec.addr)
        )).scalar_one_or_none()
        if found is None:
            await session.execute(nodes_t.insert().values(site_id=site_id, **values))
            created += 1
        else:
            await session.execute(
                nodes_t.update().where(nodes_t.c.id == found)
                .values(**{k: v for k, v in values.items() if k != "addr"}))
            updated += 1

    await session.commit()
    broadcaster.mark_dirty()
    return {"site": body.slug, "siteId": site_id, "nodesCreated": created,
            "nodesUpdated": updated}


# -------------------------------------------------------------------- ingest
class FrameBatch(BaseModel):
    """Uplink from a gateway. Frames are raw protocol bytes, base64 encoded."""

    frames: list[str] = Field(min_length=1, max_length=256)
    gateway: str | None = None
    site: str | None = None


@router.post("/ingest")
async def ingest(body: FrameBatch, session: SessionDep,
                 settings: SettingsDep) -> dict[str, Any]:
    try:
        raw = [base64.b64decode(f, validate=True) for f in body.frames]
    except Exception as exc:
        raise HTTPException(400, f"frames must be base64: {exc}") from exc

    result = await ingest_frames(session, settings, raw, site_slug=body.site)
    if result.accepted:
        broadcaster.mark_dirty()
    return result.as_dict()


# ------------------------------------------------------------------- stats
@router.get("/stats")
async def stats(session: SessionDep) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    frames = (await session.execute(
        sa.select(sa.func.count()).select_from(telemetry)
        .where(telemetry.c.time >= since))).scalar() or 0
    total = (await session.execute(
        sa.select(sa.func.count()).select_from(telemetry))).scalar() or 0
    return {"framesLast24h": frames, "framesTotal": total}
