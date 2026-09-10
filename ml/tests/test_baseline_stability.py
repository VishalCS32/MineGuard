from datetime import datetime, timedelta, timezone

import pytest

from inference.pipeline import predict
from models.estimators import DeformationState


def record(node_id: str, tilt: float, when: datetime, *, x: float = 0.0,
           flags: int = 0, battery: int = 3900, rssi: int = -70,
           snr: float = 8.0) -> dict:
    return {
        "node_id": node_id, "timestamp": when.isoformat(),
        "pitch_deg": tilt, "roll_deg": 0.0,
        "vibration_rms_mg": 20, "vibration_peak_hz": 30,
        "temperature_c": 28.0, "n_samples": 32, "gnss_status": 14,
        "battery_mv": battery, "rssi_dbm": rssi, "snr_db": snr,
        "flags": flags, "x_m": x, "y_m": 0.0,
    }


def series(node_id: str, values: list[float], *, start=None, x=0.0, **kwargs):
    start = start or datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    return [record(node_id, value, start + timedelta(minutes=15 * index), x=x, **kwargs)
            for index, value in enumerate(values)]


def request(current, history, **kwargs):
    return predict(current, {"N1": history}, **kwargs)


def test_insufficient_history_does_not_claim_rapid_deformation():
    observations = series("N1", [0.1, 0.3])
    result = request(observations[-1:], observations[:-1])
    assert result["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert result["deformation_state"] == "INSUFFICIENT_HISTORY"
    assert result["forecast"] is None
    assert result["time_to_threshold"]["warning_hours"] is None
    assert result["time_to_threshold"]["critical_hours"] is None
    assert result["time_to_threshold"]["warning_status"] == "INSUFFICIENT_HISTORY"
    assert result["time_to_threshold"]["critical_status"] == "INSUFFICIENT_HISTORY"
    assert result["risk"]["confidence"] == 0.0
    assert result["anomaly"]["severity"] == "INSUFFICIENT_HISTORY"


def test_stable_history_is_stable_and_forecast_is_bounded():
    observations = series("N1", [0.10, 0.101, 0.099, 0.100, 0.101])
    result = request(observations[-1:], observations[:-1])
    assert result["data_sufficiency"]["status"] == "READY"
    assert result["deformation_state"] == DeformationState.STABLE.value
    assert result["forecast"]["24"]["tilt_deg"] == pytest.approx(0.101, abs=0.01)


def test_increasing_history_gets_robust_progression_and_lead_time():
    observations = series("N1", [0.10, 0.12, 0.15, 0.18, 0.21])
    result = request(observations[-1:], observations[:-1])
    assert result["deformation_state"] in {"SLOW_CREEP", "ACCELERATING"}
    assert result["forecast"]["24"]["tilt_deg"] < 1.0
    assert result["time_to_threshold"]["warning_hours"] is not None


def test_outlier_does_not_create_quadratic_forecast():
    observations = series("N1", [0.10, 0.11, 0.12, 0.80, 0.13])
    result = request(observations[-1:], observations[:-1])
    assert result["data_sufficiency"]["status"] == "READY"
    assert result["forecast"]["24"]["tilt_deg"] < 2.0


def test_sensor_fault_and_communications_are_reported_separately():
    observations = series("N1", [0.1, 0.1, 0.1, 0.1, 0.1], flags=1,
                          battery=3400, rssi=-120, snr=-8)
    result = request(observations[-1:], observations[:-1])
    node = result["nodes"][0]
    assert node["health"]["status"] in {"FAULTY", "SENSOR_FAULT"}
    assert "low battery" in node["health"]["reasons"]
    assert "degraded communication" in node["health"]["reasons"]
    assert result["anomaly"]["detected"] is False


def test_stale_node_is_reported_as_health_evidence():
    start = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    current = [record("N1", 0.1, start), record("N2", 0.1, start + timedelta(hours=2), x=50)]
    history = {
        "N1": series("N1", [0.1, 0.1, 0.1, 0.1], start=start - timedelta(hours=1)),
        "N2": series("N2", [0.1, 0.1, 0.1, 0.1], start=start - timedelta(hours=1), x=50),
    }
    result = predict(current, history)
    node = next(item for item in result["nodes"] if item["node_id"] == "N1")
    assert "telemetry is stale" in node["health"]["reasons"]


def test_neighbouring_nodes_are_spatially_consistent():
    start = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    current = [record("N1", 0.6, start + timedelta(hours=1), x=0),
               record("N2", 0.61, start + timedelta(hours=1), x=50)]
    history = {
        "N1": series("N1", [0.1, 0.15, 0.2, 0.25], x=0),
        "N2": series("N2", [0.1, 0.15, 0.2, 0.25], x=50),
    }
    result = predict(current, history)
    assert result["spatial"]["consistency"] == 1.0
    assert result["spatial"]["spreading"] is True


def test_physics_residual_is_only_returned_when_expected_is_supplied():
    observations = series("N1", [0.1, 0.1, 0.1, 0.1, 0.1])
    unavailable = request(observations[-1:], observations[:-1])
    available = request(observations[-1:], observations[:-1],
                        derived={"N1": {"observed": 0.8, "expected": 0.2}})
    assert unavailable["physics"]["residual_score"] is None
    assert unavailable["physics"]["status"] == "UNAVAILABLE"
    assert available["physics"]["residual_score"] == pytest.approx(0.6)
    assert available["physics"]["status"] == "AVAILABLE"


def test_unhealthy_sensor_fault_is_gated_from_physical_alarm():
    # Sensor with low battery and protocol flags (unhealthy)
    observations = series("N1", [0.1, 0.1, 0.1, 0.1, 0.1], battery=3200, flags=1)
    result = request(observations[-1:], observations[:-1])
    n1_out = result["nodes"][0]
    assert n1_out["health"]["status"] in {"SUSPECT", "FAULTY", "SENSOR_FAULT"}
    assert n1_out["anomaly"]["confirmed_physical"] is False
    assert n1_out["anomaly"]["evidence_status"] == "SENSOR_FAULT"


def test_persistent_anomaly_confirms_physical_event():
    # Elevated deformation sequence
    observations = series("N1", [0.1, 0.15, 0.25, 0.35, 0.45])
    result = request(observations[-1:], observations[:-1])
    assert result["anomaly"]["confirmed_physical"] is True
    assert result["anomaly"]["evidence_status"] == "CONFIRMED_PHYSICAL"


def test_spatial_corroboration_confirms_physical_event():
    start = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    current = [record("N1", 0.30, start + timedelta(hours=1), x=0),
               record("N2", 0.31, start + timedelta(hours=1), x=40)]
    history = {
        "N1": series("N1", [0.1, 0.1, 0.1, 0.1], x=0),
        "N2": series("N2", [0.1, 0.1, 0.1, 0.1], x=40),
    }
    result = predict(current, history, warning_tilt_deg=0.25)
    assert result["spatial"]["spreading"] is True
    assert result["anomaly"]["confirmed_physical"] is True
    assert result["anomaly"]["evidence_status"] == "CONFIRMED_PHYSICAL"
