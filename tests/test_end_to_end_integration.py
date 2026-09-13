import asyncio
import os
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parents[1])
_ml_root = str(Path(__file__).resolve().parents[1] / "ml")
if _root not in sys.path:
    sys.path.insert(0, _root)
if _ml_root not in sys.path:
    sys.path.insert(0, _ml_root)

from datetime import datetime, timedelta, timezone
from typing import Any
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gateway.uplink import GatewayUplink, build_telemetry_payload
from backend.app.main import app as backend_app
from backend.app.config import get_settings
from backend.app.db import dispose_db, init_db
from backend.app.ml_payload import build_ml_payload, telemetry_to_ml_node
from ml.inference.pipeline import predict as ml_inference_predict


def run_ml_predict(nodes: list[dict[str, Any]], history: dict[str, Any] | None = None, derived: dict[str, Any] | None = None, registered_positions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Helper wrapping the production ML pipeline predict call."""
    return ml_inference_predict(
        current=nodes,
        history=history,
        derived=derived,
        registered_positions=registered_positions,
    )


@pytest_asyncio.fixture
async def e2e_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'e2e.db'}")
    monkeypatch.setenv("MQTT_HOST", "")
    monkeypatch.setenv("ML_SERVICE_URL", "")
    get_settings.cache_clear()
    await dispose_db()

    async with AsyncClient(transport=ASGITransport(app=backend_app), base_url="http://test") as client:
        await init_db()
        # Provision default test site
        site_req = {
            "slug": "jharia-l7",
            "name": "Jharia Panel L-7",
            "origin_lat": 23.7500,
            "origin_lon": 86.4200,
            "nodes": [
                {"addr": 1, "label": "NODE-001", "lat": 23.7501, "lon": 86.4201, "x_m": 0.0, "y_m": 0.0},
                {"addr": 2, "label": "NODE-002", "lat": 23.7502, "lon": 86.4202, "x_m": 25.0, "y_m": 0.0},
            ],
        }
        resp = await client.post("/api/provision", json=site_req)
        assert resp.status_code == 201
        yield client

    await dispose_db()
    get_settings.cache_clear()


class TestMandatoryScenarios:

    # 1. One valid sensor frame
    @pytest.mark.asyncio
    async def test_01_one_valid_sensor_frame(self, e2e_client):
        payload = build_telemetry_payload(
            node_id="NODE-001",
            pitch_deg=0.35,
            roll_deg=-0.12,
            vibration_rms_mg=18.5,
            temperature_c=26.4,
            battery_mv=3920.0,
            latitude=23.7501,
            longitude=86.4201,
        )
        resp = await e2e_client.post("/api/v1/telemetry", json=payload)
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 1}

        snap = (await e2e_client.get("/api/snapshot")).json()
        assert len(snap["nodes"]) >= 1
        node = next(n for n in snap["nodes"] if n["label"] == "NODE-001")
        assert node["online"] is True
        assert abs(node["tempC"] - 26.4) < 0.1

    # 2. Multiple frames
    @pytest.mark.asyncio
    async def test_02_multiple_frames(self, e2e_client):
        base_t = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            payload = build_telemetry_payload(
                node_id="NODE-001",
                timestamp=base_t + timedelta(minutes=15 * i),
                pitch_deg=0.10 + (0.02 * i),
                roll_deg=-0.05,
                vibration_rms_mg=15.0,
            )
            resp = await e2e_client.post("/api/v1/telemetry", json=payload)
            assert resp.status_code == 202

        hist = (await e2e_client.get("/api/nodes/1/history")).json()
        assert len(hist) >= 5
        # Verify chronological order
        assert hist[-1]["t"] >= hist[0]["t"]

    # 3. Multiple nodes
    @pytest.mark.asyncio
    async def test_03_multiple_nodes(self, e2e_client):
        batch = [
            build_telemetry_payload(node_id=f"NODE-{i:03d}", pitch_deg=0.1 * i, roll_deg=0.0)
            for i in range(1, 4)
        ]
        resp = await e2e_client.post("/api/v1/telemetry", json=batch)
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 3}

        snap = (await e2e_client.get("/api/snapshot")).json()
        labels = {n["label"] for n in snap["nodes"]}
        assert {"NODE-001", "NODE-002", "NODE-003"}.issubset(labels)

    # 4. Malformed payload
    @pytest.mark.asyncio
    async def test_04_malformed_payload(self, e2e_client):
        # Missing node_id
        resp = await e2e_client.post("/api/v1/telemetry", json={"pitch_deg": 12.0})
        assert resp.status_code == 422

    # 5. Missing telemetry (empty list)
    @pytest.mark.asyncio
    async def test_05_missing_telemetry(self, e2e_client):
        resp = await e2e_client.post("/api/v1/telemetry", json=[])
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 0}

    # 6. Duplicate frame handling
    @pytest.mark.asyncio
    async def test_06_duplicate_frame(self, e2e_client):
        payload = build_telemetry_payload(
            node_id="NODE-001",
            timestamp="2026-09-13T08:00:00Z",
            pitch_deg=0.25,
        )
        # First send
        resp1 = await e2e_client.post("/api/v1/telemetry", json=payload)
        assert resp1.status_code == 202

        # Second send of identical frame
        resp2 = await e2e_client.post("/api/v1/telemetry", json=payload)
        assert resp2.status_code == 202

        hist = (await e2e_client.get("/api/nodes/1/history")).json()
        # Database should store safely
        assert len(hist) >= 1

    # 7. Stale timestamp
    @pytest.mark.asyncio
    async def test_07_stale_timestamp(self, e2e_client):
        stale_t = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        payload = build_telemetry_payload(
            node_id="NODE-001",
            timestamp=stale_t,
            pitch_deg=0.1,
        )
        resp = await e2e_client.post("/api/v1/telemetry", json=payload)
        assert resp.status_code == 202

    # 8. Gateway retry logic on transient failure
    def test_08_gateway_retry(self):
        gw = GatewayUplink(backend_url="http://127.0.0.1:59999/api/v1/telemetry", timeout_s=0.2, max_retries=2)
        reading = build_telemetry_payload(node_id="NODE-001")
        res = gw.send_reading(reading)
        # Network unreachable -> buffered in gateway spool
        assert res.success is False
        assert len(gw.buffer) == 1

    # 9. Backend unavailable
    def test_09_backend_unavailable(self):
        gw = GatewayUplink(backend_url="http://localhost:59999", timeout_s=0.1, max_retries=0)
        reading = build_telemetry_payload(node_id="NODE-001")
        res = gw.send_reading(reading)
        assert res.success is False
        assert res.error is not None
        # Reading must not be lost
        assert len(gw.buffer) == 1

    # 10. ML unavailable
    @pytest.mark.asyncio
    async def test_10_ml_unavailable(self, e2e_client):
        # With ML_SERVICE_URL unset or unavailable, snapshot must succeed with ml_status indicator
        snap = (await e2e_client.get("/api/snapshot")).json()
        assert "kpis" in snap
        assert "nodes" in snap
        # ML field indicates degradation without crashing backend
        assert snap.get("ml") is None or snap.get("ml", {}).get("ml_status") in ("ML_UNAVAILABLE", None)

    # 11. Insufficient history
    def test_11_insufficient_history(self):
        # 1 point only -> insufficient history for trend forecasting
        reading = build_telemetry_payload(node_id="NODE-001", pitch_deg=0.04, roll_deg=0.01)
        ml_node = telemetry_to_ml_node(reading)
        res = run_ml_predict(nodes=[ml_node], history=None)
        assert res["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY"
        assert res["overall"]["status"] in ("NORMAL", "INSUFFICIENT_HISTORY")

    # 12. Dynamic node counts: 1, 2, 5, 10, 21, 25, 50 nodes and arbitrary IDs
    @pytest.mark.parametrize("n_count", [1, 2, 5, 10, 21, 25, 50])
    def test_12_dynamic_node_counts(self, n_count):
        custom_ids = ["NODE-001", "N42", "ROOF-A", "CENTER-3", "SENSOR-ALPHA"]
        now = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
        nodes = []
        history = {}
        for i in range(n_count):
            nid = custom_ids[i] if i < len(custom_ids) else f"DYN-{i:03d}"
            cur = telemetry_to_ml_node(build_telemetry_payload(
                node_id=nid,
                timestamp=now,
                pitch_deg=0.050,
                roll_deg=0.01,
                battery_mv=3900.0,
            ))
            nodes.append(cur)
            history[nid] = [
                telemetry_to_ml_node(build_telemetry_payload(
                    node_id=nid,
                    timestamp=now - timedelta(minutes=15 * (5 - h)),
                    pitch_deg=0.048 + 0.001 * (h % 3),
                    roll_deg=0.01,
                    battery_mv=3900.0,
                ))
                for h in range(5)
            ]
        res = run_ml_predict(nodes=nodes, history=history)
        assert len(res["nodes"]) == n_count
        assert res["sensor_health"]["healthy_nodes"] == n_count

    # 13. Accelerometer present
    def test_13_accelerometer_present(self):
        reading = build_telemetry_payload(
            node_id="NODE-001",
            pitch_deg=0.35,
            accel_x=0.12,
            accel_y=-0.04,
            accel_z=9.78,
        )
        assert reading["sensor_data"]["accelerometer"]["x"] == 0.12
        ml_node = telemetry_to_ml_node(reading)
        assert ml_node["accel"]["x"] == 0.12
        assert ml_node["accel"]["z"] == 9.78
        res = run_ml_predict(nodes=[ml_node])
        assert res["overall"]["status"] in ("NORMAL", "INSUFFICIENT_HISTORY")

    # 14. Gyroscope present
    def test_14_gyroscope_present(self):
        reading = build_telemetry_payload(
            node_id="NODE-001",
            pitch_deg=0.35,
            gyro_x=0.012,
            gyro_y=-0.008,
            gyro_z=0.021,
        )
        assert reading["sensor_data"]["gyro"]["x"] == 0.012
        ml_node = telemetry_to_ml_node(reading)
        assert ml_node["gyro"]["x"] == 0.012
        res = run_ml_predict(nodes=[ml_node])
        assert res["overall"]["status"] in ("NORMAL", "INSUFFICIENT_HISTORY")

    # 15. Gyroscope missing (null, not fabricated)
    def test_15_gyroscope_missing(self):
        reading = build_telemetry_payload(node_id="NODE-001", pitch_deg=0.35, gyro_x=None)
        assert reading["sensor_data"]["gyro"]["x"] is None
        ml_node = telemetry_to_ml_node(reading)
        assert ml_node["gyro"]["x"] is None
        res = run_ml_predict(nodes=[ml_node])
        assert res["overall"]["status"] in ("NORMAL", "INSUFFICIENT_HISTORY")

    # 16. Accelerometer missing (null, not fabricated)
    def test_16_accelerometer_missing(self):
        reading = build_telemetry_payload(node_id="NODE-001", pitch_deg=0.35, accel_x=None)
        assert reading["sensor_data"]["accelerometer"]["x"] is None
        ml_node = telemetry_to_ml_node(reading)
        assert ml_node["accel"]["x"] is None
        res = run_ml_predict(nodes=[ml_node])
        assert res["overall"]["status"] in ("NORMAL", "INSUFFICIENT_HISTORY")

    # 17. GPS present
    def test_17_gps_present(self):
        reading = build_telemetry_payload(
            node_id="NODE-001",
            latitude=23.7500,
            longitude=86.4200,
            altitude_m=245.3,
            satellites=14,
        )
        ml_node = telemetry_to_ml_node(reading)
        assert ml_node["gps"]["latitude"] == 23.7500
        assert ml_node["gps"]["longitude"] == 86.4200
        assert ml_node["gps"]["altitude_m"] == 245.3
        res = run_ml_predict(
            nodes=[ml_node],
            registered_positions={"NODE-001": {"latitude": 23.7500, "longitude": 86.4200}},
        )
        assert res["anti_theft"]["alert"] is False

    # 18. GPS missing
    def test_18_gps_missing(self):
        reading = build_telemetry_payload(node_id="NODE-001", latitude=None, longitude=None)
        ml_node = telemetry_to_ml_node(reading)
        assert ml_node["gps"]["latitude"] is None
        res = run_ml_predict(nodes=[ml_node])
        assert res["anti_theft"]["alert"] is False

    # 19. Sensor fault (e.g. low battery / hardware flags)
    def test_19_sensor_fault(self):
        reading = build_telemetry_payload(node_id="NODE-001", battery_mv=2900.0, flags=0x01)
        ml_node = telemetry_to_ml_node(reading)
        res = run_ml_predict(nodes=[ml_node])
        assert res["overall"]["status"] == "SENSOR_FAULT"
        assert "NODE-001" in res["sensor_health"]["faulty_nodes"]

    # 20. Normal telemetry
    def test_20_normal_telemetry(self):
        # 4 historical points + current frame, baseline resting ~0.04 deg
        history = {
            "NODE-001": [
                telemetry_to_ml_node(build_telemetry_payload(node_id="NODE-001", timestamp=f"2026-09-13T0{h}:00:00Z", pitch_deg=0.04, roll_deg=0.01))
                for h in range(1, 5)
            ]
        }
        current = [telemetry_to_ml_node(build_telemetry_payload(node_id="NODE-001", timestamp="2026-09-13T05:00:00Z", pitch_deg=0.041, roll_deg=0.01))]
        res = run_ml_predict(nodes=current, history=history)
        assert res["overall"]["status"] == "NORMAL"
        assert res["overall"]["alarm"] is False
        assert res["overall"]["risk_level"] == "LOW"

    # 21. Anomalous telemetry
    def test_21_anomalous_telemetry(self):
        # Progressive deformation exceeding warning threshold
        now = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
        history = {
            "NODE-001": [
                telemetry_to_ml_node(build_telemetry_payload(
                    node_id="NODE-001",
                    timestamp=now - timedelta(minutes=15 * (5 - i)),
                    pitch_deg=p,
                    roll_deg=0.0,
                    battery_mv=3950.0,
                ))
                for i, p in enumerate([0.10, 0.15, 0.20, 0.25, 0.30])
            ]
        }
        current = [
            telemetry_to_ml_node(build_telemetry_payload(
                node_id="NODE-001",
                timestamp=now,
                pitch_deg=0.35,
                roll_deg=0.0,
                battery_mv=3950.0,
            ))
        ]
        res = run_ml_predict(nodes=current, history=history)
        assert res["overall"]["status"] in ("WARNING", "CRITICAL")
        assert res["overall"]["alarm"] is True
        assert res["time_to_threshold"]["warning_status"] in ("PREDICTED", "ALREADY_EXCEEDED")
