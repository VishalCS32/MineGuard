"""Comprehensive test suite for MineGuard ML Output Contract & Edge Cases.

Verifies:
- 21-node input yields exactly 21 output nodes in matching order.
- Unique node IDs preserved.
- Complete schema on every node (health, anomaly, deformation, risk, forecast,
  threshold_prediction, confidence, data_sufficiency, reason_codes).
- Resolution of the null problem with explicit statuses.
- Sensor fault separation (SUPPRESSED physical deformation).
- Array-level overall aggregation.
- All 12 required edge-case scenarios.
"""

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from service.app import app


client = TestClient(app)


def _base_record(node_id: str, ts: datetime, *, pitch: float = 0.05, roll: float = 0.01,
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


def test_21_node_full_contract_and_order() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    current = []
    history = {}

    for i in range(1, 22):
        nid = f"NODE-{i:03d}"
        x = (i - 1) * 20.0
        # Build 6 historical frames (sufficient history)
        hist = [
            _base_record(nid, now - timedelta(hours=6 - j), pitch=0.05, x=x)
            for j in range(6)
        ]
        history[nid] = hist
        current.append(_base_record(nid, now, pitch=0.05, x=x))

    response = client.post("/predict", json={
        "nodes": current,
        "history": history,
    })
    assert response.status_code == 200
    body = response.json()

    # Top-level contract
    assert "timestamp" in body
    assert "model_version" in body
    assert "overall" in body
    assert body["overall"]["status"] in {"NORMAL", "WARNING", "CRITICAL", "SENSOR_FAULT", "INSUFFICIENT_HISTORY"}
    assert "alarm" in body["overall"]
    assert "alarm_reason" in body["overall"]
    assert "threshold_prediction" in body["overall"]

    # 21 nodes in -> exactly 21 nodes out
    nodes_out = body["nodes"]
    assert len(nodes_out) == 21
    out_ids = [n["node_id"] for n in nodes_out]
    expected_ids = [f"NODE-{i:03d}" for i in range(1, 22)]
    assert out_ids == expected_ids
    assert len(set(out_ids)) == 21

    # Verify complete schema on every single node
    for n in nodes_out:
        assert "node_id" in n
        assert "health" in n
        assert n["health"]["status"] in {"HEALTHY", "SUSPECT", "FAULTY", "SENSOR_FAULT", "STALE_DATA"}
        assert "confidence" in n["health"]
        assert "reasons" in n["health"]

        assert "anomaly" in n
        assert "detected" in n["anomaly"]
        assert "score" in n["anomaly"]
        assert "severity" in n["anomaly"]

        assert "deformation" in n
        assert n["deformation"]["status"] in {
            "NORMAL", "INSUFFICIENT_HISTORY", "UNCONFIRMED_ANOMALY",
            "CONFIRMED_PHYSICAL", "SUPPRESSED", "OOD_LOW_CONFIDENCE", "STALE_DATA"
        }
        assert "tilt_deg" in n["deformation"]
        assert "tilt_rate_deg_per_hour" in n["deformation"]
        assert "evidence" in n["deformation"]
        assert "temporal" in n["deformation"]["evidence"]
        assert "spatial" in n["deformation"]["evidence"]
        assert "physics" in n["deformation"]["evidence"]

        assert "risk" in n
        assert "score" in n["risk"]
        assert "level" in n["risk"]

        assert "forecast" in n
        assert "threshold_prediction" in n
        tp = n["threshold_prediction"]
        assert tp["warning_threshold_deg"] == 0.50
        assert tp["critical_threshold_deg"] == 1.00
        assert tp["warning_status"] in {
            "INSUFFICIENT_HISTORY", "NOT_REACHED_IN_FORECAST", "ALREADY_EXCEEDED", "PREDICTED", "LOW_CONFIDENCE"
        }
        assert tp["critical_status"] in {
            "INSUFFICIENT_HISTORY", "NOT_REACHED_IN_FORECAST", "ALREADY_EXCEEDED", "PREDICTED", "LOW_CONFIDENCE"
        }

        assert "confidence" in n
        assert "data_sufficiency" in n
        assert n["data_sufficiency"]["status"] == "READY"
        assert "reason_codes" in n
        assert isinstance(n["reason_codes"], list)


def test_12_required_edge_cases() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    current = []
    history = {}

    def make_history(nid, pitches, dt_step=timedelta(hours=1), base_ts=now, **kwargs):
        hist = []
        for i, p in enumerate(pitches):
            t = base_ts - dt_step * (len(pitches) - i)
            hist.append(_base_record(nid, t, pitch=p, **kwargs))
        return hist

    # Case 1: Healthy stable node
    nid1 = "NODE-001"
    history[nid1] = make_history(nid1, [0.05, 0.05, 0.05, 0.05, 0.05])
    current.append(_base_record(nid1, now, pitch=0.05))

    # Case 2: Insufficient-history node (only 1 prior frame)
    nid2 = "NODE-002"
    history[nid2] = make_history(nid2, [0.05])
    current.append(_base_record(nid2, now, pitch=0.05))

    # Case 3: Gradual deformation (rate ~0.04 deg/h, tilt approaches warning)
    nid3 = "NODE-003"
    history[nid3] = make_history(nid3, [0.10, 0.14, 0.18, 0.22, 0.26])
    current.append(_base_record(nid3, now, pitch=0.30))

    # Case 4: Rapid deformation (rate ~0.15 deg/h)
    nid4 = "NODE-004"
    history[nid4] = make_history(nid4, [0.10, 0.25, 0.40, 0.55, 0.70])
    current.append(_base_record(nid4, now, pitch=0.85))

    # Case 5: Already above warning (0.65 deg >= 0.50 deg)
    nid5 = "NODE-005"
    history[nid5] = make_history(nid5, [0.45, 0.50, 0.55, 0.60, 0.62])
    current.append(_base_record(nid5, now, pitch=0.65))

    # Case 6: Already above critical (1.15 deg >= 1.00 deg)
    nid6 = "NODE-006"
    history[nid6] = make_history(nid6, [0.80, 0.90, 0.98, 1.05, 1.10])
    current.append(_base_record(nid6, now, pitch=1.15))

    # Case 7: Threshold not reached in forecast (flat 0.10 deg)
    nid7 = "NODE-007"
    history[nid7] = make_history(nid7, [0.10, 0.10, 0.10, 0.10, 0.10])
    current.append(_base_record(nid7, now, pitch=0.10))

    # Case 8: Sensor fault (low battery, protocol flag)
    nid8 = "NODE-008"
    history[nid8] = make_history(nid8, [0.05, 0.05, 0.05, 0.05, 0.05])
    current.append(_base_record(nid8, now, pitch=0.05, bat=3200.0, flags=1))

    # Case 9: Stale telemetry (timestamp 3 hours old)
    nid9 = "NODE-009"
    stale_ts = now - timedelta(hours=3)
    history[nid9] = make_history(nid9, [0.05, 0.05, 0.05, 0.05, 0.05], base_ts=stale_ts)
    current.append(_base_record(nid9, stale_ts, pitch=0.05))

    # Case 10: OOD/poor quality input (temperature 85C, extreme vibration)
    nid10 = "NODE-010"
    history[nid10] = make_history(nid10, [0.05, 0.05, 0.05, 0.05, 0.05])
    current.append(_base_record(nid10, now, pitch=0.05, temp=85.0, bat=4900.0))

    # Case 11: Multi-node spatial deformation (adjacent nodes tilting together)
    nid11a = "NODE-011"
    nid11b = "NODE-012"
    history[nid11a] = make_history(nid11a, [0.20, 0.30, 0.40, 0.50, 0.55], x=100.0, y=0.0)
    history[nid11b] = make_history(nid11b, [0.22, 0.31, 0.41, 0.51, 0.56], x=130.0, y=0.0)
    current.append(_base_record(nid11a, now, pitch=0.60, x=100.0, y=0.0))
    current.append(_base_record(nid11b, now, pitch=0.61, x=130.0, y=0.0))

    # Case 12: Normal operational vibration (vibration 45 mg, resting tilt 0.04)
    nid12 = "NODE-013"
    history[nid12] = make_history(nid12, [0.04, 0.04, 0.04, 0.04, 0.04], vib=45.0)
    current.append(_base_record(nid12, now, pitch=0.04, vib=50.0))

    # Pad remaining to 21 nodes
    for i in range(14, 22):
        nid = f"NODE-{i:03d}"
        history[nid] = make_history(nid, [0.05, 0.05, 0.05, 0.05, 0.05])
        current.append(_base_record(nid, now, pitch=0.05))

    response = client.post("/predict", json={
        "nodes": current,
        "history": history,
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) == 21
    by_id = {n["node_id"]: n for n in body["nodes"]}

    # Case 1 Verification
    n1 = by_id["NODE-001"]
    assert n1["deformation"]["status"] == "NORMAL"
    assert n1["threshold_prediction"]["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert n1["threshold_prediction"]["warning_hours"] is None

    # Case 2 Verification (Insufficient History)
    n2 = by_id["NODE-002"]
    assert n2["deformation"]["status"] == "INSUFFICIENT_HISTORY"
    assert n2["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert n2["forecast"] is None
    assert n2["threshold_prediction"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert n2["threshold_prediction"]["warning_hours"] is None
    assert "INSUFFICIENT_HISTORY" in n2["reason_codes"]

    # Case 3 Verification (Gradual Deformation Predicted)
    n3 = by_id["NODE-003"]
    assert n3["threshold_prediction"]["warning_status"] == "PREDICTED"
    assert n3["threshold_prediction"]["warning_hours"] is not None
    assert n3["threshold_prediction"]["warning_hours"] > 0

    # Case 4 Verification (Rapid Deformation)
    n4 = by_id["NODE-004"]
    assert n4["deformation"]["status"] == "CONFIRMED_PHYSICAL"
    assert n4["risk"]["level"] in {"HIGH", "CRITICAL"}

    # Case 5 Verification (Already Above Warning)
    n5 = by_id["NODE-005"]
    assert n5["threshold_prediction"]["warning_status"] == "ALREADY_EXCEEDED"
    assert n5["threshold_prediction"]["warning_hours"] == 0.0
    assert "THRESHOLD_ALREADY_EXCEEDED" in n5["reason_codes"]

    # Case 6 Verification (Already Above Critical)
    n6 = by_id["NODE-006"]
    assert n6["threshold_prediction"]["critical_status"] == "ALREADY_EXCEEDED"
    assert n6["threshold_prediction"]["critical_hours"] == 0.0

    # Case 7 Verification (Not Reached in Forecast)
    n7 = by_id["NODE-007"]
    assert n7["threshold_prediction"]["warning_status"] == "NOT_REACHED_IN_FORECAST"
    assert n7["threshold_prediction"]["warning_hours"] is None

    # Case 8 Verification (Sensor Fault Gating)
    n8 = by_id["NODE-008"]
    assert n8["health"]["status"] in {"SENSOR_FAULT", "FAULTY"}
    assert n8["deformation"]["status"] == "SUPPRESSED"
    assert "LOW_BATTERY" in n8["reason_codes"]

    # Case 9 Verification (Stale Telemetry)
    n9 = by_id["NODE-009"]
    assert n9["health"]["status"] in {"STALE_DATA", "SUSPECT"}
    assert "STALE_TELEMETRY" in n9["reason_codes"]

    # Case 10 Verification (OOD Telemetry)
    n10 = by_id["NODE-010"]
    assert n10["threshold_prediction"]["warning_status"] == "LOW_CONFIDENCE"
    assert "OOD" in n10["reason_codes"]

    # Case 11 Verification (Spatial Corroboration)
    n11a = by_id["NODE-011"]
    n11b = by_id["NODE-012"]
    assert n11a["deformation"]["evidence"]["spatial"] is True
    assert n11b["deformation"]["evidence"]["spatial"] is True
    assert "SPATIAL_CORROBORATION" in n11a["reason_codes"]

    # Case 12 Verification (Normal Operational Vibration)
    n12 = by_id["NODE-013"]
    assert n12["deformation"]["status"] == "NORMAL"
    assert n12["anomaly"]["detected"] is False

    # Overall Array-Level Verification
    assert body["overall"]["alarm"] is True
    assert body["overall"]["alarm_reason"] == "CONFIRMED_PHYSICAL_DEFORMATION"
    assert body["overall"]["threshold_prediction"]["warning_status"] == "ALREADY_EXCEEDED"
