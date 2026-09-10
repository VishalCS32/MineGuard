"""Build requests for the MineGuard ML inference service."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .models import telemetry, nodes


def telemetry_to_ml_node(telemetry) -> dict:
    """Convert backend telemetry into the ML node format."""

    def get(name):
        if isinstance(telemetry, dict):
            return telemetry.get(name)
        return getattr(telemetry, name)

    return {
        "node_id": str(get("node_id")),
        "timestamp": get("time").isoformat(),

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
            "pitch": (get("pitch_mdeg") or 0) / 1000.0,
            "roll": (get("roll_mdeg") or 0) / 1000.0,
        },

        "vibration": {
            "rms_mg": get("vib_rms_mg") or 0,
            "peak_hz": get("vib_peak_hz") or 0,
        },

        "gps": {
            "latitude": None,
            "longitude": None,
            "status": get("gnss_status") or 0,
        },

        "ml": {},
    }

def build_derived(
    field: dict,
    node_labels: dict | None = None,
) -> dict:
    """Convert backend FieldEstimate objects into ML derived data."""

    node_labels = node_labels or {}

    return {
        str(node_labels.get(addr, addr)): {
            "subsidence_mm": estimate.subsidence_mm,
            "strain_mm_per_m": estimate.strain_mm_per_m,
        }
        for addr, estimate in field.items()
    }


def build_ml_payload(
    nodes: list,
    history: dict | None = None,
    field: dict | None = None,
) -> dict:
    """Build the complete Backend → ML request."""

    ml_nodes = []
    node_labels = {}

    for node in nodes:
        ml_node = telemetry_to_ml_node(node)

        if isinstance(node, dict):
            node_label = node.get("node_label")
            node_addr = node.get("node_addr", node.get("node_id"))
        else:
            node_label = getattr(node, "node_label", None)
            node_addr = getattr(node, "node_addr", getattr(node, "node_id", None))

        if node_label:
            ml_node["node_id"] = str(node_label)

        if node_addr is not None and node_label:
            node_labels[node_addr] = str(node_label)

        ml_nodes.append(ml_node)

    return {
        "nodes": ml_nodes,
        "history": history or {},
        "derived": build_derived(field or {}, node_labels),
    }


async def build_history(
    session: AsyncSession,
    node_ids: list[int],
    since,
) -> dict[str, list[dict]]:
    """Load chronological telemetry history grouped by node label."""

    stmt = (
        sa.select(telemetry, nodes.c.label)
        .join(nodes, nodes.c.id == telemetry.c.node_id)
        .where(
            telemetry.c.node_id.in_(node_ids),
            telemetry.c.time >= since,
        )
        .order_by(telemetry.c.node_id, telemetry.c.time)
    )

    rows = (await session.execute(stmt)).mappings().all()

    history: dict[str, list[dict]] = {}

    for row in rows:
        node_label = str(row["label"])

        history.setdefault(node_label, []).append(
            telemetry_to_ml_node(row)
        )

        history[node_label][-1]["node_id"] = node_label

    return history