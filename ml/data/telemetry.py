"""Simulator-independent MineGuard telemetry records and input parsing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from math import hypot
from typing import Any, Mapping

# Canonical standard gravity constant for acceleration unit conversion: 1 g = 9.80665 m/s^2
STANDARD_GRAVITY: float = 9.80665


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
    temperature_c: float | None = None
    n_samples: int = 1
    gnss_status: int | None = None
    battery_mv: float | None = None
    rssi_dbm: float | None = None
    snr_db: float | None = None
    flags: int | None = None
    x_m: float | None = None
    y_m: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    accel_x: float | None = None
    accel_y: float | None = None
    accel_z: float | None = None
    gyro_x: float | None = None
    gyro_y: float | None = None
    gyro_z: float | None = None

    @property
    def tilt_deg(self) -> float:
        return hypot(self.pitch_deg, self.roll_deg)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NodeTelemetry":
        """Parse nested MineGuard node data and legacy flat fields."""

        try:
            node_id = str(value["node_id"])
            timestamp = _timestamp(value["timestamp"])

            orientation = value.get("orientation") if isinstance(value.get("orientation"), Mapping) else {}
            vibration_data = value.get("vibration") if isinstance(value.get("vibration"), Mapping) else {}
            gps = value.get("gps") if isinstance(value.get("gps"), Mapping) else {}

            pitch = (
                float(orientation["pitch"])
                if "pitch" in orientation and orientation["pitch"] is not None
                else _number(value, "pitch_deg", "pitch_mdeg", scale=0.001)
            )

            roll = (
                float(orientation["roll"])
                if "roll" in orientation and orientation["roll"] is not None
                else _number(value, "roll_deg", "roll_mdeg", scale=0.001)
            )

            vibration = (
                float(vibration_data["rms_mg"])
                if "rms_mg" in vibration_data and vibration_data["rms_mg"] is not None
                else _number(value, "vibration_rms_mg", "vib_rms_mg")
            )

            peak = (
                float(vibration_data["peak_hz"])
                if "peak_hz" in vibration_data and vibration_data["peak_hz"] is not None
                else _number(value, "vibration_peak_hz", "vib_peak_hz")
            )

            temperature = _optional_number(value, "temperature_c")
            if temperature is None and "temp_c_x100" in value and value["temp_c_x100"] is not None:
                temperature = float(value["temp_c_x100"]) * 0.01
            elif temperature is None and "temp_c" in value:
                temperature = _optional_number(value, "temp_c")

            samples = (
                int(value["n_samples"])
                if "n_samples" in value and value["n_samples"] is not None
                else 1
            )

            gnss_raw = gps.get("status") if "status" in gps and gps.get("status") is not None else value.get("gnss_status")
            gnss = int(gnss_raw) if gnss_raw is not None else None

            battery = _optional_number(value, "battery_mv")
            if battery is None and "vbat_mv" in value and value["vbat_mv"] is not None:
                battery = float(value["vbat_mv"])
            elif battery is None and "vbat" in value and value["vbat"] is not None:
                battery = float(value["vbat"]) * 1000.0

            rssi = _optional_number(value, "rssi_dbm")
            if rssi is None and "rssi" in value and value["rssi"] is not None:
                rssi = float(value["rssi"])

            snr = _optional_number(value, "snr_db")
            if snr is None and "snr" in value and value["snr"] is not None:
                snr = float(value["snr"]) * 0.25 - 20.0

            flags_raw = value.get("flags")
            flags = int(flags_raw) if flags_raw is not None else None

            x_m = _optional_number(value, "x_m")
            if x_m is None and "x" in value:
                x_m = _optional_number(value, "x")

            y_m = _optional_number(value, "y_m")
            if y_m is None and "y" in value:
                y_m = _optional_number(value, "y")

            # GPS Parsing and Validation (Phase 1)
            lat_raw = None
            lon_raw = None
            alt_raw = None

            if isinstance(gps, Mapping):
                lat_raw = gps.get("latitude") if "latitude" in gps else gps.get("lat")
                lon_raw = gps.get("longitude") if "longitude" in gps else gps.get("lon")
                alt_raw = (
                    gps.get("altitude_m") if "altitude_m" in gps
                    else gps.get("alt_m") if "alt_m" in gps
                    else gps.get("altitude")
                )

            if lat_raw is None:
                lat_raw = value.get("latitude") if "latitude" in value else value.get("lat")
            if lon_raw is None:
                lon_raw = value.get("longitude") if "longitude" in value else value.get("lon")
            if alt_raw is None:
                alt_raw = (
                    value.get("altitude_m") if "altitude_m" in value
                    else value.get("alt_m") if "alt_m" in value
                    else value.get("altitude")
                )

            latitude = _validate_coordinate(lat_raw, min_val=-90.0, max_val=90.0)
            longitude = _validate_coordinate(lon_raw, min_val=-180.0, max_val=180.0)
            altitude_m = _validate_altitude(alt_raw)

            # Accelerometer Parsing (Phase 2)
            # Canonical internal unit is m/s^2. If unit="g" is provided, converts by STANDARD_GRAVITY.
            accel_data = value.get("accel") if isinstance(value.get("accel"), Mapping) else {}
            ax_raw = accel_data.get("x") if "x" in accel_data else value.get("accel_x")
            ay_raw = accel_data.get("y") if "y" in accel_data else value.get("accel_y")
            az_raw = accel_data.get("z") if "z" in accel_data else value.get("accel_z")

            accel_unit = str(accel_data.get("unit", "")).strip().lower() if isinstance(accel_data, Mapping) else ""
            scale_to_mps2 = STANDARD_GRAVITY if accel_unit in {"g", "gravity"} else 1.0

            if ax_raw is None and value.get("accel_x_g") is not None:
                ax_raw = value.get("accel_x_g")
                scale_to_mps2 = STANDARD_GRAVITY
            if ay_raw is None and value.get("accel_y_g") is not None:
                ay_raw = value.get("accel_y_g")
                scale_to_mps2 = STANDARD_GRAVITY
            if az_raw is None and value.get("accel_z_g") is not None:
                az_raw = value.get("accel_z_g")
                scale_to_mps2 = STANDARD_GRAVITY

            accel_x = _parse_accel(ax_raw, scale=scale_to_mps2)
            accel_y = _parse_accel(ay_raw, scale=scale_to_mps2)
            accel_z = _parse_accel(az_raw, scale=scale_to_mps2)

            # Gyroscope Parsing (Phase 4 - Future Hardware BOM Reserved)
            gyro_data = value.get("gyro") if isinstance(value.get("gyro"), Mapping) else {}
            gx_raw = gyro_data.get("x") if "x" in gyro_data else value.get("gyro_x")
            gy_raw = gyro_data.get("y") if "y" in gyro_data else value.get("gyro_y")
            gz_raw = gyro_data.get("z") if "z" in gyro_data else value.get("gyro_z")

            gyro_x = _parse_gyro(gx_raw)
            gyro_y = _parse_gyro(gy_raw)
            gyro_z = _parse_gyro(gz_raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise TelemetryValidationError(f"invalid telemetry: {exc}") from exc

        if not node_id:
            raise TelemetryValidationError("node_id must not be empty")

        if samples < 1:
            raise TelemetryValidationError("n_samples must be positive")

        if vibration < 0.0:
            raise TelemetryValidationError("vibration_rms_mg must be non-negative")

        return cls(
            node_id=node_id,
            timestamp=timestamp,
            pitch_deg=pitch,
            roll_deg=roll,
            vibration_rms_mg=vibration,
            vibration_peak_hz=peak,
            temperature_c=temperature,
            n_samples=samples,
            gnss_status=gnss,
            battery_mv=battery,
            rssi_dbm=rssi,
            snr_db=snr,
            flags=flags,
            x_m=x_m,
            y_m=y_m,
            latitude=latitude,
            longitude=longitude,
            altitude_m=altitude_m,
            accel_x=accel_x,
            accel_y=accel_y,
            accel_z=accel_z,
            gyro_x=gyro_x,
            gyro_y=gyro_y,
            gyro_z=gyro_z,
        )


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


def _number(
    value: Mapping[str, Any],
    engineering: str,
    raw: str,
    scale: float = 1.0,
    encoded: bool = False,
) -> float:
    if engineering in value:
        return float(value[engineering])

    result = float(value[raw]) * scale

    if encoded:
        result -= 20.0

    return result


def _optional_number(
    value: Mapping[str, Any],
    key: str,
) -> float | None:
    return None if value.get(key) is None else float(value[key])


def _validate_coordinate(val: Any, min_val: float, max_val: float) -> float | None:
    """Validate latitude/longitude coordinate range and numeric type safely."""
    if val is None:
        return None
    try:
        num = float(val)
        if not math.isfinite(num):
            return None
        if min_val <= num <= max_val:
            return num
        return None
    except (ValueError, TypeError):
        return None


def _validate_altitude(val: Any) -> float | None:
    """Validate optional elevation/altitude float safely."""
    if val is None:
        return None
    try:
        num = float(val)
        if not math.isfinite(num):
            return None
        return num
    except (ValueError, TypeError):
        return None


def _parse_accel(val: Any, scale: float = 1.0) -> float | None:
    """Parse raw acceleration component into canonical m/s^2."""
    if val is None:
        return None
    try:
        num = float(val)
        if not math.isfinite(num):
            return None
        return num * scale
    except (ValueError, TypeError):
        return None


def _parse_gyro(val: Any) -> float | None:
    """Parse angular rate component into float safely."""
    if val is None:
        return None
    try:
        num = float(val)
        if not math.isfinite(num):
            return None
        return num
    except (ValueError, TypeError):
        return None
