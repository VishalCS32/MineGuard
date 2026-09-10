"""Comprehensive 21-Node ML Integration and Regression Test Suite for MineGuard.

Tests:
1. Exact 21-node input/output contract preservation and deterministic ordering.
2. Heterogeneous node state handling:
   - NODE-001: Persistent physical deformation (temporal persistence, alarm).
   - NODE-002: Spatially corroborated deformation (neighboring co-movement before 0.50 deg).
   - NODE-003: Operational/machinery vibration (high vibe without displacement -> OPERATIONAL_VIBRATION).
   - NODE-004: Sensor health fault (battery degradation -> SENSOR_FAULT / SUPPRESSED).
   - NODE-005: Thermal cooling / settling (negative rate -> COOLING_NORMAL / THERMAL_COOLING).
   - NODE-006: Stale telemetry (old timestamp -> STALE_DATA).
   - NODE-007: Extreme / OOD tilt (exceeds operational limits -> OOD_LOW_CONFIDENCE).
   - NODE-008: Insufficient history (missing/short history -> INSUFFICIENT_HISTORY, null forecast).
   - NODE-009 to NODE-021: Healthy normal nodes (HEALTHY / NORMAL).
3. Complete top-level and node-level response schema compliance.
4. Forecast behavior (1h persistence, damped longer horizons, null on insufficient history).
5. Warning (0.50 deg) and critical (1.00 deg) time-to-threshold predictions (explicit statuses, clamped 0.0).
6. Remediation regression checks (A through G).
"""

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from fastapi.testclient import TestClient
import pytest

from inference.pipeline import compute_node_baseline, predict
from service.app import app


client = TestClient(app)


def _make_telemetry(node_id: str, ts: datetime, *, pitch: float = 0.05, roll: float = 0.0,
                    vib: float = 18.0, temp: float = 26.0, bat: float = 3950.0,
                    rssi: float = -70.0, snr: float = 8.0, flags: int = 0,
                    x: float = 0.0, y: float = 0.0) -> dict[str, Any]:
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


def _build_21_node_fixture(now: datetime | None = None) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    if now is None:
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    
    node_ids = [f"NODE-{i:03d}" for i in range(1, 22)]
    current_nodes: list[dict[str, Any]] = []
    history: dict[str, list[dict[str, Any]]] = {}

    for i, nid in enumerate(node_ids):
        # 5x4 grid layout with 30m spacing
        x = float((i % 5) * 30.0)
        y = float((i // 5) * 30.0)

        if nid == "NODE-001":
            # SCENARIO 1: Persistent physical deformation
            # 5 history points showing increasing tilt from resting 0.05 deg up to 0.25 deg
            hist_pitches = [0.05, 0.10, 0.15, 0.20, 0.25]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=hist_pitches[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=0.30, x=x, y=y))

        elif nid == "NODE-002":
            # SCENARIO 2: Spatially corroborated deformation
            # Neighbor of NODE-001 at distance 30m, also moving coherently
            hist_pitches = [0.05, 0.09, 0.13, 0.17, 0.21]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=hist_pitches[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=0.25, x=x, y=y))

        elif nid == "NODE-003":
            # SCENARIO 3: Operational/machinery vibration without deformation
            # Stable tilt (0.05 deg) with elevated 65 mg machinery vibration
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], vib=60.0, x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=0.05, vib=65.0, x=x, y=y))

        elif nid == "NODE-004":
            # SCENARIO 4: Sensor health fault
            # Low battery voltage (3100 mV) and protocol error flag
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=0.05, bat=3100.0, flags=1, x=x, y=y))

        elif nid == "NODE-005":
            # SCENARIO 5: Thermal cooling / settling
            # Negative tilt rate (-0.02 deg/h) settling from 0.075 to 0.050 deg
            hist_pitches = [0.075, 0.070, 0.065, 0.060, 0.055]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=hist_pitches[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=0.050, x=x, y=y))

        elif nid == "NODE-006":
            # SCENARIO 6: Stale telemetry
            # Timestamp is 2 hours older than the current frame
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            stale_ts = now - timedelta(hours=2)
            history[nid] = [
                _make_telemetry(nid, stale_ts - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, stale_ts, pitch=0.05, x=x, y=y))

        elif nid == "NODE-007":
            # SCENARIO 7: Extreme / out-of-distribution (OOD) tilt
            # 82 deg tilt exceeds the 75 deg physical operational boundary.
            # Placed at isolated sector (500m, 500m) to reflect borehole OOD without polluting local grid
            x_ood, y_ood = 500.0, 500.0
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x_ood, y=y_ood)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=82.0, x=x_ood, y=y_ood))

        elif nid == "NODE-008":
            # SCENARIO 8: Insufficient history
            # Empty prior telemetry history
            history[nid] = []
            current_nodes.append(_make_telemetry(nid, now, pitch=0.05, x=x, y=y))

        else:
            # SCENARIO 9: Normal healthy resting nodes (NODE-009 through NODE-021)
            # Resting tilt ~0.05 deg with natural MEMS sensor noise floor (~1 mdeg)
            jitter = [0.049, 0.051, 0.050, 0.051, 0.049]
            history[nid] = [
                _make_telemetry(nid, now - timedelta(minutes=15 * (5 - j)), pitch=jitter[j], x=x, y=y)
                for j in range(5)
            ]
            current_nodes.append(_make_telemetry(nid, now, pitch=0.05, x=x, y=y))

    return current_nodes, history, node_ids


# ==============================================================================
# TEST 1: 21-NODE OUTPUT CONTRACT & DETERMINISTIC ORDER PRESERVATION
# ==============================================================================

def test_21_node_count_order_and_uniqueness() -> None:
    current_nodes, history, expected_order = _build_21_node_fixture()
    payload = {"nodes": current_nodes, "history": history}

    response = client.post("/predict", json=payload)
    assert response.status_code == 200, f"API error: {response.text}"
    body = response.json()

    # Verify node count is exactly 21
    assert "nodes" in body
    out_nodes = body["nodes"]
    assert len(out_nodes) == 21, f"Expected 21 nodes, got {len(out_nodes)}"

    # Verify deterministic node ordering is exactly preserved
    actual_order = [n["node_id"] for n in out_nodes]
    assert actual_order == expected_order, f"Order mismatch: {actual_order} != {expected_order}"

    # Verify no duplicate node IDs
    assert len(set(actual_order)) == 21, "Duplicate node IDs found in response"


# ==============================================================================
# TEST 2: FULL TOP-LEVEL AND NODE-LEVEL SCHEMA VALIDATION
# ==============================================================================

def test_21_node_full_schema_completeness() -> None:
    current_nodes, history, _ = _build_21_node_fixture()
    payload = {"nodes": current_nodes, "history": history}

    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.json()

    # Verify all 16 required top-level fields
    required_top_keys = [
        "timestamp", "model_version", "overall", "data_sufficiency",
        "data_quality", "risk", "anomaly", "deformation_state",
        "forecast", "time_to_threshold", "spatial", "physics",
        "sensor_health", "nodes", "dominant_factors", "explanation"
    ]
    for key in required_top_keys:
        assert key in body, f"Missing top-level key: {key}"

    # Top-level overall sub-structure
    overall = body["overall"]
    assert "status" in overall
    assert "risk_level" in overall
    assert "risk_score" in overall
    assert "alarm" in overall
    assert "alarm_reason" in overall
    assert "threshold_prediction" in overall

    # Verify all 10 required per-node fields for every node
    required_node_keys = [
        "node_id", "health", "anomaly", "deformation", "risk",
        "forecast", "threshold_prediction", "confidence",
        "data_sufficiency", "reason_codes"
    ]
    for node_obj in body["nodes"]:
        for nkey in required_node_keys:
            assert nkey in node_obj, f"Node {node_obj.get('node_id')} missing key: {nkey}"

        # Check nested structures
        assert "status" in node_obj["health"]
        assert "score" in node_obj["health"]
        assert "confidence" in node_obj["health"]
        assert "reasons" in node_obj["health"]

        assert "detected" in node_obj["anomaly"]
        assert "score" in node_obj["anomaly"]
        assert "severity" in node_obj["anomaly"]
        assert "confirmed_physical" in node_obj["anomaly"]
        assert "evidence_status" in node_obj["anomaly"]

        assert "status" in node_obj["deformation"]
        assert "tilt_deg" in node_obj["deformation"]
        assert "tilt_rate_deg_per_hour" in node_obj["deformation"]
        assert "evidence" in node_obj["deformation"]
        assert "temporal" in node_obj["deformation"]["evidence"]
        assert "spatial" in node_obj["deformation"]["evidence"]
        assert "physics" in node_obj["deformation"]["evidence"]

        assert "score" in node_obj["risk"]
        assert "level" in node_obj["risk"]

        assert "warning_threshold_deg" in node_obj["threshold_prediction"]
        assert "critical_threshold_deg" in node_obj["threshold_prediction"]
        assert "warning_hours" in node_obj["threshold_prediction"]
        assert "critical_hours" in node_obj["threshold_prediction"]
        assert "warning_status" in node_obj["threshold_prediction"]
        assert "critical_status" in node_obj["threshold_prediction"]

        assert "status" in node_obj["data_sufficiency"]
        assert "required_prior_observations" in node_obj["data_sufficiency"]
        assert "available_prior_observations" in node_obj["data_sufficiency"]


# ==============================================================================
# TEST 3: EXACT 21-NODE SCENARIO-BY-SCENARIO VERIFICATION
# ==============================================================================

def test_21_node_heterogeneous_scenarios() -> None:
    current_nodes, history, _ = _build_21_node_fixture()
    payload = {"nodes": current_nodes, "history": history}

    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.json()
    nodes_map = {n["node_id"]: n for n in body["nodes"]}

    # NODE-001: Persistent physical deformation
    n1 = nodes_map["NODE-001"]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True
    assert n1["deformation"]["evidence"]["temporal"] is True
    assert "CONFIRMED_PHYSICAL_DEFORMATION" in n1["reason_codes"]
    assert body["overall"]["alarm"] is True

    # NODE-002: Spatially corroborated deformation
    n2 = nodes_map["NODE-002"]
    assert n2["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n2["anomaly"]["confirmed_physical"] is True
    assert n2["deformation"]["evidence"]["spatial"] is True
    assert "SPATIAL_CORROBORATION" in n2["reason_codes"]

    # NODE-003: Operational/machinery vibration without deformation
    n3 = nodes_map["NODE-003"]
    assert n3["anomaly"]["evidence_status"] == "OPERATIONAL_VIBRATION"
    assert n3["deformation"]["status"] == "NORMAL"
    assert n3["anomaly"]["confirmed_physical"] is False
    assert "OPERATIONAL_VIBRATION" in n3["reason_codes"]

    # NODE-004: Sensor health fault
    n4 = nodes_map["NODE-004"]
    assert n4["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert n4["deformation"]["status"] == "SUPPRESSED"
    assert n4["anomaly"]["confirmed_physical"] is False
    assert "LOW_BATTERY" in n4["reason_codes"] or "PROTOCOL_FAULT" in n4["reason_codes"]

    # NODE-005: Thermal cooling / settling
    n5 = nodes_map["NODE-005"]
    assert n5["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert n5["deformation"]["status"] == "NORMAL"
    assert n5["anomaly"]["confirmed_physical"] is False
    assert "THERMAL_COOLING" in n5["reason_codes"]

    # NODE-006: Stale telemetry
    n6 = nodes_map["NODE-006"]
    assert n6["health"]["status"] == "STALE_DATA"
    assert n6["deformation"]["status"] == "STALE_DATA"
    assert n6["anomaly"]["evidence_status"] == "STALE_DATA"
    assert "STALE_TELEMETRY" in n6["reason_codes"]

    # NODE-007: Extreme / out-of-distribution tilt
    n7 = nodes_map["NODE-007"]
    assert n7["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    assert n7["anomaly"]["evidence_status"] == "SUSPECT"
    assert n7["confidence"] < nodes_map["NODE-009"]["confidence"], "OOD node must have reduced confidence"
    assert "OOD" in n7["reason_codes"]

    # NODE-008: Insufficient history
    n8 = nodes_map["NODE-008"]
    assert n8["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert n8["deformation"]["status"] == "INSUFFICIENT_HISTORY"
    assert n8["forecast"] is None
    assert n8["threshold_prediction"]["warning_hours"] is None
    assert n8["threshold_prediction"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert n8["threshold_prediction"]["critical_status"] == "INSUFFICIENT_HISTORY"
    assert n8["confidence"] == 0.0
    assert "INSUFFICIENT_HISTORY" in n8["reason_codes"]

    # NODE-009 through NODE-021: Normal healthy nodes
    for i in range(9, 22):
        nid = f"NODE-{i:03d}"
        node_obj = nodes_map[nid]
        assert node_obj["health"]["status"] == "HEALTHY", f"{nid} not healthy"
        assert node_obj["anomaly"]["detected"] is False, f"{nid} anomaly falsely detected"
        assert node_obj["deformation"]["status"] == "NORMAL", f"{nid} deformation not normal"
        assert node_obj["anomaly"]["confirmed_physical"] is False, f"{nid} false physical confirm"


# ==============================================================================
# TEST 4: FORECAST BEHAVIOR & PERSISTENCE / DAMPED TREND LOGIC
# ==============================================================================

def test_forecast_consistency_and_horizons() -> None:
    current_nodes, history, _ = _build_21_node_fixture()
    payload = {"nodes": current_nodes, "history": history}

    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.json()
    nodes_map = {n["node_id"]: n for n in body["nodes"]}

    # Sufficient history node: NODE-001
    n1 = nodes_map["NODE-001"]
    fc = n1["forecast"]
    assert fc is not None
    for h in ["1h", "6h", "12h", "24h"]:
        assert h in fc
        val = fc[h]["tilt_deg"]
        assert val is not None
        assert isfinite(val)
        assert val >= 0.0

    # 1h forecast must equal persistence (current tilt)
    assert round(fc["1h"]["tilt_deg"], 2) == round(n1["deformation"]["tilt_deg"], 2)

    # Insufficient history node: NODE-008 must be null
    n8 = nodes_map["NODE-008"]
    assert n8["forecast"] is None


# ==============================================================================
# TEST 5: TIME-TO-THRESHOLD CLAMPING, STATUSES & EXPLICIT NULLS
# ==============================================================================

def test_time_to_threshold_deterministic_contracts() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    
    # 1. Already exceeded warning (tilt = 0.65 deg)
    hist_warn = [_make_telemetry("N_WARN", now - timedelta(hours=i), pitch=0.60) for i in range(5, 0, -1)]
    cur_warn = [_make_telemetry("N_WARN", now, pitch=0.65)]
    res_warn = predict(cur_warn, {"N_WARN": hist_warn})
    tp_warn = res_warn["nodes"][0]["threshold_prediction"]
    assert tp_warn["warning_hours"] == 0.0
    assert tp_warn["warning_status"] == "ALREADY_EXCEEDED"

    # 2. Already exceeded critical (tilt = 1.10 deg)
    hist_crit = [_make_telemetry("N_CRIT", now - timedelta(hours=i), pitch=1.05) for i in range(5, 0, -1)]
    cur_crit = [_make_telemetry("N_CRIT", now, pitch=1.10)]
    res_crit = predict(cur_crit, {"N_CRIT": hist_crit})
    tp_crit = res_crit["nodes"][0]["threshold_prediction"]
    assert tp_crit["critical_hours"] == 0.0
    assert tp_crit["critical_status"] == "ALREADY_EXCEEDED"

    # 3. Predictable crossing within 24h: current = 0.20, rate = 0.02 deg/h
    # Expected hours = (0.50 - 0.20) / 0.02 = 15.0h
    hist_pred = [_make_telemetry("N_PRED", now - timedelta(hours=i), pitch=0.20 - 0.02 * i) for i in range(5, 0, -1)]
    cur_pred = [_make_telemetry("N_PRED", now, pitch=0.20)]
    res_pred = predict(cur_pred, {"N_PRED": hist_pred})
    tp_pred = res_pred["nodes"][0]["threshold_prediction"]
    assert tp_pred["warning_status"] == "PREDICTED"
    assert tp_pred["warning_hours"] is not None
    assert 10.0 <= tp_pred["warning_hours"] <= 20.0

    # 4. Zero rate / Static node: warning not reached
    hist_stat = [_make_telemetry("N_STAT", now - timedelta(hours=i), pitch=0.08) for i in range(5, 0, -1)]
    cur_stat = [_make_telemetry("N_STAT", now, pitch=0.08)]
    res_stat = predict(cur_stat, {"N_STAT": hist_stat})
    tp_stat = res_stat["nodes"][0]["threshold_prediction"]
    assert tp_stat["warning_hours"] is None
    assert tp_stat["warning_status"] == "NOT_REACHED_IN_FORECAST"


# ==============================================================================
# TEST 6: REMEDIATION REGRESSION LOGIC (A THROUGH G)
# ==============================================================================

def test_remediation_regression_protections() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)

    # Protection A: Negative cooling rate must NOT become positive deformation
    hist_cool = [_make_telemetry("N_COOL", now - timedelta(minutes=15 * i), pitch=0.08 - 0.005 * (4 - i)) for i in range(4, -1, -1)]
    cur_cool = [_make_telemetry("N_COOL", now, pitch=0.055)]
    res_cool = predict(cur_cool, {"N_COOL": hist_cool})
    assert res_cool["nodes"][0]["deformation"]["status"] == "NORMAL"
    assert res_cool["nodes"][0]["anomaly"]["confirmed_physical"] is False

    # Protection B: Small resting sensor offset evaluated relative to node baseline
    hist_bias = [_make_telemetry("N_BIAS", now - timedelta(minutes=15 * i), pitch=0.08) for i in range(5, 0, -1)]
    cur_bias = [_make_telemetry("N_BIAS", now, pitch=0.085)]
    res_bias = predict(cur_bias, {"N_BIAS": hist_bias})
    assert res_bias["nodes"][0]["deformation"]["status"] == "NORMAL"

    # Protection C: Baseline does not chase active deformation
    hist_deform = [_make_telemetry("N_DEF", now - timedelta(minutes=15 * (10 - i)), pitch=p)
                   for i, p in enumerate([0.05, 0.05, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.22])]
    b_est, _ = compute_node_baseline(hist_deform)
    assert b_est <= 0.065, f"Baseline chased deformation! Baseline: {b_est}"

    # Protection D: Vibration without displacement remains operational vibration
    hist_vib = [_make_telemetry("N_VIB", now - timedelta(minutes=15 * i), pitch=0.05, vib=55.0) for i in range(5, 0, -1)]
    cur_vib = [_make_telemetry("N_VIB", now, pitch=0.05, vib=70.0)]
    res_vib = predict(cur_vib, {"N_VIB": hist_vib})
    assert res_vib["nodes"][0]["anomaly"]["evidence_status"] == "OPERATIONAL_VIBRATION"
    assert res_vib["nodes"][0]["deformation"]["status"] == "NORMAL"

    # Protection E: Spatial confirmation available before 0.50 deg
    h_spat1 = [_make_telemetry("N_SP1", now - timedelta(minutes=15 * i), pitch=0.05 + 0.03 * (5 - i), x=0.0, y=0.0) for i in range(5, 0, -1)]
    h_spat2 = [_make_telemetry("N_SP2", now - timedelta(minutes=15 * i), pitch=0.05 + 0.03 * (5 - i), x=25.0, y=0.0) for i in range(5, 0, -1)]
    cur_spat = [_make_telemetry("N_SP1", now, pitch=0.22, x=0.0, y=0.0), _make_telemetry("N_SP2", now, pitch=0.21, x=25.0, y=0.0)]
    res_spat = predict(cur_spat, {"N_SP1": h_spat1, "N_SP2": h_spat2})
    assert res_spat["nodes"][0]["deformation"]["evidence"]["spatial"] is True
    assert res_spat["nodes"][0]["deformation"]["status"] == "CONFIRMED_PHYSICAL"

    # Protection F: Stale telemetry does not participate as fresh evidence
    stale_ts = now - timedelta(hours=3)
    hist_stale = [_make_telemetry("N_STALE", stale_ts - timedelta(hours=i), pitch=0.05) for i in range(5, 0, -1)]
    hist_fresh = [_make_telemetry("N_FRESH", now - timedelta(hours=i), pitch=0.05) for i in range(5, 0, -1)]
    cur_stale = [_make_telemetry("N_FRESH", now, pitch=0.05), _make_telemetry("N_STALE", stale_ts, pitch=0.25)]
    res_stale = predict(cur_stale, {"N_FRESH": hist_fresh, "N_STALE": hist_stale})
    n_stale = next(n for n in res_stale["nodes"] if n["node_id"] == "N_STALE")
    assert n_stale["health"]["status"] == "STALE_DATA"
    assert n_stale["deformation"]["status"] == "STALE_DATA"

    # Protection G: OOD readings reduce confidence
    hist_ood = [_make_telemetry("N_OOD", now - timedelta(hours=i), pitch=0.05 + 0.001 * (i % 2)) for i in range(5, 0, -1)]
    cur_ood = [_make_telemetry("N_OOD", now, pitch=85.0)]
    res_ood = predict(cur_ood, {"N_OOD": hist_ood})
    assert res_ood["nodes"][0]["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    assert "OOD" in res_ood["nodes"][0]["reason_codes"]
    assert res_ood["data_quality"]["out_of_distribution"] is True
    # Verify confidence is suppressed relative to normal reading under identical history/health
    hist_norm = [_make_telemetry("N_NORM", now - timedelta(hours=i), pitch=0.05 + 0.001 * (i % 2)) for i in range(5, 0, -1)]
    cur_norm = [_make_telemetry("N_NORM", now, pitch=0.05)]
    res_norm = predict(cur_norm, {"N_NORM": hist_norm})
    assert res_ood["nodes"][0]["confidence"] < res_norm["nodes"][0]["confidence"]


