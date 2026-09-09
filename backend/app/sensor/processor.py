from .models import SensorReading
from .validator import validate_reading
from .fusion import fuse_orientation
from .vibration import calculate_magnitude
from .state import NodeState
from .state_manager import SensorStateManager


def process_reading(
    reading: SensorReading,
    state_manager: SensorStateManager,
) -> dict:

    # 1. Validate incoming data
    validate_reading(reading)

    # 2. Get this node's previous state
    previous_state = state_manager.get(reading.node_id)

    # 3. Calculate the time difference
    if previous_state.timestamp is None:
        dt = 0.01
    else:
        dt = (
            reading.timestamp - previous_state.timestamp
        ).total_seconds()

        # Protect against invalid timestamps
        if dt <= 0:
            raise ValueError(
                "Reading timestamp must be later than previous timestamp"
            )

    # 4. Calculate orientation
    roll, pitch = fuse_orientation(
        accel=reading.accelerometer,
        gyro=reading.gyroscope,
        previous_roll=previous_state.roll,
        previous_pitch=previous_state.pitch,
        dt=dt,
    )

    # 5. Calculate vibration magnitude
    vibration_magnitude = calculate_magnitude(
        reading.vibration
    )

    # 6. Save the new state
    new_state = NodeState(
        roll=roll,
        pitch=pitch,
        timestamp=reading.timestamp,
    )

    state_manager.update(
        reading.node_id,
        new_state,
    )

    # 7. Return processed data
    return {
        "node_id": reading.node_id,
        "timestamp": reading.timestamp,

        "accelerometer": reading.accelerometer,
        "gyroscope": reading.gyroscope,
        "vibration": reading.vibration,

        "roll": roll,
        "pitch": pitch,
        "vibration_magnitude": vibration_magnitude,

        "gnss": reading.gnss,
        "battery_percentage": reading.battery_percentage,

        "dt": dt,
    }