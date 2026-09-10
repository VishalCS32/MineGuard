"""One supervised XGBoost future-tilt model for offline MineGuard data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from data.offline_dataset import OfflineDataset, chronological_split, chronological_windows, generate_dataset
from training.anomaly import FEATURE_NAMES, FeatureEncoder

HORIZON_STEPS = 4
HORIZON_HOURS = 1
MODEL_VERSION = "mineguard-xgboost-future-tilt-v1"


def build_supervised_samples(dataset: OfflineDataset) -> list[dict[str, Any]]:
    """Build leakage-safe samples with future tilt used only as the target."""
    rows = list(chronological_windows(dataset))
    by_node: dict[str, list[dict]] = {}
    for item in dataset.records:
        by_node.setdefault(item.record["node_id"], []).append(item.record)

    encoder = FeatureEncoder()
    samples: list[dict[str, Any]] = []
    for current, history, _, label_name in rows:
        node_id = current["node_id"]
        node_rows = by_node[node_id]
        index = next(i for i, item in enumerate(node_rows)
                     if item["timestamp"] == current["timestamp"])
        future = node_rows[index + 1:index + 1 + HORIZON_STEPS]
        if len(history) < 4 or len(future) < HORIZON_STEPS:
            continue
        features = encoder.transform(current, history)[0]
        target = max(_tilt(record) for record in future)
        samples.append({
            "timestamp": current["timestamp"],
            "node_id": node_id,
            "features": features,
            "target": target,
            "baseline": _tilt(current),
            "label_name": label_name,
        })
    return samples


def train_xgboost_artifact(dataset: OfflineDataset, artifact_dir: str | Path,
                           *, train_fraction: float = 0.5,
                           validation_fraction: float = 0.15,
                           seed: int = 42) -> dict[str, Any]:
    samples = build_supervised_samples(dataset)
    timestamps = sorted({sample["timestamp"] for sample in samples})
    train_end = timestamps[int(len(timestamps) * train_fraction)]
    validation_end = timestamps[int(len(timestamps) * (train_fraction + validation_fraction))]
    splits = {
        "train": [item for item in samples if item["timestamp"] < train_end],
        "validation": [item for item in samples
                        if train_end <= item["timestamp"] < validation_end],
        "test": [item for item in samples if item["timestamp"] >= validation_end],
    }
    x_train = np.asarray([item["features"] for item in splits["train"]])
    y_train = np.asarray([item["target"] for item in splits["train"]])
    if len(x_train) == 0:
        raise ValueError("no training samples available")

    model = XGBRegressor(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="reg:squarederror",
        random_state=seed,
        n_jobs=1,
    )
    model.fit(x_train, y_train, eval_set=[(np.asarray([item["features"] for item in splits["validation"]]),
                                           np.asarray([item["target"] for item in splits["validation"]]))],
              verbose=False)

    metrics = {name: _metrics(model, rows) for name, rows in splits.items()}
    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_path / "model.joblib")
    metadata = {
        "model_version": MODEL_VERSION,
        "model_type": "XGBRegressor",
        "dataset_version": dataset.dataset_version,
        "target": "maximum same-node tilt_deg over the next 1 hour",
        "horizon_hours": HORIZON_HOURS,
        "feature_names": list(FEATURE_NAMES),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_training_data": True,
        "split": {name: {"samples": len(rows),
                          "timestamps": len({item["timestamp"] for item in rows})}
                  for name, rows in splits.items()},
        "parameters": {
            "n_estimators": 120, "max_depth": 3, "learning_rate": 0.05,
            "subsample": 0.8, "colsample_bytree": 0.8, "random_state": seed,
        },
        "metrics": metrics,
        "baseline": "persistence: current tilt_deg",
        "limitations": ["synthetic data only", "no Knothe expected value supplied"],
    }
    (artifact_path / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def _metrics(model, rows: list[dict[str, Any]]) -> dict[str, float]:
    actual = np.asarray([item["target"] for item in rows])
    predicted = model.predict(np.asarray([item["features"] for item in rows]))
    baseline = np.asarray([item["baseline"] for item in rows])
    return {
        "samples": int(len(rows)),
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
        "r2": float(r2_score(actual, predicted)),
        "baseline_mae": float(mean_absolute_error(actual, baseline)),
        "baseline_rmse": float(mean_squared_error(actual, baseline) ** 0.5),
        "target_mean": float(actual.mean()),
        "target_std": float(actual.std()),
    }


def load_xgboost_artifact(artifact_dir: str | Path):
    path = Path(artifact_dir)
    return joblib.load(path / "model.joblib"), json.loads(
        (path / "metadata.json").read_text(encoding="utf-8"))


def predict_future_tilt(model, features: np.ndarray) -> float:
    return float(model.predict(np.asarray(features).reshape(1, -1))[0])


def _tilt(record: dict) -> float:
    return float((float(record["pitch_deg"]) ** 2 + float(record["roll_deg"]) ** 2) ** 0.5)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "artifacts" / "xgboost"
    print(json.dumps(train_xgboost_artifact(generate_dataset(), target), indent=2))
