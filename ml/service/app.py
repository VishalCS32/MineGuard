"""FastAPI entry point for MineGuard ML inference."""

from __future__ import annotations

from typing import Any, Mapping
from pathlib import Path

import os
import sys
from pathlib import Path

_ml_root = str(Path(__file__).resolve().parents[1])
if _ml_root not in sys.path:
    sys.path.insert(0, _ml_root)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from inference.pipeline import MODEL_VERSION, predict
from training.anomaly import load_anomaly_artifact

try:
    from service.demo import DEMO_SCENARIOS, generate_demo_payload
except ImportError:
    from ml.service.demo import DEMO_SCENARIOS, generate_demo_payload

app = FastAPI(
    title="MineGuard ML Service",
    version=MODEL_VERSION,
    description="Physics-guided early-warning intelligence over MineGuard telemetry.",
)

# Configurable CORS support for Web Dashboard development
_cors_env = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000",
)
_allow_origins = ["*"] if _cors_env.strip() == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    """Explicit request schema for telemetry inference."""
    nodes: list[dict[str, Any]] = Field(..., min_length=1, description="List of current node telemetry records")
    history: dict[str, list[dict[str, Any]]] | None = Field(default=None, description="Prior telemetry mapped by node_id")
    derived: dict[str, dict[str, Any]] | None = Field(default=None, description="Reconstructed deformation and Knothe parameters")
    registered_positions: dict[str, Any] | None = Field(default=None, description="Optional registered installation coordinates by node_id")


class PredictDemoRequest(BaseModel):
    """Request schema for predefined demo scenario inference."""
    scenario: str = Field(
        default="normal",
        description="Demo scenario: normal, warning, critical, sensor_fault, hardware_theft",
    )


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
    registered_positions = None
    if isinstance(payload, PredictRequest):
        nodes = payload.nodes
        history = payload.history
        derived = payload.derived
        registered_positions = payload.registered_positions
    elif isinstance(payload, dict):
        nodes = payload.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise HTTPException(status_code=422, detail="payload.nodes must be a non-empty list")
        history = payload.get("history")
        derived = payload.get("derived")
        registered_positions = payload.get("registered_positions")
    else:
        raise HTTPException(status_code=422, detail="Invalid request payload")

    try:
        return predict(nodes, history, derived, registered_positions=registered_positions)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/predict/demo")
def prediction_demo(
    payload: PredictDemoRequest | dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Execute production ML inference on a predefined physical or security scenario.

    Supported scenarios:
    - normal: All 21 nodes stable, resting baseline, no alarms.
    - warning: Persistent positive deformation approaching warning threshold (0.50 deg).
    - critical: Confirmed physical deformation exceeding critical limit with high risk.
    - sensor_fault: Low battery / hardware error flag; deformation alarm suppressed.
    - hardware_theft: Node moved >= 10m from registered coordinates with confirmed debounce.
    """
    target_scenario = "normal"
    if scenario:
        target_scenario = scenario
    elif isinstance(payload, PredictDemoRequest):
        target_scenario = payload.scenario
    elif isinstance(payload, dict) and "scenario" in payload:
        target_scenario = str(payload["scenario"])

    clean_scenario = target_scenario.strip().lower()
    if clean_scenario not in DEMO_SCENARIOS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid demo scenario: '{target_scenario}'. Supported scenarios: {', '.join(DEMO_SCENARIOS)}",
        )

    nodes, history, derived, registered_positions = generate_demo_payload(clean_scenario)
    try:
        return predict(nodes, history, derived, registered_positions=registered_positions)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=f"Inference failure on demo scenario: {exc}") from exc


@app.get("/predict/demo")
def prediction_demo_get(scenario: str = "normal") -> dict[str, Any]:
    """Convenience GET endpoint for frontend developers testing in a browser."""
    return prediction_demo(scenario=scenario)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("ML_HOST", "0.0.0.0")
    port = int(os.getenv("ML_PORT", "8001"))
    uvicorn.run("service.app:app", host=host, port=port, reload=False)
