from datetime import datetime, timedelta, timezone

import pytest

from data.telemetry import NodeTelemetry, TelemetryValidationError
from features.engineering import build_features


def _record(node_id: str, pitch: float, when: datetime, x: float) -> NodeTelemetry:
    return NodeTelemetry.from_mapping({
        "node_id": node_id,
        "timestamp": when,
        "pitch_deg": pitch,
        "roll_deg": 0.0,
        "vibration_rms_mg": 12,
        "vibration_peak_hz": 30,
        "temperature_c": 28.0,
        "n_samples": 32,
        "gnss_status": 14,
        "battery_mv": 3900,
        "rssi_dbm": -70,
        "snr_db": 8.0,
        "flags": 0,
        "x_m": x,
        "y_m": 0.0,
    })


def test_protocol_scale_fields_are_converted() -> None:
    node = NodeTelemetry.from_mapping({
        "node_id": "NODE-001",
        "timestamp": "2026-09-09T12:30:15.250Z",
        "pitch_mdeg": 420,
        "roll_mdeg": -310,
        "vib_rms_mg": 101,
        "vib_peak_hz": 12,
        "temp_c_x100": 2800,
        "n_samples": 32,
        "gnss_status": 14,
        "vbat_mv": 3900,
        "rssi": -80,
        "snr": 112,
        "flags": 0,
    })
    assert node.pitch_deg == 0.42
    assert node.tilt_deg == pytest.approx(0.5220, abs=1e-4)
    assert node.snr_db == 8.0


def test_features_use_only_prior_history_and_neighbours() -> None:
    now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    previous = _record("N1", 0.1, now - timedelta(hours=2), 0)
    current = [_record("N1", 0.3, now, 0), _record("N2", 0.3, now, 50)]
    frame = build_features(current, {"N1": [previous]})
    assert frame.nodes[0].tilt_rate_deg_per_hour == pytest.approx(0.1)
    assert frame.nodes[0].history_count == 2
    assert frame.spatial_consistency == 1.0


def test_invalid_sample_count_is_rejected() -> None:
    with pytest.raises(TelemetryValidationError):
        NodeTelemetry.from_mapping({
            "node_id": "N1", "timestamp": 1, "pitch_deg": 0, "roll_deg": 0,
            "vibration_rms_mg": 0, "vibration_peak_hz": 0, "temperature_c": 0,
            "n_samples": 0, "gnss_status": 0, "battery_mv": 0, "rssi_dbm": 0,
            "snr_db": 0, "flags": 0,
        })
