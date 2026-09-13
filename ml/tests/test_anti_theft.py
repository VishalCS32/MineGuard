"""Tests for MineGuard Hardware Anti-Theft / Movement Detection.

Covers all 21 mandatory test requirements:
1. Node within 10 m -> NORMAL.
2. Node exactly at approximately 10 m -> movement threshold behavior.
3. One reading beyond 10 m -> MOVEMENT_SUSPECTED, alert false.
4. Two consecutive readings beyond 10 m -> MOVEMENT_SUSPECTED, alert false.
5. Three consecutive readings beyond 10 m -> THEFT_SUSPECTED, alert true.
6. Movement returns below threshold before confirmation -> confirmation resets appropriately.
7. Confirmed theft persists correctly.
8. Missing GPS -> GPS_UNAVAILABLE.
9. Invalid latitude -> safe failure.
10. Invalid longitude -> safe failure.
11. No registered coordinates -> no theft alert.
12. GPS altitude changes dramatically but lat/lon remain stable -> NO theft.
13. Small GPS jitter around registered location -> no theft.
14. Different nodes maintain independent confirmation counters.
15. One node stolen while others remain normal.
16. All 21 nodes can be processed without breaking the contract.
17. Existing ML JSON fields remain present.
18. anti_theft.alert is boolean.
19. Confirmed event contains node_id and distance.
20. No simulator imports in production anti-theft module.
21. Existing production IForest feature vector remains exactly 8 features.
"""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path
from typing import Any

import pytest

try:
    from security.anti_theft import (
        ANTI_THEFT_CONFIRMATION_READINGS,
        ANTI_THEFT_RADIUS_M,
        REASON_GPS_INVALID,
        REASON_GPS_UNAVAILABLE,
        REASON_MOVED_BEYOND_THRESHOLD,
        REASON_MOVEMENT_BEYOND_THRESHOLD,
        REASON_REGISTERED_UNAVAILABLE,
        REASON_WITHIN_RADIUS,
        STATUS_GPS_UNAVAILABLE,
        STATUS_MOVEMENT_SUSPECTED,
        STATUS_NORMAL,
        STATUS_THEFT_SUSPECTED,
        AntiTheftTracker,
        evaluate_anti_theft_frame,
        haversine_distance_m,
    )
    from inference.pipeline import predict
    from data.telemetry import NodeTelemetry
    from training.anomaly import FEATURE_NAMES
except ImportError:
    from ml.security.anti_theft import (
        ANTI_THEFT_CONFIRMATION_READINGS,
        ANTI_THEFT_RADIUS_M,
        REASON_GPS_INVALID,
        REASON_GPS_UNAVAILABLE,
        REASON_MOVED_BEYOND_THRESHOLD,
        REASON_MOVEMENT_BEYOND_THRESHOLD,
        REASON_REGISTERED_UNAVAILABLE,
        REASON_WITHIN_RADIUS,
        STATUS_GPS_UNAVAILABLE,
        STATUS_MOVEMENT_SUSPECTED,
        STATUS_NORMAL,
        STATUS_THEFT_SUSPECTED,
        AntiTheftTracker,
        evaluate_anti_theft_frame,
        haversine_distance_m,
    )
    from ml.inference.pipeline import predict
    from ml.data.telemetry import NodeTelemetry
    from ml.training.anomaly import FEATURE_NAMES


# Base reference coordinates: Mine Site A (Jharia Coalfield reference)
BASE_LAT = 23.750000
BASE_LON = 86.420000

# 1 degree of latitude is ~111,195 m.
# 10 metres in latitude ~ 10 / 111195 ~ 0.00008993 degrees
METRES_TO_LAT_DEG = 1.0 / 111195.0


def _offset_lat(lat: float, dist_m: float) -> float:
    """Offset latitude north by dist_m metres."""
    return lat + (dist_m * METRES_TO_LAT_DEG)


# 1. Node within 10 m -> NORMAL
def test_node_within_10m_normal():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # 5 metres offset
    lat_5m = _offset_lat(BASE_LAT, 5.0)
    res = tracker.update_node("N01", lat_5m, BASE_LON, BASE_LAT, BASE_LON)

    assert res.status == STATUS_NORMAL
    assert res.alert is False
    assert res.confirmed is False
    assert res.distance_from_registered_m is not None
    assert 4.9 <= res.distance_from_registered_m <= 5.1
    assert res.confirmation_count == 0
    assert res.reason_code == REASON_WITHIN_RADIUS


# 2. Node exactly at approximately 10 m -> movement threshold behavior
def test_node_at_threshold_boundary():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # Exactly 10.0m offset
    lat_10m = _offset_lat(BASE_LAT, 10.0)
    res = tracker.update_node("N01", lat_10m, BASE_LON, BASE_LAT, BASE_LON)

    # At or above 10.0 m triggers initial suspected movement
    assert res.status == STATUS_MOVEMENT_SUSPECTED
    assert res.alert is False
    assert res.confirmed is False
    assert res.confirmation_count == 1
    assert res.threshold_m == 10.0
    assert res.reason_code == REASON_MOVEMENT_BEYOND_THRESHOLD


# 3. One reading beyond 10 m -> MOVEMENT_SUSPECTED, alert false
def test_one_reading_beyond_10m():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_12m = _offset_lat(BASE_LAT, 12.3)
    res = tracker.update_node("N01", lat_12m, BASE_LON, BASE_LAT, BASE_LON)

    assert res.status == STATUS_MOVEMENT_SUSPECTED
    assert res.alert is False
    assert res.confirmed is False
    assert res.confirmation_count == 1
    assert res.reason_code == REASON_MOVEMENT_BEYOND_THRESHOLD


# 4. Two consecutive readings beyond 10 m -> MOVEMENT_SUSPECTED, alert false
def test_two_consecutive_readings_beyond_10m():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_11m = _offset_lat(BASE_LAT, 11.2)
    lat_12m = _offset_lat(BASE_LAT, 12.0)

    res1 = tracker.update_node("N01", lat_11m, BASE_LON, BASE_LAT, BASE_LON)
    assert res1.status == STATUS_MOVEMENT_SUSPECTED
    assert res1.alert is False
    assert res1.confirmation_count == 1

    res2 = tracker.update_node("N01", lat_12m, BASE_LON, BASE_LAT, BASE_LON)
    assert res2.status == STATUS_MOVEMENT_SUSPECTED
    assert res2.alert is False
    assert res2.confirmed is False
    assert res2.confirmation_count == 2
    assert res2.reason_code == REASON_MOVEMENT_BEYOND_THRESHOLD


# 5. Three consecutive readings beyond 10 m -> THEFT_SUSPECTED, alert true
def test_three_consecutive_readings_confirmed_theft():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_11m = _offset_lat(BASE_LAT, 11.2)
    lat_12m = _offset_lat(BASE_LAT, 12.0)
    lat_15m = _offset_lat(BASE_LAT, 14.7)

    tracker.update_node("N01", lat_11m, BASE_LON, BASE_LAT, BASE_LON)
    tracker.update_node("N01", lat_12m, BASE_LON, BASE_LAT, BASE_LON)
    res3 = tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)

    assert res3.status == STATUS_THEFT_SUSPECTED
    assert res3.alert is True
    assert res3.confirmed is True
    assert res3.confirmation_count >= 3
    assert res3.reason_code == REASON_MOVED_BEYOND_THRESHOLD
    assert res3.distance_from_registered_m is not None
    assert round(res3.distance_from_registered_m, 1) == 14.7


# 6. Movement returns below threshold before confirmation -> confirmation resets appropriately
def test_movement_returns_below_threshold_resets_counter():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_12m = _offset_lat(BASE_LAT, 12.0)
    lat_2m = _offset_lat(BASE_LAT, 2.0)

    # Reading 1: beyond 10m -> count=1
    r1 = tracker.update_node("N01", lat_12m, BASE_LON, BASE_LAT, BASE_LON)
    assert r1.confirmation_count == 1

    # Reading 2: beyond 10m -> count=2
    r2 = tracker.update_node("N01", lat_12m, BASE_LON, BASE_LAT, BASE_LON)
    assert r2.confirmation_count == 2

    # Reading 3: back within radius -> count resets to 0, status NORMAL
    r3 = tracker.update_node("N01", lat_2m, BASE_LON, BASE_LAT, BASE_LON)
    assert r3.status == STATUS_NORMAL
    assert r3.alert is False
    assert r3.confirmed is False
    assert r3.confirmation_count == 0
    assert r3.reason_code == REASON_WITHIN_RADIUS

    # Next reading beyond 10m starts over at 1
    r4 = tracker.update_node("N01", lat_12m, BASE_LON, BASE_LAT, BASE_LON)
    assert r4.confirmation_count == 1
    assert r4.alert is False


# 7. Confirmed theft persists correctly
def test_confirmed_theft_persists():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_15m = _offset_lat(BASE_LAT, 15.0)

    # 3 consecutive readings confirm theft
    for _ in range(3):
        res = tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert res.confirmed is True
    assert res.alert is True

    # Subsequent readings beyond threshold continue to maintain confirmed theft alert
    res_next = tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert res_next.status == STATUS_THEFT_SUSPECTED
    assert res_next.alert is True
    assert res_next.confirmed is True

    # Tracker reset clears confirmed state cleanly
    tracker.reset("N01")
    res_after_reset = tracker.update_node("N01", _offset_lat(BASE_LAT, 2.0), BASE_LON, BASE_LAT, BASE_LON)
    assert res_after_reset.status == STATUS_NORMAL
    assert res_after_reset.alert is False
    assert res_after_reset.confirmed is False


# 8. Missing GPS -> GPS_UNAVAILABLE
def test_missing_gps_coordinates():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)

    # None latitude
    res1 = tracker.update_node("N01", None, BASE_LON, BASE_LAT, BASE_LON)
    assert res1.status == STATUS_GPS_UNAVAILABLE
    assert res1.alert is False
    assert res1.confirmed is False
    assert res1.distance_from_registered_m is None
    assert res1.reason_code == REASON_GPS_UNAVAILABLE

    # None longitude
    res2 = tracker.update_node("N01", BASE_LAT, None, BASE_LAT, BASE_LON)
    assert res2.status == STATUS_GPS_UNAVAILABLE
    assert res2.alert is False
    assert res2.reason_code == REASON_GPS_UNAVAILABLE


# 9. Invalid latitude -> safe failure
def test_invalid_latitude_safe_failure():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # Latitude > 90
    res = tracker.update_node("N01", 95.0, BASE_LON, BASE_LAT, BASE_LON)
    assert res.status == STATUS_GPS_UNAVAILABLE
    assert res.alert is False
    assert res.confirmed is False
    assert res.distance_from_registered_m is None
    assert res.reason_code == REASON_GPS_INVALID


# 10. Invalid longitude -> safe failure
def test_invalid_longitude_safe_failure():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # Longitude < -180
    res = tracker.update_node("N01", BASE_LAT, -195.0, BASE_LAT, BASE_LON)
    assert res.status == STATUS_GPS_UNAVAILABLE
    assert res.alert is False
    assert res.confirmed is False
    assert res.distance_from_registered_m is None
    assert res.reason_code == REASON_GPS_INVALID


# 11. No registered coordinates -> no theft alert
def test_no_registered_coordinates_safe_failure():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    res = tracker.update_node("N01", BASE_LAT, BASE_LON, None, None)
    assert res.status == STATUS_GPS_UNAVAILABLE
    assert res.alert is False
    assert res.confirmed is False
    assert res.distance_from_registered_m is None
    assert res.reason_code == REASON_REGISTERED_UNAVAILABLE


# 12. GPS altitude changes dramatically but lat/lon remain stable -> NO theft
def test_altitude_changes_do_not_trigger_theft():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # Anti-theft update_node strictly uses horizontal lat/lon and does not accept altitude
    # Telemetry item has large altitude delta, but lat/lon are identical to registered
    item1 = {
        "node_id": "N01",
        "latitude": BASE_LAT,
        "longitude": BASE_LON,
        "altitude": 100.0,
    }
    item2 = {
        "node_id": "N01",
        "latitude": BASE_LAT,
        "longitude": BASE_LON,
        "altitude": 5000.0,  # 4900m vertical jump
    }
    reg = {"N01": {"latitude": BASE_LAT, "longitude": BASE_LON}}

    summary1 = evaluate_anti_theft_frame([item1], registered_positions=reg, tracker=tracker)
    assert summary1.alert is False
    assert summary1.status == STATUS_NORMAL

    summary2 = evaluate_anti_theft_frame([item2], registered_positions=reg, tracker=tracker)
    assert summary2.alert is False
    assert summary2.status == STATUS_NORMAL
    assert summary2.events[0].distance_from_registered_m == 0.0


# 13. Small GPS jitter around registered location -> no theft
def test_small_gps_jitter_no_theft():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # Simulate 1m to 4m jitter around base location
    jitter_offsets = [1.2, 2.5, 3.8, 0.5, 2.1, 4.0]
    for dist in jitter_offsets:
        lat = _offset_lat(BASE_LAT, dist)
        res = tracker.update_node("N01", lat, BASE_LON, BASE_LAT, BASE_LON)
        assert res.status == STATUS_NORMAL
        assert res.alert is False
        assert res.confirmed is False
        assert res.confirmation_count == 0


# 14. Different nodes maintain independent confirmation counters
def test_independent_confirmation_counters():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_15m = _offset_lat(BASE_LAT, 15.0)

    # N01 has 2 readings beyond threshold
    tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    res_n01_2 = tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert res_n01_2.confirmation_count == 2
    assert res_n01_2.alert is False

    # N02 has only 1 reading beyond threshold
    res_n02_1 = tracker.update_node("N02", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert res_n02_1.confirmation_count == 1
    assert res_n02_1.alert is False

    # N01 gets 3rd reading -> N01 confirmed, N02 still at 1
    res_n01_3 = tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert res_n01_3.confirmed is True
    assert res_n01_3.alert is True

    # Check N02 again
    res_n02_2 = tracker.update_node("N02", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert res_n02_2.confirmed is False
    assert res_n02_2.alert is False
    assert res_n02_2.confirmation_count == 2


# 15. One node stolen while others remain normal
def test_one_node_stolen_others_normal():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    stolen_lat = _offset_lat(BASE_LAT, 35.0)  # 35m away

    nodes = [
        {"node_id": "N01", "latitude": BASE_LAT, "longitude": BASE_LON},
        {"node_id": "N02", "latitude": stolen_lat, "longitude": BASE_LON},
        {"node_id": "N03", "latitude": BASE_LAT, "longitude": BASE_LON},
    ]
    registered = {
        "N01": {"latitude": BASE_LAT, "longitude": BASE_LON},
        "N02": {"latitude": BASE_LAT, "longitude": BASE_LON},
        "N03": {"latitude": BASE_LAT, "longitude": BASE_LON},
    }

    # 3 frames to confirm theft on N02
    for _ in range(3):
        summary = evaluate_anti_theft_frame(nodes, registered_positions=registered, tracker=tracker)

    assert summary.alert is True
    assert summary.status == STATUS_THEFT_SUSPECTED
    assert summary.affected_node_ids == ("N02",)

    by_node = {e.node_id: e for e in summary.events}
    assert by_node["N01"].status == STATUS_NORMAL
    assert by_node["N01"].alert is False
    assert by_node["N02"].status == STATUS_THEFT_SUSPECTED
    assert by_node["N02"].alert is True
    assert by_node["N03"].status == STATUS_NORMAL
    assert by_node["N03"].alert is False


# 16. All 21 nodes can be processed without breaking the contract
def test_all_21_nodes_processed_cleanly():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    nodes = []
    registered = {}

    for i in range(1, 22):
        nid = f"N{i:02d}"
        nodes.append({
            "node_id": nid,
            "latitude": BASE_LAT + (i * 0.00001),
            "longitude": BASE_LON,
            "gnss_status": 3,
        })
        registered[nid] = {
            "latitude": BASE_LAT + (i * 0.00001),
            "longitude": BASE_LON,
        }

    summary = evaluate_anti_theft_frame(nodes, registered_positions=registered, tracker=tracker)
    assert len(summary.events) == 21
    assert summary.alert is False
    assert summary.status == STATUS_NORMAL
    assert len(summary.affected_node_ids) == 0

    as_dict = summary.to_dict()
    assert isinstance(as_dict["alert"], bool)
    assert as_dict["alert"] is False
    assert len(as_dict["events"]) == 21


# 17. Existing ML JSON fields remain present
def test_ml_json_pipeline_integration_preserves_fields():
    # Construct a valid NodeTelemetry item
    raw_t = {
        "node_id": "N01",
        "timestamp": "2026-09-11T12:00:00Z",
        "pitch_deg": 1.2,
        "roll_deg": 0.0,
        "vibration_rms_mg": 25.0,
        "vibration_peak_hz": 12.0,
        "temperature_c": 28.5,
        "battery_mv": 3900.0,
        "latitude": BASE_LAT,
        "longitude": BASE_LON,
        "gnss_status": 3,
    }

    out = predict([raw_t], registered_positions={"N01": {"latitude": BASE_LAT, "longitude": BASE_LON}})

    # Mandatory pipeline contract fields
    assert "overall" in out
    assert "status" in out["overall"]
    assert "timestamp" in out
    assert "nodes" in out
    assert "anti_theft" in out

    # Anti-theft top-level contract
    at = out["anti_theft"]
    assert "alert" in at
    assert isinstance(at["alert"], bool)
    assert "status" in at
    assert "affected_node_ids" in at
    assert "events" in at

    # Node-level fields preserved
    assert len(out["nodes"]) == 1
    n0 = out["nodes"][0]
    assert "node_id" in n0
    assert "anomaly" in n0
    assert "score" in n0["anomaly"]
    assert "detected" in n0["anomaly"]
    assert "health" in n0
    assert "anti_theft" in n0
    assert n0["anti_theft"]["status"] == STATUS_NORMAL
    assert n0["anti_theft"]["alert"] is False


# 18. anti_theft.alert is boolean
def test_anti_theft_alert_is_boolean():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    # Normal case
    res1 = tracker.update_node("N01", BASE_LAT, BASE_LON, BASE_LAT, BASE_LON)
    assert isinstance(res1.alert, bool)
    assert res1.alert is False

    # Thefts
    lat_15m = _offset_lat(BASE_LAT, 15.0)
    for _ in range(3):
        res2 = tracker.update_node("N01", lat_15m, BASE_LON, BASE_LAT, BASE_LON)
    assert isinstance(res2.alert, bool)
    assert res2.alert is True


# 19. Confirmed event contains node_id and distance
def test_confirmed_event_contains_node_id_and_distance():
    tracker = AntiTheftTracker(radius_m=ANTI_THEFT_RADIUS_M)
    lat_20m = _offset_lat(BASE_LAT, 20.0)

    for _ in range(3):
        res = tracker.update_node("N05", lat_20m, BASE_LON, BASE_LAT, BASE_LON)

    assert res.confirmed is True
    d = res.to_dict()
    assert d["node_id"] == "N05"
    assert d["distance_from_registered_m"] is not None
    assert 19.5 <= d["distance_from_registered_m"] <= 20.5
    assert d["threshold_m"] == 10.0
    assert d["confirmation_count"] >= 3
    assert d["reason_code"] == REASON_MOVED_BEYOND_THRESHOLD


# 20. No simulator imports in production anti-theft module
def test_no_simulator_imports_in_anti_theft():
    anti_theft_path = Path(__file__).resolve().parent.parent / "security" / "anti_theft.py"
    assert anti_theft_path.exists(), f"File {anti_theft_path} must exist"

    source = anti_theft_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "simulator" not in alias.name, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "simulator" not in module, f"Forbidden import from: {module}"


# 21. Existing production IForest feature vector remains exactly 8 features
def test_isolation_forest_features_frozen_at_8():
    expected_8_features = (
        "tilt_deg",
        "robust_tilt_rate_deg_per_hour",
        "vibration_rms_mg",
        "vibration_peak_hz",
        "temperature_c",
        "history_count",
        "temporal_span_hours",
        "temporal_std_tilt_deg",
    )
    assert FEATURE_NAMES == expected_8_features
    assert len(FEATURE_NAMES) == 8
    # Ensure no GPS fields were added to the anomaly feature vector
    for f in FEATURE_NAMES:
        assert "lat" not in f
        assert "lon" not in f
        assert "gps" not in f
