from fastapi.testclient import TestClient
import pytest

from service.app import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "model_version" in body


def test_model_info_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/model/info")
    assert response.status_code == 200
    body = response.json()
    assert "model_version" in body
    assert "data_source" in body
    assert "feature_names" in body


def test_predict_api_returns_sufficiency_and_safe_empty_forecast() -> None:
    client = TestClient(app)
    response = client.post("/predict", json={
        "nodes": [{
            "node_id": "N1", "timestamp": "2026-09-09T12:00:00Z",
            "pitch_deg": 0.8, "roll_deg": 0.0,
            "vibration_rms_mg": 20, "vibration_peak_hz": 30,
            "temperature_c": 28.0, "n_samples": 32,
            "gnss_status": 14, "battery_mv": 3900,
            "rssi_dbm": -70, "snr_db": 8, "flags": 0,
        }],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
    assert body["forecast"] is None
    assert body["time_to_threshold"]["warning_hours"] is None
    assert body["physics"]["status"] == "UNAVAILABLE"
    assert body["data_quality"]["status"] == "NORMAL"


def test_predict_api_rejects_malformed_input() -> None:
    client = TestClient(app)
    # Empty nodes
    res1 = client.post("/predict", json={"nodes": []})
    assert res1.status_code == 422

    # Missing nodes entirely
    res2 = client.post("/predict", json={"history": {}})
    assert res2.status_code == 422

    # Malformed node types
    res3 = client.post("/predict", json={"nodes": "not_a_list"})
    assert res3.status_code == 422


def test_predict_backend_telemetry_integration() -> None:
    """Simulate backend ingestion record format flowing into ML service."""
    client = TestClient(app)
    timestamps = [
        f"2026-09-09T{hour:02d}:00:00Z" for hour in range(10, 16)
    ]
    history = [
        {
            "node_id": "101",
            "timestamp": ts,
            "pitch_deg": 0.10 + i * 0.02,
            "roll_deg": 0.01,
            "vibration_rms_mg": 15.0,
            "vibration_peak_hz": 30.0,
            "temperature_c": 28.5,
            "n_samples": 32,
            "gnss_status": 14,
            "battery_mv": 3950,
            "rssi_dbm": -72,
            "snr_db": 8.5,
            "flags": 0,
            "x_m": 50.0,
            "y_m": 0.0,
        }
        for i, ts in enumerate(timestamps[:-1])
    ]
    current = [{
        "node_id": "101",
        "timestamp": timestamps[-1],
        "pitch_deg": 0.20,
        "roll_deg": 0.01,
        "vibration_rms_mg": 18.0,
        "vibration_peak_hz": 30.0,
        "temperature_c": 28.6,
        "n_samples": 32,
        "gnss_status": 14,
        "battery_mv": 3940,
        "rssi_dbm": -73,
        "snr_db": 8.0,
        "flags": 0,
        "x_m": 50.0,
        "y_m": 0.0,
    }]
    derived = {
        "101": {
            "observed": 45.0,
            "expected": 42.0,
            "strain_mm_per_m": 0.12,
        }
    }

    response = client.post("/predict", json={
        "nodes": current,
        "history": {"101": history},
        "derived": derived,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["data_sufficiency"]["status"] == "READY"
    assert body["physics"]["status"] == "AVAILABLE"
    assert body["physics"]["residual_score"] is not None
    assert body["forecast"] is not None
    assert "1" in body["forecast"]
    assert "24" in body["forecast"]
    assert body["forecast"]["1"]["tilt_deg"] == pytest.approx(current[0]["pitch_deg"], abs=0.01)
    assert body["risk"]["score"] >= 0.0
    assert body["data_quality"]["status"] == "NORMAL"


def test_predict_detects_out_of_distribution_telemetry() -> None:
    client = TestClient(app)
    # Abnormal temperature (95C) and extreme battery (5000 mV)
    response = client.post("/predict", json={
        "nodes": [{
            "node_id": "N1", "timestamp": "2026-09-09T12:00:00Z",
            "pitch_deg": 0.1, "roll_deg": 0.0,
            "vibration_rms_mg": 20, "vibration_peak_hz": 30,
            "temperature_c": 95.0,  # OOD
            "n_samples": 32,
            "gnss_status": 14,
            "battery_mv": 5100,     # OOD
            "rssi_dbm": -70, "snr_db": 8, "flags": 0,
        }],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["data_quality"]["status"] == "DEGRADED"
    assert body["data_quality"]["out_of_distribution"] is True
    assert len(body["data_quality"]["warnings"]) >= 2
