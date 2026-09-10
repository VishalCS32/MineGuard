from datetime import datetime
from types import SimpleNamespace

from .ml_payload import build_ml_payload


telemetry = SimpleNamespace(
    node_id=1,
    time=datetime(2026, 9, 10, 12, 0, 0),
    pitch_mdeg=120,
    roll_mdeg=80,
    vib_rms_mg=18.5,
    vib_peak_hz=42.0,
    temp_c_x100=3120,
    vbat_mv=3890,
    rssi=-82,
    snr_db=7.5,
    gnss_status=1,
)

# Simulated backend history
history = {
    "NODE-001": [
        {
            "node_id": "NODE-001",
            "timestamp": "2026-09-10T11:00:00+00:00",

            "gyro": {
                "x": None,
                "y": None,
                "z": None,
            },

            "accel": {
                "x": None,
                "y": None,
                "z": None,
            },

            "orientation": {
                "pitch": 0.10,
                "roll": 0.07,
            },

            "vibration": {
                "rms_mg": 17.0,
                "peak_hz": 41.0,
            },

            "gps": {
                "latitude": None,
                "longitude": None,
                "status": 1,
            },

            "ml": {},
        }
    ]
}

# Simulated backend deformation result
field = {
    1: SimpleNamespace(
        subsidence_mm=14.3,
        strain_mm_per_m=0.72,
    )
}

# Resolve the human-readable node label
node = telemetry
node.node_label = "NODE-001"

payload = build_ml_payload(
    nodes=[node],
    history=history,
    field=field,
)

print(payload)