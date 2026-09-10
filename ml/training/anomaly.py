"""Chronological Isolation Forest training for MineGuard telemetry."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from data.offline_dataset import OfflineDataset, chronological_split, chronological_windows, generate_dataset
from data.telemetry import NodeTelemetry
from features.engineering import build_features

FEATURE_NAMES = (
    "tilt_deg", "robust_tilt_rate_deg_per_hour", "vibration_rms_mg",
    "vibration_peak_hz", "temperature_c",
    "history_count", "temporal_span_hours", "temporal_std_tilt_deg",
)


class FeatureEncoder:
    """The same numeric encoder is used by training and runtime inference."""

    feature_names = FEATURE_NAMES

    def transform(self, current: dict, history: Sequence[dict], positions=None) -> np.ndarray:
        node = NodeTelemetry.from_mapping(current)
        prior = [NodeTelemetry.from_mapping(item) for item in history]
        frame = build_features([node], {node.node_id: prior})
        item = frame.nodes[0]
        values = {
            "tilt_deg": item.tilt_deg,
            "robust_tilt_rate_deg_per_hour": item.robust_tilt_rate_deg_per_hour,
            "vibration_rms_mg": item.vibration_rms_mg,
            "vibration_peak_hz": item.vibration_peak_hz,
            "temperature_c": item.temperature_c,
            "history_count": item.history_count,
            "temporal_span_hours": item.temporal_span_hours,
            "temporal_std_tilt_deg": item.temporal_std_tilt_deg,
            "neighbour_count": item.neighbour_count,
            "neighbour_mean_tilt_deg": item.neighbour_mean_tilt_deg,
            "neighbour_difference_deg": item.neighbour_difference_deg,
        }
        return np.asarray([[float(values[name] or 0.0) for name in FEATURE_NAMES]], dtype=float)


def train_anomaly_artifact(dataset: OfflineDataset, artifact_dir: str | Path,
                           *, train_fraction: float = 0.5,
                           validation_fraction: float = 0.15,
                           seed: int = 42) -> dict[str, Any]:
    """Train on chronological normal data and evaluate on a later test period."""
    train_records, validation_records, test_records = chronological_split(
        dataset, train_fraction=train_fraction, validation_fraction=validation_fraction)
    rows = list(chronological_windows(dataset))
    cutoff_train = len(train_records)
    cutoff_validation = cutoff_train + len(validation_records)
    encoder = FeatureEncoder()
    train_rows = rows[:cutoff_train]
    validation_rows = rows[cutoff_train:cutoff_validation]
    test_rows = rows[cutoff_validation:]
    x_train = np.vstack([encoder.transform(current, history, dataset.node_positions)[0]
                         for current, history, label, _ in train_rows
                         if len(history) >= 4 and label == 0])
    if len(x_train) < 20:
        raise ValueError("not enough normal chronological training rows")
    model = IsolationForest(
        n_estimators=150, contamination="auto", random_state=seed,
        n_jobs=-1, max_samples="auto",
    ).fit(x_train)
    normal_scores = -model.decision_function(x_train)
    threshold = float(np.quantile(normal_scores, 0.95))
    score_upper = float(np.quantile(normal_scores, 0.99))

    metrics = {
        "train": _evaluate(model, threshold, encoder, train_rows, dataset.node_positions),
        "validation": _evaluate(model, threshold, encoder, validation_rows, dataset.node_positions),
        "test": _evaluate(model, threshold, encoder, test_rows, dataset.node_positions),
    }
    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "threshold": threshold},
                artifact_path / "model.joblib")
    metadata = {
        "model_version": "mineguard-anomaly-iforest-v2",
        "model_type": "IsolationForest",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset.dataset_version,
        "synthetic_training_data": True,
        "feature_names": list(FEATURE_NAMES),
        "minimum_history_count": 9,
        "train_fraction": train_fraction,
        "validation_fraction": validation_fraction,
        "test_fraction": 1.0 - train_fraction - validation_fraction,
        "train_rows": len(x_train),
        "validation_rows": len(validation_rows),
        "test_rows": len(test_rows),
        "threshold": threshold,
        "score_upper": score_upper,
        "metrics": metrics,
        "parameters": {
            "n_estimators": 150,
            "contamination": "auto",
            "random_state": seed,
            "max_samples": "auto",
        },
    }
    (artifact_path / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def _evaluate(model, threshold: float, encoder: FeatureEncoder, rows, positions) -> dict[str, Any]:
    usable = [(current, history, label, label_name)
              for current, history, label, label_name in rows if len(history) >= 4]
    if not usable:
        return {"samples": 0, "normal_count": 0, "anomaly_count": 0,
                "predicted_anomaly_count": 0, "precision": 0.0,
                "recall": 0.0, "f1": 0.0, "false_alarm_rate": 0.0,
                "confusion_matrix": [[0, 0], [0, 0]], "by_label": {}}
    scores = [-float(model.decision_function(encoder.transform(current, history, positions))[0])
              for current, history, _, _ in usable]
    actual = np.asarray([label for _, _, label, _ in usable], dtype=int)
    predicted = np.asarray([score >= threshold for score in scores], dtype=int)
    normal = actual == 0
    false_alarm_rate = float(predicted[normal].mean()) if normal.any() else 0.0
    by_label: dict[str, dict[str, int]] = {}
    for label_name in sorted({label_name for _, _, _, label_name in usable}):
        selected = np.asarray([label == label_name for _, _, _, label in usable], dtype=bool)
        by_label[label_name] = {
            "samples": int(selected.sum()),
            "predicted_anomaly_count": int(predicted[selected].sum()),
        }
    return {
        "samples": int(len(actual)),
        "normal_count": int((actual == 0).sum()),
        "anomaly_count": int((actual == 1).sum()),
        "predicted_anomaly_count": int(predicted.sum()),
        "precision": float(precision_score(actual, predicted, zero_division=0)),
        "recall": float(recall_score(actual, predicted, zero_division=0)),
        "f1": float(f1_score(actual, predicted, zero_division=0)),
        "false_alarm_rate": false_alarm_rate,
        "confusion_matrix": confusion_matrix(actual, predicted, labels=[0, 1]).tolist(),
        "by_label": by_label,
    }


def load_anomaly_artifact(artifact_dir: str | Path):
    path = Path(artifact_dir)
    return joblib.load(path / "model.joblib"), json.loads((path / "metadata.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "artifacts" / "anomaly"
    result = train_anomaly_artifact(generate_dataset(), target)
    print(json.dumps(result, indent=2))
