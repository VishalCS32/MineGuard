"""Comprehensive Expanded Telemetry Test Suite for MineGuard ML.

Validates Phase 1 through Phase 10 requirements:
1.  Existing legacy payload (backwards compatibility)
2.  Payload with valid GPS (latitude, longitude, altitude_m)
3.  Payload without GPS
4.  Payload with accel XYZ (both SI m/s^2 and 'g' unit conversion)
5.  Payload with accel null (exact backend ml_payload.py format)
6.  Payload with GPS + accel
7.  Future-ready gyro fields null
8.  Future gyro values accepted but not used by production IForest
9.  Invalid GPS (out of range, non-numeric, malformed) does not crash
10. Invalid accel (non-numeric, infinite) does not crash
11. Missing optional fields
12. 21-node payload
13. Existing NORMAL scenario
14. Existing deformation scenarios (gradual & accelerating)
15. Existing vibration scenario (operational vibration separation)
16. Existing thermal scenario (cooling trend separation)
17. Existing sensor fault scenario (fault suppression)
18. Existing insufficient-history scenario (safe null forecasts)
19. Existing OOD scenario (out-of-distribution handling)
20. Existing recovery scenario (return to normal)
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Any
import pytest
from fastapi.testclient import TestClient

from data.telemetry import NodeTelemetry, STANDARD_GRAVITY
from features.engineering import build_features, NodeFeatures
from inference.pipeline import predict
from service.app import app
from experiments.candidate_features import (
    extract_candidate_accel_features,
    extract_candidate_geodetic_features,
)

client = TestClient(app)


def _base_record(
    node_id: str,
    ts: datetime,
    *,
    pitch: float = 0.05,
    roll: float = 0.0,
    vib_rms: float = 18.0,
    vib_peak: float = 30.0,
    temp_c: float = 26.0,
    bat: float = 3950.0,
    rssi: float = -70.0,
    snr: float = 8.0,
    flags: int = 0,
    x: float = 0.0,
    y: float = 0.0,
    **kwargs: Any,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "node_id": node_id,
        "timestamp": ts.isoformat(),
        "pitch_deg": pitch,
        "roll_deg": roll,
        "vibration_rms_mg": vib_rms,
        "vibration_peak_hz": vib_peak,
        "temperature_c": temp_c,
        "n_samples": 32,
        "gnss_status": 14,
        "battery_mv": bat,
        "rssi_dbm": rssi,
        "snr_db": snr,
        "flags": flags,
        "x_m": x,
        "y_m": y,
    }
    rec.update(kwargs)
    return rec


def _history(
    node_id: str,
    pitches: list[float],
    now: datetime,
    dt: timedelta = timedelta(hours=1),
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return [
        _base_record(node_id, now - dt * (len(pitches) - i), pitch=p, **kwargs)
        for i, p in enumerate(pitches)
    ]


# ==============================================================================
# 1. Existing legacy payload
# ==============================================================================
def test_1_existing_legacy_payload():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = {
        "node_id": "NODE-001",
        "timestamp": now.isoformat(),
        "orientation": {"pitch": 0.05, "roll": 0.01},
        "vibration": {"rms_mg": 15.0, "peak_hz": 25.0},
        "temperature_c": 26.0,
    }
    node = NodeTelemetry.from_mapping(raw)
    assert node.node_id == "NODE-001"
    assert round(node.pitch_deg, 2) == 0.05
    assert round(node.roll_deg, 2) == 0.01
    assert node.latitude is None
    assert node.accel_x is None
    assert node.gyro_x is None

    # Without history, status is INSUFFICIENT_HISTORY and alarm is False
    res_no_hist = predict([raw])
    assert res_no_hist["overall"]["status"] == "INSUFFICIENT_HISTORY"
    assert res_no_hist["overall"]["alarm"] is False

    # With history, status is NORMAL
    hist = {"NODE-001": _history("NODE-001", [0.05] * 6, now)}
    res_with_hist = predict([raw], hist)
    assert res_with_hist["overall"]["status"] == "NORMAL"
    assert res_with_hist["overall"]["alarm"] is False


# ==============================================================================
# 2. Payload with GPS
# ==============================================================================
def test_2_payload_with_gps():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _base_record(
        "NODE-001",
        now,
        gps={
            "latitude": 23.7954,
            "longitude": 86.4278,
            "altitude_m": 210.5,
            "status": 14,
        },
    )
    node = NodeTelemetry.from_mapping(raw)
    assert node.latitude == 23.7954
    assert node.longitude == 86.4278
    assert node.altitude_m == 210.5
    assert node.gnss_status == 14

    frame = build_features([node])
    feat = frame.nodes[0]
    assert feat.latitude == 23.7954
    assert feat.longitude == 86.4278
    assert feat.altitude_m == 210.5


# ==============================================================================
# 3. Payload without GPS
# ==============================================================================
def test_3_payload_without_gps():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _base_record("NODE-001", now)
    raw.pop("gnss_status", None)
    raw.pop("gps", None)
    node = NodeTelemetry.from_mapping(raw)
    assert node.latitude is None
    assert node.longitude is None
    assert node.altitude_m is None
    assert node.gnss_status is None


# ==============================================================================
# 4. Payload with accel XYZ (both SI m/s^2 and 'g' unit conversion)
# ==============================================================================
def test_4_payload_with_accel_xyz():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)

    # 4A: SI units (m/s^2)
    raw_si = _base_record(
        "NODE-001", now,
        accel={"x": 0.05, "y": -0.10, "z": 9.80665},
    )
    node_si = NodeTelemetry.from_mapping(raw_si)
    assert node_si.accel_x == 0.05
    assert node_si.accel_y == -0.10
    assert node_si.accel_z == 9.80665

    frame = build_features([node_si])
    f_node = frame.nodes[0]
    assert f_node.accel_magnitude_mps2 is not None
    assert f_node.accel_dynamic_dev_mps2 is not None
    assert f_node.accel_horizontal_mps2 is not None
    assert f_node.accel_vertical_mps2 == 9.80665

    # 4B: 'g' units with explicit conversion
    raw_g = _base_record(
        "NODE-002", now,
        accel={"x": 0.0, "y": 0.0, "z": 1.0, "unit": "g"},
    )
    node_g = NodeTelemetry.from_mapping(raw_g)
    assert math.isclose(node_g.accel_z, STANDARD_GRAVITY, rel_tol=1e-4)


# ==============================================================================
# 5. Payload with accel null (exact backend ml_payload.py format)
# ==============================================================================
def test_5_payload_with_accel_null():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _base_record(
        "NODE-001", now,
        accel={"x": None, "y": None, "z": None},
    )
    node = NodeTelemetry.from_mapping(raw)
    assert node.accel_x is None
    assert node.accel_y is None
    assert node.accel_z is None

    frame = build_features([node])
    assert frame.nodes[0].accel_magnitude_mps2 is None


# ==============================================================================
# 6. Payload with GPS + accel
# ==============================================================================
def test_6_payload_with_gps_and_accel():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _base_record(
        "NODE-001", now,
        gps={"latitude": 23.7, "longitude": 86.4, "altitude_m": 150.0},
        accel={"x": 0.0, "y": 0.0, "z": 9.81},
    )
    node = NodeTelemetry.from_mapping(raw)
    assert node.latitude == 23.7
    assert node.accel_z == 9.81

    hist = {"NODE-001": _history("NODE-001", [0.05] * 6, now)}
    res = predict([raw], hist)
    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 7. Future-ready gyro fields null
# ==============================================================================
def test_7_future_ready_gyro_fields_null():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _base_record(
        "NODE-001", now,
        gyro={"x": None, "y": None, "z": None},
    )
    node = NodeTelemetry.from_mapping(raw)
    assert node.gyro_x is None
    assert node.gyro_y is None
    assert node.gyro_z is None


# ==============================================================================
# 8. Future gyro values accepted but not used by production IForest
# ==============================================================================
def test_8_future_gyro_values_accepted_not_used_by_production_iforest():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw_no_gyro = _base_record("NODE-001", now)
    raw_with_gyro = _base_record(
        "NODE-001", now,
        gyro={"x": 0.05, "y": -0.02, "z": 0.01},
    )

    hist = _history("NODE-001", [0.05] * 6, now)

    res1 = predict([raw_no_gyro], {"NODE-001": hist})
    res2 = predict([raw_with_gyro], {"NODE-001": hist})

    # The production IForest score and alarm decision must be identical
    assert res1["overall"]["status"] == res2["overall"]["status"]
    assert math.isclose(res1["risk"]["score"], res2["risk"]["score"], abs_tol=1e-3)
    assert math.isclose(
        res1["nodes"][0]["anomaly"]["score"],
        res2["nodes"][0]["anomaly"]["score"],
        abs_tol=1e-3,
    )


# ==============================================================================
# 9. Invalid GPS (out of range, non-numeric, malformed)
# ==============================================================================
def test_9_invalid_gps_handled_safely():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)

    # Out of range latitude (> 90) and longitude (< -180)
    raw_bad_range = _base_record(
        "NODE-001", now,
        gps={"latitude": 120.0, "longitude": -250.0},
    )
    node1 = NodeTelemetry.from_mapping(raw_bad_range)
    assert node1.latitude is None
    assert node1.longitude is None

    # Malformed non-numeric values
    raw_garbage = _base_record(
        "NODE-002", now,
        gps={"latitude": "corrupted_text", "longitude": None},
    )
    node2 = NodeTelemetry.from_mapping(raw_garbage)
    assert node2.latitude is None

    # Malformed GPS object (string instead of dict)
    raw_str_gps = _base_record("NODE-003", now, gps="broken_gps_string")
    node3 = NodeTelemetry.from_mapping(raw_str_gps)
    assert node3.latitude is None
    assert node3.longitude is None

    # End-to-end predict does not crash on malformed GPS records
    res = predict([raw_bad_range, raw_garbage, raw_str_gps])
    assert len(res["nodes"]) == 3
    assert res["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"


# ==============================================================================
# 10. Invalid accel (non-numeric, infinite)
# ==============================================================================
def test_10_invalid_accel_handled_safely():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _base_record(
        "NODE-001", now,
        accel={"x": "non_numeric", "y": float("inf"), "z": float("nan")},
    )
    node = NodeTelemetry.from_mapping(raw)
    assert node.accel_x is None
    assert node.accel_y is None
    assert node.accel_z is None

    hist = {"NODE-001": _history("NODE-001", [0.05] * 6, now)}
    res = predict([raw], hist)
    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 11. Missing optional fields
# ==============================================================================
def test_11_missing_optional_fields():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    minimal_raw = {
        "node_id": "MIN-01",
        "timestamp": now.isoformat(),
        "pitch_deg": 0.04,
        "roll_deg": 0.02,
        "vibration_rms_mg": 12.0,
        "vibration_peak_hz": 20.0,
    }
    node = NodeTelemetry.from_mapping(minimal_raw)
    assert node.temperature_c is None
    assert node.battery_mv is None
    assert node.latitude is None
    assert node.accel_x is None

    hist = {"MIN-01": [
        {
            "node_id": "MIN-01",
            "timestamp": (now - timedelta(hours=6 - i)).isoformat(),
            "pitch_deg": 0.04,
            "roll_deg": 0.02,
            "vibration_rms_mg": 12.0,
            "vibration_peak_hz": 20.0,
        }
        for i in range(6)
    ]}
    res = predict([minimal_raw], hist)
    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 12. 21-node payload
# ==============================================================================
def test_12_21_node_payload():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    nodes = []
    hist = {}
    for i in range(1, 22):
        nid = f"NODE-{i:03d}"
        rec = _base_record(
            nid, now,
            x=float(i * 20),
            y=0.0,
            gps={"latitude": 23.7 + i * 0.001, "longitude": 86.4 + i * 0.001},
            accel={"x": 0.0, "y": 0.0, "z": 9.81},
        )
        nodes.append(rec)
        hist[nid] = _history(nid, [0.05] * 6, now, x=float(i * 20), y=0.0)

    res = predict(nodes, hist)
    assert len(res["nodes"]) == 21
    assert res["overall"]["status"] == "NORMAL"


# ==============================================================================
# 13. Existing NORMAL scenario
# ==============================================================================
def test_13_existing_normal_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_base_record("N1", now, pitch=0.05)]
    hist = {"N1": _history("N1", [0.05] * 6, now)}
    res = predict(cur, hist)
    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 14. Existing deformation scenarios (gradual & accelerating)
# ==============================================================================
def test_14_existing_deformation_scenarios():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)

    # Accelerating persistent deformation
    pitches = [0.05, 0.08, 0.15, 0.28, 0.48, 0.75]
    hist = {"N1": _history("N1", pitches[:-1], now)}
    cur = [_base_record("N1", now, pitch=pitches[-1])]

    res = predict(cur, hist)
    n1 = res["nodes"][0]
    assert n1["anomaly"]["detected"] is True
    assert n1["deformation"]["status"] in {"CONFIRMED_PHYSICAL", "UNCONFIRMED_ANOMALY"}


# ==============================================================================
# 15. Existing vibration scenario (operational vibration separation)
# ==============================================================================
def test_15_existing_vibration_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # High vibration with flat tilt
    cur = [_base_record("N1", now, pitch=0.05, vib_rms=150.0)]
    hist = {"N1": _history("N1", [0.05] * 6, now, vib_rms=150.0)}
    res = predict(cur, hist)
    n1 = res["nodes"][0]
    assert n1["anomaly"]["evidence_status"] == "OPERATIONAL_VIBRATION"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 16. Existing thermal scenario (cooling trend separation)
# ==============================================================================
def test_16_existing_thermal_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    pitches = [0.12, 0.10, 0.08, 0.06, 0.05]
    hist = {"N1": _history("N1", pitches, now)}
    cur = [_base_record("N1", now, pitch=0.04)]
    res = predict(cur, hist)
    n1 = res["nodes"][0]
    assert n1["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 17. Existing sensor fault scenario (fault suppression)
# ==============================================================================
def test_17_existing_sensor_fault_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_base_record("N1", now, pitch=0.35, bat=3100.0, flags=1)]
    hist = {"N1": _history("N1", [0.05] * 6, now)}
    res = predict(cur, hist)
    n1 = res["nodes"][0]
    assert n1["health"]["status"] in {"FAULTY", "SENSOR_FAULT"}
    assert n1["deformation"]["status"] == "SUPPRESSED"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 18. Existing insufficient-history scenario (safe null forecasts)
# ==============================================================================
def test_18_existing_insufficient_history_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_base_record("N1", now, pitch=0.05)]
    res = predict(cur, {})
    assert res["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert res["forecast"] is None
    assert res["time_to_threshold"]["warning_hours"] is None


# ==============================================================================
# 19. Existing OOD scenario (out-of-distribution handling)
# ==============================================================================
def test_19_existing_ood_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_base_record("N1", now, pitch=82.0)]
    hist = {"N1": _history("N1", [0.05] * 6, now)}
    res = predict(cur, hist)
    assert res["data_quality"]["out_of_distribution"] is True


# ==============================================================================
# 20. Existing recovery scenario (return to normal)
# ==============================================================================
def test_20_existing_recovery_scenario():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # Series that had an event but has settled to a stable value
    pitches = [0.05, 0.15, 0.20, 0.20, 0.20, 0.20]
    hist = {"N1": _history("N1", pitches[:-1], now)}
    cur = [_base_record("N1", now, pitch=pitches[-1])]
    res = predict(cur, hist)
    # Rate of change is 0.0; should not trigger acute alarm
    assert res["overall"]["status"] in {"NORMAL", "MEDIUM", "LOW"}


# ==============================================================================
# 21. Candidate Research Features Isolated Testing
# ==============================================================================
def test_candidate_research_features_isolated():
    cand_accel = extract_candidate_accel_features(0.0, 0.0, 9.80665, vibration_rms_mg=20.0)
    assert cand_accel.dynamic_magnitude_mps2 == 0.0
    assert cand_accel.dynamic_shock_index == 0.0

    cand_geo = extract_candidate_geodetic_features(23.7955, 86.4278, 23.7954, 86.4278)
    assert cand_geo.horizontal_displacement_m is not None
    assert cand_geo.horizontal_displacement_m > 0.0
