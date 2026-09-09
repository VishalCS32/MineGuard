from .models import Vector3
from .vibration import calculate_magnitude


vibration = Vector3(
    x=3.0,
    y=4.0,
    z=0.0,
)

magnitude = calculate_magnitude(vibration)

print("Vibration magnitude:", magnitude)