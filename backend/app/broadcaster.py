"""Throttled snapshot broadcaster.

Ingest can accept many frames per second; rebuilding and pushing the full
snapshot on each one would spend most of the server's time serialising JSON that
no human can perceive. Instead ingest marks the state dirty and this task
rebuilds at most a few times a second, coalescing bursts into one update.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .config import get_settings
from .db import get_sessionmaker
from .hub import hub
from .state import build_snapshot

log = logging.getLogger(__name__)

MAX_RATE_HZ = 4.0

_dirty = asyncio.Event()
_task: asyncio.Task | None = None


def mark_dirty() -> None:
    """Called by ingest. Cheap and non-blocking."""
    _dirty.set()


async def _run() -> None:
    interval = 1.0 / MAX_RATE_HZ
    sessionmaker = get_sessionmaker()
    settings = get_settings()
    while True:
        await _dirty.wait()
        _dirty.clear()
        try:
            if hub.subscriber_count:
                async with sessionmaker() as session:
                    snapshot = await build_snapshot(session, settings)
                await hub.publish(snapshot)
        except Exception:  # pragma: no cover - a broadcast failure must not kill ingest
            log.exception("snapshot broadcast failed")
        await asyncio.sleep(interval)


async def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_run(), name="snapshot-broadcaster")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
