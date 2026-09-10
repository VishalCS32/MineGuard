"""Interpretable ML baselines for MineGuard inference.

These estimators are deliberately deterministic fallbacks. They can later be
replaced or augmented by trained artifacts without changing the input contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import exp, isfinite
from statistics import mean
from typing import Sequence

from features.engineering import FeatureFrame, NodeFeatures


class DeformationState(str, Enum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STABLE = "STABLE"
    SLOW_CREEP = "SLOW_CREEP"
    ACCELERATING = "ACCELERATING"
    RAPID_DEFORMATION = "RAPID_DEFORMATION"


class SensorHealth(str, Enum):
    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    FAULTY = "FAULTY"
    SENSOR_FAULT = "SENSOR_FAULT"


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    score: float
    detected: bool
    severity: str
    status: str = "READY"


@dataclass(frozen=True, slots=True)
class HealthResult:
    node_id: str
    status: SensorHealth
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    horizon_hours: int
    tilt_deg: float | None
    tilt_rate_deg_per_hour: float | None


MINIMUM_PRIOR_OBSERVATIONS = 4
MINIMUM_HISTORY_HOURS = 1.0
TREND_PERSISTENCE_HOURS = 6.0


def has_sufficient_history(features: NodeFeatures,
                           minimum_prior: int = MINIMUM_PRIOR_OBSERVATIONS) -> bool:
    """Whether a node has enough prior observations for temporal inference."""
    return (features.history_count - 1 >= minimum_prior
            and features.temporal_span_hours >= MINIMUM_HISTORY_HOURS)


def anomaly_for_node(features: NodeFeatures, *, tilt_limit_deg: float = 0.5,
                     rate_limit_deg_per_hour: float = 0.05,
                     vibration_limit_mg: float = 500.0) -> AnomalyResult:
    if not has_sufficient_history(features):
        return AnomalyResult(0.0, False, "INSUFFICIENT_HISTORY", "INSUFFICIENT_HISTORY")
    evidence = [
        _ratio(abs(features.tilt_deg), tilt_limit_deg),
        _ratio(abs(features.robust_tilt_rate_deg_per_hour or 0.0), rate_limit_deg_per_hour),
        _ratio(features.vibration_rms_mg, vibration_limit_mg),
    ]
    score = min(1.0, max(evidence))
    score = score * 0.75 + (1.0 if features.isolated_from_neighbours else score) * 0.25
    score = min(1.0, score)
    severity = "CRITICAL" if score >= 0.85 else "ANOMALOUS" if score >= 0.6 else "UNUSUAL" if score >= 0.35 else "NORMAL"
    return AnomalyResult(score, score >= 0.6, severity)


def classify_progression(features: Sequence[NodeFeatures]) -> DeformationState:
    if not features or not all(has_sufficient_history(item) for item in features):
        return DeformationState.INSUFFICIENT_HISTORY
    rates = [item.robust_tilt_rate_deg_per_hour for item in features
             if item.robust_tilt_rate_deg_per_hour is not None]
    accelerations = [item.tilt_acceleration_deg_per_hour2 for item in features
                     if item.tilt_acceleration_deg_per_hour2 is not None]
    max_rate = max((abs(value) for value in rates), default=0.0)
    max_accel = max((value for value in accelerations), default=0.0)
    max_tilt = max((item.tilt_deg for item in features), default=0.0)
    if max_rate >= 0.20 or max_tilt >= 1.5:
        return DeformationState.RAPID_DEFORMATION
    if max_accel >= 0.02 or max_rate >= 0.05:
        return DeformationState.ACCELERATING
    if max_rate >= 0.01 or max_tilt >= 0.15:
        return DeformationState.SLOW_CREEP
    return DeformationState.STABLE


def forecast(features: NodeFeatures, horizons: Sequence[int] = (1, 6, 12, 24)) -> tuple[ForecastPoint, ...]:
    if not has_sufficient_history(features):
        return tuple(ForecastPoint(hour, None, None) for hour in horizons)
    rate = features.robust_tilt_rate_deg_per_hour
    if rate is None:
        return tuple(ForecastPoint(hour, None, None) for hour in horizons)
    if abs(rate) < 0.01:
        rate = 0.0
    points: list[ForecastPoint] = []
    for hour in horizons:
        # At 1h short horizon, high-frequency sensor noise makes rate extrapolation
        # noisier than the persistence baseline. A hybrid strategy uses persistence
        # for 1h while leveraging damped exponential trend decay for 6h, 12h, and 24h.
        if hour <= 1:
            projected_tilt = features.tilt_deg
        else:
            projected_tilt = max(
                0.0,
                features.tilt_deg
                + rate * TREND_PERSISTENCE_HOURS
                * (1.0 - exp(-hour / TREND_PERSISTENCE_HOURS)),
            )
        points.append(ForecastPoint(
            hour,
            projected_tilt,
            rate * exp(-hour / TREND_PERSISTENCE_HOURS),
        ))
    return tuple(points)


def health_for_node(features: NodeFeatures, *, stale: bool = False) -> HealthResult:
    reasons: list[str] = []
    if features.flags & 0x0F:
        reasons.append("protocol fault or calibration flag")
    if features.battery_mv < 3500:
        reasons.append("low battery")
    if features.rssi_dbm < -115 or features.snr_db < -5:
        reasons.append("degraded communication")
    if features.gnss_fix == 0:
        reasons.append("no GNSS fix")
    if features.isolated_from_neighbours:
        reasons.append("disagrees with neighbouring nodes")
    if stale:
        reasons.append("telemetry is stale")
    if features.history_count >= 2 and features.temporal_std_tilt_deg == 0:
        reasons.append("unchanging sensor value")
    score = max(0.0, 1.0 - 0.2 * len(reasons))
    status = SensorHealth.FAULTY if features.flags & 0x07 else SensorHealth.SUSPECT if reasons else SensorHealth.HEALTHY
    return HealthResult(features.node_id, status, score, tuple(reasons))


def _ratio(value: float, limit: float) -> float:
    return min(1.0, value / limit) if limit > 0 and isfinite(value) else 1.0
