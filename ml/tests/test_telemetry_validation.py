"""Focused Real-Time Telemetry Validation Regression Test Suite for MineGuard ML.

Verifies that malformed, stale, impossible, or incomplete telemetry cannot silently produce
misleading NORMAL results or false physical mine alarms.

Sections:
1. Node ID Validation: Missing, empty, duplicate node IDs.
2. Timestamp Validation: Missing, malformed, stale, future timestamps, and temporal gaps.
3. Orientation Validation: Missing, non-numeric, extreme/out-of-domain tilt.
4. Vibration Validation: Negative RMS, non-numeric vibration, extreme vibration, operational vibration separation.
5. Temperature Validation: Missing, valid, unreasonable temperature, cooling trend separation.
6. Battery Validation: Missing, low battery, nominal battery.
7. GPS Validation: Missing GPS, missing coordinates, GNSS loss.
8. History Validation: Empty, insufficient, non-chronological, temporal gaps.
9. 21-Node Field Validation: Full 21 nodes, partial array, deterministic ordering.
10. Derived Physics Validation: Reconstructed subsidence/strain, missing vs provided Knothe expectations.
11. Malformed Payload Validation: Schema and type rejection at API boundary.
12. Safety Principle Invariant: Malformed, stale, insufficient, fault, OOD never produce false alarms.
"""

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from data.telemetry import NodeTelemetry, TelemetryValidationError
from inference.pipeline import predict
from service.app import app


client = TestClient(app)


def _record(node_id: str, ts: datetime, *, pitch: float = 0.05, roll: float = 0.0,
            vib: float = 18.0, temp: float = 28.0, bat: float = 3950.0,
            rssi: float = -70.0, snr: float = 8.0, flags: int = 0,
            x: float = 0.0, y: float = 0.0) -> dict:
    return {
        "node_id": node_id,
        "timestamp": ts.isoformat(),
        "pitch_deg": pitch,
        "roll_deg": roll,
        "vibration_rms_mg": vib,
        "vibration_peak_hz": 30.0,
        "temperature_c": temp,
        "n_samples": 32,
        "gnss_status": 14,
        "battery_mv": bat,
        "rssi_dbm": rssi,
        "snr_db": snr,
        "flags": flags,
        "x_m": x,
        "y_m": y,
    }


def _history_series(node_id: str, pitches, base_ts: datetime,
                    dt=timedelta(hours=1), **kwargs) -> list[dict]:
    hist = []
    for i, p in enumerate(pitches):
        t = base_ts - dt * (len(pitches) - i)
        hist.append(_record(node_id, t, pitch=p, **kwargs))
    return hist


# ==============================================================================
# 1. NODE ID VALIDATION
# ==============================================================================

def test_missing_node_id_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now)
    del raw["node_id"]

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_empty_node_id_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("", now)

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_duplicate_node_id_in_frame_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.05), _record("N1", now, pitch=0.06)]

    with pytest.raises(ValueError, match="duplicate node_id"):
        predict(cur)

    res = client.post("/predict", json={"nodes": cur})
    assert res.status_code == 422


# ==============================================================================
# 2. TIMESTAMP VALIDATION
# ==============================================================================

def test_missing_timestamp_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now)
    del raw["timestamp"]

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_malformed_timestamp_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now)
    raw["timestamp"] = "not-a-valid-iso-date"

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_stale_telemetry_detected_and_alarm_suppressed():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    stale_ts = now - timedelta(hours=3)
    # N1 telemetry is 3 hours behind newest reporting node N2
    cur = [_record("N1", stale_ts, pitch=0.05), _record("N2", now, pitch=0.05)]
    hist = {
        "N1": _history_series("N1", [0.05]*5, stale_ts),
        "N2": _history_series("N2", [0.05]*5, now),
    }

    res = predict(cur, hist)
    n1 = next(n for n in res["nodes"] if n["node_id"] == "N1")
    assert n1["health"]["status"] in {"STALE_DATA", "SUSPECT"}
    assert n1["deformation"]["status"] in {"STALE_DATA", "NORMAL"}
    assert "STALE_TELEMETRY" in n1["reason_codes"]
    assert res["overall"]["alarm"] is False


def test_future_timestamp_detected_as_ood():
    # Timestamp set to 2 years in the future
    future_ts = datetime(2028, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", future_ts, pitch=0.05)]
    hist = {"N1": _history_series("N1", [0.05]*5, future_ts)}

    res = predict(cur, hist)
    assert res["data_quality"]["out_of_distribution"] is True
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 3. ORIENTATION VALIDATION
# ==============================================================================

def test_missing_orientation_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now)
    del raw["pitch_deg"]

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_non_numeric_orientation_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now)
    raw["pitch_deg"] = "invalid_angle"

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_extreme_out_of_domain_tilt_detected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # Physically impossible tilt for in-situ ground monitoring (> 75 deg)
    cur = [_record("N1", now, pitch=85.0)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    res = predict(cur, hist)
    assert res["data_quality"]["out_of_distribution"] is True
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    assert n1["threshold_prediction"]["warning_status"] == "LOW_CONFIDENCE"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 4. VIBRATION VALIDATION
# ==============================================================================

def test_negative_vibration_rms_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now, vib=-15.0)

    with pytest.raises(TelemetryValidationError, match="non-negative"):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_non_numeric_vibration_rejected():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now)
    raw["vibration_rms_mg"] = "invalid_rms"

    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping(raw)

    res = client.post("/predict", json={"nodes": [raw]})
    assert res.status_code == 422


def test_operational_vibration_separated_from_deformation():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # High machinery vibration (65 mg) with resting tilt (0.04)
    hist = _history_series("N1", [0.04]*5, now, vib=60.0)
    cur = [_record("N1", now, pitch=0.04, vib=65.0)]

    res = predict(cur, {"N1": hist})
    assert res["overall"]["alarm"] is False
    assert res["overall"]["severity"] == "NORMAL"
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert n1["anomaly"]["evidence_status"] == "OPERATIONAL_VIBRATION"
    assert "OPERATIONAL_VIBRATION" in n1["reason_codes"]
    assert "operational vibration" in res["explanation"].lower()


# ==============================================================================
# 5. TEMPERATURE VALIDATION
# ==============================================================================

def test_missing_temperature_handled_safely():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    raw = _record("N1", now, temp=None)
    del raw["temperature_c"]
    node = NodeTelemetry.from_mapping(raw)
    assert node.temperature_c is None

    cur = [_record("N1", now, temp=None)]
    pitches = [0.050, 0.051, 0.049, 0.050, 0.051]
    hist = {"N1": [_record("N1", now - timedelta(hours=5 - i), pitch=pitches[i], temp=None) for i in range(5)]}
    res = predict(cur, hist)
    n1 = res["nodes"][0]
    # Missing temperature must NOT become a fault or false cooling
    assert n1["health"]["status"] == "HEALTHY"
    assert "THERMAL_COOLING" not in n1["reason_codes"]


def test_unreasonable_temperature_triggers_ood():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, temp=85.0)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    res = predict(cur, hist)
    assert res["data_quality"]["out_of_distribution"] is True
    assert any("temperature" in w.lower() for w in res["data_quality"]["warnings"])


def test_cooling_trend_is_classified_as_normal():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.12, 0.10, 0.08, 0.06, 0.05], now)
    cur = [_record("N1", now, pitch=0.04)]

    res = predict(cur, {"N1": hist})
    assert res["overall"]["alarm"] is False
    assert res["overall"]["severity"] == "NORMAL"
    assert res["nodes"][0]["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert "THERMAL_COOLING" in res["nodes"][0]["reason_codes"]


# ==============================================================================
# 6. BATTERY VALIDATION
# ==============================================================================

def test_missing_battery_does_not_trigger_low_battery():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, bat=None)]
    pitches = [0.050, 0.051, 0.049, 0.050, 0.051]
    hist = {"N1": [_record("N1", now - timedelta(hours=5 - i), pitch=pitches[i], bat=None) for i in range(5)]}

    res = predict(cur, hist)
    n1 = res["nodes"][0]
    assert n1["health"]["status"] == "HEALTHY"
    assert "LOW_BATTERY" not in n1["reason_codes"]


def test_low_battery_triggers_sensor_fault_and_suppresses_alarm():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.30, bat=3100.0, flags=1)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    res = predict(cur, hist)
    n1 = res["nodes"][0]
    assert n1["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert n1["deformation"]["status"] == "SUPPRESSED"
    assert "SENSOR_FAULT" in n1["reason_codes"]
    assert "LOW_BATTERY" in n1["reason_codes"]
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 7. GPS VALIDATION
# ==============================================================================

def test_missing_gps_and_coordinates_safe():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    rec1 = _record("N1", now, x=None, y=None)
    rec1["gnss_status"] = None
    node = NodeTelemetry.from_mapping(rec1)
    assert node.x_m is None
    assert node.y_m is None
    assert node.gnss_status is None

    # Missing coordinates must NOT fabricate spatial corroboration
    hist1 = _history_series("N1", [0.05]*5, now, x=None, y=None)
    res = predict([rec1], {"N1": hist1})
    assert res["nodes"][0]["deformation"]["evidence"]["spatial"] is False


def test_gnss_loss_triggers_reason_code():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    rec = _record("N1", now)
    rec["gnss_status"] = 0  # 0 satellites / no fix
    res = predict([rec], {"N1": _history_series("N1", [0.05]*5, now)})
    assert "GNSS_LOSS" in res["nodes"][0]["reason_codes"]


# ==============================================================================
# 8. HISTORY VALIDATION
# ==============================================================================

def test_empty_and_insufficient_history_safe():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.15)]
    res = predict(cur, {})

    assert res["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert res["forecast"] is None
    assert res["time_to_threshold"]["warning_hours"] is None
    assert res["time_to_threshold"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert res["overall"]["alarm"] is False


def test_non_chronological_history_is_sorted():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # Provided shuffled: 4h ago, 1h ago, 3h ago, 2h ago
    h1 = _record("N1", now - timedelta(hours=4), pitch=0.10)
    h2 = _record("N1", now - timedelta(hours=1), pitch=0.25)
    h3 = _record("N1", now - timedelta(hours=3), pitch=0.15)
    h4 = _record("N1", now - timedelta(hours=2), pitch=0.20)
    h5 = _record("N1", now - timedelta(hours=5), pitch=0.05)
    shuffled_hist = [h1, h2, h3, h4, h5]

    res = predict([_record("N1", now, pitch=0.30)], {"N1": shuffled_hist})
    # Automatic chronological sorting allows accurate rate calculation
    assert res["nodes"][0]["deformation"]["tilt_rate_deg_per_hour"] > 0.03


# ==============================================================================
# 9. 21-NODE FIELD VALIDATION
# ==============================================================================

def test_21_node_deterministic_order_preserved():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    input_ids = [f"NODE-{i:03d}" for i in range(1, 22)]
    cur = [_record(nid, now, pitch=0.05) for nid in input_ids]
    hist = {nid: _history_series(nid, [0.05]*5, now) for nid in input_ids}

    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    output_ids = [n["node_id"] for n in res["nodes"]]
    assert output_ids == input_ids


def test_partial_node_array_does_not_invent_missing_nodes():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # Only 18 nodes provided
    partial_ids = [f"NODE-{i:03d}" for i in range(1, 19)]
    cur = [_record(nid, now, pitch=0.05) for nid in partial_ids]
    hist = {nid: _history_series(nid, [0.05]*5, now) for nid in partial_ids}

    res = predict(cur, hist)
    assert len(res["nodes"]) == 18
    assert [n["node_id"] for n in res["nodes"]] == partial_ids


# ==============================================================================
# 10. DERIVED PHYSICS VALUES
# ==============================================================================

def test_derived_physics_subsidence_and_knothe_profile():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.05)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    # Case A: Only observed reconstruction supplied, expected missing
    derived_a = {
        "N1": {
            "subsidence_mm": 18.5,
            "strain_mm_per_m": 0.32,
        }
    }
    res_a = predict(cur, hist, derived=derived_a)
    assert res_a["physics"]["status"] == "UNAVAILABLE"
    assert res_a["physics"]["residual_score"] is None
    assert res_a["nodes"][0]["deformation"]["derived"]["subsidence_mm"] == 18.5

    # Case B: Both observed and Knothe expected profile supplied
    derived_b = {
        "N1": {
            "subsidence_mm": 18.5,
            "expected_subsidence_mm": 20.0,
            "strain_mm_per_m": 0.32,
            "expected_strain_mm_per_m": 0.35,
        }
    }
    res_b = predict(cur, hist, derived=derived_b)
    assert res_b["physics"]["status"] == "AVAILABLE"
    assert res_b["physics"]["residual_score"] is not None
    assert 0.0 <= res_b["physics"]["residual_score"] <= 1.0


# ==============================================================================
# 11. MALFORMED INPUT REJECTION
# ==============================================================================

def test_malformed_payload_rejected_by_api():
    # 1. Nodes not an array
    res1 = client.post("/predict", json={"nodes": "invalid_string"})
    assert res1.status_code == 422

    # 2. Nodes is empty
    res2 = client.post("/predict", json={"nodes": []})
    assert res2.status_code == 422

    # 3. History is not an object
    res3 = client.post("/predict", json={"nodes": [_record("N1", datetime.now(timezone.utc))], "history": "not_an_object"})
    assert res3.status_code == 422

    # 4. Invalid primitive type in node record
    bad_node = _record("N1", datetime.now(timezone.utc))
    bad_node["pitch_deg"] = None  # Pitch cannot be null
    res4 = client.post("/predict", json={"nodes": [bad_node]})
    assert res4.status_code == 422


# ==============================================================================
# 12. SAFETY PRINCIPLE INVARIANT
# ==============================================================================

def test_safety_invariants_never_create_unjustified_alarm():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)

    # 1. Stale data must not produce alarm
    stale_ts = now - timedelta(hours=3)
    res_stale = predict([_record("N1", stale_ts, pitch=0.05), _record("N2", now, pitch=0.05)],
                        {"N1": _history_series("N1", [0.05]*5, stale_ts), "N2": _history_series("N2", [0.05]*5, now)})
    assert res_stale["overall"]["alarm"] is False

    # 2. Insufficient history must not produce alarm
    res_insuf = predict([_record("N1", now, pitch=0.05)], {})
    assert res_insuf["overall"]["alarm"] is False

    # 3. Sensor fault must not produce alarm
    res_fault = predict([_record("N1", now, pitch=0.25, bat=3100.0, flags=1)],
                        {"N1": _history_series("N1", [0.05]*5, now)})
    assert res_fault["overall"]["alarm"] is False
    assert res_fault["overall"]["severity"] == "SENSOR_FAULT"

    # 4. OOD telemetry must not produce alarm
    res_ood = predict([_record("N1", now, pitch=80.0, temp=85.0)],
                      {"N1": _history_series("N1", [0.05]*5, now)})
    assert res_ood["overall"]["alarm"] is False
