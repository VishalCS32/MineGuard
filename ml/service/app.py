"""FastAPI entry point for MineGuard ML inference."""

from __future__ import annotations

from typing import Any, Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from inference.pipeline import MODEL_VERSION, predict
from training.anomaly import load_anomaly_artifact

app = FastAPI(
    title="MineGuard ML Service",
    version=MODEL_VERSION,
    description="Physics-guided early-warning intelligence over MineGuard telemetry.",
)


class PredictRequest(BaseModel):
    """Explicit request schema for telemetry inference."""
    nodes: list[dict[str, Any]] = Field(..., min_length=1, description="List of current node telemetry records")
    history: dict[str, list[dict[str, Any]]] | None = Field(default=None, description="Prior telemetry mapped by node_id")
    derived: dict[str, dict[str, Any]] | None = Field(default=None, description="Reconstructed deformation and Knothe parameters")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.get("/model/info")
def model_info() -> dict[str, Any]:
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts" / "anomaly"
    try:
        _, metadata = load_anomaly_artifact(artifact_dir)
    except (FileNotFoundError, OSError, ValueError):
        metadata = {"model_version": MODEL_VERSION, "model_type": "baseline",
                    "synthetic_training_data": False, "metrics": {}}
    return {"model_version": metadata["model_version"],
            "kind": metadata.get("model_type", "baseline"),
            "data_source": "MineGuard telemetry",
            "synthetic_training": metadata.get("synthetic_training_data", False),
            "metrics": metadata.get("metrics", {}),
            "feature_names": metadata.get("feature_names", [])}


@app.post("/predict")
def prediction(payload: PredictRequest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, PredictRequest):
        nodes = payload.nodes
        history = payload.history
        derived = payload.derived
    elif isinstance(payload, dict):
        nodes = payload.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise HTTPException(status_code=422, detail="payload.nodes must be a non-empty list")
        history = payload.get("history")
        derived = payload.get("derived")
    else:
        raise HTTPException(status_code=422, detail="Invalid request payload")

    try:
        return predict(nodes, history, derived)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
