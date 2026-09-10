from pathlib import Path

import numpy as np

from data.offline_dataset import generate_dataset
from training.xgboost_model import (
    FEATURE_NAMES, build_supervised_samples, load_xgboost_artifact,
    predict_future_tilt, train_xgboost_artifact,
)


def test_future_tilt_samples_are_leakage_safe_and_have_features():
    samples = build_supervised_samples(generate_dataset(steps=40, seed=7))
    assert samples
    assert all(len(item["features"]) == len(FEATURE_NAMES) for item in samples)
    assert all(item["timestamp"] < "2026-01-01T10:00:00+00:00" for item in samples)
    assert all(item["target"] >= 0 for item in samples)


def test_xgboost_artifact_loads_and_predicts(tmp_path: Path):
    metadata = train_xgboost_artifact(generate_dataset(seed=7), tmp_path)
    model, loaded = load_xgboost_artifact(tmp_path)
    assert metadata["model_type"] == "XGBRegressor"
    assert loaded["model_version"] == metadata["model_version"]
    value = predict_future_tilt(model, np.zeros(len(FEATURE_NAMES)))
    assert isinstance(value, float)
    assert np.isfinite(value)
    assert set(metadata["metrics"]) == {"train", "validation", "test"}


def test_artifact_metadata_has_persistence_baseline(tmp_path: Path):
    metadata = train_xgboost_artifact(generate_dataset(seed=7), tmp_path)
    assert metadata["target"] == "maximum same-node tilt_deg over the next 1 hour"
    assert metadata["baseline"].startswith("persistence")
    assert all("baseline_mae" in values for values in metadata["metrics"].values())
