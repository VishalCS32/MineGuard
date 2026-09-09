from datetime import datetime, timezone, timedelta

from .models import SensorReading, Vector3, GNSS
from .processor import process_reading
from .state_manager import SensorStateManager


# -------------------------
# First reading
# -------------------------

reading = SensorReading(
    node_id="NODE_001",
    timestamp=datetime.now(timezone.utc),

    accelerometer=Vector3(
        x=0.12,
        y=-0.04,
        z=9.81,
    ),

    gyroscope=Vector3(
        x=0.21,
        y=0.08,
        z=-0.11,
    ),

    vibration=Vector3(
        x=0.02,
        y=0.03,
        z=0.01,
    ),

    gnss=GNSS(
        latitude=23.4567,
        longitude=87.1234,
    ),

    battery_percentage=87.0,
)


# Create the state manager
state_manager = SensorStateManager()


# Process the first reading
result = process_reading(
    reading,
    state_manager,
)

print("First reading:")
print(result)


# -------------------------
# Second reading
# -------------------------

reading_2 = SensorReading(
    node_id="NODE_001",

    # 20 milliseconds after the first reading
    timestamp=reading.timestamp + timedelta(milliseconds=20),

    accelerometer=Vector3(
        x=0.15,
        y=-0.02,
        z=9.80,
    ),

    gyroscope=Vector3(
        x=0.30,
        y=0.10,
        z=-0.08,
    ),

    vibration=Vector3(
        x=0.03,
        y=0.04,
        z=0.02,
    ),

    gnss=GNSS(
        latitude=23.4567,
        longitude=87.1234,
    ),

    battery_percentage=86.9,
)


# Process the second reading
result_2 = process_reading(
    reading_2,
    state_manager,
)

print("\nSecond reading:")
print(result_2)

# -------------------------
# NODE_002
# -------------------------

reading_3 = SensorReading(
    node_id="NODE_002",
    timestamp=reading.timestamp + timedelta(milliseconds=20),

    accelerometer=Vector3(
        x=0.50,
        y=0.20,
        z=9.70,
    ),

    gyroscope=Vector3(
        x=1.00,
        y=0.50,
        z=0.20,
    ),

    vibration=Vector3(
        x=0.10,
        y=0.20,
        z=0.05,
    ),

    gnss=GNSS(
        latitude=23.4568,
        longitude=87.1235,
    ),

    battery_percentage=92.0,
)


result_3 = process_reading(
    reading_3,
    state_manager,
)

print("\nNODE_002 reading:")
print(result_3)