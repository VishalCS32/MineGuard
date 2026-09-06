"""In-process publish/subscribe for WebSocket fan-out.

One ingest writes; every connected dashboard and phone reads. Each subscriber
gets its own bounded queue so a slow or stalled client cannot apply back-pressure
to ingest -- if a client falls behind, its oldest frames are dropped and it
catches up on the next snapshot, which is the right trade for live telemetry.

Redis pub/sub replaces this unchanged behind the same interface when the API is
scaled to more than one process; the compose file already runs Redis for it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

QUEUE_DEPTH = 8


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_DEPTH)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop the oldest frame rather than block ingest on a slow client.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    log.debug("dropped a frame for a stalled subscriber")

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


hub = Hub()
