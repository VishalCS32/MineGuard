"""Client for communicating with the MineGuard ML inference service."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("backend.ml_client")


async def predict(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Send telemetry data to the ML service and return its prediction.
    
    If ML service is unconfigured, returns None.
    If ML service fails or is unreachable, logs the failure and returns an
    explicit degraded ML result with ml_status='ML_UNAVAILABLE' without
    crashing the backend.
    """
    settings = get_settings()

    if not settings.ml_service_url:
        return None

    url = f"{settings.ml_service_url.rstrip('/')}/predict"

    try:
        timeout = getattr(settings, "ml_service_timeout_seconds", 5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict):
                result["ml_status"] = "AVAILABLE"
                return result
            return {"ml_status": "INVALID_RESPONSE", "error": "Response was not a JSON object"}
    except httpx.TimeoutException as exc:
        log.warning("ML service timeout calling %s: %s", url, exc)
        return {"ml_status": "ML_UNAVAILABLE", "error": f"Timeout: {exc}"}
    except httpx.ConnectError as exc:
        log.warning("ML service connection error calling %s: %s", url, exc)
        return {"ml_status": "ML_UNAVAILABLE", "error": f"ConnectError: {exc}"}
    except httpx.HTTPStatusError as exc:
        log.warning("ML service HTTP error %d calling %s: %s", exc.response.status_code, url, exc)
        return {
            "ml_status": "ML_UNAVAILABLE",
            "error": f"HTTPError {exc.response.status_code}: {exc.response.text[:200]}",
        }
    except Exception as exc:
        log.warning("Unexpected error communicating with ML service %s: %s", url, exc)
        return {"ml_status": "ML_UNAVAILABLE", "error": f"Error: {exc}"}
