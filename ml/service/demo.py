"""Development demo scenario generator for MineGuard ML service.

Provides deterministic, production-pipeline-compatible payloads representing
different physical mine conditions and security states:
- normal: All 21 nodes stable, resting baseline, no alarms.
- warning: Node NODE-001 exhibiting persistent positive deformation approaching 0.50 deg.
- critical: Multiple nodes exhibiting confirmed physical deformation exceeding 0.50 deg with high risk.
- sensor_fault: Node exhibiting low battery / hardware fault flags; physical alarm suppressed.
- hardware_theft: Node displaced >= 10m from registered position with 3 confirmed readings.

IMPORTANT ARCHITECTURAL INVARIANT:
This module is strictly for development, frontend integration, and mock evaluation.
It constructs standard dictionaries and does NOT import ml.simulator.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Mine site reference geodetic coordinates (Jharia Coalfield panel reference)
BASE_LAT = 23.750000
BASE_LON = 86.420000
METRES_TO_LAT_DEG = 1.0 / 111195.0

DEMO_SCENARIOS = (
    "normal",
    "warning",
    "critical",
    "sensor_fault",
    "hardware_theft",
)


def _offset_lat(lat: float, dist_m: float) -> float:
    return lat + (dist_m * METRES_TO_LAT_DEG)


def _make_node_payload(
    node_id: str,
    ts: datetime,
    *,
    pitch: float = 0.05,
    roll: float = 0.0,
    vibration_rms: float = 16.0,
    vibration_peak: float = 28.0,
    temperature: float = 27.5,
    battery: float = 3950.0,
    rssi: float = -72.0,
    snr: float = 8.5,
    flags: int = 0,
    x: float = 0.0,
    y: float = 0.0,
    lat: float | None = None,
    lon: float | None = None,
    gnss_status: int = 15,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "timestamp": ts.isoformat(),
        "pitch_deg": pitch,
        "roll_deg": roll,
        "vibration_rms_mg": vibration_rms,
        "vibration_peak_hz": vibration_peak,
        "temperature_c": temperature,
        "n_samples": 32,
        "battery_mv": battery,
        "rssi_dbm": rssi,
        "snr_db": snr,
        "flags": flags,
        "x_m": x,
        "y_m": y,
        "latitude": lat if lat is not None else BASE_LAT,
        "longitude": lon if lon is not None else BASE_LON,
        "gnss_status": gnss_status,
        "altitude_m": 210.0,
        "accel": {
            "x": 0.0,
            "y": 0.0,
            "z": 9.80665,
            "unit": "m/s2",
        },
        "gyro": {
            "x": None,
            "y": None,
            "z": None,
        },
    }


def generate_demo_payload(
    scenario: str = "normal",
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any] | None, dict[str, Any]]:
    """Generate a realistic 21-node telemetry payload for the requested scenario.

    Returns:
        nodes: Current observation frame (list of 21 node dictionaries).
        history: Chronological prior observations for each node.
        derived: Spatial/physics reconstruction values (or None).
        registered_positions: Configured installation coordinates for each node.
    """
    clean_scenario = scenario.strip().lower()
    if clean_scenario not in DEMO_SCENARIOS:
        raise ValueError(
            f"Invalid demo scenario: '{scenario}'. Supported: {', '.join(DEMO_SCENARIOS)}"
        )

    if now is None:
        now = datetime.now(timezone.utc).replace(microsecond=0)

    # 4 historical frames spaced 15 minutes apart (-60m, -45m, -30m, -15m) + current frame
    hist_times = [now - timedelta(minutes=15 * (4 - j)) for j in range(4)]

    current_nodes: list[dict[str, Any]] = []
    history: dict[str, list[dict[str, Any]]] = {}
    registered_positions: dict[str, Any] = {}
    derived: dict[str, Any] | None = None

    for i in range(1, 22):
        nid = f"NODE-{i:03d}"
        # 5x4+1 grid layout with 30m spacing
        x = float((i % 5) * 30.0)
        y = float((i // 5) * 30.0)
        node_lat = _offset_lat(BASE_LAT, y)
        node_lon = BASE_LON + ((x / 111195.0) if x != 0 else 0.0)

        registered_positions[nid] = {
            "latitude": node_lat,
            "longitude": node_lon,
        }

        if clean_scenario == "normal":
            # All 21 nodes stable, resting baseline ~0.05 deg, no alarms
            history[nid] = [
                _make_node_payload(nid, ht, pitch=0.045 + (j * 0.001), x=x, y=y, lat=node_lat, lon=node_lon)
                for j, ht in enumerate(hist_times)
            ]
            current_nodes.append(
                _make_node_payload(nid, now, pitch=0.050, x=x, y=y, lat=node_lat, lon=node_lon)
            )

        elif clean_scenario == "warning":
            # NODE-001 shows persistent positive tilt rate approaching 0.50 deg
            if nid == "NODE-001":
                hist_pitches = [0.15, 0.20, 0.26, 0.31]
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=hist_pitches[j], x=x, y=y, lat=node_lat, lon=node_lon)
                    for j, ht in enumerate(hist_times)
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.37, x=x, y=y, lat=node_lat, lon=node_lon)
                )
            else:
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                    for ht in hist_times
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                )

        elif clean_scenario == "critical":
            # NODE-001 and NODE-002 demonstrate severe deformation breaching critical 1.0 deg limit
            if nid == "NODE-001":
                hist_pitches = [0.40, 0.55, 0.72, 0.90]
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=hist_pitches[j], x=x, y=y, lat=node_lat, lon=node_lon)
                    for j, ht in enumerate(hist_times)
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=1.10, x=x, y=y, lat=node_lat, lon=node_lon)
                )
            elif nid == "NODE-002":
                hist_pitches = [0.35, 0.50, 0.68, 0.82]
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=hist_pitches[j], x=x, y=y, lat=node_lat, lon=node_lon)
                    for j, ht in enumerate(hist_times)
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.96, x=x, y=y, lat=node_lat, lon=node_lon)
                )
            else:
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                    for ht in hist_times
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                )

            derived = {
                "NODE-001": {"observed": 1.10, "expected": 1.05, "strain_mm_per_m": 3.4},
                "NODE-002": {"observed": 0.96, "expected": 0.90, "strain_mm_per_m": 2.8},
            }

        elif clean_scenario == "sensor_fault":
            # NODE-001 has battery fault (< 3300 mV) and protocol error flag (1) while pitch is resting baseline
            if nid == "NODE-001":
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=0.05, battery=3150.0, flags=1, x=x, y=y, lat=node_lat, lon=node_lon)
                    for ht in hist_times
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.05, battery=3100.0, flags=1, x=x, y=y, lat=node_lat, lon=node_lon)
                )
            else:
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                    for ht in hist_times
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                )

        elif clean_scenario == "hardware_theft":
            # NODE-001 is moved 14.7 metres from registered location across 3 consecutive observations
            theft_lat = _offset_lat(node_lat, 14.7)
            if nid == "NODE-001":
                # History shows node was moved for the last 2 frames
                history[nid] = [
                    _make_node_payload(nid, hist_times[0], pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon),
                    _make_node_payload(nid, hist_times[1], pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon),
                    _make_node_payload(nid, hist_times[2], pitch=0.05, x=x, y=y, lat=theft_lat, lon=node_lon),
                    _make_node_payload(nid, hist_times[3], pitch=0.05, x=x, y=y, lat=theft_lat, lon=node_lon),
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.05, x=x, y=y, lat=theft_lat, lon=node_lon)
                )
            else:
                history[nid] = [
                    _make_node_payload(nid, ht, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                    for ht in hist_times
                ]
                current_nodes.append(
                    _make_node_payload(nid, now, pitch=0.05, x=x, y=y, lat=node_lat, lon=node_lon)
                )

    return current_nodes, history, derived, registered_positions
