"""Dedicated Robustness Remediation Test Suite for MineGuard.

Validates:
1. Baseline freezing: developing deformation does not chase baseline.
2. Directional kinetics (A: cooling-only, B: recovering tilt, C: positive gradual deformation,
   D: deformation during cooling, E: deformation during warming).
3. Thermal compensation (T1: temp change with stable ground, T2: temp change with node bias,
   T3: temp change with genuine deformation, T4: repeated diurnal cycles).
4. Vibration regimes (V1: 40 mg, V2: 60 mg, V3: 90 mg transient, V4: high vibration + persistent tilt).
5. Spatial early onset (S1: early onset before 0.50 deg, S2: spatial thermal movement rejected,
   S3: single-node deformation confirmed without neighbors, S4: boundary node fair evaluation).
6. Knothe physics evidence (P1: stable ground, P2: consistent support, P3: inconsistent not rejected).
7. 21-node full contract mixed regression.
"""

from datetime import datetime, timedelta, timezone
from math import sqrt
import pytest

from inference.pipeline import compute_node_baseline, predict
from data.telemetry import NodeTelemetry


def _make_rec(node_id: str, ts: datetime, *, pitch: float = 0.05, roll: float = 0.0,
              vib: float = 18.0, temp: float = 26.0, bat: float = 3950.0,
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


def _hist_series(node_id: str, pitches, base_ts: datetime,
                 dt=timedelta(minutes=15), temps=None, **kwargs) -> list[dict]:
    hist = []
    for i, p in enumerate(pitches):
        t = base_ts - dt * (len(pitches) - i)
        temp_val = temps[i] if temps is not None else kwargs.get("temp", 26.0)
        hist.append(_make_rec(node_id, t, pitch=p, temp=temp_val, **kwargs))
    return hist


# ==============================================================================
# 1. BASELINE ESTIMATION & FREEZING INTEGRITY
# ==============================================================================

def test_baseline_does_not_chase_developing_deformation():
    """Verify that as deformation progresses (0.05 -> 0.18 deg), the baseline remains

    frozen near the normal historical median (0.05 deg) and residual continues increasing.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # 5 baseline samples followed by developing deformation
    history_pitches = [0.050, 0.052, 0.048, 0.051, 0.060, 0.070, 0.080, 0.100, 0.120, 0.150]
    hist = _hist_series("N1", history_pitches, now)

    baseline, mad = compute_node_baseline(hist)
    # Baseline must remain near pre-event resting level (approx 0.050), NOT >= 0.08
    assert baseline <= 0.060, f"Baseline chased deformation! Got {baseline:.4f}"
    
    # Check that current observation at 0.18 deg yields a residual >= 0.12 deg
    cur = [_make_rec("N1", now, pitch=0.180)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    residual = n1["deformation"]["tilt_deg"] - baseline
    assert residual >= 0.120, f"Residual normalized away! Residual: {residual:.4f}"
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"


# ==============================================================================
# 2. DIRECTIONAL KINETICS (A - E)
# ==============================================================================

def test_scenario_a_cooling_only_no_alarm():
    """Cooling-only trend (tilt 0.06, rate negative -0.02 deg/h) must NOT confirm physical deformation."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Decreasing tilt from 0.08 to 0.06 due to cooling
    hist = _hist_series("N1", [0.080, 0.075, 0.070, 0.065], now, dt=timedelta(minutes=15))
    cur = [_make_rec("N1", now, pitch=0.060)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] in {"NORMAL", "UNCONFIRMED_ANOMALY"}
    assert n1["anomaly"]["confirmed_physical"] is False
    assert res["overall"]["alarm"] is False


def test_scenario_b_recovering_tilt_remains_confirmed():
    """When a sensor is in recovering tilt but macroscopic deformation remains (tilt = 0.35 deg),

    it must still reflect physical deformation, not be prematurely dismissed as normal.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Tilt was 0.38, now recovering to 0.35 (negative rate, but severe elevation)
    hist = _hist_series("N1", [0.38, 0.37, 0.36, 0.355], now, dt=timedelta(minutes=15))
    cur = [_make_rec("N1", now, pitch=0.350)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True
    assert res["overall"]["alarm"] is True


def test_scenario_c_positive_gradual_deformation():
    """Gradual positive creep (tilt 0.16, positive rate +0.02 deg/h) confirms physical deformation."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.08, 0.11, 0.135], now, dt=timedelta(minutes=15))
    cur = [_make_rec("N1", now, pitch=0.160)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True
    assert res["overall"]["alarm"] is True


def test_scenario_d_deformation_during_cooling():
    """Genuine ground displacement occurring while ambient temperature is cooling.

    Ground movement overcomes thermal contraction, yielding net positive displacement.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Ambient temp dropping from 30 to 24 C, but tilt rising from 0.05 to 0.18 deg
    temps = [30.0, 28.5, 27.0, 25.5]
    pitches = [0.05, 0.09, 0.13, 0.155]
    hist = _hist_series("N1", pitches, now, temps=temps)
    cur = [_make_rec("N1", now, pitch=0.180, temp=24.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True


def test_scenario_e_deformation_during_warming():
    """Genuine ground displacement occurring while ambient temperature is warming."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    temps = [24.0, 26.0, 28.0, 30.0]
    pitches = [0.05, 0.09, 0.14, 0.17]
    hist = _hist_series("N1", pitches, now, temps=temps)
    cur = [_make_rec("N1", now, pitch=0.200, temp=32.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True


# ==============================================================================
# 3. THERMAL COMPENSATION & DRIFT TESTS (T1 - T4)
# ==============================================================================

def test_thermal_t1_large_temp_swing_stable_ground():
    """Ambient temperature changes substantially (20 -> 35 C), ground remains stable -> NORMAL."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # Mount expands slightly by 0.015 deg across 15 C swing
    temps = [20.0, 24.0, 28.0, 32.0]
    pitches = [0.040, 0.044, 0.048, 0.052]
    hist = _hist_series("N1", pitches, now, temps=temps)
    cur = [_make_rec("N1", now, pitch=0.055, temp=35.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_thermal_t2_temp_change_with_node_bias():
    """Node with high zero-bias (0.08 deg) undergoes thermal cycling -> remains NORMAL."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    temps = [22.0, 26.0, 30.0, 32.0]
    pitches = [0.080, 0.084, 0.088, 0.092]
    hist = _hist_series("N1", pitches, now, temps=temps)
    cur = [_make_rec("N1", now, pitch=0.095, temp=34.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_thermal_t3_temp_change_plus_genuine_deformation():
    """Temperature swings while genuine subsidence accelerates -> CONFIRMED_PHYSICAL."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    temps = [25.0, 27.0, 29.0, 31.0]
    pitches = [0.05, 0.10, 0.16, 0.22]
    hist = _hist_series("N1", pitches, now, temps=temps)
    cur = [_make_rec("N1", now, pitch=0.28, temp=33.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert res["overall"]["alarm"] is True


def test_thermal_t4_repeated_thermal_cycles_no_false_alarm():
    """Full 24h sinusoidal temperature cycle on stable ground must produce 0 physical alarms."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # 8 frames spanning 12 hours of heating and cooling
    temps = [22.0, 26.0, 30.0, 33.0, 30.0, 26.0, 22.0, 20.0]
    pitches = [0.040, 0.045, 0.050, 0.054, 0.049, 0.044, 0.039, 0.038]
    hist = _hist_series("N1", pitches[:-1], now, temps=temps[:-1])
    cur = [_make_rec("N1", now, pitch=pitches[-1], temp=temps[-1])]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


# ==============================================================================
# 4. VIBRATION REGIMES (V1 - V4)
# ==============================================================================

def test_vibration_v1_40mg_stable_tilt():
    """V1: 40 mg machinery vibration + stable tilt -> NORMAL / operational disturbance."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.05, 0.05, 0.05], now, vib=40.0)
    cur = [_make_rec("N1", now, pitch=0.05, vib=42.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_vibration_v2_60mg_stable_tilt():
    """V2: 60 mg machinery vibration + stable tilt -> NORMAL / operational disturbance."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.05, 0.05, 0.05], now, vib=58.0)
    cur = [_make_rec("N1", now, pitch=0.05, vib=62.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_vibration_v3_90mg_transient_shock_stable_tilt():
    """V3: 90 mg haulage transient shock + stable tilt -> NORMAL or UNCONFIRMED, no alarm."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.05, 0.05, 0.05], now, vib=20.0)
    cur = [_make_rec("N1", now, pitch=0.05, vib=95.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] in {"NORMAL", "UNCONFIRMED_ANOMALY"}
    assert n1["anomaly"]["confirmed_physical"] is False
    assert res["overall"]["alarm"] is False


def test_vibration_v4_high_vibration_with_persistent_tilt_confirms():
    """V4: High machinery vibration accompanied by persistent positive tilt deformation confirms."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.10, 0.15, 0.20], now, vib=60.0)
    cur = [_make_rec("N1", now, pitch=0.25, vib=65.0)]
    res = predict(cur, {"N1": hist})
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True
    assert res["overall"]["alarm"] is True


# ==============================================================================
# 5. SPATIAL EARLY-ONSET & BOUNDARY EVALUATION (S1 - S4)
# ==============================================================================

def test_spatial_s1_early_onset_detected_before_warning_threshold():
    """S1: 3 neighboring nodes (0.15 -> 0.20 -> 0.25 deg) move coherently.

    Spatial evidence must be active BEFORE reaching the 0.50 deg threshold.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    h1 = _hist_series("N1", [0.05, 0.09, 0.13, 0.16], now, x=0.0, y=0.0)
    h2 = _hist_series("N2", [0.05, 0.09, 0.12, 0.15], now, x=30.0, y=0.0)
    h3 = _hist_series("N3", [0.05, 0.08, 0.12, 0.15], now, x=0.0, y=30.0)
    cur = [
        _make_rec("N1", now, pitch=0.20, x=0.0, y=0.0),
        _make_rec("N2", now, pitch=0.19, x=30.0, y=0.0),
        _make_rec("N3", now, pitch=0.18, x=0.0, y=30.0),
    ]
    res = predict(cur, {"N1": h1, "N2": h2, "N3": h3})
    for node_out in res["nodes"]:
        assert node_out["deformation"]["evidence"]["spatial"] is True
        assert node_out["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert res["overall"]["alarm"] is True


def test_spatial_s2_coherent_thermal_drift_rejected():
    """S2: 3 neighboring nodes undergo small diurnal thermal movement together -> NO physical alarm."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    h1 = _hist_series("N1", [0.04, 0.045, 0.05, 0.052], now, x=0.0, y=0.0)
    h2 = _hist_series("N2", [0.04, 0.045, 0.05, 0.052], now, x=30.0, y=0.0)
    h3 = _hist_series("N3", [0.04, 0.045, 0.05, 0.052], now, x=0.0, y=30.0)
    cur = [
        _make_rec("N1", now, pitch=0.055, x=0.0, y=0.0),
        _make_rec("N2", now, pitch=0.055, x=30.0, y=0.0),
        _make_rec("N3", now, pitch=0.055, x=0.0, y=30.0),
    ]
    res = predict(cur, {"N1": h1, "N2": h2, "N3": h3})
    for node_out in res["nodes"]:
        assert node_out["deformation"]["status"] == "NORMAL"
    assert res["overall"]["alarm"] is False


def test_spatial_s3_single_node_deformation_detectable_without_neighbors():
    """S3: Sinkhole directly under N1 alone. N2 and N3 remain resting.

    N1 must confirm via temporal persistence alone.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    h1 = _hist_series("N1", [0.05, 0.09, 0.13, 0.17], now, x=0.0, y=0.0)
    h2 = _hist_series("N2", [0.05, 0.05, 0.05, 0.05], now, x=30.0, y=0.0)
    h3 = _hist_series("N3", [0.05, 0.05, 0.05, 0.05], now, x=0.0, y=30.0)
    cur = [
        _make_rec("N1", now, pitch=0.22, x=0.0, y=0.0),
        _make_rec("N2", now, pitch=0.05, x=30.0, y=0.0),
        _make_rec("N3", now, pitch=0.05, x=0.0, y=30.0),
    ]
    res = predict(cur, {"N1": h1, "N2": h2, "N3": h3})
    n1 = next(n for n in res["nodes"] if n["node_id"] == "N1")
    n2 = next(n for n in res["nodes"] if n["node_id"] == "N2")
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n2["deformation"]["status"] == "NORMAL"


def test_spatial_s4_boundary_node_fair_corroboration():
    """S4: Boundary node on mine edge has only 1 neighbor within 100m.

    When both move coherently, boundary node receives spatial corroboration.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # N_edge at (0, 0), N_neighbor at (40, 0). No other neighbors.
    h_edge = _hist_series("N_edge", [0.05, 0.09, 0.13, 0.16], now, x=0.0, y=0.0)
    h_neigh = _hist_series("N_neigh", [0.05, 0.09, 0.13, 0.16], now, x=40.0, y=0.0)
    cur = [
        _make_rec("N_edge", now, pitch=0.20, x=0.0, y=0.0),
        _make_rec("N_neigh", now, pitch=0.19, x=40.0, y=0.0),
    ]
    res = predict(cur, {"N_edge": h_edge, "N_neigh": h_neigh})
    n_edge = next(n for n in res["nodes"] if n["node_id"] == "N_edge")
    assert n_edge["deformation"]["evidence"]["spatial"] is True
    assert n_edge["deformation"]["status"] == "CONFIRMED_PHYSICAL"


# ==============================================================================
# 6. KNOTHE PHYSICS EVIDENCE (P1 - P3)
# ==============================================================================

def test_physics_p1_stable_ground_no_false_alarm():
    """P1: Stable ground with Knothe residual supplied -> NORMAL."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.05, 0.05, 0.05], now)
    cur = [_make_rec("N1", now, pitch=0.05)]
    derived = {"N1": {"observed": 0.05, "expected": 0.05}}
    res = predict(cur, {"N1": hist}, derived=derived)
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "NORMAL"
    assert res["physics"]["status"] == "AVAILABLE"


def test_physics_p2_knothe_consistent_deformation():
    """P2: Developing deformation consistent with Knothe -> positive physics support."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.09, 0.13, 0.16], now)
    cur = [_make_rec("N1", now, pitch=0.20)]
    derived = {"N1": {"observed": 0.20, "expected": 0.20}}
    res = predict(cur, {"N1": hist}, derived=derived)
    n1 = res["nodes"][0]
    assert n1["deformation"]["evidence"]["physics"] is True
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"


def test_physics_p3_knothe_inconsistent_not_rejected():
    """P3: Genuine geological deformation inconsistent with simplified Knothe model

    must NOT be rejected when independent temporal evidence is strong.
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    hist = _hist_series("N1", [0.05, 0.10, 0.15, 0.20], now)
    cur = [_make_rec("N1", now, pitch=0.26)]
    # Inconsistent Knothe expectation (model expected 0.05)
    derived = {"N1": {"observed": 0.26, "expected": 0.05}}
    res = predict(cur, {"N1": hist}, derived=derived)
    n1 = res["nodes"][0]
    assert n1["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n1["anomaly"]["confirmed_physical"] is True


# ==============================================================================
# 7. 21-NODE OUTPUT CONTRACT MIXED REGRESSION
# ==============================================================================

def test_21_node_contract_mixed_heterogeneous_regression():
    """21 heterogeneous nodes in -> EXACTLY 21 outputs out, preserved order, no contamination."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    node_ids = [f"NODE-{i:03d}" for i in range(1, 22)]
    
    # Heterogeneous setup:
    # NODE-001: Persistent deformation
    # NODE-002: Spatial neighbor of 001, also deforming
    # NODE-003: Operational machinery vibration (60 mg)
    # NODE-004: Sensor fault (battery 3100 mV)
    # NODE-005: Thermal cooling (rate -0.02 deg/h)
    # NODE-006: Stale data
    # NODE-007: OOD tilt
    # NODE-008: Insufficient history
    # NODE-009 through 021: Healthy normal nodes
    cur = []
    hist_map = {}
    
    for nid in node_ids:
        if nid == "NODE-001":
            hist_map[nid] = _hist_series(nid, [0.05, 0.10, 0.15, 0.20], now, x=0.0)
            cur.append(_make_rec(nid, now, pitch=0.25, x=0.0))
        elif nid == "NODE-002":
            hist_map[nid] = _hist_series(nid, [0.05, 0.09, 0.14, 0.19], now, x=25.0)
            cur.append(_make_rec(nid, now, pitch=0.24, x=25.0))
        elif nid == "NODE-003":
            hist_map[nid] = _hist_series(nid, [0.05, 0.05, 0.05, 0.05], now, vib=60.0)
            cur.append(_make_rec(nid, now, pitch=0.05, vib=65.0))
        elif nid == "NODE-004":
            hist_map[nid] = _hist_series(nid, [0.05, 0.05, 0.05, 0.05], now)
            cur.append(_make_rec(nid, now, pitch=0.05, bat=3100.0, flags=1))
        elif nid == "NODE-005":
            hist_map[nid] = _hist_series(nid, [0.08, 0.07, 0.06, 0.055], now)
            cur.append(_make_rec(nid, now, pitch=0.050))
        elif nid == "NODE-006":
            hist_map[nid] = _hist_series(nid, [0.05, 0.05, 0.05, 0.05], now)
            cur.append(_make_rec(nid, now - timedelta(hours=2), pitch=0.05))
        elif nid == "NODE-007":
            hist_map[nid] = _hist_series(nid, [0.05, 0.05, 0.05, 0.05], now)
            cur.append(_make_rec(nid, now, pitch=85.0))  # OOD
        elif nid == "NODE-008":
            hist_map[nid] = []  # Insufficient history
            cur.append(_make_rec(nid, now, pitch=0.05))
        else:
            hist_map[nid] = _hist_series(nid, [0.05, 0.05, 0.05, 0.05], now)
            cur.append(_make_rec(nid, now, pitch=0.05))

    res = predict(cur, hist_map)
    out_nodes = res["nodes"]
    assert len(out_nodes) == 21
    assert [n["node_id"] for n in out_nodes] == node_ids

    # Verify independent states
    out_map = {n["node_id"]: n for n in out_nodes}
    assert out_map["NODE-001"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert out_map["NODE-002"]["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert out_map["NODE-003"]["deformation"]["status"] == "NORMAL"  # Vibe only
    assert out_map["NODE-004"]["health"]["status"] == "SENSOR_FAULT"
    assert out_map["NODE-005"]["deformation"]["status"] == "NORMAL"  # Cooling
    assert out_map["NODE-006"]["health"]["status"] == "STALE_DATA"
    assert out_map["NODE-007"]["deformation"]["status"] == "OOD_LOW_CONFIDENCE"
    assert out_map["NODE-008"]["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert out_map["NODE-009"]["deformation"]["status"] == "NORMAL"
