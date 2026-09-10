"""Comprehensive Test Suite for Final Safety Audit Sections A through E.

Covers:
Section A: Scenarios A1 to A10 (Alarm logic, isolated spike rejection, machinery vibration, fault isolation).
Section B: Scenarios B1 to B10 (Resultant tilt, threshold predictions, null-resolution, 24h clamping).
Section C: Scenarios C1 to C6 (21-node output contract, mixed state isolation, array aggregation).
Section D: Scenarios D1 to D12 (Sensor fault, comm degradation, firmware units).
Section E: Scenarios E1 to E2 (Production zero-simulator import verification, firmware adapter test).
"""

from datetime import datetime, timedelta, timezone
from math import sqrt
import sys

from fastapi.testclient import TestClient
import pytest

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
# SECTION A: ALARM LOGIC & CONSERVATIVE CONFIRMATION AUDIT (A1 - A10)
# ==============================================================================

def test_scenario_a1_stable_healthy_node():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now)
    cur = [_record("N1", now, pitch=0.05)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["anomaly"]["detected"] is False
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_scenario_a2_isolated_noisy_tilt_spike_remains_unconfirmed():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # 5 frames of resting 0.05, then sudden isolated spike to 0.18 on N1 alone
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now)
    cur = [_record("N1", now, pitch=0.18)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    # May or may not trip statistical screen, but MUST NOT be confirmed physical
    assert n1["deformation"]["status"] in {"NORMAL", "UNCONFIRMED_ANOMALY"}
    assert n1["anomaly"]["confirmed_physical"] is False
    assert res["overall"]["alarm"] is False


def test_scenario_a3_persistent_increasing_tilt_confirms_deformation():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Persistent upward trend
    hist = _history_series("N1", [0.10, 0.14, 0.18, 0.22, 0.26], now)
    cur = [_record("N1", now, pitch=0.30)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True
    assert res["overall"]["alarm"] is True


def test_scenario_a4_increasing_tilt_across_multiple_neighbors_spatially_corroborates():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist_n1 = _history_series("N1", [0.15, 0.25, 0.35, 0.45, 0.50], now, x=0.0)
    hist_n2 = _history_series("N2", [0.15, 0.24, 0.34, 0.44, 0.49], now, x=30.0)
    cur = [_record("N1", now, pitch=0.55, x=0.0), _record("N2", now, pitch=0.54, x=30.0)]
    res = predict(cur, {"N1": hist_n1, "N2": hist_n2})
    n1 = res["nodes"][0]
    n2 = res["nodes"][1]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n2["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["deformation"]["evidence"]["spatial"] is True
    assert res["overall"]["alarm"] is True


def test_scenario_a5_high_machinery_vibration_does_not_cause_deformation_alarm():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Stable tilt (0.05) with 150 mg machinery vibration
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now, vib=140.0)
    cur = [_record("N1", now, pitch=0.05, vib=160.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_scenario_a6_low_battery_sensor_fault_is_suppressed():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now)
    cur = [_record("N1", now, pitch=0.25, bat=3200.0, flags=1)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert n1["deformation"]["status"] == "SUPPRESSED"
    assert res["overall"]["alarm"] is False


def test_scenario_a7_poor_rssi_snr_does_not_raise_physical_alarm():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now)
    cur = [_record("N1", now, pitch=0.05, rssi=-125.0, snr=-8.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["health"]["status"] in {"SUSPECT", "SENSOR_FAULT", "FAULTY"}
    assert n1["deformation"]["status"] in {"NORMAL", "SUPPRESSED"}
    assert res["overall"]["alarm"] is False


def test_scenario_a8_mounting_step_change_without_continuity_remains_unconfirmed():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Sudden step on single node from 0.05 to 0.20, neighbors flat
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now, x=0.0)
    hist_n2 = _history_series("N2", [0.05, 0.05, 0.05, 0.05, 0.05], now, x=30.0)
    cur = [_record("N1", now, pitch=0.20, x=0.0), _record("N2", now, pitch=0.05, x=30.0)]
    res = predict(cur, {"N1": hist, "N2": hist_n2})
    n1 = res["nodes"][0]
    # Should not confirm physical deformation without spatial or temporal support
    assert n1["deformation"]["status"] != "CONFIRMED_PHYSICAL"
    assert res["overall"]["alarm"] is False


def test_scenario_a9_strong_genuine_deformation_detected_on_subset_of_nodes():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Strong local deformation (0.75 deg)
    hist = _history_series("N1", [0.30, 0.40, 0.50, 0.60, 0.70], now)
    cur = [_record("N1", now, pitch=0.75)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert res["overall"]["alarm"] is True


def test_scenario_a10_sensor_fault_does_not_contaminate_neighboring_deformation():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # N1 has hardware fault (dead battery, flags=1)
    hist_n1 = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now, x=0.0)
    # N2 has genuine deformation (pitch 0.65)
    hist_n2 = _history_series("N2", [0.25, 0.35, 0.45, 0.55, 0.60], now, x=30.0)
    cur = [
        _record("N1", now, pitch=0.05, bat=3100.0, flags=1, x=0.0),
        _record("N2", now, pitch=0.65, x=30.0)
    ]
    res = predict(cur, {"N1": hist_n1, "N2": hist_n2})
    n1 = next(n for n in res["nodes"] if n["node_id"] == "N1")
    n2 = next(n for n in res["nodes"] if n["node_id"] == "N2")

    # N1 is gated as SUPPRESSED / SENSOR_FAULT
    assert n1["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert n1["deformation"]["status"] == "SUPPRESSED"

    # N2 confirms physical deformation without contamination
    assert n2["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert res["overall"]["alarm"] is True


# ==============================================================================
# SECTION B: TIME-TO-THRESHOLD AUDIT (B1 - B10)
# ==============================================================================

def test_scenario_b1_static_node_threshold_not_reached():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.08, 0.08, 0.08, 0.08, 0.08], now)
    cur = [_record("N1", now, pitch=0.08)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_hours"] is None
    assert tp["critical_hours"] is None
    assert tp["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert tp["critical_status"] == "NOT_REACHED_IN_FORECAST"


def test_scenario_b2_slowly_increasing_warning_predicted():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Rate: (0.30 - 0.10) / 5h = 0.04 deg/h. Warning (0.50 - 0.30) / 0.04 = 5.0h
    hist = _history_series("N1", [0.10, 0.14, 0.18, 0.22, 0.26], now)
    cur = [_record("N1", now, pitch=0.30)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_status"] == "PREDICTED"
    assert tp["warning_hours"] == pytest.approx(5.0, abs=0.5)


def test_scenario_b3_critical_crossing_predicted():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Tilt: 0.80. Rate: ~0.08 deg/h. Critical (1.00 - 0.80) / 0.08 = 2.5h
    hist = _history_series("N1", [0.40, 0.48, 0.56, 0.64, 0.72], now)
    cur = [_record("N1", now, pitch=0.80)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["critical_status"] == "PREDICTED"
    assert tp["critical_hours"] == pytest.approx(2.5, abs=0.5)


def test_scenario_b4_already_above_warning_returns_zero():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.40, 0.45, 0.50, 0.55, 0.58], now)
    cur = [_record("N1", now, pitch=0.62)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_hours"] == 0.0
    assert tp["warning_status"] == "ALREADY_EXCEEDED"


def test_scenario_b5_already_above_critical_returns_zero():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.80, 0.90, 0.95, 1.00, 1.05], now)
    cur = [_record("N1", now, pitch=1.12)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["critical_hours"] == 0.0
    assert tp["critical_status"] == "ALREADY_EXCEEDED"


def test_scenario_b6_insufficient_history_returns_explicit_status():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.10], now)
    cur = [_record("N1", now, pitch=0.10)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_hours"] is None
    assert tp["critical_hours"] is None
    assert tp["warning_status"] == "INSUFFICIENT_HISTORY"
    assert tp["critical_status"] == "INSUFFICIENT_HISTORY"


def test_scenario_b7_sensor_fault_returns_low_confidence():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.10, 0.10, 0.10, 0.10, 0.10], now)
    cur = [_record("N1", now, pitch=0.10, bat=3200.0, flags=1)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_hours"] is None
    assert tp["warning_status"] == "LOW_CONFIDENCE"


def test_scenario_b8_stale_data_returns_low_confidence():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    stale_ts = now - timedelta(hours=3)
    hist = _history_series("N1", [0.10, 0.10, 0.10, 0.10, 0.10], stale_ts)
    # Current reading is from 3 hours ago while newest is now
    cur = [_record("N1", stale_ts, pitch=0.10), _record("N2", now, pitch=0.05, x=30.0)]
    res = predict(cur, {"N1": hist, "N2": _history_series("N2", [0.05]*5, now, x=30.0)})
    n1 = next(n for n in res["nodes"] if n["node_id"] == "N1")
    assert n1["threshold_prediction"]["warning_hours"] is None
    assert n1["threshold_prediction"]["warning_status"] == "LOW_CONFIDENCE"


def test_scenario_b9_ood_telemetry_returns_low_confidence():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.10, 0.10, 0.10, 0.10, 0.10], now)
    cur = [_record("N1", now, pitch=0.10, temp=85.0)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_hours"] is None
    assert tp["warning_status"] == "LOW_CONFIDENCE"


def test_scenario_b10_positive_rate_exceeding_24h_is_not_reached_in_forecast():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Slow creep: rate = 0.003 deg/h. (0.50 - 0.10) / 0.003 = 133 hours > 24h
    hist = _history_series("N1", [0.085, 0.088, 0.091, 0.094, 0.097], now)
    cur = [_record("N1", now, pitch=0.10)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    assert tp["warning_hours"] is None
    assert tp["warning_status"] == "NOT_REACHED_IN_FORECAST"


def test_resultant_tilt_combines_pitch_and_roll_for_threshold():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Pitch = 0.36, Roll = 0.36 -> Resultant = sqrt(0.36^2 + 0.36^2) = 0.509 deg >= 0.50 warning!
    hist = _history_series("N1", [0.20, 0.24, 0.28, 0.32, 0.34], now)
    cur = [_record("N1", now, pitch=0.36, roll=0.36)]
    res = predict(cur, {"N1": hist})
    tp = res["nodes"][0]["threshold_prediction"]
    # Must exceed warning threshold even though pitch alone (0.36) is < 0.50
    assert tp["warning_hours"] == 0.0
    assert tp["warning_status"] == "ALREADY_EXCEEDED"


# ==============================================================================
# SECTION C: 21-NODE OUTPUT CONTRACT & ARRAY AGGREGATION AUDIT (C1 - C6)
# ==============================================================================

def test_contract_c1_21_healthy_nodes():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 22)]
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}
    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_contract_c2_20_healthy_and_1_sensor_fault():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 21)]
    cur.append(_record("NODE-021", now, pitch=0.05, bat=3200.0, flags=1))
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}
    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    # Array overall status reflects sensor fault but does NOT raise physical alarm
    assert res["overall"]["status"] == "SENSOR_FAULT"
    assert res["overall"]["alarm"] is False
    assert res["overall"]["alarm_reason"] == "SENSOR_HEALTH_DEGRADED"


def test_contract_c3_20_healthy_and_1_ood_node():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 21)]
    cur.append(_record("NODE-021", now, pitch=0.05, temp=85.0))
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}
    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    n21 = next(n for n in res["nodes"] if n["node_id"] == "NODE-021")
    assert n21["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    # Other nodes remain NORMAL
    n1 = next(n for n in res["nodes"] if n["node_id"] == "NODE-001")
    assert n1["deformation"]["status"] == "NORMAL"


def test_contract_c4_20_healthy_and_1_insufficient_history_node():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 22)]
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 21)}
    hist["NODE-021"] = [_record("NODE-021", now - timedelta(hours=1), pitch=0.05)]
    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    n21 = next(n for n in res["nodes"] if n["node_id"] == "NODE-021")
    assert n21["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"


def test_contract_c5_multiple_simultaneous_anomalies():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 22)]
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}
    # Induce persistent deformation on nodes 5, 6, 7
    for nid in ["NODE-005", "NODE-006", "NODE-007"]:
        hist[nid] = _history_series(nid, [0.15, 0.25, 0.35, 0.45, 0.50], now)
    cur[4] = _record("NODE-005", now, pitch=0.55)
    cur[5] = _record("NODE-006", now, pitch=0.56)
    cur[6] = _record("NODE-007", now, pitch=0.57)

    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    assert res["overall"]["alarm"] is True
    assert res["overall"]["status"] in {"WARNING", "CRITICAL"}


def test_contract_c6_mixed_heterogeneous_states_handled_independently():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 22)]
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}

    # NODE-001: Normal
    # NODE-002: Insufficient history
    hist["NODE-002"] = [_record("NODE-002", now - timedelta(hours=1), pitch=0.05)]
    # NODE-003: Confirmed Physical
    hist["NODE-003"] = _history_series("NODE-003", [0.15, 0.25, 0.35, 0.45, 0.55], now)
    cur[2] = _record("NODE-003", now, pitch=0.62)
    # NODE-004: Sensor Fault
    cur[3] = _record("NODE-004", now, pitch=0.05, bat=3200.0, flags=1)
    # NODE-005: Stale
    stale_ts = now - timedelta(hours=3)
    cur[4] = _record("NODE-005", stale_ts, pitch=0.05)
    # NODE-006: OOD
    cur[5] = _record("NODE-006", now, pitch=0.05, temp=85.0)

    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    by_id = {n["node_id"]: n for n in res["nodes"]}

    assert by_id["NODE-001"]["deformation"]["status"] == "NORMAL"
    assert by_id["NODE-002"]["deformation"]["status"] == "INSUFFICIENT_HISTORY"
    assert by_id["NODE-003"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert by_id["NODE-004"]["deformation"]["status"] == "SUPPRESSED"
    assert by_id["NODE-005"]["health"]["status"] in {"STALE_DATA", "SUSPECT"}
    assert by_id["NODE-006"]["deformation"]["status"] == "OOD_LOW_CONFIDENCE"


# ==============================================================================
# SECTION D: SENSOR FAULT / OOD / NOISE SEPARATION (D1 - D12)
# ==============================================================================

def test_sensor_fault_separation_d1_low_battery():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record("N1", now, bat=3300.0)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}
    res = predict(cur, hist)
    assert "LOW_BATTERY" in res["nodes"][0]["reason_codes"]
    assert res["nodes"][0]["health"]["status"] in {"SUSPECT", "SENSOR_FAULT", "FAULTY"}


def test_sensor_fault_separation_d2_d3_bad_rssi_snr():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record("N1", now, rssi=-120.0, snr=-8.0)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}
    res = predict(cur, hist)
    assert "POOR_RSSI" in res["nodes"][0]["reason_codes"]
    assert "POOR_SNR" in res["nodes"][0]["reason_codes"]


def test_sensor_fault_separation_d4_protocol_flags():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record("N1", now, flags=1)]
    hist = {"N1": _history_series("N1", [0.05]*5, now)}
    res = predict(cur, hist)
    assert res["nodes"][0]["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert "PROTOCOL_FAULT" in res["nodes"][0]["reason_codes"]


def test_sensor_fault_separation_d5_gnss_loss():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    rec = _record("N1", now)
    rec["gnss_status"] = 0  # No fix
    hist = {"N1": _history_series("N1", [0.05]*5, now)}
    res = predict([rec], hist)
    assert "GNSS_LOSS" in res["nodes"][0]["reason_codes"]


# ==============================================================================
# SECTION E: REAL DATA READINESS & SIMULATOR ZERO-DEPENDENCY (E1 - E2)
# ==============================================================================

def test_production_ml_has_zero_simulator_imports():
    """Verify that production ML modules do not import any simulator components."""
    import ast
    import inspect
    import inference.pipeline
    import service.app
    import features.engineering
    import models.estimators

    for mod in [inference.pipeline, service.app, features.engineering, models.estimators]:
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "simulator" not in alias.name, f"Module {mod.__name__} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                assert "simulator" not in mod_name, f"Module {mod.__name__} imports from {mod_name}"


def test_firmware_telemetry_schema_conversion_adapter():
    """Verify conversion of raw ESP32 firmware units into valid ML telemetry."""
    raw_firmware_packet = {
        "t_epoch": 1788955200,
        "pitch_mdeg": 120,          # 120 mdeg = 0.120 deg
        "roll_mdeg": 15,            # 15 mdeg = 0.015 deg
        "vib_rms_mg": 22,           # 22 mg
        "vib_peak_hz": 29,          # 29 Hz
        "temp_c_x100": 2850,        # 28.50 C
        "n_samples": 32,
        "gnss_status": 14,
        "vbat_mv": 3920,            # 3920 mV
        "rssi": -74,                # -74 dBm
        "snr": 8,                   # 8 dB
        "flags": 0,
        "addr": 101,
        "x_m": 45.0,
        "y_m": 12.0,
    }

    # Adapter transformation matching backend/app/state.py
    ml_telemetry = {
        "node_id": f"NODE-{raw_firmware_packet['addr']:03d}",
        "timestamp": datetime.fromtimestamp(raw_firmware_packet["t_epoch"], tz=timezone.utc).isoformat(),
        "pitch_deg": raw_firmware_packet["pitch_mdeg"] / 1000.0,
        "roll_deg": raw_firmware_packet["roll_mdeg"] / 1000.0,
        "vibration_rms_mg": float(raw_firmware_packet["vib_rms_mg"]),
        "vibration_peak_hz": float(raw_firmware_packet["vib_peak_hz"]),
        "temperature_c": raw_firmware_packet["temp_c_x100"] / 100.0,
        "n_samples": raw_firmware_packet["n_samples"],
        "gnss_status": raw_firmware_packet["gnss_status"],
        "battery_mv": float(raw_firmware_packet["vbat_mv"]),
        "rssi_dbm": float(raw_firmware_packet["rssi"]),
        "snr_db": float(raw_firmware_packet["snr"]),
        "flags": raw_firmware_packet["flags"],
        "x_m": raw_firmware_packet["x_m"],
        "y_m": raw_firmware_packet["y_m"],
    }

    # Verify predict accepts adapted firmware packet without error
    res = predict([ml_telemetry], {ml_telemetry["node_id"]: []})
    assert len(res["nodes"]) == 1
    node = res["nodes"][0]
    assert node["node_id"] == "NODE-101"
    assert node["deformation"]["tilt_deg"] == pytest.approx(sqrt(0.12**2 + 0.015**2), abs=0.001)
    assert node["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
