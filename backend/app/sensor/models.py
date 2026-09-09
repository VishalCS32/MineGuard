from dataclasses import dataclass
from datetime import datetime


@dataclass
class Vector3:
    x: float
    y: float
    z: float


@dataclass
class GNSS:
    latitude: float
    longitude: float


@dataclass
class SensorReading:
    node_id: str
    timestamp: datetime

    accelerometer: Vector3
    gyroscope: Vector3
    vibration: Vector3

    gnss: GNSS
    battery_percentage: float