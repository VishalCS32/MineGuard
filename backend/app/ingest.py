"""Frame ingest: radio bytes in, stored telemetry and alerts out.

Every uplink -- whether it arrived over MQTT from a real gateway or over HTTP
from the simulator -- lands here as raw protocol bytes and is decoded with the
same codec the firmware encodes with. Nothing trusts the radio: a malformed or
corrupt frame is logged and dropped, never allowed to raise an exception that
would stop the ingest loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from subnet_proto import (
    Config, ConfigAck, Event, Header, MsgType, NeighborReport, ProtocolError, Telemetry,
    TimeSync, decode,
)

from .config import Settings
from .models import alerts as alerts_t
from .models import events as events_t
from .models import mesh_links, node_configs, nodes as nodes_t, sites as sites_t, telemetry
from .risk import Thresholds, assess, severity_of

log = logging.getLogger(__name__)

#: Minimum gap between alerts for the same node. An early-warning system that
#: repeats itself every few seconds gets muted by the people it is meant to warn.
ALERT_COOLDOWN = timedelta(minutes=20)

EVENT_TITLES = {
    0x01: "Tilt Rate Exceeded",
    0x02: "Abnormal Tilt Detected",
    0x03: "Crack Initiation Detected",
    0x04: "Unusual Vibration Detected",
    0x05: "Displacement Detected",
    0x06: "Node Tamper Detected",
    0x07: "Node Battery Low",
}


class IngestResult:
    __slots__ = ("accepted", "rejected", "alerts_raised", "errors")

    def __init__(self) -> None:
        self.accepted = 0
        self.rejected = 0
        self.alerts_raised = 0
        self.errors: list[str] = []

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "alertsRaised": self.alerts_raised,
            "errors": self.errors[:5],
        }


async def ingest_frames(session: AsyncSession, settings: Settings, frames: list[bytes],
                        *, site_slug: str | None = None,
                        auto_provision: bool = True) -> IngestResult:
    """Decode and persist a batch of frames. Returns per-batch counts."""
    result = IngestResult()
    site = (await session.execute(
        sa.select(sites_t).where(sites_t.c.slug == site_slug).limit(1) if site_slug
        else sa.select(sites_t).limit(1)
    )).mappings().first()
    if site is None:
        result.rejected += len(frames)
        result.errors.append("no site configured")
        return result

    for raw in frames:
        try:
            header, payload = decode(raw)
        except ProtocolError as exc:
            # Corrupt radio frames are expected, not exceptional.
            result.rejected += 1
            if len(result.errors) < 5:
                result.errors.append(str(exc))
            log.debug("dropped frame: %s", exc)
            continue

        try:
            await _handle(session, settings, site, header, payload, result, auto_provision)
            result.accepted += 1
        except Exception as exc:  # pragma: no cover - defensive
            result.rejected += 1
            if len(result.errors) < 5:
                result.errors.append(f"{type(exc).__name__}: {exc}")
            log.exception("ingest failed for frame from 0x%04X", header.src)

    await session.commit()
    return result


async def _handle(session: AsyncSession, settings: Settings, site, header: Header,
                  payload, result: IngestResult, auto_provision: bool) -> None:
    node = await _node_for(session, site["id"], header.src, auto_provision)
    if node is None:
        raise ValueError(f"unknown node address 0x{header.src:04X}")

    match payload:
        case Telemetry():
            await _telemetry(session, settings, site, node, header, payload, result)
        case Event():
            await _event(session, site, node, payload, result)
        case ConfigAck():
            await _config_ack(session, node, payload)
        case NeighborReport():
            await _neighbors(session, site, header, payload)
        case Config() | TimeSync():
            # Downlink types; a node echoing one back is harmless but ignorable.
            log.debug("ignoring downlink-type frame from 0x%04X", header.src)
        case _:  # pragma: no cover
            raise ValueError(f"unhandled payload {type(payload).__name__}")


async def _node_for(session: AsyncSession, site_id: int, addr: int, auto_provision: bool):
    row = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site_id, nodes_t.c.addr == addr)
    )).mappings().first()
    if row is not None or not auto_provision:
        return row

    # A node that appears on the mesh should appear on the dashboard. It is
    # provisioned unplaced -- an operator drops the pin on the map afterwards --
    # because a node reporting from an unknown position is still better than a
    # node silently discarded.
    await session.execute(nodes_t.insert().values(
        site_id=site_id, addr=addr, label=f"N-{addr:04X}", zone="Unassigned",
        lat=None, lon=None, x_m=None, y_m=None,
    ))
    await session.flush()
    log.info("auto-provisioned node 0x%04X", addr)
    return (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site_id, nodes_t.c.addr == addr)
    )).mappings().first()


async def _telemetry(session: AsyncSession, settings: Settings, site, node,
                     header: Header, tlm: Telemetry, result: IngestResult) -> None:
    when = datetime.fromtimestamp(tlm.t_epoch, tz=timezone.utc)
    thresholds = Thresholds(settings.tilt_threshold_deg, settings.crack_threshold_mm,
                            settings.vibration_threshold_mg)

    # A node with no baseline yet is baselined *by this frame*, so its tilt is
    # zero by definition. Assessing it against a notional zero instead would read
    # the installation angle -- how hard the post was hammered in -- as ground
    # movement, and fire a critical alert on every node the moment it joins.
    first_frame = node["baseline_pitch_mdeg"] is None
    baseline_pitch = tlm.pitch_mdeg if first_frame else node["baseline_pitch_mdeg"]
    baseline_roll = tlm.roll_mdeg if first_frame else node["baseline_roll_mdeg"]

    a = assess(
        pitch_mdeg=tlm.pitch_mdeg, roll_mdeg=tlm.roll_mdeg,
        vib_rms_mg=tlm.vib_rms_mg, crack_ohm=tlm.crack_ohm, thresholds=thresholds,
        baseline_pitch_mdeg=baseline_pitch,
        baseline_roll_mdeg=baseline_roll,
    )

    values = dict(
        time=when, node_id=node["id"],
        pitch_mdeg=tlm.pitch_mdeg, roll_mdeg=tlm.roll_mdeg,
        tilt_mdeg=a.tilt_deg * 1000.0,
        vib_rms_mg=tlm.vib_rms_mg, vib_peak_hz=tlm.vib_peak_hz,
        tof_mm=tlm.tof_mm, crack_ohm=tlm.crack_ohm, vbat_mv=tlm.vbat_mv,
        rssi=tlm.rssi, snr_db=tlm.snr_db, flags=tlm.flags,
        hops=header.hops, seq=header.seq,
    )
    # The protocol timestamps in whole seconds, so two frames from one node can
    # legitimately share a key. Upsert rather than ignore: a relayed duplicate
    # rewrites identical values and is therefore idempotent, while a genuinely
    # newer reading in the same second replaces the older one. Dropping the
    # second frame instead would discard real measurements silently, which is
    # the worst way for a monitoring system to fail.
    insert = (sa.dialects.sqlite.insert if session.bind.dialect.name == "sqlite"
              else sa.dialects.postgresql.insert)
    stmt = insert(telemetry).values(**values)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[telemetry.c.node_id, telemetry.c.time],
        set_={k: stmt.excluded[k] for k in values if k not in ("node_id", "time")},
    ))

    # First frame from a node establishes its baseline: how it was planted, not
    # how the ground has moved.
    updates: dict = {"last_seen": when}
    if first_frame:
        updates |= {"baseline_pitch_mdeg": tlm.pitch_mdeg,
                    "baseline_roll_mdeg": tlm.roll_mdeg,
                    "baseline_tof_mm": tlm.tof_mm}
    await session.execute(
        nodes_t.update().where(nodes_t.c.id == node["id"]).values(**updates))

    if not first_frame and a.band in ("high", "critical"):
        raised = await _raise_alert(
            session, site, node, when,
            severity=severity_of(a.band),
            category="threshold",
            title=("Crack Initiation Detected"
                   if a.crack_mm > settings.crack_threshold_mm * 0.55
                   else "High Deformation Detected" if a.band == "critical"
                   else "Abnormal Tilt Detected"),
            tilt_deg=a.tilt_deg, crack_mm=a.crack_mm, vibration_mg=float(tlm.vib_rms_mg),
            damage_class=a.damage_class,
        )
        if raised:
            result.alerts_raised += 1


async def _event(session: AsyncSession, site, node, evt: Event,
                 result: IngestResult) -> None:
    """A node-side threshold breach, sent immediately rather than at duty cycle."""
    when = datetime.fromtimestamp(evt.t_epoch, tz=timezone.utc)
    await session.execute(events_t.insert().values(
        time=when, node_id=node["id"], event_code=int(evt.event_code),
        severity=int(evt.severity), value=evt.value, threshold=evt.threshold,
    ))
    raised = await _raise_alert(
        session, site, node, when,
        severity=int(evt.severity), category="threshold",
        title=EVENT_TITLES.get(int(evt.event_code), "Node Event"),
        tilt_deg=abs(evt.value) / 1000.0, crack_mm=0.0, vibration_mg=0.0,
        damage_class=None,
    )
    if raised:
        result.alerts_raised += 1


async def _config_ack(session: AsyncSession, node, ack: ConfigAck) -> None:
    """Close the loop on a pushed config so the UI can show it really landed."""
    status = {0: "applied", 1: "rejected", 2: "partial"}.get(int(ack.status), "applied")
    await session.execute(
        node_configs.update()
        .where(node_configs.c.node_id == node["id"],
               node_configs.c.cfg_version == ack.cfg_version)
        .values(status=status, applied_at=datetime.now(timezone.utc))
    )
    if status == "applied":
        await session.execute(
            nodes_t.update().where(nodes_t.c.id == node["id"])
            .values(active_cfg_version=ack.cfg_version))


async def _neighbors(session: AsyncSession, site, header: Header,
                     report: NeighborReport) -> None:
    when = datetime.fromtimestamp(report.t_epoch, tz=timezone.utc)
    for n in report.neighbors:
        await session.execute(mesh_links.insert().values(
            time=when, site_id=site["id"], src_addr=header.src, dst_addr=n.addr,
            rssi=n.rssi, snr_db=n.snr_db,
        ))


async def _raise_alert(session: AsyncSession, site, node, when: datetime, *,
                       severity: int, category: str, title: str,
                       tilt_deg: float, crack_mm: float, vibration_mg: float,
                       damage_class: str | None) -> bool:
    """Insert an alert unless this node raised one recently. Returns True if raised."""
    recent = (await session.execute(
        sa.select(alerts_t.c.id, alerts_t.c.raised_at)
        .where(alerts_t.c.node_id == node["id"], alerts_t.c.state != "resolved")
        .order_by(alerts_t.c.raised_at.desc()).limit(1)
    )).mappings().first()
    if recent is not None:
        last = recent["raised_at"]
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if when - last < ALERT_COOLDOWN:
            return False

    await session.execute(alerts_t.insert().values(
        site_id=site["id"], node_id=node["id"], raised_at=when, severity=severity,
        category=category, title=title, detail=node["zone"] or "",
        tilt_deg=tilt_deg, crack_mm=crack_mm, vibration_mg=vibration_mg,
        damage_class=damage_class,
    ))
    return True
