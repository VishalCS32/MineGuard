from fastapi.testclient import TestClient
import pytest

from service.app import app, PredictRequest


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


def test_cors_middleware_headers() -> None:
    client = TestClient(app)
    response = client.options(
        "/predict",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers


def test_demo_endpoint_normal_scenario() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "normal"})
    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["status"] == "NORMAL"
    assert body["overall"]["alarm"] is False
    assert body["anti_theft"]["alert"] is False
    assert body["anti_theft"]["status"] == "NORMAL"
    assert len(body["nodes"]) == 21


def test_demo_endpoint_warning_scenario() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "warning"})
    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["severity"] == "WARNING"
    assert body["time_to_threshold"]["warning_status"] == "PREDICTED"
    assert body["time_to_threshold"]["warning_hours"] is not None
    assert body["time_to_threshold"]["warning_hours"] >= 0.0
    assert len(body["nodes"]) == 21


def test_demo_endpoint_critical_scenario() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "critical"})
    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["severity"] == "CRITICAL"
    assert body["overall"]["alarm"] is True
    assert body["overall"]["alarm_reason"] == "CONFIRMED_PHYSICAL_DEFORMATION"
    assert body["anomaly"]["confirmed_physical"] is True
    assert len(body["nodes"]) == 21


def test_demo_endpoint_sensor_fault_scenario() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "sensor_fault"})
    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["severity"] == "SENSOR_FAULT"
    assert body["overall"]["alarm"] is False  # Alarm suppressed for sensor fault
    assert "NODE-001" in body["sensor_health"]["faulty_nodes"]
    assert len(body["nodes"]) == 21


def test_demo_endpoint_hardware_theft_scenario() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "hardware_theft"})
    assert response.status_code == 200
    body = response.json()
    assert body["anti_theft"]["alert"] is True
    assert body["anti_theft"]["status"] == "THEFT_SUSPECTED"
    assert "NODE-001" in body["anti_theft"]["affected_node_ids"]
    assert len(body["anti_theft"]["events"]) == 21
    stolen = next(e for e in body["anti_theft"]["events"] if e["node_id"] == "NODE-001")
    assert stolen["alert"] is True
    assert stolen["confirmed"] is True
    assert stolen["distance_from_registered_m"] >= 14.0
    assert stolen["reason_code"] == "NODE_MOVED_BEYOND_THRESHOLD"


def test_demo_endpoint_get_convenience() -> None:
    client = TestClient(app)
    response = client.get("/predict/demo?scenario=normal")
    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["status"] == "NORMAL"
    assert len(body["nodes"]) == 21


def test_demo_endpoint_invalid_scenario_returns_422() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "unsupported_xyz"})
    assert response.status_code == 422
    assert "Invalid demo scenario" in response.text


def test_response_contains_all_top_level_and_node_level_fields() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "normal"})
    assert response.status_code == 200
    body = response.json()

    # Required top-level fields
    expected_top_fields = [
        "timestamp", "model_version", "overall", "data_sufficiency",
        "data_quality", "risk", "anomaly", "deformation_state",
        "forecast", "time_to_threshold", "spatial", "physics",
        "anti_theft", "sensor_health", "nodes", "dominant_factors",
        "explanation",
    ]
    for field in expected_top_fields:
        assert field in body, f"Missing top-level field: {field}"

    # Required node-level fields
    assert len(body["nodes"]) == 21
    for node in body["nodes"]:
        expected_node_fields = [
            "node_id", "anti_theft", "health", "anomaly",
            "deformation", "risk", "forecast", "threshold_prediction",
            "confidence", "data_sufficiency", "reason_codes",
        ]
        for nfield in expected_node_fields:
            assert nfield in node, f"Missing node field: {nfield} in node {node.get('node_id')}"


def test_forecast_and_threshold_fields_present_on_sufficient_history() -> None:
    client = TestClient(app)
    response = client.post("/predict/demo", json={"scenario": "warning"})
    assert response.status_code == 200
    body = response.json()
    assert body["forecast"] is not None
    assert all(h in body["forecast"] for h in ("1", "6", "12", "24"))
    assert body["time_to_threshold"]["warning_status"] in ("PREDICTED", "ALREADY_EXCEEDED")


def test_demo_endpoint_does_not_import_simulator() -> None:
    import ast
    from pathlib import Path
    for file_name in ("demo.py", "app.py"):
        p = Path(__file__).resolve().parents[1] / "service" / file_name
        assert p.exists()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "simulator" not in alias.name, f"Forbidden import {alias.name} in {file_name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "simulator" not in mod, f"Forbidden from-import {mod} in {file_name}"


def test_sample_21_node_request_file_valid() -> None:
    import json
    from pathlib import Path
    sample_path = Path(__file__).resolve().parents[2] / "docs" / "samples" / "mineguard-21-node-sample-request.json"
    assert sample_path.exists(), f"Sample request file not found: {sample_path}"
    payload = json.loads(sample_path.read_text(encoding="utf-8"))

    # Validate Pydantic request model
    req = PredictRequest(**payload)
    assert len(req.nodes) == 21
    assert len(payload["history"]) == 21
    assert len(payload["registered_positions"]) == 21

    client = TestClient(app)
    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) == 21
    assert body["data_sufficiency"]["status"] == "READY"
    assert body["anti_theft"]["alert"] is False
    assert body["anti_theft"]["status"] == "NORMAL"


def test_sample_21_node_theft_request_file_valid() -> None:
    import json
    from pathlib import Path
    sample_path = Path(__file__).resolve().parents[2] / "docs" / "samples" / "mineguard-21-node-hardware-theft-test.json"
    assert sample_path.exists(), f"Sample request file not found: {sample_path}"
    payload = json.loads(sample_path.read_text(encoding="utf-8"))

    req = PredictRequest(**payload)
    assert len(req.nodes) == 21

    client = TestClient(app)
    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) == 21
    assert body["anti_theft"]["alert"] is True
    assert body["anti_theft"]["status"] == "THEFT_SUSPECTED"
    assert "NODE-001" in body["anti_theft"]["affected_node_ids"]

