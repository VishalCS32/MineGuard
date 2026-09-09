import math

from .models import Vector3


def calculate_accelerometer_angles(accel: Vector3) -> tuple[float, float]:
    """
    Calculate roll and pitch from accelerometer data.

    Returns:
        roll, pitch in degrees
    """

    roll = math.degrees(
        math.atan2(accel.y, accel.z)
    )

    pitch = math.degrees(
        math.atan2(
            -accel.x,
            math.sqrt(accel.y ** 2 + accel.z ** 2)
        )
    )

    return roll, pitch


def fuse_orientation(
    accel: Vector3,
    gyro: Vector3,
    previous_roll: float,
    previous_pitch: float,
    dt: float,
    alpha: float = 0.98,
) -> tuple[float, float]:
    """
    Combine accelerometer and gyroscope measurements
    using a complementary filter.

    Returns:
        roll, pitch in degrees
    """

    # Accelerometer gives an absolute orientation estimate
    accel_roll, accel_pitch = calculate_accelerometer_angles(accel)

    # Gyroscope gives angular velocity.
    # Integrate it over the time interval to estimate
    # how much the orientation changed.
    gyro_roll = previous_roll + gyro.x * dt
    gyro_pitch = previous_pitch + gyro.y * dt

    # Complementary filter
    roll = (
        alpha * gyro_roll
        + (1 - alpha) * accel_roll
    )

    pitch = (
        alpha * gyro_pitch
        + (1 - alpha) * accel_pitch
    )

    return roll, pitch