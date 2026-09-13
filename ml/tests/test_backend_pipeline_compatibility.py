"""Tests for backend-sensor-pipeline payload compatibility, physics adapter, and optional fields."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inference.pipeline import predict
from models.estimators import SensorHealth
from service.app import app

client = TestClient(app)


def _make_backend_node(
    node_id: str,
    ts: datetime,
    *,
    pitch: float = 0.05,
    roll: float = 0.0,
    vib_rms: float = 18.0,
    vib_peak: float = 30.0,
    lat: float | None = 23.456,
    lon: float | None = 85.123,
    gnss_status: int = 14,
    x: float | None = None,
    y: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a telemetry item matching backend/app/ml_payload.py:telemetry_to_ml_node exactly."""
    node: dict[str, Any] = {
        "node_id": str(node_id),
        "timestamp": ts.isoformat(),
        "gyro": {"x": None, "y": None, "z": None},
        "accel": {"x": None, "y": None, "z": None},
        "orientation": {
            "pitch": pitch,
            "roll": roll,
        },
        "vibration": {
            "rms_mg": vib_rms,
            "peak_hz": vib_peak,
        },
        "gps": {
            "latitude": lat,
            "longitude": lon,
            "status": gnss_status,
        },
        "ml": {},
    }
    if x is not None:
        node["x_m"] = x
    if y is not None:
        node["y_m"] = y
    if extra:
        node.update(extra)
    return node


# ==============================================================================
# FIX 6: 21-NODE TEST WITH NESTED BACKEND SCHEMA
# ==============================================================================

def test_21_node_backend_schema_integration() -> None:
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    node_ids = [f"NODE-{i:03d}" for i in range(1, 22)]
    current_nodes: list[dict[str, Any]] = []
    history: dict[str, list[dict[str, Any]]] = {}

    for i, nid in enumerate(node_ids):
        x = float((i % 5) * 30.0)
        y = float((i // 5) * 30.0)

        if nid == "NODE-001":
            # NODE-001: Persistent deformation
            pitches = [0.05, 0.10, 0.15, 0.20, 0.25]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=pitches[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=0.30, x=x, y=y))

        elif nid == "NODE-002":
            # NODE-002: Spatially corroborated neighbor (distance 30m)
            pitches = [0.05, 0.09, 0.13, 0.17, 0.21]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=pitches[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=0.25, x=x, y=y))

        elif nid == "NODE-003":
            # NODE-003: Operational vibration (65 mg, normal tilt)
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], vib_rms=60.0, x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=0.05, vib_rms=65.0, x=x, y=y))

        elif nid == "NODE-004":
            # NODE-004: Low battery / sensor health fault
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=0.05, x=x, y=y, extra={"battery_mv": 3100.0, "flags": 1}))

        elif nid == "NODE-005":
            # NODE-005: Thermal cooling / settling (negative rate, tilt near baseline)
            pitches = [0.075, 0.070, 0.065, 0.060, 0.055]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=pitches[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=0.050, x=x, y=y))

        elif nid == "NODE-006":
            # NODE-006: Stale telemetry (2 hours old)
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            stale_ts = now - timedelta(hours=2)
            history[nid] = [
                _make_backend_node(nid, stale_ts - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, stale_ts, pitch=0.05, x=x, y=y))

        elif nid == "NODE-007":
            # NODE-007: OOD extreme tilt (82 deg) in isolated sector
            x_ood, y_ood = 500.0, 500.0
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x_ood, y=y_ood)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=82.0, x=x_ood, y=y_ood))

        elif nid == "NODE-008":
            # NODE-008: Insufficient history
            history[nid] = []
            current_nodes.append(_make_backend_node(nid, now, pitch=0.05, x=x, y=y))

        else:
            # NODE-009..021: Normal healthy nodes with natural MEMS noise floor
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_backend_node(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_backend_node(nid, now, pitch=0.05, x=x, y=y))

    # Backend derived field reconstruction
    derived = {
        "NODE-001": {"subsidence_mm": 25.4, "strain_mm_per_m": 1.2},
        "NODE-002": {"subsidence_mm": 18.2, "strain_mm_per_m": 0.8},
    }

    payload = {
        "nodes": current_nodes,
        "history": history,
        "derived": derived,
    }

    response = client.post("/predict", json=payload)
    assert response.status_code == 200, f"Error: {response.text}"
    body = response.json()

    # Verify node count and exact ordering
    assert len(body["nodes"]) == 21
    returned_ids = [n["node_id"] for n in body["nodes"]]
    assert returned_ids == node_ids

    nodes_map = {n["node_id"]: n for n in body["nodes"]}

    # Verify individual scenarios
    assert nodes_map["NODE-001"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert nodes_map["NODE-001"]["anomaly"]["confirmed_physical"] is True
    assert nodes_map["NODE-001"]["deformation"]["evidence"]["temporal"] is True
    assert "derived" in nodes_map["NODE-001"]["deformation"]
    assert nodes_map["NODE-001"]["deformation"]["derived"]["subsidence_mm"] == 25.4

    assert nodes_map["NODE-002"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert nodes_map["NODE-002"]["deformation"]["evidence"]["spatial"] is True

    assert nodes_map["NODE-003"]["anomaly"]["evidence_status"] == "OPERATIONAL_VIBRATION"
    assert nodes_map["NODE-003"]["deformation"]["status"] == "NORMAL"

    assert nodes_map["NODE-004"]["health"]["status"] in {"FAULTY", "SENSOR_FAULT"}
    assert nodes_map["NODE-004"]["deformation"]["status"] == "SUPPRESSED"

    assert nodes_map["NODE-005"]["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert nodes_map["NODE-005"]["deformation"]["status"] == "NORMAL"

    assert nodes_map["NODE-006"]["health"]["status"] == "STALE_DATA"
    assert nodes_map["NODE-006"]["deformation"]["status"] == "STALE_DATA"

    assert nodes_map["NODE-007"]["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    assert "OOD" in nodes_map["NODE-007"]["reason_codes"]
    assert nodes_map["NODE-007"]["confidence"] < nodes_map["NODE-009"]["confidence"]

    assert nodes_map["NODE-008"]["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert nodes_map["NODE-008"]["forecast"] is None
    assert nodes_map["NODE-008"]["confidence"] == 0.0

    # Verify normal nodes are not contaminated
    for i in range(9, 22):
        nid = f"NODE-{i:03d}"
        assert nodes_map[nid]["health"]["status"] == "HEALTHY", f"{nid} not healthy"
        assert nodes_map[nid]["deformation"]["status"] == "NORMAL", f"{nid} not normal"


# ==============================================================================
# FIX 7: PHYSICS TESTS
# ==============================================================================

def test_physics_backend_derived_without_expected() -> None:
    """Backend derived with subsidence_mm + strain_mm_per_m but no expected reference."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    cur = [_make_backend_node("01", now, pitch=0.10)]
    hist = [_make_backend_node("01", now - timedelta(hours=i), pitch=0.05) for i in range(5, 0, -1)]
    derived = {"01": {"subsidence_mm": 15.2, "strain_mm_per_m": 0.55}}

    res = predict(cur, {"01": hist}, derived=derived)

    # Status must be UNAVAILABLE because no reference expected value was provided
    assert res["physics"]["status"] == "UNAVAILABLE"
    assert res["physics"]["residual_score"] is None
    assert "Backend supplied array reconstruction" in res["physics"]["explanation"]
    assert "derived" in res["nodes"][0]["deformation"]
    assert res["nodes"][0]["deformation"]["derived"]["subsidence_mm"] == 15.2
    assert res["nodes"][0]["deformation"]["evidence"]["physics"] is False


def test_physics_missing_derived_entirely() -> None:
    """Missing expected/reference physics entirely."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    cur = [_make_backend_node("01", now, pitch=0.05)]
    hist = [_make_backend_node("01", now - timedelta(hours=i), pitch=0.05) for i in range(5, 0, -1)]

    res = predict(cur, {"01": hist}, derived=None)
    assert res["physics"]["status"] == "UNAVAILABLE"
    assert res["physics"]["residual_score"] is None
    assert "Knothe expected deformation was not supplied" in res["physics"]["explanation"]


def test_physics_valid_reference_supported() -> None:
    """When a valid expected reference is provided, status is AVAILABLE."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    cur = [_make_backend_node("01", now, pitch=0.20)]
    hist = [_make_backend_node("01", now - timedelta(hours=i), pitch=0.05) for i in range(5, 0, -1)]

    # Format with explicit observed and expected
    derived = {"01": {"observed": 0.20, "expected": 0.20}}
    res = predict(cur, {"01": hist}, derived=derived)
    assert res["physics"]["status"] == "AVAILABLE"
    assert res["physics"]["residual_score"] == 0.0
    assert res["nodes"][0]["deformation"]["evidence"]["physics"] is True

    # Format with subsidence_mm and expected_subsidence_mm
    derived_sub = {"01": {"subsidence_mm": 20.0, "expected_subsidence_mm": 20.0}}
    res_sub = predict(cur, {"01": hist}, derived=derived_sub)
    assert res_sub["physics"]["status"] == "AVAILABLE"
    assert res_sub["physics"]["residual_score"] == 0.0


# ==============================================================================
# FIX 8: HEALTH TESTS FOR MISSING & ACTUAL SENSOR TELEMETRY
# ==============================================================================

def test_missing_optional_fields_do_not_create_faults() -> None:
    """Verify missing optional telemetry fields (battery, RF, flags, temp, coords) do not create false faults."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    # Minimal node without battery, RF, flags, temp, coordinates
    cur = [_make_backend_node("01", now, pitch=0.05, x=None, y=None)]
    jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
    hist = [_make_backend_node("01", now - timedelta(hours=i), pitch=jitter[5 - i], x=None, y=None) for i in range(5, 0, -1)]

    res = predict(cur, {"01": hist})
    n = res["nodes"][0]

    # 1. Missing battery != LOW_BATTERY
    assert "low battery" not in n["health"]["reasons"]
    # 2. Missing RSSI != POOR_RSSI
    assert "degraded communication" not in n["health"]["reasons"]
    # 3. Missing SNR != POOR_SNR
    assert "degraded communication" not in n["health"]["reasons"]
    # 4. Missing flags != PROTOCOL_FAULT
    assert "protocol fault or calibration flag" not in n["health"]["reasons"]
    # Overall health must be HEALTHY
    assert n["health"]["status"] == "HEALTHY"
    # 5. Missing coordinates != spatial corroboration
    assert n["deformation"]["evidence"]["spatial"] is False
    # 6. Missing temperature != thermal cooling
    assert n["anomaly"]["evidence_status"] == "NORMAL"


def test_actual_sensor_faults_are_correctly_classified() -> None:
    """Verify actual fault measurements correctly degrade health and trigger proper fault statuses."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    jitter = [0.049, 0.051, 0.050, 0.051, 0.049]

    # 7. Actual low battery -> low battery reason
    cur_bat = [_make_backend_node("N_BAT", now, pitch=0.05, extra={"battery_mv": 3200.0})]
    hist_bat = [_make_backend_node("N_BAT", now - timedelta(hours=i), pitch=jitter[5 - i], extra={"battery_mv": 3200.0}) for i in range(5, 0, -1)]
    res_bat = predict(cur_bat, {"N_BAT": hist_bat})
    assert "low battery" in res_bat["nodes"][0]["health"]["reasons"]
    assert res_bat["nodes"][0]["health"]["status"] == "SUSPECT"

    # 8. Actual poor RF -> degraded communication reason
    cur_rf = [_make_backend_node("N_RF", now, pitch=0.05, extra={"rssi_dbm": -120.0, "snr_db": -8.0})]
    hist_rf = [_make_backend_node("N_RF", now - timedelta(hours=i), pitch=jitter[5 - i], extra={"rssi_dbm": -120.0, "snr_db": -8.0}) for i in range(5, 0, -1)]
    res_rf = predict(cur_rf, {"N_RF": hist_rf})
    assert "degraded communication" in res_rf["nodes"][0]["health"]["reasons"]
    assert res_rf["nodes"][0]["health"]["status"] == "SUSPECT"

    # 9. Actual protocol flag -> FAULTY / SENSOR_FAULT
    cur_flag = [_make_backend_node("N_FLG", now, pitch=0.05, extra={"flags": 1})]
    hist_flag = [_make_backend_node("N_FLG", now - timedelta(hours=i), pitch=jitter[5 - i], extra={"flags": 1}) for i in range(5, 0, -1)]
    res_flag = predict(cur_flag, {"N_FLG": hist_flag})
    assert "protocol fault or calibration flag" in res_flag["nodes"][0]["health"]["reasons"]
    assert res_flag["nodes"][0]["health"]["status"] in {"FAULTY", "SENSOR_FAULT"}


# ==============================================================================
# FIX 5: BACKEND NODE ID MAPPING (e.g. "01", "02")
# ==============================================================================

def test_backend_string_node_ids_match_history() -> None:
    """Verify numeric strings like '01' match correctly without losing history."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    cur = [_make_backend_node("01", now, pitch=0.08)]
    hist = [_make_backend_node("01", now - timedelta(hours=i), pitch=0.05) for i in range(5, 0, -1)]

    res = predict(cur, {"01": hist})
    assert res["nodes"][0]["node_id"] == "01"
    assert res["nodes"][0]["data_sufficiency"]["status"] == "READY"
    assert res["nodes"][0]["forecast"] is not None
