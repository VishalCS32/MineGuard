"""MineGuard Gateway Uplink Client.

Responsible for transmitting sensor telemetry from the gateway to the
deployed MineGuard Backend API (or local backend) over HTTPS/HTTP.

Contract target:
POST /api/v1/telemetry
Content-Type: application/json
Optional: Authorization: Bearer <INGEST_TOKEN>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.request

log = logging.getLogger("gateway.uplink")

DEFAULT_BACKEND_URL = os.getenv("GATEWAY_BACKEND_URL", "https://mineguard-api.tenant.eu.org")
DEFAULT_INGEST_PATH = "/api/v1/telemetry"
DEFAULT_GATEWAY_ID = os.getenv("GATEWAY_ID", "GW-001")
DEFAULT_SITE_SLUG = os.getenv("SITE_SLUG", "jharia-l7")
MAX_BATCH_SIZE = 500
HTTP_TIMEOUT_S = 15.0


@dataclass
class UplinkResult:
    success: bool
    status_code: int
    accepted_count: int
    error: str | None = None
    response_body: dict[str, Any] | None = None


def build_telemetry_payload(
    node_id: str,
    *,
    timestamp: str | datetime | None = None,
    pitch_deg: float | None = None,
    roll_deg: float | None = None,
    vibration_rms_m_s2: float | None = None,
    vibration_rms_mg: float | None = None,
    temperature_c: float | None = None,
    battery_mv: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    altitude_m: float | None = None,
    satellites: int | None = None,
    hdop: float | None = None,
    h_acc_m: float | None = None,
    rssi_dbm: float | None = None,
    snr_db: float | None = None,
    flags: int = 0,
    accel_x: float | None = None,
    accel_y: float | None = None,
    accel_z: float | None = None,
    gyro_x: float | None = None,
    gyro_y: float | None = None,
    gyro_z: float | None = None,
    stamped_by: str = "node",
) -> dict[str, Any]:
    """Construct a canonical telemetry record conforming to the deployed API schema.
    
    Preserves actual gyro and accelerometer values when provided; leaves them null
    when hardware does not supply them (never fabricates).
    """
    if timestamp is None:
        ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        ts_str = str(timestamp)

    # Unit conversion: if vibration_rms_mg supplied, convert to m/s^2 for the payload
    vib_rms = vibration_rms_m_s2
    if vib_rms is None and vibration_rms_mg is not None:
        vib_rms = round(vibration_rms_mg * 9.80665 / 1000.0, 6)

    gyro_obj = {
        "x": float(gyro_x) if gyro_x is not None else None,
        "y": float(gyro_y) if gyro_y is not None else None,
        "z": float(gyro_z) if gyro_z is not None else None,
        "unit": "deg/s",
    }

    accel_obj = {
        "x": float(accel_x) if accel_x is not None else None,
        "y": float(accel_y) if accel_y is not None else None,
        "z": float(accel_z) if accel_z is not None else None,
        "unit": "m/s^2",
    }

    orientation_obj = {
        "roll": float(roll_deg) if roll_deg is not None else None,
        "pitch": float(pitch_deg) if pitch_deg is not None else None,
        "unit": "deg",
    }

    vibration_obj = {
        "x": None,
        "y": None,
        "z": None,
        "rms": float(vib_rms) if vib_rms is not None else None,
        "unit": "m/s^2",
    }

    sensor_data: dict[str, Any] = {
        "gyro": gyro_obj,
        "accelerometer": accel_obj,
        "orientation": orientation_obj,
        "vibration": vibration_obj,
        "temperature_c": float(temperature_c) if temperature_c is not None else None,
        "battery_mv": float(battery_mv) if battery_mv is not None else None,
    }

    gps_obj: dict[str, Any] = {
        "latitude": float(latitude) if latitude is not None else None,
        "longitude": float(longitude) if longitude is not None else None,
        "altitude": float(altitude_m) if altitude_m is not None else None,
        "satellites": int(satellites) if satellites is not None else None,
        "hdop": float(hdop) if hdop is not None else None,
        "h_acc_m": float(h_acc_m) if h_acc_m is not None else None,
    }

    comm_obj: dict[str, Any] = {
        "rssi_dbm": float(rssi_dbm) if rssi_dbm is not None else None,
        "snr_db": float(snr_db) if snr_db is not None else None,
    }

    return {
        "node_id": str(node_id),
        "timestamp": ts_str,
        "stamped_by": stamped_by,
        "sensor_data": sensor_data,
        "gps": gps_obj,
        "communication": comm_obj,
        "flags": int(flags),
    }


class GatewayUplink:
    """Production-grade gateway uplink manager with retry, queueing, and deduplication."""

    def __init__(
        self,
        backend_url: str | None = None,
        ingest_path: str = DEFAULT_INGEST_PATH,
        token: str | None = None,
        gateway_id: str = DEFAULT_GATEWAY_ID,
        site_slug: str = DEFAULT_SITE_SLUG,
        timeout_s: float = HTTP_TIMEOUT_S,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
    ) -> None:
        self.backend_url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/")
        self.ingest_path = ingest_path
        self.token = token or os.getenv("INGEST_TOKEN", "").strip()
        self.gateway_id = gateway_id
        self.site_slug = site_slug
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.buffer: list[dict[str, Any]] = []
        self._sent_keys: set[str] = set()

    @property
    def target_url(self) -> str:
        if self.backend_url.endswith("/api/v1/telemetry") or self.backend_url.endswith("/telemetry"):
            return self.backend_url
        base = self.backend_url.rstrip("/")
        path = "/" + self.ingest_path.lstrip("/")
        return f"{base}{path}"

    def _make_key(self, record: dict[str, Any]) -> str:
        return f"{record.get('node_id')}:{record.get('timestamp')}"

    def send_reading(self, reading: dict[str, Any]) -> UplinkResult:
        """Send a single telemetry reading synchronously."""
        return self.send_batch([reading])

    def send_batch(self, readings: Sequence[dict[str, Any]]) -> UplinkResult:
        """Send a batch of telemetry readings with chunking, retry, and local buffering."""
        if not readings:
            return UplinkResult(success=True, status_code=200, accepted_count=0)

        # Enqueue into buffer (filtering out already sent keys to avoid duplicate transmissions)
        new_items = []
        for r in readings:
            k = self._make_key(r)
            if k not in self._sent_keys:
                new_items.append(r)
        self.buffer.extend(new_items)

        total_accepted = 0
        last_status = 0
        last_error = None
        last_body = None

        while self.buffer:
            chunk = self.buffer[:MAX_BATCH_SIZE]
            res = self._post_with_retry(chunk)
            last_status = res.status_code
            last_error = res.error
            last_body = res.response_body

            if res.success:
                total_accepted += res.accepted_count
                for item in chunk:
                    self._sent_keys.add(self._make_key(item))
                del self.buffer[:len(chunk)]
                # Keep cache bounded
                if len(self._sent_keys) > 10000:
                    self._sent_keys = set(list(self._sent_keys)[-5000:])
            else:
                log.warning(
                    "Uplink chunk of %d readings failed (%s, status %d). %d readings buffered.",
                    len(chunk), res.error, res.status_code, len(self.buffer)
                )
                break

        return UplinkResult(
            success=total_accepted > 0 or not self.buffer,
            status_code=last_status,
            accepted_count=total_accepted,
            error=last_error,
            response_body=last_body,
        )

    def _post_with_retry(self, chunk: list[dict[str, Any]]) -> UplinkResult:
        payload_bytes = json.dumps(chunk).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"MineGuard-Gateway/{self.gateway_id}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        attempt = 0
        delay = 0.5

        while attempt <= self.max_retries:
            attempt += 1
            req = urllib.request.Request(self.target_url, data=payload_bytes, headers=headers, method="POST")
            try:
                t0 = time.time()
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    status = resp.status
                    resp_bytes = resp.read()
                    elapsed = time.time() - t0
                    body_dict = {}
                    if resp_bytes:
                        try:
                            body_dict = json.loads(resp_bytes.decode("utf-8"))
                        except Exception:
                            pass
                    
                    accepted = body_dict.get("accepted", len(chunk))
                    log.info(
                        "Uplink success: %s -> HTTP %d (%d accepted) in %.2fs",
                        self.target_url, status, accepted, elapsed
                    )
                    return UplinkResult(
                        success=True,
                        status_code=status,
                        accepted_count=accepted,
                        response_body=body_dict,
                    )
            except urllib.error.HTTPError as exc:
                body_str = exc.read().decode("utf-8", errors="replace")
                log.warning(
                    "Uplink HTTPError: %s -> HTTP %d: %s (attempt %d/%d)",
                    self.target_url, exc.code, body_str[:200], attempt, self.max_retries + 1
                )
                # 4xx client errors (e.g. 422, 401) should not be retried indefinitely
                if 400 <= exc.code < 500:
                    return UplinkResult(
                        success=False,
                        status_code=exc.code,
                        accepted_count=0,
                        error=f"HTTP {exc.code}: {body_str[:150]}",
                    )
                last_err = f"HTTP {exc.code}: {body_str[:150]}"
                last_code = exc.code
            except Exception as exc:
                log.warning(
                    "Uplink connection error: %s (attempt %d/%d)",
                    exc, attempt, self.max_retries + 1
                )
                last_err = str(exc)
                last_code = 0

            if attempt <= self.max_retries:
                time.sleep(delay)
                delay *= self.backoff_factor

        return UplinkResult(
            success=False,
            status_code=last_code,
            accepted_count=0,
            error=last_err,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="MineGuard Gateway Uplink Client")
    parser.add_argument("--url", default=DEFAULT_BACKEND_URL, help="Backend URL (e.g. https://mineguard-api.tenant.eu.org)")
    parser.add_argument("--node-id", default="INTEGRATION-TEST-001", help="Node ID to report")
    parser.add_argument("--pitch", type=float, default=0.35, help="Pitch angle in degrees")
    parser.add_argument("--roll", type=float, default=-0.12, help="Roll angle in degrees")
    parser.add_argument("--vib-mg", type=float, default=18.5, help="Vibration RMS in milli-g")
    parser.add_argument("--temp", type=float, default=26.4, help="Temperature in deg C")
    parser.add_argument("--vbat", type=float, default=3920.0, help="Battery in mV")
    parser.add_argument("--lat", type=float, default=23.7500, help="Latitude")
    parser.add_argument("--lon", type=float, default=86.4200, help="Longitude")
    parser.add_argument("--token", default=None, help="Bearer token for ingest")
    args = parser.parse_args()

    client = GatewayUplink(backend_url=args.url, token=args.token)
    reading = build_telemetry_payload(
        node_id=args.node_id,
        pitch_deg=args.pitch,
        roll_deg=args.roll,
        vibration_rms_mg=args.vib_mg,
        temperature_c=args.temp,
        battery_mv=args.vbat,
        latitude=args.lat,
        longitude=args.lon,
    )
    print(f"Sending telemetry for node {args.node_id} to {client.target_url}...")
    res = client.send_reading(reading)
    print(f"Result: Success={res.success}, Status={res.status_code}, Accepted={res.accepted_count}, Error={res.error}")
    if not res.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
