"""The wire contract, as Pydantic models.

Deliberately permissive about *absence* and strict about *type*. A node that
cannot measure something sends null, and null is not an error -- this system
exists to receive readings from hardware that is partly broken, in the field,
at night. Rejecting a whole document because one sensor is unwired would lose
the five that work.

`extra="allow"` for the same reason in the other direction: the gateway sends
a couple of fields this schema does not name (`stamped_by`, `gps.h_acc_m`),
and a receiver that 422s on an unrecognised key makes every future firmware
change a breaking one. Unknown keys are kept in the stored raw document.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class Vector(_Loose):
    x: float | None = None
    y: float | None = None
    z: float | None = None
    unit: str | None = None


class Orientation(_Loose):
    roll: float | None = None
    pitch: float | None = None
    unit: str | None = None


class Vibration(Vector):
    rms: float | None = None


class SensorData(_Loose):
    gyro: Vector = Field(default_factory=Vector)
    accelerometer: Vector = Field(default_factory=Vector)
    orientation: Orientation = Field(default_factory=Orientation)
    vibration: Vibration = Field(default_factory=Vibration)
    temperature_c: float | None = None
    battery_mv: int | None = None


class Gps(_Loose):
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    satellites: int | None = None
    hdop: float | None = None


class Communication(_Loose):
    rssi_dbm: int | None = None
    snr_db: float | None = None


class Reading(_Loose):
    node_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime | None = None
    sensor_data: SensorData = Field(default_factory=SensorData)
    gps: Gps = Field(default_factory=Gps)
    communication: Communication = Field(default_factory=Communication)
    flags: int = 0

    @field_validator("timestamp")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        """A timestamp without a zone is a timestamp in an unknown place.

        The gateway sends `...Z`, but a naive value would otherwise be stored
        as though it were server-local and silently shift the reading by
        whatever the deployment's offset happens to be.
        """
        if v is None:
            return None
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
