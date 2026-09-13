"""Automated Response-Contract Regression Test & Validator for MineGuard ML /predict.

Validates the production response schema:
TEST 1  — ROOT SCHEMA: Top-level keys and correct data types.
TEST 2  — OVERALL: Severity enum, alarm boolean, risk score range, and status consistency.
TEST 3  — FORECAST: 1h persistence, 6h/12h/24h damped trend, and null handling.
TEST 4  — TIME TO THRESHOLD: warning_hours, critical_hours, and strict contract enums.
TEST 5  — CONFIDENCE: Value ranges [0.0, 1.0] and float types.
TEST 6  — 21-NODE CONTRACT: Exactly 21 nodes, preserved IDs, deterministic ordering, no duplicates.
TEST 7  — SENSOR HEALTH: Correct health statuses and summary counts.
TEST 8  — PHYSICAL VS NON-PHYSICAL: Operational vibration, thermal cooling, and sensor fault separation.
TEST 9  — INSUFFICIENT HISTORY: Null forecast, null threshold ETA, and safe non-escalation.
TEST 10 — OOD: Out-of-distribution detection, degraded status, and suppressed false alarms.
TEST 11 — MALFORMED RESPONSE VALIDATION: Validator helper detecting malformed response payloads.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import pytest
from fastapi.testclient import TestClient

from service.app import app
from inference.pipeline import predict


client = TestClient(app)


def validate_predict_response(resp: dict[str, Any], expected_node_count: int | None = None) -> list[str]:
    """Validate a /predict response dictionary against the MineGuard ML contract."""
    errors: list[str] = []

    required_root_keys = {
        "timestamp": str,
        "model_version": str,
        "overall": dict,
        "data_sufficiency": dict,
        "data_quality": dict,
        "risk": dict,
        "anomaly": dict,
        "deformation_state": str,
        "forecast": (dict, type(None)),
        "time_to_threshold": dict,
        "spatial": dict,
        "physics": dict,
        "sensor_health": dict,
        "nodes": list,
        "dominant_factors": list,
        "explanation": str,
    }

    for key, expected_type in required_root_keys.items():
        if key not in resp:
            errors.append(f"Missing required root key: '{key}'")
        elif not isinstance(resp[key], expected_type):
            errors.append(f"Root key '{key}' has type {type(resp[key]).__name__}, expected {expected_type}")

    # Overall validation
    if "overall" in resp and isinstance(resp["overall"], dict):
        overall = resp["overall"]
        valid_severities = {"NORMAL", "WARNING", "CRITICAL", "SENSOR_FAULT"}
        valid_statuses = {"NORMAL", "WARNING", "CRITICAL", "SENSOR_FAULT", "INSUFFICIENT_HISTORY"}
        valid_risk_levels = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

        if overall.get("severity") not in valid_severities:
            errors.append(f"Invalid overall.severity: '{overall.get('severity')}'")
        if overall.get("status") not in valid_statuses:
            errors.append(f"Invalid overall.status: '{overall.get('status')}'")
        if not isinstance(overall.get("alarm"), bool):
            errors.append(f"overall.alarm must be bool, got {type(overall.get('alarm')).__name__}")
        if overall.get("risk_level") not in valid_risk_levels:
            errors.append(f"Invalid overall.risk_level: '{overall.get('risk_level')}'")
        risk_score = overall.get("risk_score")
        if not isinstance(risk_score, (int, float)) or not (0.0 <= risk_score <= 1.0):
            errors.append(f"overall.risk_score out of bounds [0.0, 1.0]: {risk_score}")

        # Top-level threshold prediction
        if "threshold_prediction" in overall and isinstance(overall["threshold_prediction"], dict):
            tp = overall["threshold_prediction"]
            valid_tp_statuses = {"INSUFFICIENT_HISTORY", "NOT_REACHED_IN_FORECAST", "ALREADY_EXCEEDED", "PREDICTED", "LOW_CONFIDENCE"}
            if tp.get("warning_status") not in valid_tp_statuses:
                errors.append(f"Invalid overall warning_status: '{tp.get('warning_status')}'")
            if tp.get("critical_status") not in valid_tp_statuses:
                errors.append(f"Invalid overall critical_status: '{tp.get('critical_status')}'")

    # Risk block validation
    if "risk" in resp and isinstance(resp["risk"], dict):
        conf = resp["risk"].get("confidence")
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            errors.append(f"risk.confidence out of bounds [0.0, 1.0]: {conf}")

    # Nodes array validation
    if "nodes" in resp and isinstance(resp["nodes"], list):
        nodes = resp["nodes"]
        if expected_node_count is not None and len(nodes) != expected_node_count:
            errors.append(f"Expected {expected_node_count} nodes, got {len(nodes)}")

        node_ids = [n.get("node_id") for n in nodes if isinstance(n, dict)]
        if len(node_ids) != len(set(node_ids)):
            errors.append("Duplicate node IDs detected in nodes array")

        valid_node_tp_statuses = {"INSUFFICIENT_HISTORY", "NOT_REACHED_IN_FORECAST", "ALREADY_EXCEEDED", "PREDICTED", "LOW_CONFIDENCE"}
        valid_health_statuses = {"HEALTHY", "SUSPECT", "FAULTY", "SENSOR_FAULT", "STALE_DATA"}

        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"Node at index {idx} is not a dict")
                continue

            # Node confidence
            node_conf = node.get("confidence")
            if not isinstance(node_conf, (int, float)) or not (0.0 <= node_conf <= 1.0):
                errors.append(f"Node[{idx}].confidence out of bounds: {node_conf}")

            # Node health
            health = node.get("health")
            if isinstance(health, dict):
                if health.get("status") not in valid_health_statuses:
                    errors.append(f"Node[{idx}] invalid health status: '{health.get('status')}'")

            # Node threshold prediction
            tp = node.get("threshold_prediction")
            if isinstance(tp, dict):
                w_status = tp.get("warning_status")
                c_status = tp.get("critical_status")
                if w_status not in valid_node_tp_statuses:
                    errors.append(f"Node[{idx}] invalid warning_status: '{w_status}'")
                if c_status not in valid_node_tp_statuses:
                    errors.append(f"Node[{idx}] invalid critical_status: '{c_status}'")

                # ETA consistency
                w_hours = tp.get("warning_hours")
                if w_status in {"INSUFFICIENT_HISTORY", "NOT_REACHED_IN_FORECAST", "LOW_CONFIDENCE"} and w_hours is not None:
                    errors.append(f"Node[{idx}] warning_hours must be null for status '{w_status}', got {w_hours}")
                elif w_status == "ALREADY_EXCEEDED" and w_hours != 0.0:
                    errors.append(f"Node[{idx}] warning_hours must be 0.0 for ALREADY_EXCEEDED, got {w_hours}")
                elif w_status == "PREDICTED" and (w_hours is None or w_hours <= 0.0):
                    errors.append(f"Node[{idx}] warning_hours must be > 0.0 for PREDICTED, got {w_hours}")

    return errors


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
# TEST 1 — ROOT SCHEMA
# ==============================================================================

def test_1_root_schema():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 22)]
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}

    res = predict(cur, hist)
    errors = validate_predict_response(res, expected_node_count=21)
    assert errors == [], f"Validation errors found: {errors}"


# ==============================================================================
# TEST 2 — OVERALL
# ==============================================================================

def test_2_overall():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.05)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    res = predict(cur, hist)
    overall = res["overall"]

    assert overall["severity"] in {"NORMAL", "WARNING", "CRITICAL", "SENSOR_FAULT"}
    assert isinstance(overall["alarm"], bool)
    assert 0.0 <= overall["risk_score"] <= 1.0
    assert overall["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert overall["status"] == "NORMAL"
    assert overall["severity"] == "NORMAL"
    assert overall["alarm"] is False


# ==============================================================================
# TEST 3 — FORECAST
# ==============================================================================

def test_3_forecast():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # Sufficient history with upward trend
    hist = _history_series("N1", [0.10, 0.14, 0.18, 0.22, 0.26], now)
    cur = [_record("N1", now, pitch=0.30)]

    res = predict(cur, {"N1": hist})
    fc = res["forecast"]
    assert fc is not None
    for hour in (1, 6, 12, 24):
        key = str(hour) if str(hour) in fc else f"{hour}h"
        assert key in fc
        assert isinstance(fc[key]["tilt_deg"], (int, float))
        assert fc[key]["tilt_deg"] >= 0.0

    # 1h persistence check: projected tilt at 1h equals current resultant tilt
    key_1 = "1" if "1" in fc else "1h"
    assert fc[key_1]["tilt_deg"] == pytest.approx(0.30, abs=0.01)

    # Node forecast includes both 1h and 1
    node_fc = res["nodes"][0]["forecast"]
    assert "1h" in node_fc and "1" in node_fc

    # Insufficient history test: forecast must be None
    res_insuf = predict([_record("N1", now, pitch=0.30)], {})
    assert res_insuf["forecast"] is None


# ==============================================================================
# TEST 4 — TIME TO THRESHOLD
# ==============================================================================

def test_4_time_to_threshold():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    valid_statuses = {"INSUFFICIENT_HISTORY", "NOT_REACHED_IN_FORECAST", "ALREADY_EXCEEDED", "PREDICTED", "LOW_CONFIDENCE"}

    # Case A: Predicted positive ETA
    hist_a = _history_series("N1", [0.10, 0.14, 0.18, 0.22, 0.26], now)
    res_a = predict([_record("N1", now, pitch=0.30)], {"N1": hist_a})
    tp_a = res_a["nodes"][0]["threshold_prediction"]
    assert tp_a["warning_status"] == "PREDICTED"
    assert tp_a["warning_hours"] is not None
    assert tp_a["warning_hours"] > 0.0

    # Case B: Already exceeded (tilt 0.65 >= 0.50 warning)
    hist_b = _history_series("N1", [0.45, 0.50, 0.55, 0.60, 0.62], now)
    res_b = predict([_record("N1", now, pitch=0.65)], {"N1": hist_b})
    tp_b = res_b["nodes"][0]["threshold_prediction"]
    assert tp_b["warning_status"] == "ALREADY_EXCEEDED"
    assert tp_b["warning_hours"] == 0.0

    # Case C: Not reached in forecast (flat tilt)
    hist_c = _history_series("N1", [0.08, 0.08, 0.08, 0.08, 0.08], now)
    res_c = predict([_record("N1", now, pitch=0.08)], {"N1": hist_c})
    tp_c = res_c["nodes"][0]["threshold_prediction"]
    assert tp_c["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert tp_c["warning_hours"] is None

    # Verify all statuses are valid
    for tp in (tp_a, tp_b, tp_c):
        assert tp["warning_status"] in valid_statuses
        assert tp["critical_status"] in valid_statuses


# ==============================================================================
# TEST 5 — CONFIDENCE
# ==============================================================================

def test_5_confidence():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.05)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    res = predict(cur, hist)
    assert isinstance(res["risk"]["confidence"], (int, float))
    assert 0.0 <= res["risk"]["confidence"] <= 1.0

    n1 = res["nodes"][0]
    assert isinstance(n1["confidence"], (int, float))
    assert 0.0 <= n1["confidence"] <= 1.0


# ==============================================================================
# TEST 6 — 21-NODE CONTRACT
# ==============================================================================

def test_6_21_node_contract():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    expected_ids = [f"NODE-{i:03d}" for i in range(1, 22)]
    cur = [_record(nid, now, pitch=0.05) for nid in expected_ids]
    hist = {nid: _history_series(nid, [0.05]*5, now) for nid in expected_ids}

    res = predict(cur, hist)
    output_nodes = res["nodes"]

    assert len(output_nodes) == 21
    output_ids = [n["node_id"] for n in output_nodes]
    # Exact matching deterministic ordering preserved
    assert output_ids == expected_ids
    # No duplicates
    assert len(set(output_ids)) == 21


# ==============================================================================
# TEST 7 — SENSOR HEALTH
# ==============================================================================

def test_7_sensor_health():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [
        _record("N1", now, pitch=0.05),
        _record("N2", now, pitch=0.05, bat=3100.0, flags=1),  # Faulty
    ]
    hist = {
        "N1": _history_series("N1", [0.050, 0.051, 0.049, 0.050, 0.051], now),
        "N2": _history_series("N2", [0.050, 0.051, 0.049, 0.050, 0.051], now),
    }

    res = predict(cur, hist)
    by_id = {n["node_id"]: n for n in res["nodes"]}

    assert by_id["N1"]["health"]["status"] == "HEALTHY"
    assert by_id["N2"]["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert "N2" in res["sensor_health"]["faulty_nodes"]
    assert res["sensor_health"]["healthy_nodes"] == 1


# ==============================================================================
# TEST 8 — PHYSICAL VS NON-PHYSICAL EVENTS
# ==============================================================================

def test_8_physical_vs_non_physical():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)

    # 1. Operational vibration does NOT cause physical alarm
    hist_vib = _history_series("N1", [0.04]*5, now, vib=50.0)
    res_vib = predict([_record("N1", now, pitch=0.04, vib=60.0)], {"N1": hist_vib})
    assert res_vib["overall"]["alarm"] is False
    assert res_vib["overall"]["severity"] == "NORMAL"
    assert res_vib["nodes"][0]["deformation"]["status"] == "NORMAL"

    # 2. Thermal cooling does NOT cause physical alarm
    hist_cool = _history_series("N1", [0.12, 0.10, 0.08, 0.06, 0.05], now)
    res_cool = predict([_record("N1", now, pitch=0.04)], {"N1": hist_cool})
    assert res_cool["overall"]["alarm"] is False
    assert res_cool["overall"]["severity"] == "NORMAL"

    # 3. Sensor fault is separated from physical deformation
    hist_fault = _history_series("N1", [0.05]*5, now)
    res_fault = predict([_record("N1", now, pitch=0.25, bat=3100.0, flags=1)], {"N1": hist_fault})
    assert res_fault["overall"]["alarm"] is False
    assert res_fault["overall"]["severity"] == "SENSOR_FAULT"
    assert res_fault["nodes"][0]["deformation"]["status"] == "SUPPRESSED"

    # 4. Genuine corroborated deformation produces physical alarm
    hist_phys = _history_series("N1", [0.15, 0.25, 0.35, 0.45, 0.55], now)
    res_phys = predict([_record("N1", now, pitch=0.62)], {"N1": hist_phys})
    assert res_phys["overall"]["alarm"] is True
    assert res_phys["overall"]["severity"] in {"WARNING", "CRITICAL"}
    assert res_phys["nodes"][0]["deformation"]["status"] == "CONFIRMED_PHYSICAL"


# ==============================================================================
# TEST 9 — INSUFFICIENT HISTORY
# ==============================================================================

def test_9_insufficient_history():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.15)]
    res = predict(cur, {})

    assert res["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert res["forecast"] is None
    assert res["time_to_threshold"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert res["time_to_threshold"]["warning_hours"] is None
    assert res["overall"]["alarm"] is False
    assert res["overall"]["severity"] == "NORMAL"


# ==============================================================================
# TEST 10 — OOD
# ==============================================================================

def test_10_ood():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    # Temperature 85 C is physically out-of-distribution for mine sensor
    cur = [_record("N1", now, pitch=0.05, temp=85.0)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    res = predict(cur, hist)
    assert res["data_quality"]["out_of_distribution"] is True
    assert res["overall"]["alarm"] is False

    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    assert n1["threshold_prediction"]["warning_status"] == "LOW_CONFIDENCE"
    assert n1["threshold_prediction"]["warning_hours"] is None


# ==============================================================================
# TEST 11 — MALFORMED RESPONSE VALIDATION
# ==============================================================================

def test_11_malformed_response_validation():
    now = datetime(2026, 9, 11, 7, 30, tzinfo=timezone.utc)
    cur = [_record("N1", now, pitch=0.05)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}

    valid_res = predict(cur, hist)
    assert validate_predict_response(valid_res, expected_node_count=1) == []

    # 1. Missing required root field
    bad_missing = dict(valid_res)
    del bad_missing["overall"]
    errs = validate_predict_response(bad_missing)
    assert any("Missing required root key: 'overall'" in e for e in errs)

    # 2. Wrong type for alarm (string instead of bool)
    bad_alarm = dict(valid_res)
    bad_alarm["overall"] = dict(valid_res["overall"])
    bad_alarm["overall"]["alarm"] = "true"  # type error
    errs = validate_predict_response(bad_alarm)
    assert any("overall.alarm must be bool" in e for e in errs)

    # 3. Invalid severity string
    bad_sev = dict(valid_res)
    bad_sev["overall"] = dict(valid_res["overall"])
    bad_sev["overall"]["severity"] = "DANGER"  # invalid enum
    errs = validate_predict_response(bad_sev)
    assert any("Invalid overall.severity: 'DANGER'" in e for e in errs)

    # 4. Invalid threshold status
    bad_tp = dict(valid_res)
    bad_tp["nodes"] = [dict(valid_res["nodes"][0])]
    bad_tp["nodes"][0]["threshold_prediction"] = dict(valid_res["nodes"][0]["threshold_prediction"])
    bad_tp["nodes"][0]["threshold_prediction"]["warning_status"] = "PENDING"  # invalid status
    errs = validate_predict_response(bad_tp)
    assert any("invalid warning_status: 'PENDING'" in e for e in errs)

    # 5. Invalid confidence out of range
    bad_conf = dict(valid_res)
    bad_conf["risk"] = dict(valid_res["risk"])
    bad_conf["risk"]["confidence"] = 1.85  # out of bounds
    errs = validate_predict_response(bad_conf)
    assert any("risk.confidence out of bounds" in e for e in errs)

    # 6. Duplicate node IDs
    bad_dup = dict(valid_res)
    bad_dup["nodes"] = [dict(valid_res["nodes"][0]), dict(valid_res["nodes"][0])]
    errs = validate_predict_response(bad_dup)
    assert any("Duplicate node IDs" in e for e in errs)

    # 7. Wrong node count
    errs = validate_predict_response(valid_res, expected_node_count=21)
    assert any("Expected 21 nodes, got 1" in e for e in errs)
