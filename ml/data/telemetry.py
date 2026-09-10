"""Simulator-independent MineGuard telemetry records and input parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import hypot
from typing import Any, Mapping


class TelemetryValidationError(ValueError):
    """Raised when an ML input does not represent MineGuard telemetry."""


@dataclass(frozen=True, slots=True)
class NodeTelemetry:
    """Decoded sensor telemetry in engineering units.

    The protocol decoder remains responsible for binary frames. This record is
    the stable boundary between decoded backend data and ML code.
    """

    node_id: str
    timestamp: datetime
    pitch_deg: float
    roll_deg: float
    vibration_rms_mg: float
    vibration_peak_hz: float
    temperature_c: float
    n_samples: int
    gnss_status: int
    battery_mv: float
    rssi_dbm: float
    snr_db: float
    flags: int
    x_m: float | None = None
    y_m: float | None = None

    @property
    def tilt_deg(self) -> float:
        return hypot(self.pitch_deg, self.roll_deg)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NodeTelemetry":
        """Parse backend/API values using protocol-derived field names.

        Raw integer protocol names are accepted alongside engineering-unit
        aliases so the adapter can consume either decoded records or a service
        request without changing the radio contract.
        """
        try:
            node_id = str(value["node_id"])
            timestamp = _timestamp(value["timestamp"])
            pitch = _number(value, "pitch_deg", "pitch_mdeg", scale=0.001)
            roll = _number(value, "roll_deg", "roll_mdeg", scale=0.001)
            vibration = _number(value, "vibration_rms_mg", "vib_rms_mg")
            peak = _number(value, "vibration_peak_hz", "vib_peak_hz")
            temperature = _number(value, "temperature_c", "temp_c_x100", scale=0.01)
            samples = int(value.get("n_samples", 1))
            gnss = int(value.get("gnss_status", 0))
            battery = _number(value, "battery_mv", "vbat_mv")
            rssi = _number(value, "rssi_dbm", "rssi")
            snr = _number(value, "snr_db", "snr", scale=0.25, encoded=True)
            flags = int(value.get("flags", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise TelemetryValidationError(f"invalid telemetry: {exc}") from exc

        if not node_id:
            raise TelemetryValidationError("node_id must not be empty")
        if samples < 1:
            raise TelemetryValidationError("n_samples must be positive")
        return cls(node_id, timestamp, pitch, roll, vibration, peak, temperature,
                   samples, gnss, battery, rssi, snr, flags,
                   _optional_number(value, "x_m"), _optional_number(value, "y_m"))


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("timestamp must be ISO text, epoch seconds, or datetime")
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _number(value: Mapping[str, Any], engineering: str, raw: str,
            scale: float = 1.0, encoded: bool = False) -> float:
    if engineering in value:
        return float(value[engineering])
    result = float(value[raw]) * scale
    if encoded:
        result -= 20.0
    return result


def _optional_number(value: Mapping[str, Any], key: str) -> float | None:
    return None if value.get(key) is None else float(value[key])
