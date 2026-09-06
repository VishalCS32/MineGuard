"""Optional MQTT bridge to the field gateways.

Real gateways publish uplink frames to the broker and subscribe for downlink
commands. This module is deliberately optional: if no broker is configured or
reachable, the API still serves and gateways can use the HTTP ingest endpoint
instead -- which is also the simpler path for a constrained ESP32 that already
has a TLS-free WiFi stack. Losing the broker degrades the transport, never the
system.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging

from subnet_proto import ADDR_GATEWAY, Config

from . import broadcaster
from .config import get_settings
from .db import get_sessionmaker
from .ingest import ingest_frames

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_client = None


async def _consume() -> None:
    """Subscribe to gateway uplinks and feed them through the same ingest path."""
    global _client
    settings = get_settings()
    try:
        import aiomqtt
    except ImportError:  # pragma: no cover
        log.warning("aiomqtt not installed; MQTT bridge disabled")
        return

    sessionmaker = get_sessionmaker()
    while True:
        try:
            async with aiomqtt.Client(settings.mqtt_host, port=settings.mqtt_port) as client:
                _client = client
                await client.subscribe(settings.mqtt_uplink_topic)
                log.info("MQTT connected to %s:%s, subscribed to %s",
                         settings.mqtt_host, settings.mqtt_port, settings.mqtt_uplink_topic)
                async for message in client.messages:
                    payload = message.payload
                    if not isinstance(payload, (bytes, bytearray)):
                        continue
                    frames = _split(bytes(payload))
                    async with sessionmaker() as session:
                        result = await ingest_frames(session, settings, frames)
                    if result.accepted:
                        broadcaster.mark_dirty()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A field deployment loses its broker regularly. Retry quietly.
            _client = None
            log.warning("MQTT connection lost (%s); retrying in 5s", exc)
            await asyncio.sleep(5)


def _split(payload: bytes) -> list[bytes]:
    """A gateway may batch several frames into one message.

    Batched frames are newline-separated base64; a bare binary payload is a
    single frame.
    """
    if b"\n" in payload or payload[:1] in (b"e", b"W", b"b"):
        out = []
        for line in payload.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(base64.b64decode(line, validate=True))
            except Exception:
                return [payload]
        return out or [payload]
    return [payload]


async def publish_downlink(addr: int, cfg: Config) -> bool:
    """Send a CONFIG_SET frame toward a node. Returns False if no broker is up."""
    settings = get_settings()
    if _client is None or not settings.mqtt_host:
        return False
    try:
        frame = cfg.frame(src=ADDR_GATEWAY, dst=addr)
        topic = settings.mqtt_downlink_topic.format(gateway="+").replace("+", "all")
        await _client.publish(topic, frame)
        return True
    except Exception as exc:  # pragma: no cover
        log.warning("downlink publish failed: %s", exc)
        return False


async def start() -> None:
    global _task
    settings = get_settings()
    if not settings.mqtt_host:
        log.info("MQTT_HOST unset -- gateways should use POST /api/ingest")
        return
    if _task is None:
        _task = asyncio.create_task(_consume(), name="mqtt-bridge")


async def stop() -> None:
    global _task, _client
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
    _client = None
