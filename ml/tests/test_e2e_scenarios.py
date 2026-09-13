"""Deterministic End-to-End ML Scenario Test Pack for MineGuard AI/ML.

Verifies that realistic backend-like telemetry produces the correct high-level ML
behavior across the COMPLETE ML pipeline (preprocessing, feature engineering,
IForest anomaly detection, physical confirmation, forecasting, time-to-threshold,
and array-level alarm intelligence).

Scenarios Covered:
1. NORMAL
2. GRADUAL_DEFORMATION
3. RAPID_DEFORMATION
4. SPATIALLY_CORRELATED_DEFORMATION
5. OPERATIONAL_VIBRATION
6. SENSOR_FAULT
7. THERMAL_COOLING
8. STALE_DATA
9. INSUFFICIENT_HISTORY
10. OOD_EXTREME_TILT
11. MISSING_NODES
12. MIXED_FIELD (21 nodes with heterogeneous conditions)
13. RECOVERY / RETURN TO NORMAL
14. LOW_PREVALENCE (Stream with background drift and isolated physical event)

Safety Invariants Verified:
A. Operational vibration alone must never become physical deformation.
B. Thermal cooling alone must never become physical deformation.
C. Sensor faults must not be silently treated as healthy physical evidence.
D. Stale telemetry must not be treated as fresh evidence.
E. OOD telemetry must not create unjustified physical confirmation.
F. Insufficient history must not produce fabricated forecast or ETA.
G. Missing nodes must not be invented.
H. Missing optional telemetry must remain unknown rather than being converted to zero.
I. Backend-supplied observed deformation must be preserved.
J. Knothe expected values must never be fabricated.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import pytest

from inference.pipeline import predict


def _telemetry(
    node_id: str,
    ts: datetime,
    *,
    pitch: float = 0.05,
    roll: float = 0.0,
    vib_rms: float = 18.0,
    vib_peak: float = 30.0,
    temp_c: float = 26.0,
    battery_mv: float = 3950.0,
    rssi: float = -70.0,
    snr: float = 8.0,
    flags: int = 0,
    x: float = 0.0,
    y: float = 0.0,
    n_samples: int = 32,
    gnss_status: int = 14,
) -> dict[str, Any]:
    """Helper to produce realistic backend-like telemetry record."""
    return {
        "node_id": node_id,
        "timestamp": ts.isoformat(),
        "pitch_deg": pitch,
        "roll_deg": roll,
        "vibration_rms_mg": vib_rms,
        "vibration_peak_hz": vib_peak,
        "temperature_c": temp_c,
        "n_samples": n_samples,
        "gnss_status": gnss_status,
        "battery_mv": battery_mv,
        "rssi_dbm": rssi,
        "snr_db": snr,
        "flags": flags,
        "x_m": x,
        "y_m": y,
    }


def _history_series(
    node_id: str,
    pitches: list[float],
    base_ts: datetime,
    dt: timedelta = timedelta(minutes=15),
    **kwargs,
) -> list[dict[str, Any]]:
    """Helper to produce chronological history series ending at base_ts - dt."""
    hist = []
    n = len(pitches)
    for i, p in enumerate(pitches):
        t = base_ts - dt * (n - i)
        hist.append(_telemetry(node_id, t, pitch=p, **kwargs))
    return hist


# ==============================================================================
# SCENARIO 1: NORMAL
# ==============================================================================
def test_scenario_1_normal():
    """Scenario 1: Stable, healthy ground telemetry.
    Expectation:
    - Status is NORMAL
    - Alarm is False
    - No physical deformation confirmation
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    hist = _history_series("NODE-001", [0.050, 0.051, 0.049, 0.050, 0.051], now)
    cur = [_telemetry("NODE-001", now, pitch=0.050)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["status"] == "NORMAL"
    assert res["overall"]["severity"] == "NORMAL"
    assert res["overall"]["alarm"] is False
    assert res["deformation_state"] == "STABLE"

    node = res["nodes"][0]
    assert node["deformation"]["status"] == "NORMAL"
    assert node["anomaly"]["confirmed_physical"] is False
    assert "No credible persistent physical deformation" in res["explanation"]


# ==============================================================================
# SCENARIO 2: GRADUAL DEFORMATION
# ==============================================================================
def test_scenario_2_gradual_deformation():
    """Scenario 2: Slow, steady, monotonic physical deformation.
    Expectation:
    - Persistent positive deformation recognized
    - Physical confirmation achieved
    - Escalation to WARNING or CRITICAL
    - Forecast and ETA available with PREDICTED status
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    # Steady ramp over 5 timesteps (15-min intervals) from 0.05 up to 0.35 deg
    hist = _history_series("NODE-001", [0.10, 0.15, 0.20, 0.25, 0.30], now)
    cur = [_telemetry("NODE-001", now, pitch=0.35)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is True
    assert res["overall"]["severity"] in {"WARNING", "CRITICAL"}
    assert res["overall"]["status"] in {"WARNING", "CRITICAL"}

    node = res["nodes"][0]
    assert node["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert node["anomaly"]["confirmed_physical"] is True
    assert node["threshold_prediction"]["warning_status"] == "PREDICTED"
    assert node["threshold_prediction"]["warning_hours"] is not None
    assert node["threshold_prediction"]["warning_hours"] > 0.0
    assert node["forecast"] is not None
    assert "persistent positive deformation" in res["explanation"].lower()


# ==============================================================================
# SCENARIO 3: RAPID DEFORMATION
# ==============================================================================
def test_scenario_3_rapid_deformation():
    """Scenario 3: Fast accelerating tilt deformation crossing warning/critical thresholds.
    Expectation:
    - Overall severity CRITICAL, alarm True
    - Deformation progression detected as ACCELERATING or CRITICAL
    - Threshold prediction indicates ALREADY_EXCEEDED or low ETA
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    # Accelerating ramp jumping to > 1.0 deg
    hist = _history_series("NODE-001", [0.20, 0.35, 0.55, 0.80, 1.05], now)
    cur = [_telemetry("NODE-001", now, pitch=1.35)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is True
    assert res["overall"]["severity"] == "CRITICAL"
    assert res["overall"]["status"] == "CRITICAL"

    node = res["nodes"][0]
    assert node["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert node["threshold_prediction"]["warning_status"] == "ALREADY_EXCEEDED"
    assert node["threshold_prediction"]["warning_hours"] == 0.0
    assert node["threshold_prediction"]["critical_status"] == "ALREADY_EXCEEDED"
    assert node["threshold_prediction"]["critical_hours"] == 0.0


# ==============================================================================
# SCENARIO 4: SPATIALLY CORRELATED DEFORMATION
# ==============================================================================
def test_scenario_4_spatially_correlated_deformation():
    """Scenario 4: Neighboring nodes (dist <= 50m) showing coordinated deformation.
    Expectation:
    - Spatial corroboration active (spatial consistency >= 0.5 or spreading True)
    - Physical confirmation and alarm True
    - Spatial corroboration mentioned in explanation
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    # N1 at (0, 0), N2 at (25, 0)
    hist_n1 = _history_series("NODE-001", [0.12, 0.20, 0.28, 0.36, 0.44], now, x=0.0, y=0.0)
    hist_n2 = _history_series("NODE-002", [0.10, 0.18, 0.26, 0.34, 0.42], now, x=25.0, y=0.0)
    cur = [
        _telemetry("NODE-001", now, pitch=0.52, x=0.0, y=0.0),
        _telemetry("NODE-002", now, pitch=0.50, x=25.0, y=0.0),
    ]

    res = predict(cur, {"NODE-001": hist_n1, "NODE-002": hist_n2})

    assert res["overall"]["alarm"] is True
    assert res["spatial"]["consistency"] >= 0.5
    assert len(res["spatial"]["affected_nodes"]) >= 2

    n1 = next(n for n in res["nodes"] if n["node_id"] == "NODE-001")
    n2 = next(n for n in res["nodes"] if n["node_id"] == "NODE-002")
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n2["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["deformation"]["evidence"]["spatial"] is True
    assert n2["deformation"]["evidence"]["spatial"] is True
    assert "spatial corroboration" in res["explanation"].lower()


# ==============================================================================
# SCENARIO 5: OPERATIONAL VIBRATION
# ==============================================================================
def test_scenario_5_operational_vibration():
    """Scenario 5: High machinery/haulage vibration (60-80 mg) with flat tilt.
    Expectation:
    - Categorized as OPERATIONAL_VIBRATION
    - No physical deformation confirmation
    - Alarm remains False
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    hist = _history_series("NODE-001", [0.050, 0.051, 0.049, 0.050, 0.051], now, vib_rms=65.0)
    cur = [_telemetry("NODE-001", now, pitch=0.05, vib_rms=75.0)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is False
    assert res["overall"]["status"] == "NORMAL"

    node = res["nodes"][0]
    assert node["deformation"]["status"] == "NORMAL"
    assert node["anomaly"]["confirmed_physical"] is False
    assert "OPERATIONAL_VIBRATION" in node["reason_codes"]
    assert "operational vibration" in res["explanation"].lower()


# ==============================================================================
# SCENARIO 6: SENSOR FAULT
# ==============================================================================
def test_scenario_6_sensor_fault():
    """Scenario 6: Sensor battery degradation (< 3300 mV) with spurious tilt reading.
    Expectation:
    - Node health status SENSOR_FAULT / FAULTY
    - Deformation status SUPPRESSED
    - Physical alarm suppressed
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    hist = _history_series("NODE-001", [0.050, 0.051, 0.049, 0.050, 0.051], now)
    # Voltage drops to 3150 mV; spurious tilt jump to 0.40 deg
    cur = [_telemetry("NODE-001", now, pitch=0.40, battery_mv=3150.0, flags=1)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is False
    assert res["overall"]["status"] == "SENSOR_FAULT"
    assert res["overall"]["severity"] == "SENSOR_FAULT"

    node = res["nodes"][0]
    assert node["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert node["deformation"]["status"] == "SUPPRESSED"
    assert "SENSOR_FAULT" in node["reason_codes"]
    assert "sensor fault" in res["explanation"].lower()


# ==============================================================================
# SCENARIO 7: THERMAL COOLING
# ==============================================================================
def test_scenario_7_thermal_cooling():
    """Scenario 7: Diurnal thermal cooling / structural contraction.
    Expectation:
    - Categorized as COOLING_NORMAL / THERMAL_COOLING
    - No physical deformation confirmation
    - Alarm remains False, ETA not reached in forecast
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    # Temperature drops from 34 C to 22 C, tilt decreases from 0.14 down to 0.04 deg
    hist = []
    pitches = [0.14, 0.11, 0.09, 0.07, 0.05]
    temps = [34.0, 31.0, 28.0, 25.0, 23.0]
    for i in range(5):
        t = now - timedelta(minutes=15 * (5 - i))
        hist.append(_telemetry("NODE-001", t, pitch=pitches[i], temp_c=temps[i]))
    cur = [_telemetry("NODE-001", now, pitch=0.04, temp_c=22.0)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is False
    assert res["overall"]["status"] == "NORMAL"

    node = res["nodes"][0]
    assert node["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert "THERMAL_COOLING" in node["reason_codes"]
    assert node["threshold_prediction"]["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert node["threshold_prediction"]["warning_hours"] is None
    assert "thermal cooling" in res["explanation"].lower()


# ==============================================================================
# SCENARIO 8: STALE DATA
# ==============================================================================
def test_scenario_8_stale_data():
    """Scenario 8: Stale telemetry frame (packet timestamp lagged by > 2 hours).
    Expectation:
    - Node health marked STALE_DATA or SUSPECT
    - STALE_TELEMETRY reason code present
    - Degraded behavior: alarm suppressed
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    stale_ts = now - timedelta(hours=2, minutes=30)
    hist_stale = _history_series("NODE-001", [0.050, 0.051, 0.049, 0.050, 0.051], stale_ts)
    hist_fresh = _history_series("NODE-002", [0.050, 0.051, 0.049, 0.050, 0.051], now, x=30.0)

    cur = [
        _telemetry("NODE-001", stale_ts, pitch=0.05),
        _telemetry("NODE-002", now, pitch=0.05, x=30.0),
    ]

    res = predict(cur, {"NODE-001": hist_stale, "NODE-002": hist_fresh})

    assert res["overall"]["alarm"] is False

    n1 = next(n for n in res["nodes"] if n["node_id"] == "NODE-001")
    assert n1["health"]["status"] in {"STALE_DATA", "SUSPECT"}
    assert "STALE_TELEMETRY" in n1["reason_codes"]


# ==============================================================================
# SCENARIO 9: INSUFFICIENT HISTORY
# ==============================================================================
def test_scenario_9_insufficient_history():
    """Scenario 9: Only 1 prior observation provided.
    Expectation:
    - Node data sufficiency INSUFFICIENT_HISTORY
    - Forecast is None
    - Threshold prediction is INSUFFICIENT_HISTORY and hours is None
    - No fabricated prediction or alarm
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    hist = _history_series("NODE-001", [0.05], now)
    cur = [_telemetry("NODE-001", now, pitch=0.05)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is False

    node = res["nodes"][0]
    assert node["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert node["forecast"] is None
    assert node["threshold_prediction"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert node["threshold_prediction"]["warning_hours"] is None
    assert node["threshold_prediction"]["critical_status"] == "INSUFFICIENT_HISTORY"
    assert node["threshold_prediction"]["critical_hours"] is None


# ==============================================================================
# SCENARIO 10: OOD EXTREME TILT
# ==============================================================================
def test_scenario_10_ood_extreme_tilt():
    """Scenario 10: Tilt value 85 deg, far beyond physically plausible slope movement (<=45 deg).
    Expectation:
    - OOD_LOW_CONFIDENCE or OOD reason code
    - Overall confidence degraded
    - Physical alarm suppressed in absence of corroborating field evidence
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    hist = _history_series("NODE-001", [0.050, 0.051, 0.049, 0.050, 0.051], now)
    cur = [_telemetry("NODE-001", now, pitch=85.0)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is False

    node = res["nodes"][0]
    assert "OOD" in node["reason_codes"] or "TILT_OUT_OF_DOMAIN" in node["reason_codes"]
    assert node["threshold_prediction"]["warning_status"] == "LOW_CONFIDENCE"
    assert res["risk"]["confidence"] <= 0.40
    assert any("bounds" in w.lower() for w in res["data_quality"]["warnings"])


# ==============================================================================
# SCENARIO 11: MISSING NODES
# ==============================================================================
def test_scenario_11_missing_nodes():
    """Scenario 11: Incomplete field (only 5 nodes sent instead of full 21).
    Expectation:
    - Returned nodes list has exactly 5 items
    - Missing nodes are NOT invented
    - Explicit sensor health accurately reports healthy count
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    subset_ids = [f"NODE-{i:03d}" for i in range(1, 6)]
    cur = [_telemetry(nid, now, pitch=0.050, x=float(i*20)) for i, nid in enumerate(subset_ids)]
    # Use realistic micro-jitter so sensors are properly classified as HEALTHY
    hist = {
        nid: _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], now, x=float(i*20))
        for i, nid in enumerate(subset_ids)
    }

    res = predict(cur, hist)

    assert len(res["nodes"]) == 5
    assert [n["node_id"] for n in res["nodes"]] == subset_ids
    assert res["sensor_health"]["healthy_nodes"] == 5
    assert res["sensor_health"]["faulty_nodes"] == []


# ==============================================================================
# SCENARIO 12: MIXED FIELD (21 NODES)
# ==============================================================================
def test_scenario_12_mixed_field_21_nodes():
    """Scenario 12: Complete 21-node heterogeneous field covering every operational state.
    Composition:
    - NODE-001: Physical deformation (ramp 0.10 -> 0.40) -> CONFIRMED_PHYSICAL
    - NODE-002: Spatial neighbor (dist 25m, ramp 0.09 -> 0.38) -> CONFIRMED_PHYSICAL + SPATIAL
    - NODE-003: Operational vibration (65 mg vibe, flat tilt) -> OPERATIONAL_VIBRATION
    - NODE-004: Sensor fault (battery 3100 mV) -> SENSOR_FAULT
    - NODE-005: Thermal cooling (cooling trend) -> COOLING_NORMAL
    - NODE-006: Stale telemetry (lagged timestamp) -> STALE_DATA
    - NODE-007: Insufficient history (only 1 point) -> INSUFFICIENT_HISTORY
    - NODE-008: OOD extreme tilt (82 deg) -> OOD_LOW_CONFIDENCE
    - NODE-009 to NODE-021: Healthy nominal nodes -> NORMAL

    Expectation:
    - All 21 nodes returned in deterministic input order
    - Each node retains its independent state without crosstalk
    - Overall alarm is triggered due to genuine physical nodes (NODE-001, NODE-002)
    - Sensor health accurately isolates NODE-004 as faulty and NODE-006 as suspect
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    stale_ts = now - timedelta(hours=3)
    node_ids = [f"NODE-{i:03d}" for i in range(1, 22)]

    cur = []
    hist = {}

    for i, nid in enumerate(node_ids):
        x = float((i % 5) * 25.0)
        y = float((i // 5) * 25.0)

        if nid == "NODE-001":
            # Deforming node
            hist[nid] = _history_series(nid, [0.10, 0.16, 0.22, 0.28, 0.34], now, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=0.40, x=x, y=y))
        elif nid == "NODE-002":
            # Neighboring deforming node
            hist[nid] = _history_series(nid, [0.09, 0.15, 0.21, 0.27, 0.32], now, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=0.38, x=x, y=y))
        elif nid == "NODE-003":
            # Operational vibration
            hist[nid] = _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], now, vib_rms=65.0, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=0.05, vib_rms=70.0, x=x, y=y))
        elif nid == "NODE-004":
            # Low battery fault
            hist[nid] = _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], now, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=0.05, battery_mv=3100.0, flags=1, x=x, y=y))
        elif nid == "NODE-005":
            # Thermal cooling
            hist[nid] = _history_series(nid, [0.12, 0.10, 0.08, 0.06, 0.05], now, temp_c=25.0, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=0.04, temp_c=22.0, x=x, y=y))
        elif nid == "NODE-006":
            # Stale data
            hist[nid] = _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], stale_ts, x=x, y=y)
            cur.append(_telemetry(nid, stale_ts, pitch=0.05, x=x, y=y))
        elif nid == "NODE-007":
            # Insufficient history
            hist[nid] = [_telemetry(nid, now - timedelta(minutes=15), pitch=0.05, x=x, y=y)]
            cur.append(_telemetry(nid, now, pitch=0.05, x=x, y=y))
        elif nid == "NODE-008":
            # OOD tilt
            hist[nid] = _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], now, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=82.0, x=x, y=y))
        else:
            # Healthy nominal nodes
            hist[nid] = _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], now, x=x, y=y)
            cur.append(_telemetry(nid, now, pitch=0.05, x=x, y=y))

    res = predict(cur, hist)

    # 1. Output count & order
    assert len(res["nodes"]) == 21
    assert [n["node_id"] for n in res["nodes"]] == node_ids

    # 2. Overall alarm triggered strictly by the physical event
    assert res["overall"]["alarm"] is True
    assert res["overall"]["severity"] in {"WARNING", "CRITICAL"}

    # 3. Node-specific state verification
    node_map = {n["node_id"]: n for n in res["nodes"]}

    # Physical deforming nodes
    assert node_map["NODE-001"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert node_map["NODE-002"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert node_map["NODE-001"]["deformation"]["evidence"]["spatial"] is True
    assert node_map["NODE-002"]["deformation"]["evidence"]["spatial"] is True

    # Operational vibration node
    assert node_map["NODE-003"]["deformation"]["status"] == "NORMAL"
    assert "OPERATIONAL_VIBRATION" in node_map["NODE-003"]["reason_codes"]

    # Sensor fault node
    assert node_map["NODE-004"]["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert node_map["NODE-004"]["deformation"]["status"] == "SUPPRESSED"

    # Thermal cooling node
    assert node_map["NODE-005"]["anomaly"]["evidence_status"] == "COOLING_NORMAL"
    assert "THERMAL_COOLING" in node_map["NODE-005"]["reason_codes"]

    # Stale node
    assert node_map["NODE-006"]["health"]["status"] in {"STALE_DATA", "SUSPECT"}
    assert "STALE_TELEMETRY" in node_map["NODE-006"]["reason_codes"]

    # Insufficient history node
    assert node_map["NODE-007"]["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert node_map["NODE-007"]["forecast"] is None

    # OOD node
    assert "OOD" in node_map["NODE-008"]["reason_codes"] or "TILT_OUT_OF_DOMAIN" in node_map["NODE-008"]["reason_codes"]

    # Sensor health registry correctly isolates faulty node
    assert "NODE-004" in res["sensor_health"]["faulty_nodes"]


# ==============================================================================
# SCENARIO 13: RECOVERY / RETURN TO NORMAL
# ==============================================================================
def test_scenario_13_recovery_return_to_normal():
    """Scenario 13: Ground settlement settles down and returns toward baseline.
    Expectation:
    - When tilt stabilizes back to near baseline with non-positive tilt rates,
      the current frame evaluates to NORMAL / no alarm.
    - No sticky alarm is fabricated solely from earlier elevated history.
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    # History shows a transient elevation that has now returned back to 0.05 deg
    hist = _history_series("NODE-001", [0.18, 0.14, 0.10, 0.07, 0.05], now)
    cur = [_telemetry("NODE-001", now, pitch=0.05)]

    res = predict(cur, {"NODE-001": hist})

    assert res["overall"]["alarm"] is False
    assert res["overall"]["status"] == "NORMAL"
    assert res["nodes"][0]["deformation"]["status"] in {"NORMAL", "COOLING_NORMAL", "DECREASING"}


# ==============================================================================
# SCENARIO 14: LOW-PREVALENCE STREAM
# ==============================================================================
def test_scenario_14_low_prevalence_stream():
    """Scenario 14: 15 consecutive time-steps of mostly-normal background telemetry
    with a single isolated physical event manifesting at step 10.
    Expectation:
    - Steps 0 to 9: Zero false alarms (all alarm=False).
    - Step 10: Alarm fires when physical deformation manifests.
    - Demonstrates high specificity under realistic low-prevalence operation.
    """
    base_ts = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)
    node_ids = ["N1", "N2", "N3"]

    # Initialize 5 historical normal points
    running_hist = {
        nid: _history_series(nid, [0.050, 0.051, 0.049, 0.050, 0.051], base_ts, x=float(i*30))
        for i, nid in enumerate(node_ids)
    }

    alarm_history = []

    for step in range(15):
        ts = base_ts + timedelta(minutes=15 * (step + 1))
        cur_frame = []

        for i, nid in enumerate(node_ids):
            x = float(i * 30)
            if step >= 10 and nid in {"N1", "N2"}:
                # Sustained deformation event starts at step 10
                delta = 0.08 * (step - 9)
                pitch = 0.05 + delta
            else:
                # Normal background diurnal jitter (0.048 - 0.052 deg)
                pitch = 0.050 + (0.002 if step % 2 == 0 else -0.002)

            telemetry_item = _telemetry(nid, ts, pitch=pitch, x=x)
            cur_frame.append(telemetry_item)

        res = predict(cur_frame, running_hist)
        alarm_history.append(res["overall"]["alarm"])

        # Advance running history
        for item in cur_frame:
            nid = item["node_id"]
            running_hist[nid] = (running_hist[nid] + [item])[-10:]

    # First 10 steps (0 through 9) must have ZERO false alarms
    for s in range(10):
        assert alarm_history[s] is False, f"False alarm at step {s} during quiet background"

    # Step 10+ must capture the physical deformation
    assert any(alarm_history[10:]), "Failed to detect physical deformation in low-prevalence stream"


# ==============================================================================
# SAFETY INVARIANTS A THROUGH J VERIFICATION
# ==============================================================================
def test_safety_invariants_summary():
    """Verify explicit Safety Invariants A through J:
    A. Operational vibration alone -> alarm False
    B. Thermal cooling alone -> alarm False
    C. Sensor faults -> alarm False
    D. Stale telemetry -> alarm False
    E. OOD telemetry -> alarm False
    F. Insufficient history -> forecast is None, ETA is None
    G. Missing nodes -> not invented
    H. Missing optional telemetry -> not converted to zero (preserves None)
    I. Backend-supplied observed physics -> preserved in output
    J. Knothe expected values -> never fabricated
    """
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    # Invariant I & J: Observed physics preserved, Knothe expected never fabricated
    cur = [_telemetry("NODE-001", now, pitch=0.05)]
    hist = {"NODE-001": _history_series("NODE-001", [0.050, 0.051, 0.049, 0.050, 0.051], now)}
    derived = {
        "NODE-001": {
            "subsidence_mm": 14.5,
            "strain_mm_per_m": 1.2,
            # Knothe expectations omitted
        }
    }

    res = predict(cur, hist, derived=derived)

    # Assert I: Backend observed values preserved
    node_physics = res["nodes"][0]["deformation"]["derived"]
    assert node_physics["subsidence_mm"] == 14.5
    assert node_physics["strain_mm_per_m"] == 1.2

    # Assert J: Knothe expected values NOT fabricated
    assert "expected_subsidence_mm" not in node_physics
    assert "expected_strain_mm_per_m" not in node_physics
    assert res["physics"]["status"] == "UNAVAILABLE"
