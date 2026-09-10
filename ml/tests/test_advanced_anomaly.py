from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.offline_dataset import chronological_split, generate_dataset
from inference.pipeline import predict
from training.anomaly import load_anomaly_artifact, train_anomaly_artifact


def _record(node_id: str, tilt: float, when: datetime) -> dict:
    return {
        "node_id": node_id, "timestamp": when.isoformat(), "pitch_deg": tilt,
        "roll_deg": 0.0, "vibration_rms_mg": 20, "vibration_peak_hz": 30,
        "temperature_c": 28.0, "n_samples": 32, "gnss_status": 14,
        "battery_mv": 3900, "rssi_dbm": -70, "snr_db": 8, "flags": 0,
        "x_m": 0.0, "y_m": 0.0,
    }


def test_offline_dataset_is_chronological_and_contract_compatible():
    dataset = generate_dataset(nodes=21, steps=12, seed=7)
    assert dataset.dataset_version == "offline-telemetry-v2"
    assert len(dataset.records) == 252
    assert len(dataset.node_positions) == 21
    timestamps = [item.record["timestamp"] for item in dataset.records]
    assert timestamps == sorted(timestamps)
    assert "scenario" not in dataset.records[0].record
    assert dataset.records[-1].label in (0, 1)


def test_default_dataset_has_complete_21_node_windows_and_spatial_variation():
    dataset = generate_dataset(steps=30, seed=7)
    timestamps = {}
    for item in dataset.records:
        timestamps.setdefault(item.record["timestamp"], []).append(item.record["node_id"])
    assert len(timestamps) == 30
    assert all(len(node_ids) == 21 and len(set(node_ids)) == 21
               for node_ids in timestamps.values())
    neighbor_counts = []
    for node_id, (x, y) in dataset.node_positions.items():
        neighbor_counts.append(sum(
            ((x - other_x) ** 2 + (y - other_y) ** 2) ** 0.5 <= 75.0
            for other_id, (other_x, other_y) in dataset.node_positions.items()
            if other_id != node_id
        ))
    assert len(set(neighbor_counts)) > 1


def test_chronological_split_keeps_complete_node_windows():
    dataset = generate_dataset(nodes=3, steps=40, seed=7)
    train, validation, test = chronological_split(dataset)
    assert len(train) % 3 == 0
    assert len(validation) % 3 == 0
    assert len(test) % 3 == 0
    assert train[-1].record["timestamp"] < validation[0].record["timestamp"]
    assert validation[-1].record["timestamp"] < test[0].record["timestamp"]


def test_training_writes_versioned_artifact_and_metrics(tmp_path: Path):
    metadata = train_anomaly_artifact(generate_dataset(nodes=3, steps=80), tmp_path)
    assert metadata["model_type"] == "IsolationForest"
    assert metadata["synthetic_training_data"] is True
    assert set(metadata["metrics"]) == {"train", "validation", "test"}
    for split_metrics in metadata["metrics"].values():
        assert {"precision", "recall", "f1", "false_alarm_rate",
                "confusion_matrix"}.issubset(split_metrics)
    bundle, loaded_metadata = load_anomaly_artifact(tmp_path)
    assert bundle["model"] is not None
    assert loaded_metadata["model_version"] == metadata["model_version"]


def test_runtime_predict_uses_trained_artifact_when_available():
    start = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    history = [_record("N1", 0.1 + index * 0.01,
                       start + timedelta(minutes=15 * index)) for index in range(5)]
    result = predict([_record("N1", 0.2, start + timedelta(minutes=75))],
                     {"N1": history})
    assert result["model_version"] == "mineguard-anomaly-iforest-v2"
    assert result["nodes"][0]["anomaly"]["severity"] in {
        "NORMAL", "UNUSUAL", "ANOMALOUS", "CRITICAL"
    }
