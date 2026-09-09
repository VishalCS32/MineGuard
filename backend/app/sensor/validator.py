from .models import SensorReading


def validate_reading(reading: SensorReading) -> None:
    """
    Validate a sensor reading.

    Raises ValueError if the reading is invalid.
    """

    # Node ID
    if not reading.node_id:
        raise ValueError("node_id cannot be empty")

    # Accelerometer
    accel = reading.accelerometer

    if not all(
        isinstance(value, (int, float))
        for value in (accel.x, accel.y, accel.z)
    ):
        raise ValueError("Accelerometer values must be numbers")

    # Gyroscope
    gyro = reading.gyroscope

    if not all(
        isinstance(value, (int, float))
        for value in (gyro.x, gyro.y, gyro.z)
    ):
        raise ValueError("Gyroscope values must be numbers")

    # Vibration
    vibration = reading.vibration

    if not all(
        isinstance(value, (int, float))
        for value in (vibration.x, vibration.y, vibration.z)
    ):
        raise ValueError("Vibration values must be numbers")

    # GNSS
    if not -90 <= reading.gnss.latitude <= 90:
        raise ValueError("Invalid latitude")

    if not -180 <= reading.gnss.longitude <= 180:
        raise ValueError("Invalid longitude")

    # Battery
    if not 0 <= reading.battery_percentage <= 100:
        raise ValueError("Battery percentage must be between 0 and 100")