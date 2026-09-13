"""Regression Test Suite for MineGuard Early-Warning Intelligence and Time-to-Threshold.

Verifies:
1. Stable healthy node -> NORMAL
2. Operational vibration without deformation -> NORMAL (explanation mentions operational vibration)
3. Persistent physical deformation -> physical confirmation -> WARNING / CRITICAL
4. Rapid deformation -> CRITICAL
5. Spatially corroborated deformation -> spatial evidence retained in explanation
6. Sensor fault -> SENSOR_FAULT, physical alarm suppressed, SENSOR_FAULT in reason_codes
7. Thermal cooling -> NORMAL / COOLING_NORMAL, no positive threshold ETA
8. Insufficient history -> no false alarm, forecast/ETA unavailable
9. Stale telemetry -> no false physical alarm
10. OOD telemetry -> low confidence, no false physical alarm
11. Threshold already exceeded -> ALREADY_EXCEEDED, ETA = 0.0
12. Positive trend -> PREDICTED ETA
13. No positive trend -> NO_POSITIVE_TREND in reason_codes, ETA unavailable
14. Negative/cooling trend -> no dangerous positive threshold ETA
15. Missing optional telemetry -> no false sensor fault
16. 21-node contract and overall["severity"] integrity
"""

from datetime import datetime, timedelta, timezone
import pytest

from inference.pipeline import predict


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


def test_scenario_1_stable_healthy_node():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now)
    cur = [_record("N1", now, pitch=0.05)]
    res = predict(cur, {"N1": hist})

    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["severity"] == "NORMAL"
    assert res["overall"]["alarm"] is False
    assert res["explanation"] == "No credible persistent physical deformation detected."


def test_scenario_2_operational_vibration_without_deformation():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.04, 0.04, 0.04, 0.04, 0.04], now, vib=45.0)
    cur = [_record("N1", now, pitch=0.04, vib=50.0)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["severity"] == "NORMAL"
    assert res["overall"]["alarm"] is False
    assert n1["deformation"]["status"] == "NORMAL"
    assert "OPERATIONAL_VIBRATION" in n1["reason_codes"]
    assert "operational vibration" in res["explanation"].lower()


def test_scenario_3_persistent_physical_deformation():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.10, 0.14, 0.18, 0.22, 0.26], now)
    cur = [_record("N1", now, pitch=0.30)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert res["overall"]["alarm"] is True
    assert res["overall"]["severity"] in {"WARNING", "CRITICAL"}
    assert "persistent positive deformation" in res["explanation"].lower()


def test_scenario_4_rapid_deformation():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.30, 0.45, 0.60, 0.75, 0.90], now)
    cur = [_record("N1", now, pitch=1.05)]
    res = predict(cur, {"N1": hist})

    assert res["overall"]["alarm"] is True
    assert res["overall"]["severity"] == "CRITICAL"
    assert res["overall"]["status"] == "CRITICAL"


def test_scenario_5_spatially_corroborated_deformation():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist_n1 = _history_series("N1", [0.15, 0.25, 0.35, 0.45, 0.50], now, x=0.0, y=0.0)
    hist_n2 = _history_series("N2", [0.15, 0.24, 0.34, 0.44, 0.49], now, x=30.0, y=0.0)
    cur = [_record("N1", now, pitch=0.55, x=0.0, y=0.0), _record("N2", now, pitch=0.54, x=30.0, y=0.0)]
    res = predict(cur, {"N1": hist_n1, "N2": hist_n2})

    n1 = res["nodes"][0]
    n2 = res["nodes"][1]
    assert n1["deformation"]["evidence"]["spatial"] is True
    assert n2["deformation"]["evidence"]["spatial"] is True
    assert res["overall"]["alarm"] is True
    assert "spatial corroboration" in res["explanation"].lower()


def test_scenario_6_sensor_fault_suppressed():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.05, 0.05, 0.05, 0.05, 0.05], now)
    cur = [_record("N1", now, pitch=0.25, bat=3200.0, flags=1)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert n1["deformation"]["status"] == "SUPPRESSED"
    assert "SENSOR_FAULT" in n1["reason_codes"]
    assert res["overall"]["status"] == "SENSOR_FAULT"
    assert res["overall"]["severity"] == "SENSOR_FAULT"
    assert res["overall"]["alarm"] is False
    assert "sensor fault" in res["explanation"].lower()


def test_scenario_7_thermal_cooling():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.12, 0.10, 0.08, 0.06, 0.05], now)
    cur = [_record("N1", now, pitch=0.04)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert "THERMAL_COOLING" in n1["reason_codes"]
    assert n1["threshold_prediction"]["warning_hours"] is None
    assert n1["threshold_prediction"]["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert res["overall"]["alarm"] is False
    assert "thermal cooling" in res["explanation"].lower()


def test_scenario_8_insufficient_history():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.10], now)
    cur = [_record("N1", now, pitch=0.10)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["threshold_prediction"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert n1["threshold_prediction"]["warning_hours"] is None
    assert n1["forecast"] is None
    assert "INSUFFICIENT_HISTORY" in n1["reason_codes"]
    assert res["overall"]["alarm"] is False


def test_scenario_9_stale_telemetry():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    stale_ts = now - timedelta(hours=3)
    hist = _history_series("N1", [0.05]*5, stale_ts)
    cur = [_record("N1", stale_ts, pitch=0.05), _record("N2", now, pitch=0.05, x=30.0)]
    res = predict(cur, {"N1": hist, "N2": _history_series("N2", [0.05]*5, now, x=30.0)})

    n1 = next(n for n in res["nodes"] if n["node_id"] == "N1")
    assert n1["health"]["status"] in {"STALE_DATA", "SUSPECT"}
    assert "STALE_TELEMETRY" in n1["reason_codes"]
    assert res["overall"]["alarm"] is False


def test_scenario_10_ood_telemetry():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.05]*5, now)
    cur = [_record("N1", now, pitch=0.05, temp=85.0)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["threshold_prediction"]["warning_status"] == "LOW_CONFIDENCE"
    assert "OOD" in n1["reason_codes"]
    assert res["overall"]["alarm"] is False


def test_scenario_11_threshold_already_exceeded():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.40, 0.45, 0.50, 0.55, 0.58], now)
    cur = [_record("N1", now, pitch=0.62)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["threshold_prediction"]["warning_status"] == "ALREADY_EXCEEDED"
    assert n1["threshold_prediction"]["warning_hours"] == 0.0
    assert "THRESHOLD_ALREADY_EXCEEDED" in n1["reason_codes"]


def test_scenario_12_positive_trend_eta():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.10, 0.14, 0.18, 0.22, 0.26], now)
    cur = [_record("N1", now, pitch=0.30)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["threshold_prediction"]["warning_status"] == "PREDICTED"
    assert n1["threshold_prediction"]["warning_hours"] is not None
    assert n1["threshold_prediction"]["warning_hours"] == pytest.approx(5.0, abs=0.5)
    assert "TILT_THRESHOLD_APPROACH" in n1["reason_codes"]


def test_scenario_13_no_positive_trend():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.08, 0.08, 0.08, 0.08, 0.08], now)
    cur = [_record("N1", now, pitch=0.08)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["threshold_prediction"]["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert n1["threshold_prediction"]["warning_hours"] is None
    assert "NO_POSITIVE_TREND" in n1["reason_codes"]


def test_scenario_14_negative_cooling_trend():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _history_series("N1", [0.14, 0.12, 0.10, 0.08, 0.06], now)
    cur = [_record("N1", now, pitch=0.05)]
    res = predict(cur, {"N1": hist})

    n1 = res["nodes"][0]
    assert n1["threshold_prediction"]["warning_hours"] is None
    assert n1["threshold_prediction"]["warning_status"] == "NOT_REACHED_IN_FORECAST"
    # Ensure forecast at future horizons is non-increasing and >= 0.0
    fc = n1["forecast"]
    assert fc is not None
    assert fc["24h"]["tilt_deg"] <= fc["1h"]["tilt_deg"]
    assert fc["24h"]["tilt_deg"] >= 0.0


def test_scenario_15_missing_optional_telemetry():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    minimal_cur = [{
        "node_id": "N1",
        "timestamp": now.isoformat(),
        "pitch_deg": 0.05,
        "roll_deg": 0.0,
        "vibration_rms_mg": 15.0,
        "vibration_peak_hz": 25.0,
    }]
    pitches = [0.050, 0.051, 0.049, 0.050, 0.051]
    minimal_hist = {"N1": [
        {
            "node_id": "N1",
            "timestamp": (now - timedelta(hours=5 - i)).isoformat(),
            "pitch_deg": pitches[i],
            "roll_deg": 0.0,
            "vibration_rms_mg": 15.0,
            "vibration_peak_hz": 25.0,
        }
        for i in range(5)
    ]}
    res = predict(minimal_cur, minimal_hist)
    n1 = res["nodes"][0]
    assert n1["health"]["status"] == "HEALTHY"
    assert "SENSOR_FAULT" not in n1["reason_codes"]


def test_scenario_16_21_node_contract_and_severity():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = [_record(f"NODE-{i:03d}", now, pitch=0.05) for i in range(1, 22)]
    hist = {f"NODE-{i:03d}": _history_series(f"NODE-{i:03d}", [0.05]*5, now) for i in range(1, 22)}

    # Introduce mixed state:
    # NODE-004 has sensor fault
    cur[3] = _record("NODE-004", now, pitch=0.05, bat=3100.0, flags=1)

    res = predict(cur, hist)
    assert len(res["nodes"]) == 21
    assert "severity" in res["overall"]
    assert res["overall"]["severity"] in {"NORMAL", "WARNING", "CRITICAL", "SENSOR_FAULT"}
    assert res["overall"]["severity"] == "SENSOR_FAULT"
    assert res["overall"]["alarm"] is False
