"""Client for communicating with the MineGuard ML inference service."""

from __future__ import annotations

import httpx

from .config import get_settings


async def predict(payload: dict) -> dict:
    """Send telemetry data to the ML service and return its prediction."""

    settings = get_settings()

    url = f"{settings.ml_service_url.rstrip('/')}/predict"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)

    response.raise_for_status()

    return response.json()
