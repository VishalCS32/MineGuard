"""Shared, leakage-safe feature engineering for training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from statistics import mean, pstdev
from typing import Mapping, Sequence

from data.telemetry import NodeTelemetry


@dataclass(frozen=True, slots=True)
class NodeFeatures:
    node_id: str
    tilt_deg: float
    tilt_rate_deg_per_hour: float | None
    robust_tilt_rate_deg_per_hour: float | None
    tilt_acceleration_deg_per_hour2: float | None
    vibration_rms_mg: float
    vibration_peak_hz: float
    temperature_c: float
    battery_mv: float
    rssi_dbm: float
    snr_db: float
    gnss_fix: int
    gnss_satellites: int
    flags: int
    history_count: int
    temporal_span_hours: float
    temporal_mean_tilt_deg: float
    temporal_std_tilt_deg: float
    neighbour_count: int
    neighbour_mean_tilt_deg: float | None
    neighbour_difference_deg: float | None
    isolated_from_neighbours: bool


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    timestamp: object
    nodes: tuple[NodeFeatures, ...]
    affected_node_ids: tuple[str, ...]
    spatial_consistency: float


def build_features(current: Sequence[NodeTelemetry],
                   history: Mapping[str, Sequence[NodeTelemetry]] | None = None,
                   *, neighbour_radius_m: float = 100.0,
                   anomaly_tilt_deg: float = 0.5) -> FeatureFrame:
    """Build features using only current values and prior observations.

    ``history[node_id]`` must be ordered oldest to newest and must not include
    observations later than the current frame. The function does not inspect
    simulator truth or scenario metadata.
    """
    history = history or {}
    output: list[NodeFeatures] = []
    for node in current:
        previous = tuple(history.get(node.node_id, ()))
        values = tuple(item.tilt_deg for item in previous) + (node.tilt_deg,)
        rate = _slope(previous, node)
        robust_rate = _robust_slope(previous, node)
        acceleration = _acceleration(previous, node)
        neighbours = tuple(other for other in current if other.node_id != node.node_id
                           and _distance(node, other) is not None
                           and _distance(node, other) <= neighbour_radius_m)
        neighbour_mean = (mean(item.tilt_deg for item in neighbours)
                          if neighbours else None)
        difference = (node.tilt_deg - neighbour_mean
                      if neighbour_mean is not None else None)
        output.append(NodeFeatures(
            node_id=node.node_id,
            tilt_deg=node.tilt_deg,
            tilt_rate_deg_per_hour=rate,
            robust_tilt_rate_deg_per_hour=robust_rate,
            tilt_acceleration_deg_per_hour2=acceleration,
            vibration_rms_mg=node.vibration_rms_mg,
            vibration_peak_hz=node.vibration_peak_hz,
            temperature_c=node.temperature_c,
            battery_mv=node.battery_mv,
            rssi_dbm=node.rssi_dbm,
            snr_db=node.snr_db,
            gnss_fix=node.gnss_status & 0x03,
            gnss_satellites=(node.gnss_status >> 2) & 0x3F,
            flags=node.flags,
            history_count=len(values),
            temporal_span_hours=_span_hours(previous, node),
            temporal_mean_tilt_deg=mean(values),
            temporal_std_tilt_deg=pstdev(values) if len(values) > 1 else 0.0,
            neighbour_count=len(neighbours),
            neighbour_mean_tilt_deg=neighbour_mean,
            neighbour_difference_deg=difference,
            isolated_from_neighbours=bool(neighbours and abs(difference or 0.0) > anomaly_tilt_deg),
        ))

    affected = tuple(item.node_id for item in output if item.tilt_deg >= anomaly_tilt_deg)
    comparable = [item for item in output if item.neighbour_count]
    consistency = (sum(1.0 for item in comparable if not item.isolated_from_neighbours)
                   / len(comparable) if comparable else 0.0)
    timestamp = current[0].timestamp if current else None
    return FeatureFrame(timestamp, tuple(output), affected, consistency)


def _distance(left: NodeTelemetry, right: NodeTelemetry) -> float | None:
    if left.x_m is None or left.y_m is None or right.x_m is None or right.y_m is None:
        return None
    return hypot(left.x_m - right.x_m, left.y_m - right.y_m)


def _slope(previous: Sequence[NodeTelemetry], current: NodeTelemetry) -> float | None:
    if not previous:
        return None
    first = previous[0]
    hours = (current.timestamp - first.timestamp).total_seconds() / 3600.0
    return (current.tilt_deg - first.tilt_deg) / hours if hours > 0 else None


def _robust_slope(previous: Sequence[NodeTelemetry],
                  current: NodeTelemetry) -> float | None:
    observations = tuple(previous) + (current,)
    if len(observations) < 2:
        return None
    slopes: list[float] = []
    for left, right in zip(observations, observations[1:]):
        hours = (right.timestamp - left.timestamp).total_seconds() / 3600.0
        if hours > 0:
            slopes.append((right.tilt_deg - left.tilt_deg) / hours)
    if not slopes:
        return None
    ordered = sorted(slopes)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _span_hours(previous: Sequence[NodeTelemetry], current: NodeTelemetry) -> float:
    if not previous:
        return 0.0
    return max(0.0, (current.timestamp - previous[0].timestamp).total_seconds() / 3600.0)


def _acceleration(previous: Sequence[NodeTelemetry], current: NodeTelemetry) -> float | None:
    if len(previous) < 2:
        return None
    first_rate = _slope(previous[:-1], previous[-1])
    last_rate = _slope(previous, current)
    if first_rate is None or last_rate is None:
        return None
    hours = (current.timestamp - previous[-1].timestamp).total_seconds() / 3600.0
    return (last_rate - first_rate) / hours if hours > 0 else None
