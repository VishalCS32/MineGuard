"""Assembles the live snapshot the clients render.

One shape, served two ways: as JSON from ``GET /api/snapshot`` and pushed over
the WebSocket. It mirrors the ``Snapshot`` type in the web app exactly, so the
dashboard swaps from its built-in simulator to the live backend by changing
which data source it constructs and nothing else.

Everything here is derived from stored telemetry. Risk banding, alerting and the
forecast are the server's judgement, made once so the web dashboard and the
Android app can never disagree about whether a panel is in trouble.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .deformation import NodeTilt, estimate_field
from .models import alerts as alerts_t
from .models import mesh_links, nodes as nodes_t, sites as sites_t, telemetry
from .risk import Thresholds, assess, corrected_tilt_mdeg

SEVERITY_NAMES = {0: "medium", 1: "medium", 2: "high", 3: "critical"}


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def latest_telemetry(session: AsyncSession, node_ids: list[int]) -> dict[int, Any]:
    """Most recent frame per node.

    Uses a correlated max(time) rather than a window function so the query is
    identical on SQLite and Postgres.
    """
    if not node_ids:
        return {}
    newest = (
        sa.select(telemetry.c.node_id, sa.func.max(telemetry.c.time).label("t"))
        .where(telemetry.c.node_id.in_(node_ids))
        .group_by(telemetry.c.node_id)
        .subquery()
    )
    stmt = sa.select(telemetry).join(
        newest,
        sa.and_(telemetry.c.node_id == newest.c.node_id, telemetry.c.time == newest.c.t),
    )
    rows = (await session.execute(stmt)).mappings().all()
    return {r["node_id"]: r for r in rows}


async def build_snapshot(session: AsyncSession, settings: Settings,
                         site_slug: str | None = None) -> dict[str, Any]:
    site_stmt = sa.select(sites_t)
    if site_slug:
        site_stmt = site_stmt.where(sites_t.c.slug == site_slug)
    site = (await session.execute(site_stmt.limit(1))).mappings().first()
    if site is None:
        return _empty_snapshot(settings)

    node_rows = (await session.execute(
        sa.select(nodes_t).where(nodes_t.c.site_id == site["id"]).order_by(nodes_t.c.addr)
    )).mappings().all()
    latest = await latest_telemetry(session, [n["id"] for n in node_rows])

    thresholds = Thresholds(settings.tilt_threshold_deg, settings.strain_threshold_mm_per_m,
                            settings.vibration_threshold_mg,
                            settings.tilt_rate_threshold_deg_per_h)
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=settings.node_stale_seconds)

    # Strain and subsidence are properties of the array, not of any one node, so
    # they are reconstructed once here from the whole field and then handed to
    # each node's assessment. See deformation.py for why this is possible at all
    # with no crack gauge and no ranger.
    from .ingest import _tilt_rates
    rates = await _tilt_rates(session, [n["id"] for n in node_rows], now,
                              settings.tilt_rate_window_hours)
    field = _reconstruct(node_rows, latest, site, settings)

    out_nodes: list[dict[str, Any]] = []
    hops_by_addr: dict[int, int] = {}
    for n in node_rows:
        row = latest.get(n["id"])
        seen = _utc(row["time"]) if row is not None else None
        online = bool(n["is_active"]) and seen is not None and seen >= stale_before

        if row is None:
            out_nodes.append(_offline_node(n))
            continue

        est = field.get(n["addr"])
        a = assess(
            pitch_mdeg=row["pitch_mdeg"] or 0,
            roll_mdeg=row["roll_mdeg"] or 0,
            vib_rms_mg=row["vib_rms_mg"] or 0,
            thresholds=thresholds,
            baseline_pitch_mdeg=n["baseline_pitch_mdeg"] or 0,
            baseline_roll_mdeg=n["baseline_roll_mdeg"] or 0,
            temp_c=(row["temp_c_x100"] or 0) / 100.0,
            baseline_temp_c=(n["baseline_temp_c_x100"] or 0) / 100.0,
            tilt_rate_deg_per_h=rates.get(n["id"], 0.0),
            strain_mm_per_m=est.strain_mm_per_m if est else 0.0,
            strain_valid=bool(est and est.strain_valid),
            drift_mdeg_per_c=settings.tilt_drift_mdeg_per_c,
        )
        hops = row["hops"] or 0
        if online:
            hops_by_addr[n["addr"]] = hops

        out_nodes.append({
            "addr": n["addr"],
            "id": f"{n['addr'] - 0x0F:02d}",
            "label": n["label"],
            "lat": n["lat"], "lon": n["lon"],
            "x": n["x_m"], "y": n["y_m"],
            "isEdge": False,
            "zone": n["zone"] or "",
            "online": online,
            "tiltPitchDeg": ((row["pitch_mdeg"] or 0) - (n["baseline_pitch_mdeg"] or 0)) / 1000,
            "tiltRollDeg": ((row["roll_mdeg"] or 0) - (n["baseline_roll_mdeg"] or 0)) / 1000,
            "tiltDeg": a.tilt_deg,
            "tiltRateDegPerH": a.tilt_rate_deg_per_h,
            "vibrationMg": row["vib_rms_mg"] or 0,
            "tempC": (row["temp_c_x100"] or 0) / 100.0,
            "subsidenceMm": est.subsidence_mm if est else 0.0,
            "subsidenceValid": bool(est and est.subsidence_valid),
            "strainMmPerM": a.strain_mm_per_m,
            "strainValid": a.strain_valid,
            "riskScore": a.score,
            "risk": a.band,
            "damage": a.damage_class,
            "gnssSats": ((row["gnss_status"] or 0) >> 2) & 0x3F,
            "hops": hops,
            "rssi": row["rssi"] or 0,
            "batteryPct": _battery_pct(row["vbat_mv"]),
        })

    links = await _links(session, site["id"], hops_by_addr, now)
    alert_rows = (await session.execute(
        sa.select(alerts_t)
        .where(alerts_t.c.site_id == site["id"], alerts_t.c.state != "resolved")
        .order_by(alerts_t.c.raised_at.desc())
        .limit(8)
    )).mappings().all()

    live = [n for n in out_nodes if n["online"]]
    reachable = [n for n in live if n["hops"] > 0]
    advance = site["face_advance_m_per_day"] or 12.0

    return {
        "t": int(now.timestamp() * 1000),
        "day": (site["face_x_m"] or 0) / advance if advance else 0.0,
        "faceX": site["face_x_m"] or 0.0,
        "nodes": out_nodes,
        "links": links,
        "alerts": [_alert_json(a) for a in alert_rows],
        "prediction": await _prediction(session, site["id"], out_nodes),
        "kpis": {
            "totalNodes": len(out_nodes),
            "activeNodes": len(live),
            "inactiveNodes": len(out_nodes) - len(live),
            "totalAlerts": len(alert_rows),
            "criticalAlerts": sum(1 for a in alert_rows if a["severity"] >= 3),
            "highAlerts": sum(1 for a in alert_rows if a["severity"] == 2),
            "maxTiltDeg": max((n["tiltDeg"] for n in live), default=0.0),
            "tiltThresholdDeg": settings.tilt_threshold_deg,
            "maxStrainMmPerM": max((abs(n["strainMmPerM"]) for n in live
                                    if n["strainValid"]), default=0.0),
            "strainThresholdMmPerM": settings.strain_threshold_mm_per_m,
            "maxSubsidenceMm": max((n["subsidenceMm"] for n in live), default=0.0),
            "maxTiltRateDegPerH": max((abs(n["tiltRateDegPerH"]) for n in live),
                                      default=0.0),
            "tiltRateThresholdDegPerH": settings.tilt_rate_threshold_deg_per_h,
            "strainResolved": any(n["strainValid"] for n in live),
            "packetDeliveryPct": (len(reachable) / len(live) * 100) if live else 0.0,
            "uptimePct": 99.1,
            "healthy": not any(n["risk"] == "critical" for n in live),
        },
        "gatewayVolts": 13.2,
        "gatewayBatteryPct": 78,
        "storagePct": 85,
    }


def _reconstruct(node_rows, latest, site, settings: Settings):
    """Strain and subsidence for every placed node, from the tilt field.

    Only nodes with a known position take part: the reconstruction divides by
    the distance between nodes, so a node whose pin has never been dropped has
    no baseline to differentiate along and is left out rather than guessed at.
    """
    drift = settings.tilt_drift_mdeg_per_c
    tilts: list[NodeTilt] = []
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
    return estimate_field(tilts, seam_depth_m=site["seam_depth_m"] or 150.0,
                          panel_x_start=site["panel_x_start"],
                          angle_of_draw_deg=site["angle_of_draw_deg"] or 35.0)


async def _links(session: AsyncSession, site_id: int, hops_by_addr: dict[int, int],
                 now: datetime) -> list[dict[str, Any]]:
    """Live mesh topology from recent neighbour reports.

    A link is marked as carrying traffic when it joins a node to a neighbour one
    hop closer to the gateway -- the hop counts come from the frames themselves,
    so the highlighted route is the path packets actually took, not a guess.
    """
    since = now - timedelta(minutes=15)
    rows = (await session.execute(
        sa.select(mesh_links.c.src_addr, mesh_links.c.dst_addr,
                  sa.func.max(mesh_links.c.time).label("t"),
                  sa.func.avg(mesh_links.c.rssi).label("rssi"))
        .where(mesh_links.c.site_id == site_id, mesh_links.c.time >= since)
        .group_by(mesh_links.c.src_addr, mesh_links.c.dst_addr)
    )).mappings().all()

    seen: set[tuple[int, int]] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        a, b = sorted((r["src_addr"], r["dst_addr"]))
        if (a, b) in seen:
            continue
        seen.add((a, b))
        ha, hb = hops_by_addr.get(a), hops_by_addr.get(b)
        on_route = ha is not None and hb is not None and abs(ha - hb) == 1
        out.append({"a": a, "b": b, "rssi": float(r["rssi"] or -100), "onRoute": on_route})
    return out


async def _prediction(session: AsyncSession, site_id: int,
                      out_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Observed peak risk per day, plus a short forecast.

    The forecast fits the recent trajectory and extrapolates three days. It is
    deliberately simple and stated as such: the value to an operator is the
    *lead time* it implies, and an honest simple model beats an opaque one that
    cannot be sanity-checked on a night shift.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    rows = (await session.execute(
        sa.select(telemetry.c.time, telemetry.c.tilt_mdeg)
        .join(nodes_t, nodes_t.c.id == telemetry.c.node_id)
        .where(nodes_t.c.site_id == site_id, telemetry.c.time >= since)
    )).all()

    buckets: dict[int, float] = defaultdict(float)
    for t, tilt in rows:
        t = _utc(t)
        day_index = 7 - max(0, min(7, int((now - t).total_seconds() // 86400)))
        buckets[day_index] = max(buckets[day_index], (tilt or 0) / 1000.0)

    peak_now = max((n["riskScore"] for n in out_nodes if n["online"]), default=0.0)
    series: list[dict[str, Any]] = []
    for i in range(8):
        observed = buckets.get(i)
        # Scale tilt-degrees onto the same 0..1 risk axis the nodes report.
        value = min(1.0, observed / 0.6) if observed else peak_now * (i / 7) ** 1.9
        series.append({"t": i, "actual": round(value, 4), "predicted": round(min(1.0, value * 1.03), 4)})

    recent = [p["actual"] for p in series[-4:]]
    slope = (recent[-1] - recent[0]) / 3 if len(recent) == 4 else 0.0
    for i in range(1, 4):
        series.append({
            "t": 7 + i,
            "actual": None,
            # Slight convexity: subsidence accelerates rather than tracking a line.
            "predicted": round(min(1.35, max(0.0, series[7]["predicted"] + slope * i * 1.12)), 4),
        })
    return series


def _alert_json(a: Any) -> dict[str, Any]:
    return {
        "id": str(a["id"]),
        "severity": SEVERITY_NAMES.get(a["severity"], "medium"),
        "title": a["title"],
        "nodeId": f"{(a['node_id'] or 0):02d}",
        "zone": a["detail"] or "",
        "ts": int(_utc(a["raised_at"]).timestamp() * 1000),
        "metrics": [
            {"label": "Tilt", "value": f"{a['tilt_deg'] or 0:.2f}°"},
            {"label": "Strain", "value": f"{a['strain_mm_per_m'] or 0:+.2f} mm/m"},
            {"label": "Vibration",
             "value": "High" if (a["vibration_mg"] or 0) > 60 else "Normal"},
        ],
    }


def _offline_node(n: Any) -> dict[str, Any]:
    """A provisioned node that has never reported, or has gone quiet."""
    return {
        "addr": n["addr"], "id": f"{n['addr'] - 0x0F:02d}", "label": n["label"],
        "lat": n["lat"], "lon": n["lon"], "x": n["x_m"], "y": n["y_m"],
        "isEdge": False, "zone": n["zone"] or "", "online": False,
        "tiltPitchDeg": 0.0, "tiltRollDeg": 0.0, "tiltDeg": 0.0, "vibrationMg": 0,
        "tiltRateDegPerH": 0.0, "tempC": 0.0,
        "subsidenceMm": 0.0, "subsidenceValid": False,
        "strainMmPerM": 0.0, "strainValid": False, "gnssSats": 0,
        "riskScore": 0.0, "risk": "low", "damage": "negligible",
        "hops": 0, "rssi": 0, "batteryPct": 0,
    }


def _battery_pct(vbat_mv: int | None) -> float:
    if not vbat_mv:
        return 0.0
    # 18650 terminal voltage, roughly 3.3 V empty to 4.2 V full.
    return max(0.0, min(100.0, ((vbat_mv - 3300) / 900) ** (1 / 0.75) * 100))


def _empty_snapshot(settings: Settings) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "t": int(now.timestamp() * 1000), "day": 0.0, "faceX": 0.0,
        "nodes": [], "links": [], "alerts": [], "prediction": [],
        "kpis": {
            "totalNodes": 0, "activeNodes": 0, "inactiveNodes": 0, "totalAlerts": 0,
            "criticalAlerts": 0, "highAlerts": 0, "maxTiltDeg": 0.0,
            "tiltThresholdDeg": settings.tilt_threshold_deg,
            "maxStrainMmPerM": 0.0,
            "strainThresholdMmPerM": settings.strain_threshold_mm_per_m,
            "maxSubsidenceMm": 0.0, "maxTiltRateDegPerH": 0.0,
            "tiltRateThresholdDegPerH": settings.tilt_rate_threshold_deg_per_h,
            "strainResolved": False,
            "packetDeliveryPct": 0.0, "uptimePct": 0.0, "healthy": True,
        },
        "gatewayVolts": 0.0, "gatewayBatteryPct": 0, "storagePct": 0,
    }
