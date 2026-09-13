"""Build requests for the MineGuard ML inference service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .models import telemetry as telemetry_t, nodes as nodes_t


def telemetry_to_ml_node(rec: Any) -> dict[str, Any]:
    """Convert backend telemetry into the ML node format conforming to ML-API-CONTRACT.
    
    Preserves real accelerometer and gyroscope values when provided by hardware,
    leaving them null when hardware does not supply them (never fabricates values).
    """
    def get(name: str, default: Any = None) -> Any:
        if isinstance(rec, dict):
            return rec.get(name, default)
        return getattr(rec, name, default)

    # Timestamp handling
    raw_time = get("time", get("timestamp"))
    if isinstance(raw_time, datetime):
        if raw_time.tzinfo is None:
            raw_time = raw_time.replace(tzinfo=timezone.utc)
        ts_str = raw_time.isoformat()
    elif raw_time is not None:
        ts_str = str(raw_time)
    else:
        ts_str = datetime.now(timezone.utc).isoformat()

    # Unpack nested dicts if present
    sensor_data = get("sensor_data") if isinstance(get("sensor_data"), dict) else {}
    comm_in = get("communication") if isinstance(get("communication"), dict) else {}

    # Gyroscope: preserve if present, otherwise null
    gyro_in = get("gyro") or sensor_data.get("gyro") or {}
    if isinstance(gyro_in, dict):
        gyro_x = gyro_in.get("x", get("gyro_x"))
        gyro_y = gyro_in.get("y", get("gyro_y"))
        gyro_z = gyro_in.get("z", get("gyro_z"))
    else:
        gyro_x = get("gyro_x")
        gyro_y = get("gyro_y")
        gyro_z = get("gyro_z")

    gyro_obj = {
        "x": float(gyro_x) if gyro_x is not None else None,
        "y": float(gyro_y) if gyro_y is not None else None,
        "z": float(gyro_z) if gyro_z is not None else None,
    }

    # Accelerometer: preserve if present, otherwise null
    accel_in = get("accel") or get("accelerometer") or sensor_data.get("accelerometer") or sensor_data.get("accel") or {}
    if isinstance(accel_in, dict):
        accel_x = accel_in.get("x", get("accel_x"))
        accel_y = accel_in.get("y", get("accel_y"))
        accel_z = accel_in.get("z", get("accel_z"))
    else:
        accel_x = get("accel_x")
        accel_y = get("accel_y")
        accel_z = get("accel_z")

    accel_obj = {
        "x": float(accel_x) if accel_x is not None else None,
        "y": float(accel_y) if accel_y is not None else None,
        "z": float(accel_z) if accel_z is not None else None,
    }

    # Orientation: pitch and roll in degrees
    ori_in = get("orientation") or sensor_data.get("orientation") or {}
    if isinstance(ori_in, dict) and (ori_in.get("pitch") is not None or ori_in.get("roll") is not None):
        pitch = float(ori_in.get("pitch", 0.0) or 0.0)
        roll = float(ori_in.get("roll", 0.0) or 0.0)
    elif get("pitch_deg") is not None or get("roll_deg") is not None:
        pitch = float(get("pitch_deg", 0.0) or 0.0)
        roll = float(get("roll_deg", 0.0) or 0.0)
    else:
        pitch = float((get("pitch_mdeg", 0) or 0) / 1000.0)
        roll = float((get("roll_mdeg", 0) or 0) / 1000.0)

    # Vibration: rms in mg or m/s^2, peak_hz
    vib_in = get("vibration") or sensor_data.get("vibration") or {}
    if isinstance(vib_in, dict) and (vib_in.get("rms_mg") is not None or vib_in.get("rms") is not None):
        if vib_in.get("rms_mg") is not None:
            rms_mg = float(vib_in.get("rms_mg", 0.0) or 0.0)
        else:
            # rms in m/s^2 converted to mg
            rms_mg = float(vib_in.get("rms", 0.0) or 0.0) * 1000.0 / 9.80665
        peak_hz = float(vib_in["peak_hz"]) if vib_in.get("peak_hz") is not None else None
    elif get("vibration_rms_mg") is not None:
        rms_mg = float(get("vibration_rms_mg", 0.0) or 0.0)
        peak_hz = float(get("vibration_peak_hz")) if get("vibration_peak_hz") is not None else None
    elif get("vib_rms_mg") is not None:
        rms_mg = float(get("vib_rms_mg", 0.0) or 0.0)
        peak_hz = float(get("vib_peak_hz")) if get("vib_peak_hz") is not None else None
    elif get("vib_rms") is not None:
        rms_mg = float(get("vib_rms", 0.0) or 0.0) * 1000.0 / 9.80665
        peak_hz = float(get("vib_peak_hz")) if get("vib_peak_hz") is not None else None
    else:
        rms_mg = 0.0
        peak_hz = None

    # GPS: latitude, longitude, altitude, status
    gps_in = get("gps") or {}
    if isinstance(gps_in, dict):
        lat = gps_in.get("latitude", get("lat"))
        lon = gps_in.get("longitude", get("lon"))
        alt = gps_in.get("altitude_m", gps_in.get("altitude", get("altitude_m", get("alt_m"))))
        sats = gps_in.get("satellites")
        status = gps_in.get("status", get("gnss_status"))
        if status is None and sats is not None:
            status = 3 if sats >= 4 else (2 if sats == 3 else 0)
    else:
        lat = get("lat", get("latitude"))
        lon = get("lon", get("longitude"))
        alt = get("altitude_m", get("alt_m", get("altitude")))
        status = get("gnss_status")

    # Temperature & Battery
    temp_c_raw = get("temperature_c", get("temp_c", sensor_data.get("temperature_c", sensor_data.get("temp_c"))))
    if temp_c_raw is None and get("temp_c_x100") is not None:
        temp_c = float(get("temp_c_x100")) / 100.0
    elif temp_c_raw is not None:
        temp_c = float(temp_c_raw)
    else:
        temp_c = 25.0

    vbat_raw = get("battery_mv", get("vbat_mv", sensor_data.get("battery_mv", sensor_data.get("vbat_mv"))))
    vbat_mv = float(vbat_raw) if vbat_raw is not None else 3900.0

    # RF & Flags
    rssi_raw = get("rssi_dbm", get("rssi", comm_in.get("rssi_dbm")))
    rssi_dbm = float(rssi_raw) if rssi_raw is not None else -75.0

    snr_raw = get("snr_db", get("snr", comm_in.get("snr_db")))
    snr_db = float(snr_raw) if snr_raw is not None else 10.0

    flags = int(get("flags", 0) or 0)
    n_samples = int(get("n_samples", 1) or 1)
    x_m = get("x_m", get("x"))
    y_m = get("y_m", get("y"))

    node_id_val = str(get("node_label", get("node_id", get("addr", "UNKNOWN"))))

    return {
        "node_id": node_id_val,
        "timestamp": ts_str,
        "gyro": gyro_obj,
        "accel": accel_obj,
        "orientation": {
            "pitch": round(pitch, 5),
            "roll": round(roll, 5),
        },
        "vibration": {
            "rms_mg": round(rms_mg, 4) if rms_mg is not None else None,
            "peak_hz": round(peak_hz, 2) if peak_hz is not None else None,
        },
        "gps": {
            "latitude": float(lat) if lat is not None else None,
            "longitude": float(lon) if lon is not None else None,
            "altitude_m": float(alt) if alt is not None else None,
            "status": int(status) if status is not None else None,
        },
        "temperature_c": round(temp_c, 2),
        "battery_mv": round(vbat_mv, 1),
        "rssi_dbm": round(rssi_dbm, 1),
        "snr_db": round(snr_db, 1),
        "flags": flags,
        "x_m": float(x_m) if x_m is not None else None,
        "y_m": float(y_m) if y_m is not None else None,
        "n_samples": n_samples,
    }


def build_derived(
    field: Mapping[Any, Any] | None,
    node_labels: Mapping[Any, str] | None = None,
) -> dict[str, dict[str, float]]:
    """Convert backend FieldEstimate objects into ML derived physics data."""
    if not field:
        return {}
    node_labels = node_labels or {}
    derived: dict[str, dict[str, float]] = {}

    for addr, estimate in field.items():
        key = str(node_labels.get(addr, addr))
        sub = getattr(estimate, "subsidence_mm", None)
        strain = getattr(estimate, "strain_mm_per_m", None)
        if isinstance(estimate, dict):
            sub = estimate.get("subsidence_mm", sub)
            strain = estimate.get("strain_mm_per_m", strain)
        derived[key] = {
            "subsidence_mm": float(sub or 0.0),
            "strain_mm_per_m": float(strain or 0.0),
        }
    return derived


def build_ml_payload(
    nodes: Sequence[Any],
    history: Mapping[str, Sequence[Any]] | None = None,
    field: Mapping[Any, Any] | None = None,
    registered_positions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the complete Backend → ML request conforming to POST /predict."""
    ml_nodes = []
    node_labels: dict[Any, str] = {}

    for node in nodes:
        ml_node = telemetry_to_ml_node(node)
        node_addr = getattr(node, "node_addr", None)
        node_label = getattr(node, "node_label", None)
        if isinstance(node, dict):
            node_addr = node.get("node_addr", node.get("addr", node.get("node_id")))
            node_label = node.get("node_label", node.get("label"))

        if node_label:
            ml_node["node_id"] = str(node_label)
        if node_addr is not None and node_label:
            node_labels[node_addr] = str(node_label)
        ml_nodes.append(ml_node)

    # Normalize history
    clean_history: dict[str, list[dict[str, Any]]] = {}
    if history:
        for nid, hist_list in history.items():
            clean_history[str(nid)] = [
                telemetry_to_ml_node(item) if not (isinstance(item, dict) and "orientation" in item) else item
                for item in hist_list
            ]

    payload: dict[str, Any] = {
        "nodes": ml_nodes,
        "history": clean_history,
        "derived": build_derived(field or {}, node_labels),
    }
    if registered_positions:
        payload["registered_positions"] = dict(registered_positions)
    return payload


async def build_history(
    session: AsyncSession,
    node_ids: list[int],
    since: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """Load chronological telemetry history grouped by node label."""
    if not node_ids:
        return {}

    stmt = (
        sa.select(telemetry_t, nodes_t.c.label, nodes_t.c.addr, nodes_t.c.x_m, nodes_t.c.y_m)
        .join(nodes_t, nodes_t.c.id == telemetry_t.c.node_id)
        .where(
            telemetry_t.c.node_id.in_(node_ids),
            telemetry_t.c.time >= since,
        )
        .order_by(telemetry_t.c.node_id, telemetry_t.c.time)
    )

    rows = (await session.execute(stmt)).mappings().all()

    history: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        node_label = str(row.get("label") or f"NODE-{row.get('addr', row['node_id']):03d}")
        item = telemetry_to_ml_node(dict(row))
        item["node_id"] = node_label
        history.setdefault(node_label, []).append(item)

    return history