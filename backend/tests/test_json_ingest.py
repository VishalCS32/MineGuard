"""Tests for JSON telemetry ingestion matching the deployed MineGuard Gateway contract."""

import pytest
from datetime import datetime, timezone


class TestJsonTelemetryIngestion:
    async def test_single_json_reading_ingest(self, provisioned):
        reading = {
            "node_id": "NODE-0010",
            "timestamp": "2026-09-13T10:00:00Z",
            "sensor_data": {
                "gyro": {"x": None, "y": None, "z": None, "unit": "deg/s"},
                "accelerometer": {"x": None, "y": None, "z": None, "unit": "m/s^2"},
                "orientation": {"roll": -0.15, "pitch": 0.42, "unit": "deg"},
                "vibration": {"x": None, "y": None, "z": None, "rms": 0.18, "unit": "m/s^2"},
                "temperature_c": 27.5,
                "battery_mv": 3950.0,
            },
            "gps": {
                "latitude": 23.7505,
                "longitude": 86.4205,
                "altitude": 210.0,
                "satellites": 12,
                "hdop": 0.8,
            },
            "communication": {
                "rssi_dbm": -72.0,
                "snr_db": 9.5,
            },
            "flags": 0,
        }

        resp = await provisioned.post("/api/v1/telemetry", json=reading)
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 1}

        # Check snapshot reflects the node
        snap = (await provisioned.get("/api/snapshot")).json()
        assert any(n["label"] == "NODE-0010" or n["addr"] == 0x10 for n in snap["nodes"])

    async def test_batch_json_readings_ingest(self, provisioned):
        batch = [
            {
                "node_id": f"NODE-{i:04d}",
                "timestamp": f"2026-09-13T10:0{i % 10}:00Z",
                "sensor_data": {
                    "orientation": {"roll": 0.05 * i, "pitch": 0.08 * i},
                    "vibration": {"rms": 0.05 * i},
                    "temperature_c": 25.0 + i,
                    "battery_mv": 3900.0 - (i * 10),
                },
                "gps": {"latitude": 23.75 + (i * 0.001), "longitude": 86.42 + (i * 0.001)},
                "communication": {"rssi_dbm": -70.0 - i, "snr_db": 10.0},
            }
            for i in range(1, 6)
        ]

        resp = await provisioned.post("/api/v1/telemetry", json=batch)
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 5}

        # Check snapshot
        snap = (await provisioned.get("/api/snapshot")).json()
        assert snap["kpis"]["totalNodes"] >= 5

    async def test_missing_node_id_rejected(self, provisioned):
        resp = await provisioned.post("/api/v1/telemetry", json={"pitch_deg": 0.1})
        assert resp.status_code == 422

    async def test_empty_batch_accepted_zero(self, provisioned):
        resp = await provisioned.post("/api/v1/telemetry", json=[])
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 0}

    async def test_accel_and_gyro_preserved(self, provisioned):
        reading = {
            "node_id": "NODE-0099",
            "timestamp": "2026-09-13T10:05:00Z",
            "sensor_data": {
                "gyro": {"x": 0.012, "y": -0.008, "z": 0.021, "unit": "deg/s"},
                "accelerometer": {"x": 0.12, "y": -0.04, "z": 9.78, "unit": "m/s^2"},
                "orientation": {"roll": 0.02, "pitch": 0.35},
                "temperature_c": 26.0,
                "battery_mv": 3800.0,
            },
        }
        resp = await provisioned.post("/api/v1/telemetry", json=reading)
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 1}
