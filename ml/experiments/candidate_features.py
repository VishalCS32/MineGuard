"""Candidate / Research Feature Engineering Path for MineGuard ML.

IMPORTANT ARCHITECTURAL ISOLATION NOTE:
The features in this module are RESEARCH CANDIDATES ONLY.
They are strictly ISOLATED from the frozen production Isolation Forest v2 model
artifact ('ml/artifacts/anomaly/model.joblib') and production runtime inference.

Production MineGuard ML uses a frozen 8-feature tabular contract:
    - tilt_deg
    - robust_tilt_rate_deg_per_hour
    - vibration_rms_mg
    - vibration_peak_hz
    - temperature_c
    - history_count
    - temporal_span_hours
    - temporal_std_tilt_deg

DO NOT inject these candidate features into production training or inference
without completing the rigorous validation protocol defined below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

STANDARD_GRAVITY = 9.80665


@dataclass(frozen=True, slots=True)
class CandidateAccelFeatures:
    """Experimental features derived from 3-axis accelerometer vectors.

    Physical Meaning:
    - dynamic_shock_index: Measures the ratio of instantaneous dynamic acceleration
      perturbation (| ||a|| - g |) to nominal vibration RMS. Distinguishes impulsive
      rock-mass micro-fractures from ambient heavy machinery or haul-truck vibration.
    - triaxial_anisotropy_ratio: Ratio of horizontal plane acceleration energy
      to vertical acceleration energy ((ax^2 + ay^2) / max(az^2, eps)). Geotechnically,
      slope shear slip produces predominant horizontal motion, while vertical bench
      settlement and blast waves produce predominant vertical compression.
    - dynamic_magnitude_mps2: Instantaneous non-gravitational acceleration magnitude.
    """

    dynamic_magnitude_mps2: float | None
    dynamic_shock_index: float | None
    triaxial_anisotropy_ratio: float | None


@dataclass(frozen=True, slots=True)
class CandidateGeodeticFeatures:
    """Experimental features derived from GNSS coordinates over time.

    Physical Meaning:
    - horizontal_displacement_m: Great-circle distance from node commissioning origin
      (lat0, lon0) to current fix (lat, lon). Used for detecting macro-scale bench toppling
      or catastrophic slope sliding (> 15 m) where post inclination may be masked.
    - baseline_strain_estimate: Fractional distance variation between two GNSS-equipped
      nodes: (distance_current - distance_initial) / distance_initial.

    SAFETY WARNING:
    Consumer GNSS (u-blox NEO-6M, ~2.5m horizontal CEP) is 3 orders of magnitude
    too coarse to measure millimetric subsidence directly. These features are strictly
    intended for macro-displacement and geodetic network baseline monitoring.
    """

    horizontal_displacement_m: float | None
    baseline_strain_estimate: float | None


def extract_candidate_accel_features(
    accel_x: float | None,
    accel_y: float | None,
    accel_z: float | None,
    vibration_rms_mg: float | None = None,
) -> CandidateAccelFeatures:
    """Compute research accelerometer features if raw XYZ values are available.

    Required Training Data:
    - High-frequency tri-axial accelerometer logs (100 Hz - 1 kHz) captured during
      controlled bench blasting, haul truck passes, and simulated slope shear failures.

    Required Validation Protocol:
    - Re-evaluate ROC/PR curves on at least 10,000 synthetic and field-recorded event hours.
    - Verify False Alarm Rate (FAR) remains below 0.05% under high-vibration mining operations.
    """
    if accel_x is None or accel_y is None or accel_z is None:
        return CandidateAccelFeatures(None, None, None)

    total_mag = math.sqrt(accel_x**2 + accel_y**2 + accel_z**2)
    dyn_mag = abs(total_mag - STANDARD_GRAVITY)

    shock_index = None
    if vibration_rms_mg is not None and vibration_rms_mg > 0:
        # Convert vibration_rms_mg to m/s^2 for SI consistency
        vib_mps2 = (vibration_rms_mg / 1000.0) * STANDARD_GRAVITY
        shock_index = round(dyn_mag / max(vib_mps2, 0.01), 4)

    horiz_sq = accel_x**2 + accel_y**2
    vert_sq = max(accel_z**2, 1e-4)
    anisotropy = round(horiz_sq / vert_sq, 4)

    return CandidateAccelFeatures(
        dynamic_magnitude_mps2=round(dyn_mag, 4),
        dynamic_shock_index=shock_index,
        triaxial_anisotropy_ratio=anisotropy,
    )


def extract_candidate_geodetic_features(
    lat: float | None,
    lon: float | None,
    origin_lat: float | None,
    origin_lon: float | None,
) -> CandidateGeodeticFeatures:
    """Compute candidate geodetic displacement from baseline coordinates.

    Uses the Haversine formula on WGS-84 spherical approximation (R = 6,371,000 m).
    """
    if None in (lat, lon, origin_lat, origin_lon):
        return CandidateGeodeticFeatures(None, None)

    r = 6_371_000.0
    phi1, phi2 = math.radians(origin_lat), math.radians(lat)  # type: ignore[arg-type]
    dphi = math.radians(lat - origin_lat)  # type: ignore[operator]
    dlam = math.radians(lon - origin_lon)  # type: ignore[operator]

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    dist_m = round(r * c, 3)

    return CandidateGeodeticFeatures(
        horizontal_displacement_m=dist_m,
        baseline_strain_estimate=None,
    )
