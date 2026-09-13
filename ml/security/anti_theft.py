"""MineGuard Hardware Anti-Theft and Movement Detection.

Detects unauthorized physical movement or potential theft of sensor nodes
by comparing real-time GPS coordinates against registered installation coordinates.

Operational Principles:
1. Security-Only: GPS movement is used exclusively for hardware theft detection,
   NOT for millimetric mine subsidence or geotechnical deformation monitoring.
2. 10m Default Threshold: Accounts for consumer GNSS receiver noise (u-blox NEO-6M,
   ~2.5m CEP horizontal accuracy) to prevent false alarms from satellite drift.
3. 3-Reading Debounce: Requires 3 consecutive valid GPS readings beyond the radius
   before setting confirmed theft alert (THEFT_SUSPECTED / alert=True).
4. Frozen Isolation: Completely decoupled from the production Isolation Forest v2
   anomaly detection model, risk score, time-to-threshold, and forecast logic.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

# Configurable defaults
ANTI_THEFT_RADIUS_M: float = 10.0
ANTI_THEFT_CONFIRMATION_READINGS: int = 3
RECOVERY_CONFIRMATION_READINGS: int = 3

# Status codes
STATUS_NORMAL: str = "NORMAL"
STATUS_MOVEMENT_SUSPECTED: str = "MOVEMENT_SUSPECTED"
STATUS_THEFT_SUSPECTED: str = "THEFT_SUSPECTED"
STATUS_GPS_UNAVAILABLE: str = "GPS_UNAVAILABLE"

# Reason codes
REASON_WITHIN_RADIUS: str = "WITHIN_REGISTERED_RADIUS"
REASON_MOVEMENT_BEYOND_THRESHOLD: str = "NODE_MOVEMENT_BEYOND_THRESHOLD"
REASON_MOVED_BEYOND_THRESHOLD: str = "NODE_MOVED_BEYOND_THRESHOLD"
REASON_GPS_UNAVAILABLE: str = "GPS_POSITION_UNAVAILABLE"
REASON_REGISTERED_UNAVAILABLE: str = "REGISTERED_POSITION_UNAVAILABLE"
REASON_GPS_INVALID: str = "GPS_INVALID"


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two geodetic coordinates in metres.

    Uses spherical Earth approximation with WGS-84 mean radius R = 6,371,000 m.
    """
    r = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


@dataclass(frozen=True, slots=True)
class AntiTheftNodeResult:
    """Deterministic, serializable anti-theft evaluation for a single sensor node."""

    node_id: str
    status: str
    alert: bool
    confirmed: bool
    distance_from_registered_m: float | None
    threshold_m: float = ANTI_THEFT_RADIUS_M
    confirmation_count: int = 0
    confirmation_required: int = ANTI_THEFT_CONFIRMATION_READINGS
    reason_code: str = REASON_WITHIN_RADIUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "alert": self.alert,
            "confirmed": self.confirmed,
            "distance_from_registered_m": self.distance_from_registered_m,
            "threshold_m": self.threshold_m,
            "confirmation_count": self.confirmation_count,
            "confirmation_required": self.confirmation_required,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class AntiTheftSummary:
    """Top-level ML JSON summary across all reporting sensor nodes."""

    alert: bool
    status: str
    affected_node_ids: tuple[str, ...]
    events: tuple[AntiTheftNodeResult, ...]

    def to_dict(self) -> dict[str, Any]:
        events_dicts = [e.to_dict() for e in self.events]
        res: dict[str, Any] = {
            "alert": self.alert,
            "status": self.status,
            "affected_node_ids": list(self.affected_node_ids),
            "events": events_dicts,
        }
        # If single node, expose convenience fields directly at root
        if len(events_dicts) == 1:
            single = events_dicts[0]
            res.update({
                "node_id": single["node_id"],
                "confirmed": single["confirmed"],
                "distance_from_registered_m": single["distance_from_registered_m"],
                "threshold_m": single["threshold_m"],
                "confirmation_count": single["confirmation_count"],
                "confirmation_required": single["confirmation_required"],
                "reason_code": single["reason_code"],
            })
        return res


class AntiTheftTracker:
    """Stateful, debounce-confirmed anti-theft tracking engine for multi-node deployments."""

    def __init__(
        self,
        radius_m: float = ANTI_THEFT_RADIUS_M,
        confirmation_readings: int = ANTI_THEFT_CONFIRMATION_READINGS,
        recovery_readings: int = RECOVERY_CONFIRMATION_READINGS,
    ) -> None:
        self.radius_m = float(radius_m)
        self.confirmation_readings = int(confirmation_readings)
        self.recovery_readings = int(recovery_readings)
        self._states: dict[str, dict[str, Any]] = {}

    def reset(self, node_id: str | None = None) -> None:
        """Reset anti-theft tracking state for a specific node or all nodes."""
        if node_id is not None:
            self._states.pop(str(node_id), None)
        else:
            self._states.clear()

    def update_node(
        self,
        node_id: str,
        current_lat: float | None,
        current_lon: float | None,
        registered_lat: float | None,
        registered_lon: float | None,
        gnss_status: int | None = None,
    ) -> AntiTheftNodeResult:
        """Update tracker with a new observation and return deterministic evaluation."""
        nid = str(node_id)
        state = self._states.setdefault(nid, {
            "confirmation_count": 0,
            "confirmed": False,
            "consecutive_normal_count": 0,
            "last_distance_m": None,
            "last_status": STATUS_NORMAL,
        })

        # 1. Registered Position Validation
        if registered_lat is None or registered_lon is None:
            return AntiTheftNodeResult(
                node_id=nid,
                status=STATUS_GPS_UNAVAILABLE,
                alert=False,
                confirmed=False,
                distance_from_registered_m=None,
                threshold_m=self.radius_m,
                confirmation_count=0,
                confirmation_required=self.confirmation_readings,
                reason_code=REASON_REGISTERED_UNAVAILABLE,
            )

        if not (-90.0 <= registered_lat <= 90.0 and -180.0 <= registered_lon <= 180.0):
            return AntiTheftNodeResult(
                node_id=nid,
                status=STATUS_GPS_UNAVAILABLE,
                alert=False,
                confirmed=False,
                distance_from_registered_m=None,
                threshold_m=self.radius_m,
                confirmation_count=0,
                confirmation_required=self.confirmation_readings,
                reason_code=REASON_GPS_INVALID,
            )

        # 2. Current GPS Quality / Validity Check
        if current_lat is None or current_lon is None:
            return AntiTheftNodeResult(
                node_id=nid,
                status=STATUS_GPS_UNAVAILABLE,
                alert=False,
                confirmed=False,
                distance_from_registered_m=None,
                threshold_m=self.radius_m,
                confirmation_count=0,
                confirmation_required=self.confirmation_readings,
                reason_code=REASON_GPS_UNAVAILABLE,
            )

        if not (-90.0 <= current_lat <= 90.0 and -180.0 <= current_lon <= 180.0):
            return AntiTheftNodeResult(
                node_id=nid,
                status=STATUS_GPS_UNAVAILABLE,
                alert=False,
                confirmed=False,
                distance_from_registered_m=None,
                threshold_m=self.radius_m,
                confirmation_count=0,
                confirmation_required=self.confirmation_readings,
                reason_code=REASON_GPS_INVALID,
            )

        # Discard reading if GNSS fix status is explicitly NO_FIX (low 2 bits == 0)
        if gnss_status is not None and (int(gnss_status) & 0x03) == 0:
            return AntiTheftNodeResult(
                node_id=nid,
                status=STATUS_GPS_UNAVAILABLE,
                alert=False,
                confirmed=False,
                distance_from_registered_m=None,
                threshold_m=self.radius_m,
                confirmation_count=0,
                confirmation_required=self.confirmation_readings,
                reason_code=REASON_GPS_UNAVAILABLE,
            )

        # 3. Compute Haversine Horizontal Distance
        dist_m = round(haversine_distance_m(registered_lat, registered_lon, current_lat, current_lon), 2)
        state["last_distance_m"] = dist_m

        # 4. Confirmation / Debounce Evaluation
        if dist_m >= self.radius_m:
            state["consecutive_normal_count"] = 0
            if not state["confirmed"]:
                state["confirmation_count"] += 1
                if state["confirmation_count"] >= self.confirmation_readings:
                    state["confirmed"] = True
                    state["last_status"] = STATUS_THEFT_SUSPECTED
                    return AntiTheftNodeResult(
                        node_id=nid,
                        status=STATUS_THEFT_SUSPECTED,
                        alert=True,
                        confirmed=True,
                        distance_from_registered_m=dist_m,
                        threshold_m=self.radius_m,
                        confirmation_count=state["confirmation_count"],
                        confirmation_required=self.confirmation_readings,
                        reason_code=REASON_MOVED_BEYOND_THRESHOLD,
                    )
                else:
                    state["last_status"] = STATUS_MOVEMENT_SUSPECTED
                    return AntiTheftNodeResult(
                        node_id=nid,
                        status=STATUS_MOVEMENT_SUSPECTED,
                        alert=False,
                        confirmed=False,
                        distance_from_registered_m=dist_m,
                        threshold_m=self.radius_m,
                        confirmation_count=state["confirmation_count"],
                        confirmation_required=self.confirmation_readings,
                        reason_code=REASON_MOVEMENT_BEYOND_THRESHOLD,
                    )
            else:
                # Already confirmed: maintain alert until explicit recovery
                state["last_status"] = STATUS_THEFT_SUSPECTED
                return AntiTheftNodeResult(
                    node_id=nid,
                    status=STATUS_THEFT_SUSPECTED,
                    alert=True,
                    confirmed=True,
                    distance_from_registered_m=dist_m,
                    threshold_m=self.radius_m,
                    confirmation_count=max(state["confirmation_count"], self.confirmation_readings),
                    confirmation_required=self.confirmation_readings,
                    reason_code=REASON_MOVED_BEYOND_THRESHOLD,
                )
        else:
            # Within threshold radius (< 10m)
            if state["confirmed"]:
                # Recovery mechanism: requires consecutive readings back within radius to clear confirmed theft
                state["consecutive_normal_count"] += 1
                if state["consecutive_normal_count"] >= self.recovery_readings:
                    state["confirmed"] = False
                    state["confirmation_count"] = 0
                    state["consecutive_normal_count"] = 0
                    state["last_status"] = STATUS_NORMAL
                    return AntiTheftNodeResult(
                        node_id=nid,
                        status=STATUS_NORMAL,
                        alert=False,
                        confirmed=False,
                        distance_from_registered_m=dist_m,
                        threshold_m=self.radius_m,
                        confirmation_count=0,
                        confirmation_required=self.confirmation_readings,
                        reason_code=REASON_WITHIN_RADIUS,
                    )
                else:
                    # Still in confirmed alert during recovery debounce
                    return AntiTheftNodeResult(
                        node_id=nid,
                        status=STATUS_THEFT_SUSPECTED,
                        alert=True,
                        confirmed=True,
                        distance_from_registered_m=dist_m,
                        threshold_m=self.radius_m,
                        confirmation_count=state["confirmation_count"],
                        confirmation_required=self.confirmation_readings,
                        reason_code=REASON_MOVED_BEYOND_THRESHOLD,
                    )
            else:
                # Reset debounce counter if movement was only transient
                state["confirmation_count"] = 0
                state["consecutive_normal_count"] = 0
                state["last_status"] = STATUS_NORMAL
                return AntiTheftNodeResult(
                    node_id=nid,
                    status=STATUS_NORMAL,
                    alert=False,
                    confirmed=False,
                    distance_from_registered_m=dist_m,
                    threshold_m=self.radius_m,
                    confirmation_count=0,
                    confirmation_required=self.confirmation_readings,
                    reason_code=REASON_WITHIN_RADIUS,
                )


def evaluate_anti_theft_frame(
    current_nodes: Sequence[Any],
    history_records: Mapping[str, Sequence[Any]] | None = None,
    registered_positions: Mapping[str, Any] | None = None,
    tracker: AntiTheftTracker | None = None,
    radius_m: float = ANTI_THEFT_RADIUS_M,
    confirmation_readings: int = ANTI_THEFT_CONFIRMATION_READINGS,
) -> AntiTheftSummary:
    """Evaluate anti-theft status across all nodes in a telemetry frame."""
    if not current_nodes:
        return AntiTheftSummary(
            alert=False,
            status=STATUS_NORMAL,
            affected_node_ids=(),
            events=(),
        )

    registered_positions = registered_positions or {}
    history_records = history_records or {}
    local_tracker = tracker or AntiTheftTracker(radius_m=radius_m, confirmation_readings=confirmation_readings)

    results: list[AntiTheftNodeResult] = []

    for item in current_nodes:
        node_id = str(item.node_id if hasattr(item, "node_id") else item.get("node_id", ""))
        curr_lat = item.latitude if hasattr(item, "latitude") else item.get("latitude", item.get("lat"))
        curr_lon = item.longitude if hasattr(item, "longitude") else item.get("longitude", item.get("lon"))
        gnss_status = item.gnss_status if hasattr(item, "gnss_status") else item.get("gnss_status")

        # Resolve registered position
        reg_lat = None
        reg_lon = None
        if node_id in registered_positions:
            pos = registered_positions[node_id]
            if isinstance(pos, Mapping):
                reg_lat = pos.get("latitude", pos.get("registered_latitude", pos.get("lat")))
                reg_lon = pos.get("longitude", pos.get("registered_longitude", pos.get("lon")))
            elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
                reg_lat, reg_lon = pos[0], pos[1]
        elif hasattr(item, "registered_latitude") and getattr(item, "registered_latitude") is not None:
            reg_lat = getattr(item, "registered_latitude")
            reg_lon = getattr(item, "registered_longitude", None)
        elif isinstance(item, Mapping):
            reg_lat = item.get("registered_latitude", item.get("registered_lat", item.get("installation_lat")))
            reg_lon = item.get("registered_longitude", item.get("registered_lon", item.get("installation_lon")))

        # If tracker has no prior state for this node but history exists, replay recent history
        if tracker is None and node_id in history_records and node_id not in local_tracker._states:
            prior_records = history_records[node_id]
            for prior in prior_records:
                p_lat = prior.latitude if hasattr(prior, "latitude") else prior.get("latitude", prior.get("lat"))
                p_lon = prior.longitude if hasattr(prior, "longitude") else prior.get("longitude", prior.get("lon"))
                p_gnss = prior.gnss_status if hasattr(prior, "gnss_status") else prior.get("gnss_status")
                local_tracker.update_node(node_id, p_lat, p_lon, reg_lat, reg_lon, p_gnss)

        node_result = local_tracker.update_node(node_id, curr_lat, curr_lon, reg_lat, reg_lon, gnss_status)
        results.append(node_result)

    affected = tuple(r.node_id for r in results if r.alert)
    overall_alert = bool(affected)

    if any(r.status == STATUS_THEFT_SUSPECTED for r in results):
        overall_status = STATUS_THEFT_SUSPECTED
    elif any(r.status == STATUS_MOVEMENT_SUSPECTED for r in results):
        overall_status = STATUS_MOVEMENT_SUSPECTED
    elif any(r.status == STATUS_NORMAL for r in results):
        overall_status = STATUS_NORMAL
    else:
        overall_status = STATUS_GPS_UNAVAILABLE

    return AntiTheftSummary(
        alert=overall_alert,
        status=overall_status,
        affected_node_ids=affected,
        events=tuple(results),
    )
