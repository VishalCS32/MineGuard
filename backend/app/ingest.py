"""Frame ingest: radio bytes in, stored telemetry and alerts out.

Every uplink -- whether it arrived over MQTT from a real gateway or over HTTP
from the simulator -- lands here as raw protocol bytes and is decoded with the
same codec the firmware encodes with. Nothing trusts the radio: a malformed or
corrupt frame is logged and dropped, never allowed to raise an exception that
would stop the ingest loop.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from subnet_proto import (
    Config, ConfigAck, Event, Header, MsgType, NeighborReport, Position, ProtocolError,
    Telemetry, TimeSync, decode,
)

from .config import Settings
from .deformation import NodeTilt, estimate_field
from .models import alerts as alerts_t
from .models import events as events_t
from .models import mesh_links, node_configs, nodes as nodes_t, sites as sites_t, telemetry
from .risk import Thresholds, assess, corrected_tilt_mdeg, severity_of

log = logging.getLogger(__name__)

#: Minimum gap between alerts for the same node. An early-warning system that
#: repeats itself every few seconds gets muted by the people it is meant to warn.
ALERT_COOLDOWN = timedelta(minutes=20)

EVENT_TITLES = {
    0x01: "Tilt Rate Exceeded",
    0x02: "Abnormal Tilt Detected",
    0x03: "Tilt Accelerating",
    0x04: "Unusual Vibration Detected",
    0x05: "Node Displaced",
    0x06: "Node Tamper Detected",
    0x07: "Node Battery Low",
}

#: A GNSS fix this far from the node's recorded position is not drift, it is the
#: node having physically moved -- a collapse, or somebody carrying it away.
#: Well above the receiver's own metre-scale noise, so ordinary subsidence (which
#: is millimetres) can never trip it.
GNSS_DISPLACEMENT_ALARM_M = 15.0


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

    if result.accepted:
        try:
            await _field_pass(session, settings, site, result)
        except Exception:  # pragma: no cover - a scoring failure must not lose data
            log.exception("field assessment failed; telemetry retained")

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
        case Position():
            await _position(session, site, node, payload, result)
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
    thresholds = _thresholds(settings)

    # A node with no baseline yet is baselined *by this frame*, so its tilt is
    # zero by definition. Assessing it against a notional zero instead would read
    # the installation angle -- how hard the post was hammered in -- as ground
    # movement, and fire a critical alert on every node the moment it joins.
    first_frame = node["baseline_pitch_mdeg"] is None
    baseline_pitch = tlm.pitch_mdeg if first_frame else node["baseline_pitch_mdeg"]
    baseline_roll = tlm.roll_mdeg if first_frame else node["baseline_roll_mdeg"]

    a = assess(
        pitch_mdeg=tlm.pitch_mdeg, roll_mdeg=tlm.roll_mdeg,
        vib_rms_mg=tlm.vib_rms_mg, thresholds=thresholds,
        baseline_pitch_mdeg=baseline_pitch,
        baseline_roll_mdeg=baseline_roll,
        temp_c=tlm.temp_c,
        baseline_temp_c=(tlm.temp_c if first_frame
                         else (node["baseline_temp_c_x100"] or 0) / 100.0),
        drift_mdeg_per_c=settings.tilt_drift_mdeg_per_c,
    )

    values = dict(
        time=when, node_id=node["id"],
        pitch_mdeg=tlm.pitch_mdeg, roll_mdeg=tlm.roll_mdeg,
        tilt_mdeg=a.tilt_deg * 1000.0,
        vib_rms_mg=tlm.vib_rms_mg, vib_peak_hz=tlm.vib_peak_hz,
        temp_c_x100=tlm.temp_c_x100, n_samples=tlm.n_samples,
        gnss_status=tlm.gnss_status, vbat_mv=tlm.vbat_mv,
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
        # The commissioning temperature matters as much as the attitude: drift is
        # only removable relative to the temperature the baseline was taken at.
        updates |= {"baseline_pitch_mdeg": tlm.pitch_mdeg,
                    "baseline_roll_mdeg": tlm.roll_mdeg,
                    "baseline_temp_c_x100": tlm.temp_c_x100}
    await session.execute(
        nodes_t.update().where(nodes_t.c.id == node["id"]).values(**updates))

    # No alert is raised here. Strain -- and therefore the NCB damage class --
    # is a property of the whole array, so the judgement is made once per batch
    # in _field_pass() once every frame in this batch has landed. Alerting per
    # frame would also mean alerting once per node per cycle on a shared cause.


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
        tilt_deg=abs(evt.value) / 1000.0, strain_mm_per_m=0.0, vibration_mg=0.0,
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
                       tilt_deg: float, strain_mm_per_m: float, vibration_mg: float,
                       damage_class: str | None,
                       tilt_rate_deg_per_h: float = 0.0,
                       hours_to_threshold: float | None = None) -> bool:
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
        tilt_deg=tilt_deg, strain_mm_per_m=strain_mm_per_m, vibration_mg=vibration_mg,
        damage_class=damage_class, tilt_rate_deg_per_h=tilt_rate_deg_per_h,
        hours_to_threshold=hours_to_threshold,
    ))
    return True


def _thresholds(settings: Settings) -> Thresholds:
    return Thresholds(settings.tilt_threshold_deg, settings.strain_threshold_mm_per_m,
                      settings.vibration_threshold_mg,
                      settings.tilt_rate_threshold_deg_per_h)


async def _position(session: AsyncSession, site, node, pos: Position,
                    result: IngestResult) -> None:
    """A GNSS fix.

    Two jobs, and it is worth being clear that neither is measuring subsidence.
    A NEO-6M is accurate to metres; subsidence is millimetres. Claiming otherwise
    would be the easiest lie in this system to tell and the easiest to catch.

    What it does do: place a node that nobody surveyed, and notice a node that
    has physically moved. Ground that drops far enough to drag a post metres
    sideways has done something an operator needs to know about tonight.
    """
    if not pos.is_usable:
        log.debug("ignoring unusable GNSS fix from 0x%04X", node["addr"])
        return

    when = datetime.fromtimestamp(pos.t_epoch, tz=timezone.utc)
    known_lat, known_lon = node["lat"], node["lon"]

    if known_lat is None or known_lon is None:
        # Never surveyed. A metre-accurate self-placement beats no placement.
        await session.execute(nodes_t.update().where(nodes_t.c.id == node["id"]).values(
            lat=pos.lat, lon=pos.lon,
            position_source="gnss", position_acc_m=pos.h_acc_m))
        log.info("node 0x%04X self-placed at %.5f, %.5f", node["addr"], pos.lat, pos.lon)
        return

    moved_m = _haversine_m(known_lat, known_lon, pos.lat, pos.lon)
    if moved_m < GNSS_DISPLACEMENT_ALARM_M:
        return

    # Only a survey-grade record should be overwritten by a confirmed move, so
    # the alert is raised and the recorded position is left alone for a human.
    raised = await _raise_alert(
        session, site, node, when,
        severity=3, category="threshold", title="Node Displaced",
        tilt_deg=0.0, strain_mm_per_m=0.0, vibration_mg=0.0, damage_class=None)
    if raised:
        result.alerts_raised += 1
        log.warning("node 0x%04X has moved %.0f m", node["addr"], moved_m)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


async def _tilt_rates(session: AsyncSession, node_ids: list[int],
                      now: datetime, window_hours: float) -> dict[int, float]:
    """Degrees per hour for each node, from the ends of a recent window.

    Rate is the precursor signal, and it is also the one the hardware can supply
    honestly: it needs no spatial derivative and no second sensor, only the same
    node measured twice. Taken across hours rather than between consecutive
    frames, so that per-sample noise -- which is large next to an hour of real
    movement -- averages down instead of dominating.
    """
    if not node_ids:
        return {}
    since = now - timedelta(hours=window_hours)
    rows = (await session.execute(
        sa.select(telemetry.c.node_id, telemetry.c.time, telemetry.c.tilt_mdeg)
        .where(telemetry.c.node_id.in_(node_ids), telemetry.c.time >= since)
        .order_by(telemetry.c.node_id, telemetry.c.time)
    )).all()

    by_node: dict[int, list[tuple[datetime, float]]] = {}
    for node_id, t, tilt in rows:
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        by_node.setdefault(node_id, []).append((t, (tilt or 0.0) / 1000.0))

    out: dict[int, float] = {}
    for node_id, series in by_node.items():
        if len(series) < 2:
            continue
        (t0, v0), (t1, v1) = series[0], series[-1]
        hours = (t1 - t0).total_seconds() / 3600.0
        # Too short a baseline turns sensor noise into a huge apparent rate.
        if hours >= 0.5:
            out[node_id] = (v1 - v0) / hours
    return out


async def _field_pass(session: AsyncSession, settings: Settings, site,
                      result: IngestResult) -> None:
    """Assess the whole array once, after a batch has landed.

    Strain is not a property of a node, it is a property of the field: it comes
    from how tilt *varies between* nodes. So the judgement cannot be made frame
    by frame, and this runs once per batch instead -- which also stops one
    advancing face raising twenty near-identical alerts, one per node, for what
    is plainly a single event.
    """
    from .state import latest_telemetry   # local import: state imports this module

    node_rows = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site["id"])
    )).mappings().all()
    if not node_rows:
        return
    latest = await latest_telemetry(session, [n["id"] for n in node_rows])
    if not latest:
        return

    now = datetime.now(timezone.utc)
    rates = await _tilt_rates(session, list(latest), now, settings.tilt_rate_window_hours)
    drift = settings.tilt_drift_mdeg_per_c

    tilts: list[NodeTilt] = []
    placed: dict[int, dict] = {}
    for n in node_rows:
        row = latest.get(n["id"])
        if row is None or n["x_m"] is None or n["y_m"] is None:
            continue
        base_temp = (n["baseline_temp_c_x100"] or 0) / 100.0
        temp = (row["temp_c_x100"] or 0) / 100.0
        dp = corrected_tilt_mdeg(row["pitch_mdeg"] or 0, n["baseline_pitch_mdeg"] or 0,
                                 temp, base_temp, drift) / 1000.0
        dr = corrected_tilt_mdeg(row["roll_mdeg"] or 0, n["baseline_roll_mdeg"] or 0,
                                 temp, base_temp, drift) / 1000.0
        tilts.append(NodeTilt(
            addr=n["addr"], x_m=float(n["x_m"]), y_m=float(n["y_m"]),
            tilt_x_mm_per_m=math.tan(math.radians(dp)) * 1000.0,
            tilt_y_mm_per_m=math.tan(math.radians(dr)) * 1000.0,
        ))
        placed[n["addr"]] = {"node": n, "row": row}

    field = estimate_field(tilts, seam_depth_m=site["seam_depth_m"] or 150.0,
                           panel_x_start=site["panel_x_start"],
                           angle_of_draw_deg=site["angle_of_draw_deg"] or 35.0)
    thresholds = _thresholds(settings)

    for addr, entry in placed.items():
        n, row = entry["node"], entry["row"]
        if n["baseline_pitch_mdeg"] is None:
            continue                      # still being commissioned by its first frame
        est = field.get(addr)
        rate = rates.get(n["id"], 0.0)
        a = assess(
            pitch_mdeg=row["pitch_mdeg"] or 0, roll_mdeg=row["roll_mdeg"] or 0,
            vib_rms_mg=row["vib_rms_mg"] or 0, thresholds=thresholds,
            baseline_pitch_mdeg=n["baseline_pitch_mdeg"] or 0,
            baseline_roll_mdeg=n["baseline_roll_mdeg"] or 0,
            temp_c=(row["temp_c_x100"] or 0) / 100.0,
            baseline_temp_c=(n["baseline_temp_c_x100"] or 0) / 100.0,
            tilt_rate_deg_per_h=rate,
            strain_mm_per_m=est.strain_mm_per_m if est else 0.0,
            strain_valid=bool(est and est.strain_valid),
            drift_mdeg_per_c=drift,
        )
        if a.band not in ("high", "critical"):
            continue

        when = row["time"]
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        raised = await _raise_alert(
            session, site, n, when,
            severity=severity_of(a.band), category="threshold",
            title=_alert_title(a, thresholds),
            tilt_deg=a.tilt_deg, strain_mm_per_m=a.strain_mm_per_m,
            vibration_mg=float(row["vib_rms_mg"] or 0),
            damage_class=a.damage_class if a.strain_valid else None,
            tilt_rate_deg_per_h=a.tilt_rate_deg_per_h,
            hours_to_threshold=_hours_to_threshold(a, thresholds),
        )
        if raised:
            result.alerts_raised += 1


def _alert_title(a, thresholds: Thresholds) -> str:
    """Name the alert after whichever criterion actually drove it."""
    if abs(a.tilt_rate_deg_per_h) >= thresholds.tilt_rate_deg_per_h:
        return "Tilt Rate Exceeded"
    if a.strain_valid and abs(a.strain_mm_per_m) >= thresholds.strain_mm_per_m:
        return "Ground Strain Exceeded"
    if a.band == "critical":
        return "High Deformation Detected"
    return "Abnormal Tilt Detected"


def _hours_to_threshold(a, thresholds: Thresholds) -> float | None:
    """Lead time: hours until this node's tilt reaches the disruptive limit.

    A straight-line extrapolation of the current rate, and no more than that.
    Subsidence accelerates, so this is optimistic and should read as "no sooner
    than". It is still the number an operator actually plans around, which is
    why it is stated at all rather than hidden behind a score.
    """
    remaining = thresholds.tilt_deg - a.tilt_deg
    if a.tilt_rate_deg_per_h <= 0 or remaining <= 0:
        return None
    return remaining / a.tilt_rate_deg_per_h


async def ingest_json_readings(
    session: AsyncSession,
    settings: Settings,
    readings: Sequence[Mapping[str, Any]],
    *,
    site_slug: str | None = None,
    auto_provision: bool = True,
) -> IngestResult:
    """Decode, normalize, and persist JSON telemetry records matching the deployed API schema.
    
    Supports single records or batches up to 500 records.
    Updates baseline, tilt rates, sensor health, and triggers field evaluation.
    """
    result = IngestResult()
    if not readings:
        return result

    site = (await session.execute(
        sa.select(sites_t).where(sites_t.c.slug == site_slug).limit(1) if site_slug
        else sa.select(sites_t).limit(1)
    )).mappings().first()
    if site is None:
        result.rejected += len(readings)
        result.errors.append("no site configured")
        return result

    thresholds = _thresholds(settings)

    for d in readings:
        if not isinstance(d, (dict, Mapping)) or not d.get("node_id"):
            result.rejected += 1
            if len(result.errors) < 5:
                result.errors.append("reading missing node_id")
            continue

        raw_id = str(d["node_id"]).strip()
        node = await _node_for_string_id(session, site["id"], raw_id, auto_provision)
        if node is None:
            result.rejected += 1
            if len(result.errors) < 5:
                result.errors.append(f"unknown node {raw_id}")
            continue

        # Parse timestamp
        raw_ts = d.get("timestamp") or d.get("ts") or d.get("time")
        if isinstance(raw_ts, datetime):
            when = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=timezone.utc)
        elif isinstance(raw_ts, (int, float)):
            when = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
        elif raw_ts:
            try:
                clean_ts = str(raw_ts).replace("Z", "+00:00")
                when = datetime.fromisoformat(clean_ts)
            except Exception:
                when = datetime.now(timezone.utc)
        else:
            when = datetime.now(timezone.utc)

        sensor_data = d.get("sensor_data") or {}
        ori = sensor_data.get("orientation") or {}
        vib = sensor_data.get("vibration") or {}
        gps = d.get("gps") or {}
        comm = d.get("communication") or {}

        # Tilt angles in degrees -> millidegrees
        pitch_deg = d.get("pitch_deg", ori.get("pitch", 0.0))
        roll_deg = d.get("roll_deg", ori.get("roll", 0.0))
        try:
            pitch_mdeg = int(round(float(pitch_deg or 0.0) * 1000.0))
            roll_mdeg = int(round(float(roll_deg or 0.0) * 1000.0))
        except (ValueError, TypeError):
            pitch_mdeg = roll_mdeg = 0

        # Vibration: m/s^2 -> mg
        vib_rms = d.get("vib_rms", vib.get("rms"))
        if vib_rms is not None:
            try:
                vib_rms_mg = int(round(float(vib_rms) * 1000.0 / 9.80665))
            except (ValueError, TypeError):
                vib_rms_mg = 0
        else:
            vib_rms_mg = int(round(float(d.get("vib_rms_mg", vib.get("rms_mg", 0.0)) or 0.0)))
        vib_peak_hz = float(d.get("vib_peak_hz", vib.get("peak_hz", 0.0)) or 0.0)

        # Temperature
        temp_c = d.get("temperature_c", sensor_data.get("temperature_c", 25.0))
        try:
            temp_c_x100 = int(round(float(temp_c if temp_c is not None else 25.0) * 100.0))
        except (ValueError, TypeError):
            temp_c_x100 = 2500

        # Battery
        vbat_raw = d.get("battery_mv", sensor_data.get("battery_mv", 3900.0))
        try:
            vbat_mv = int(round(float(vbat_raw if vbat_raw is not None else 3900.0)))
        except (ValueError, TypeError):
            vbat_mv = 3900

        # GPS coordinates & satellites
        lat = d.get("latitude", gps.get("latitude"))
        lon = d.get("longitude", gps.get("longitude"))
        sats = int(d.get("satellites", gps.get("satellites", 0)) or 0)
        gnss_status = (sats << 2) | (1 if lat is not None else 0)

        # RF
        rssi_raw = d.get("rssi_dbm", comm.get("rssi_dbm", -70.0))
        try:
            rssi = int(round(float(rssi_raw if rssi_raw is not None else -70.0)))
        except (ValueError, TypeError):
            rssi = -70
        snr_raw = d.get("snr_db", comm.get("snr_db", 10.0))
        try:
            snr_db = float(snr_raw if snr_raw is not None else 10.0)
        except (ValueError, TypeError):
            snr_db = 10.0

        flags = int(d.get("flags", 0) or 0)

        # Baseline calculation
        first_frame = node["baseline_pitch_mdeg"] is None
        baseline_pitch = pitch_mdeg if first_frame else node["baseline_pitch_mdeg"]
        baseline_roll = roll_mdeg if first_frame else node["baseline_roll_mdeg"]
        baseline_temp = (temp_c_x100 / 100.0) if first_frame else ((node["baseline_temp_c_x100"] or 0) / 100.0)

        a = assess(
            pitch_mdeg=pitch_mdeg, roll_mdeg=roll_mdeg,
            vib_rms_mg=vib_rms_mg, thresholds=thresholds,
            baseline_pitch_mdeg=baseline_pitch,
            baseline_roll_mdeg=baseline_roll,
            temp_c=temp_c_x100 / 100.0,
            baseline_temp_c=baseline_temp,
            drift_mdeg_per_c=settings.tilt_drift_mdeg_per_c,
        )

        values = dict(
            time=when, node_id=node["id"],
            pitch_mdeg=pitch_mdeg, roll_mdeg=roll_mdeg,
            tilt_mdeg=a.tilt_deg * 1000.0,
            vib_rms_mg=vib_rms_mg, vib_peak_hz=vib_peak_hz,
            temp_c_x100=temp_c_x100, n_samples=1,
            gnss_status=gnss_status, vbat_mv=vbat_mv,
            rssi=rssi, snr_db=snr_db, flags=flags,
            hops=1, seq=0,
        )
        insert = (sa.dialects.sqlite.insert if session.bind.dialect.name == "sqlite"
                  else sa.dialects.postgresql.insert)
        stmt = insert(telemetry).values(**values)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[telemetry.c.node_id, telemetry.c.time],
            set_={k: stmt.excluded[k] for k in values if k not in ("node_id", "time")},
        ))

        node_updates: dict[str, Any] = {"last_seen": when}
        if first_frame:
            node_updates.update({
                "baseline_pitch_mdeg": pitch_mdeg,
                "baseline_roll_mdeg": roll_mdeg,
                "baseline_temp_c_x100": temp_c_x100,
            })
        if lat is not None and lon is not None and (node["lat"] is None or node["lon"] is None):
            node_updates.update({
                "lat": float(lat),
                "lon": float(lon),
                "position_source": "gnss",
            })
        await session.execute(
            nodes_t.update().where(nodes_t.c.id == node["id"]).values(**node_updates)
        )
        result.accepted += 1

    if result.accepted:
        try:
            await _field_pass(session, settings, site, result)
        except Exception:
            log.exception("field assessment failed; telemetry retained")

    await session.commit()
    return result


async def _node_for_string_id(session: AsyncSession, site_id: int, raw_id: str, auto_provision: bool):
    """Find a node by label or address, or auto-provision if allowed."""
    row = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site_id, nodes_t.c.label == raw_id)
    )).mappings().first()
    if row is not None:
        return row

    clean = raw_id.upper().removeprefix("NODE-").removeprefix("N-").removeprefix("0X")
    try:
        addr = int(clean, 16) if any(c in "ABCDEF" for c in clean) else int(clean)
    except (ValueError, TypeError):
        addr = (abs(hash(raw_id)) % 0xFFFE) + 1

    row = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site_id, nodes_t.c.addr == addr)
    )).mappings().first()
    if row is not None or not auto_provision:
        return row

    while True:
        exists = (await session.execute(
            sa.select(nodes_t.c.id).where(nodes_t.c.site_id == site_id, nodes_t.c.addr == addr)
        )).scalar_one_or_none()
        if exists is None:
            break
        addr = (addr + 1) % 0xFFFE or 1

    await session.execute(nodes_t.insert().values(
        site_id=site_id, addr=addr, label=raw_id, zone="Unassigned",
        lat=None, lon=None, x_m=None, y_m=None,
    ))
    await session.flush()
    log.info("auto-provisioned node %s (addr 0x%04X)", raw_id, addr)
    return (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site_id, nodes_t.c.addr == addr)
    )).mappings().first()

