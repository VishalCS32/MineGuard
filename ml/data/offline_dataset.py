"""Independent offline development data for trained ML experiments.

This module deliberately does not import ``ml.simulator``. It emits the same
logical telemetry mappings that real decoded MineGuard records provide, with
labels kept outside the inference feature set for evaluation only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sin
from typing import Iterator

import numpy as np


@dataclass(frozen=True, slots=True)
class LabeledTelemetry:
    record: dict
    label: int
    label_name: str


@dataclass(frozen=True, slots=True)
class OfflineDataset:
    records: tuple[LabeledTelemetry, ...]
    node_positions: dict[str, tuple[float, float]]
    dataset_version: str


def generate_dataset(*, nodes: int = 21, steps: int = 240, seed: int = 42,
                      interval_minutes: int = 15) -> OfflineDataset:
    """Generate chronological training/development telemetry without simulator imports."""
    rng = np.random.default_rng(seed)
    # Synthetic relative layout for offline training only: a 5x4 grid plus one
    # central node. Production coordinates will come from the backend survey.
    positions = {
        f"NODE-{index + 1:03d}": (float((index % 5) * 50), float((index // 5) * 50))
        for index in range(min(nodes, 20))
    }
    if nodes > 20:
        positions["NODE-021"] = (100.0, 100.0)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output: list[LabeledTelemetry] = []
    for step in range(steps):
        when = start + timedelta(minutes=step * interval_minutes)
        for index, node_id in enumerate(positions):
            label = 0
            label_name = "normal"
            tilt = 0.02 + rng.normal(0.0, 0.008)
            vibration = 18.0 + abs(rng.normal(0.0, 4.0))
            battery = 3950.0 - step * 0.15 + rng.normal(0.0, 4.0)
            rssi = -70.0 + rng.normal(0.0, 3.0)
            snr = 8.0 + rng.normal(0.0, 1.0)
            # A bounded, spatially correlated deformation window leaves normal
            # examples in both validation and test periods. The affected group
            # occupies the center of the synthetic grid.
            deformation_start = int(steps * 0.58)
            deformation_end = int(steps * 0.82)
            if deformation_start <= step < deformation_end:
                progress = (step - deformation_start) / max(1, deformation_end - deformation_start)
                shape = sin(np.pi * progress)
                group = {"NODE-007", "NODE-008", "NODE-012", "NODE-013"}
                if node_id in group:
                    tilt += (0.42 * shape) * (1.0 + 0.08 * sin(index / 2))
                    vibration += 90.0 * shape
                    label = 1
                    label_name = "physical_deformation"
            # A small isolated physical event is separate from the group event.
            if node_id == "NODE-021" and int(steps * 0.42) <= step < int(steps * 0.50):
                tilt += 0.18 * sin(np.pi * (step - int(steps * 0.42))
                                    / max(1, int(steps * 0.08)))
                label = 1
                label_name = "physical_deformation"
            # An isolated physical event is separate from a communication fault.
            if index == nodes - 1 and int(steps * 0.42) <= step < int(steps * 0.50):
                tilt += 0.18 * sin(np.pi * (step - int(steps * 0.42))
                                    / max(1, int(steps * 0.08)))
                label = 1
                label_name = "physical_deformation"
            # A sensor-quality fault carries quality evidence but no physical
            # deformation contribution.
            if step >= int(steps * 0.84) and index == 0:
                battery = 3400.0 + rng.normal(0.0, 4.0)
                rssi = -120.0 + rng.normal(0.0, 2.0)
                snr = -8.0 + rng.normal(0.0, 0.5)
                flags = 1
                label = 1
                label_name = "sensor_anomaly"
            else:
                flags = 0
            output.append(LabeledTelemetry({
                "node_id": node_id,
                "timestamp": when.isoformat(),
                "pitch_deg": float(tilt),
                "roll_deg": float(rng.normal(0.0, 0.008)),
                "vibration_rms_mg": float(max(0.0, vibration)),
                "vibration_peak_hz": float(rng.normal(30.0, 3.0)),
                "temperature_c": float(28.0 + 5.0 * sin(step / 96.0)),
                "n_samples": 32,
                "gnss_status": 14,
                "battery_mv": float(battery),
                "rssi_dbm": float(rssi),
                "snr_db": float(snr),
                "flags": flags,
                "x_m": positions[node_id][0],
                "y_m": positions[node_id][1],
            }, label, label_name))
    return OfflineDataset(tuple(output), positions, "offline-telemetry-v2")


def chronological_split(dataset: OfflineDataset, *, train_fraction: float = 0.5,
                        validation_fraction: float = 0.15
                        ) -> tuple[tuple[LabeledTelemetry, ...], ...]:
    """Split complete timestamp windows chronologically, never individual rows."""
    timestamps = sorted({item.record["timestamp"] for item in dataset.records})
    train_end = int(len(timestamps) * train_fraction)
    validation_end = int(len(timestamps) * (train_fraction + validation_fraction))
    boundaries = (timestamps[train_end], timestamps[validation_end])
    train = tuple(item for item in dataset.records if item.record["timestamp"] < boundaries[0])
    validation = tuple(item for item in dataset.records
                       if boundaries[0] <= item.record["timestamp"] < boundaries[1])
    test = tuple(item for item in dataset.records if item.record["timestamp"] >= boundaries[1])
    return train, validation, test


def chronological_windows(dataset: OfflineDataset, *, history_size: int = 8
                          ) -> Iterator[tuple[dict, tuple[dict, ...], int, str]]:
    """Yield current records with only preceding same-node records as history."""
    by_node: dict[str, list[LabeledTelemetry]] = {}
    for item in dataset.records:
        history = tuple(item.record for item in by_node.get(item.record["node_id"], [])[-history_size:])
        yield item.record, history, item.label, item.label_name
        by_node.setdefault(item.record["node_id"], []).append(item)
