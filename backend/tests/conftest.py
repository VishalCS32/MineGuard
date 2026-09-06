"""Test harness: a throwaway SQLite database and an ASGI client per test."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.config import get_settings


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'test.db'}")
    monkeypatch.setenv("MQTT_HOST", "")
    get_settings.cache_clear()
    await db_module.dispose_db()

    from app.main import app  # imported after the env is set

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as ac:
        # Lifespan is not run by ASGITransport, so bootstrap explicitly.
        await db_module.init_db()
        yield ac

    await db_module.dispose_db()
    get_settings.cache_clear()


@pytest.fixture
def b64():
    return lambda frame: base64.b64encode(frame).decode()


SITE = {
    "slug": "test-panel",
    "name": "Test Panel",
    "origin_lat": 23.75,
    "origin_lon": 86.42,
    "panel_x_start": 0,
    "panel_x_end": 600,
    "face_x_m": 300,
    "nodes": [
        {"addr": 0x10, "label": "N1-1", "zone": "Panel A - West",
         "lat": 23.75, "lon": 86.42, "x_m": 0, "y_m": 0},
        {"addr": 0x11, "label": "N1-2", "zone": "Panel A - Center",
         "lat": 23.751, "lon": 86.421, "x_m": 150, "y_m": 0},
    ],
}


@pytest.fixture
def site_payload() -> dict:
    return {**SITE, "nodes": [dict(n) for n in SITE["nodes"]]}


@pytest_asyncio.fixture
async def provisioned(client) -> AsyncClient:
    resp = await client.post("/api/provision", json=SITE)
    assert resp.status_code == 201, resp.text
    return client
