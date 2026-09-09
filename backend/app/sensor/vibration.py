import math

from .models import Vector3


def calculate_magnitude(vibration: Vector3) -> float:
    """
    Calculate the magnitude of a 3-axis vibration measurement.
    """

    return math.sqrt(
        vibration.x ** 2
        + vibration.y ** 2
        + vibration.z ** 2
    )