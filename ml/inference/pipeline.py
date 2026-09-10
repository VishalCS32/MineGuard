"""End-to-end ML inference over decoded MineGuard telemetry."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from data.telemetry import NodeTelemetry
from features.engineering import build_features
from models.estimators import (
    MINIMUM_HISTORY_HOURS, MINIMUM_PRIOR_OBSERVATIONS, AnomalyResult, DeformationState,
    anomaly_for_node, classify_progression, forecast, has_sufficient_history,
    health_for_node,
)
from training.anomaly import load_anomaly_artifact

from math import hypot
import numpy as np

MODEL_VERSION = "mineguard-anomaly-iforest-v2"
BASELINE_MODEL_VERSION = "mineguard-ml-baseline-0.1"
ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "anomaly"


def compute_node_baseline(history_records: Sequence[Any]) -> tuple[float, float]:
    """Compute robust baseline tilt and MAD dispersion from eligible historical observations."""
    if not history_records:
        return 0.0, 0.015

    eligible = []
    for rec in history_records:
        tilt = rec.tilt_deg if hasattr(rec, "tilt_deg") else rec.get("pitch_deg", rec.get("tilt_deg", 0.0))
        bat = rec.battery_mv if hasattr(rec, "battery_mv") else rec.get("battery_mv", 3900.0)
        flags = rec.flags if hasattr(rec, "flags") else rec.get("flags", 0)
        if bat >= 3300.0 and flags == 0 and float(tilt) < 45.0:
            eligible.append(float(tilt))

    if not eligible:
        return 0.0, 0.015

    baseline = float(np.median(eligible))
    devs = [abs(x - baseline) for x in eligible]
    mad = float(np.median(devs)) if devs else 0.010
    mad = max(0.005, mad)

    # Freezing rule: during suspected deformation, freeze baseline to pre-event median
    if len(eligible) >= 6:
        initial_median = float(np.median(eligible[:max(3, len(eligible) // 2)]))
        pre_event = [x for x in eligible if (x - initial_median) < 0.08]
        if len(pre_event) >= 3:
            baseline = float(np.median(pre_event))

    return baseline, mad


def predict(current: Sequence[Mapping[str, Any]],
            history: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
            derived: Mapping[str, Mapping[str, float]] | None = None,
            *, warning_tilt_deg: float = 0.5,
            critical_tilt_deg: float = 1.0) -> dict[str, Any]:
    """Return a serializable prediction from current and prior telemetry.

    ``history`` is caller-supplied past data. No simulator classes, scenario
    labels, or future values are consulted.
    """
    nodes = tuple(NodeTelemetry.from_mapping(item) for item in current)
    history_records = {
        node_id: tuple(NodeTelemetry.from_mapping(item) for item in records)
        for node_id, records in (history or {}).items()
    }
    frame = build_features(nodes, history_records, anomaly_tilt_deg=warning_tilt_deg)
    is_ood, ood_warnings = _check_data_quality(frame)
    node_outputs: list[dict[str, Any]] = []
    all_health = []
    anomaly_scores = []
    # Precompute robust baseline and noise scale per node from eligible history
    node_baselines = {}
    for n in nodes:
        b, m = compute_node_baseline(history_records.get(n.node_id, ()))
        node_baselines[n.node_id] = (b, m)

    # Spatial co-movement tracking: nodes showing baseline-relative displacement
    elevated_node_ids = set()
    for item in frame.nodes:
        b, _ = node_baselines.get(item.node_id, (0.0, 0.015))
        delta = item.tilt_deg - b
        rate = item.robust_tilt_rate_deg_per_hour or 0.0
        if (delta >= 0.05 and rate >= 0.005) or item.tilt_deg >= warning_tilt_deg:
            elevated_node_ids.add(item.node_id)
    node_coords = {n.node_id: (n.x_m, n.y_m) for n in nodes}
    newest_timestamp = max((item.timestamp for item in nodes), default=None)

    for item in frame.nodes:
        sufficient = has_sufficient_history(item)
        anomaly = anomaly_for_node(item, tilt_limit_deg=warning_tilt_deg)
        trained = _trained_anomaly(item.node_id, nodes, history_records, item)
        if trained is not None and sufficient:
            anomaly = trained
        stale = (newest_timestamp is not None
                 and newest_timestamp - next(node.timestamp for node in nodes
                                             if node.node_id == item.node_id) > timedelta(hours=1))
        health = health_for_node(item, stale=stale)
        if (health.status.value in {"FAULTY", "SENSOR_FAULT"} and item.tilt_deg < warning_tilt_deg
                and (item.robust_tilt_rate_deg_per_hour or 0.0) < 0.05
                and item.vibration_rms_mg < 2 * 500):
            anomaly = AnomalyResult(0.0, False, "NORMAL", "SENSOR_HEALTH")

        # Multi-signal physical confirmation with node-specific baseline
        robust_rate = item.robust_tilt_rate_deg_per_hour or 0.0
        tilt = item.tilt_deg
        b, mad = node_baselines.get(item.node_id, (0.0, 0.015))
        delta_tilt = tilt - b

        # Spatial support: neighbor within 100m also elevated, or existing frame spatial consistency
        spatial_support = False
        pos_self = node_coords.get(item.node_id)
        if pos_self and pos_self[0] is not None:
            for other_id in elevated_node_ids:
                if other_id != item.node_id:
                    pos_other = node_coords.get(other_id)
                    if (pos_other and pos_other[0] is not None
                            and hypot(pos_self[0] - pos_other[0], pos_self[1] - pos_other[1]) <= 100.0):
                        spatial_support = True
                        break
        if not spatial_support and (frame.spatial_consistency >= 0.5 and len(frame.affected_node_ids) > 1):
            spatial_support = True

        prior_records = history_records.get(item.node_id, ())
        has_prior_elevation = False
        if len(prior_records) >= 1:
            prev = prior_records[-1]
            prev_tilt = float(prev.tilt_deg)
            has_prior_elevation = (prev_tilt - b) >= 0.04 or prev_tilt >= 0.10

        temporal_support = (has_prior_elevation or robust_rate >= 0.015
                            or (robust_rate >= 0.010 and delta_tilt >= 0.06))

        physics_support = False
        if derived and item.node_id in derived:
            d_item = derived[item.node_id]
            if "observed" in d_item and "expected" in d_item and d_item["expected"] is not None:
                res = abs(float(d_item["observed"]) - float(d_item["expected"]))
                if res <= 10.0 or res <= 0.2:
                    physics_support = True

        evidence_dict = {
            "temporal": bool(temporal_support),
            "spatial": bool(spatial_support),
            "physics": bool(physics_support),
        }

        # Directional & Operational Regime separation
        is_cooling_or_settling = (robust_rate < -0.010 and delta_tilt <= 0.05 and tilt < 0.15)
        is_vibration_only = (item.vibration_rms_mg >= 30.0 and delta_tilt < 0.05 and robust_rate < 0.012 and tilt < 0.15)

        node_ood, node_ood_warnings = _check_node_quality(item)
        is_sensor_fault = health.status.value in {"FAULTY", "SENSOR_FAULT"}
        health_status_str = "SENSOR_FAULT" if is_sensor_fault else ("STALE_DATA" if stale else health.status.value)

        if not sufficient:
            deformation_status = "INSUFFICIENT_HISTORY"
            confirmed_physical = False
            evidence_status = "INSUFFICIENT_HISTORY"
        elif is_sensor_fault:
            deformation_status = "SUPPRESSED"
            confirmed_physical = False
            evidence_status = "SENSOR_FAULT"
        elif stale:
            deformation_status = "STALE_DATA"
            confirmed_physical = False
            evidence_status = "STALE_DATA"
        elif node_ood:
            deformation_status = "OOD_LOW_CONFIDENCE"
            confirmed_physical = False
            evidence_status = "SUSPECT"
        elif is_cooling_or_settling:
            deformation_status = "NORMAL"
            confirmed_physical = False
            evidence_status = "COOLING_NORMAL"
        elif is_vibration_only:
            deformation_status = "NORMAL"
            confirmed_physical = False
            evidence_status = "OPERATIONAL_VIBRATION"
        elif anomaly.detected:
            # Conservative Level 3 Corroboration:
            # Distinguishes genuine physical subsidence from thermal drift,
            # resting offsets, and operational disturbances.
            is_corroborated = (
                (temporal_support and (delta_tilt >= 0.06 or tilt >= 0.12))
                or (spatial_support and (delta_tilt >= 0.05 or tilt >= 0.10))
                or (physics_support and (temporal_support or spatial_support or delta_tilt >= 0.06))
                or (delta_tilt >= 0.25 or tilt >= 0.35)
            )
            if is_corroborated:
                deformation_status = "CONFIRMED_PHYSICAL"
                confirmed_physical = True
                evidence_status = "CONFIRMED_PHYSICAL"
            else:
                deformation_status = "UNCONFIRMED_ANOMALY"
                confirmed_physical = False
                evidence_status = "UNCONFIRMED_SPIKE"
        else:
            deformation_status = "NORMAL"
            confirmed_physical = False
            evidence_status = "NORMAL"

        # Threshold prediction (Resolving the Null Problem)
        if not sufficient:
            w_hours = None
            c_hours = None
            w_status = "INSUFFICIENT_HISTORY"
            c_status = "INSUFFICIENT_HISTORY"
        elif is_sensor_fault or stale or node_ood:
            w_hours = None
            c_hours = None
            w_status = "LOW_CONFIDENCE"
            c_status = "LOW_CONFIDENCE"
        else:
            # Warning threshold logic
            if tilt >= warning_tilt_deg:
                w_hours = 0.0
                w_status = "ALREADY_EXCEEDED"
            elif robust_rate > 0.001:
                calc_w = (warning_tilt_deg - tilt) / robust_rate
                if calc_w <= 24.0:
                    w_hours = round(calc_w, 1)
                    w_status = "PREDICTED"
                else:
                    w_hours = None
                    w_status = "NOT_REACHED_IN_FORECAST"
            else:
                w_hours = None
                w_status = "NOT_REACHED_IN_FORECAST"

            # Critical threshold logic
            if tilt >= critical_tilt_deg:
                c_hours = 0.0
                c_status = "ALREADY_EXCEEDED"
            elif robust_rate > 0.001:
                calc_c = (critical_tilt_deg - tilt) / robust_rate
                if calc_c <= 24.0:
                    c_hours = round(calc_c, 1)
                    c_status = "PREDICTED"
                else:
                    c_hours = None
                    c_status = "NOT_REACHED_IN_FORECAST"
            else:
                c_hours = None
                c_status = "NOT_REACHED_IN_FORECAST"

        # Reason codes
        reason_codes: list[str] = []
        if not sufficient:
            reason_codes.append("INSUFFICIENT_HISTORY")
        if node_ood:
            reason_codes.append("OOD")
        if stale:
            reason_codes.append("STALE_TELEMETRY")
        for r in health.reasons:
            r_lower = r.lower()
            if "battery" in r_lower:
                reason_codes.append("LOW_BATTERY")
            if "communication" in r_lower or "rssi" in r_lower or "snr" in r_lower:
                reason_codes.append("POOR_RSSI")
                reason_codes.append("POOR_SNR")
            if "gnss" in r_lower:
                reason_codes.append("GNSS_LOSS")
            if "protocol" in r_lower or "flag" in r_lower:
                reason_codes.append("PROTOCOL_FAULT")
        if is_vibration_only:
            reason_codes.append("OPERATIONAL_VIBRATION")
        if is_cooling_or_settling:
            reason_codes.append("THERMAL_COOLING")
        if anomaly.detected:
            reason_codes.append("ANOMALY_DETECTED")
            if temporal_support:
                reason_codes.append("TEMPORAL_PERSISTENCE")
            if robust_rate >= 0.015:
                reason_codes.append("SUSTAINED_DEFORMATION_RATE")
            if spatial_support:
                reason_codes.append("SPATIAL_CORROBORATION")
            if physics_support:
                reason_codes.append("PHYSICS_CONSISTENT")
            if deformation_status == "UNCONFIRMED_ANOMALY":
                reason_codes.append("UNCONFIRMED_SPIKE")
        if deformation_status == "CONFIRMED_PHYSICAL":
            reason_codes.append("CONFIRMED_PHYSICAL_DEFORMATION")
        if tilt >= warning_tilt_deg:
            reason_codes.append("THRESHOLD_ALREADY_EXCEEDED")
        elif w_status == "PREDICTED":
            reason_codes.append("TILT_THRESHOLD_APPROACH")
        elif w_status == "NOT_REACHED_IN_FORECAST":
            reason_codes.append("NOT_REACHED_IN_FORECAST")
        reason_codes = list(dict.fromkeys(reason_codes))

        # Node Forecast
        if sufficient:
            fc_points = forecast(item)
            node_fc = {}
            for pt in fc_points:
                node_fc[f"{pt.horizon_hours}h"] = {"tilt_deg": pt.tilt_deg}
                node_fc[str(pt.horizon_hours)] = {"tilt_deg": pt.tilt_deg}
        else:
            node_fc = None

        node_tilt_ratio = min(1.0, tilt / critical_tilt_deg)
        node_risk_score = round(min(1.0, max(0.0, 0.5 * node_tilt_ratio + 0.35 * anomaly.score + (0.15 if spatial_support else 0.0)) * (0.5 if node_ood else 1.0)), 3)
        node_conf = round(min(1.0, (item.history_count / 6.0) * 0.4 + (health.score * 0.4) + (0.2 if not node_ood else 0.0)), 3) if sufficient else 0.0

        all_health.append(health)
        anomaly_scores.append(anomaly.score)

        node_outputs.append({
            "node_id": item.node_id,
            "health": {
                "status": health_status_str,
                "score": health.score,
                "confidence": health.score,
                "reasons": list(health.reasons),
            },
            "anomaly": {
                "detected": anomaly.detected,
                "score": anomaly.score,
                "severity": anomaly.severity,
                "confirmed_physical": confirmed_physical,
                "evidence_status": evidence_status,
            },
            "deformation": {
                "status": deformation_status,
                "tilt_deg": round(tilt, 4),
                "tilt_rate_deg_per_hour": round(robust_rate, 4),
                "evidence": evidence_dict,
            },
            "risk": {
                "score": node_risk_score,
                "level": _severity(node_risk_score),
            },
            "forecast": node_fc,
            "threshold_prediction": {
                "warning_threshold_deg": warning_tilt_deg,
                "critical_threshold_deg": critical_tilt_deg,
                "warning_hours": w_hours,
                "critical_hours": c_hours,
                "warning_status": w_status,
                "critical_status": c_status,
            },
            "confidence": node_conf,
            "data_sufficiency": {
                "status": "READY" if sufficient else "INSUFFICIENT_HISTORY",
                "required_prior_observations": MINIMUM_PRIOR_OBSERVATIONS,
                "available_prior_observations": max(0, item.history_count - 1),
                "required_history_hours": MINIMUM_HISTORY_HOURS,
                "available_history_hours": item.temporal_span_hours,
            },
            "reason_codes": reason_codes,
        })

    progression = classify_progression(frame.nodes)
    sufficient = bool(frame.nodes) and all(has_sufficient_history(item) for item in frame.nodes)
    risk_score = _risk_score(frame, anomaly_scores, all_health, critical_tilt_deg) if sufficient else 0.0
    confidence = _confidence(frame, all_health, is_ood) if sufficient else 0.0
    factors = _factors(frame, progression, all_health)
    if is_ood:
        factors.append("Out-of-distribution telemetry observed; model confidence is reduced.")

    # Array-level aggregation
    any_confirmed = any(n["deformation"]["status"] == "CONFIRMED_PHYSICAL" for n in node_outputs)
    any_fault = any(n["health"]["status"] in {"SENSOR_FAULT", "FAULTY"} for n in node_outputs)
    any_insufficient = any(n["data_sufficiency"]["status"] == "INSUFFICIENT_HISTORY" for n in node_outputs)
    max_node_risk = max((n["risk"]["score"] for n in node_outputs), default=0.0)
    alarm = bool(any_confirmed or risk_score >= 0.60 or max_node_risk >= 0.60)

    if any_confirmed:
        overall_status = "CRITICAL" if risk_score >= 0.85 or any(n["risk"]["level"] == "CRITICAL" for n in node_outputs) else "WARNING"
        alarm_reason = "CONFIRMED_PHYSICAL_DEFORMATION"
    elif risk_score >= 0.60:
        overall_status = "WARNING"
        alarm_reason = "HIGH_RISK_SUBSIDENCE"
    elif any_fault:
        overall_status = "SENSOR_FAULT"
        alarm_reason = "SENSOR_HEALTH_DEGRADED"
    elif any_insufficient:
        overall_status = "INSUFFICIENT_HISTORY"
        alarm_reason = "NONE"
    else:
        overall_status = "NORMAL"
        alarm_reason = "NONE"

    # Overall threshold prediction
    valid_w_hours = [n["threshold_prediction"]["warning_hours"] for n in node_outputs if n["threshold_prediction"]["warning_hours"] is not None]
    valid_c_hours = [n["threshold_prediction"]["critical_hours"] for n in node_outputs if n["threshold_prediction"]["critical_hours"] is not None]
    top_w_hours = min(valid_w_hours) if valid_w_hours else None
    top_c_hours = min(valid_c_hours) if valid_c_hours else None

    if any(n["threshold_prediction"]["warning_status"] == "ALREADY_EXCEEDED" for n in node_outputs):
        top_w_status = "ALREADY_EXCEEDED"
        top_w_hours = 0.0
    elif top_w_hours is not None:
        top_w_status = "PREDICTED"
    elif not sufficient:
        top_w_status = "INSUFFICIENT_HISTORY"
    elif is_ood:
        top_w_status = "LOW_CONFIDENCE"
    else:
        top_w_status = "NOT_REACHED_IN_FORECAST"

    if any(n["threshold_prediction"]["critical_status"] == "ALREADY_EXCEEDED" for n in node_outputs):
        top_c_status = "ALREADY_EXCEEDED"
        top_c_hours = 0.0
    elif top_c_hours is not None:
        top_c_status = "PREDICTED"
    elif not sufficient:
        top_c_status = "INSUFFICIENT_HISTORY"
    elif is_ood:
        top_c_status = "LOW_CONFIDENCE"
    else:
        top_c_status = "NOT_REACHED_IN_FORECAST"

    overall = {
        "status": overall_status,
        "risk_level": _severity(risk_score),
        "risk_score": round(risk_score, 3),
        "alarm": alarm,
        "alarm_reason": alarm_reason,
        "threshold_prediction": {
            "warning_threshold_deg": warning_tilt_deg,
            "critical_threshold_deg": critical_tilt_deg,
            "warning_hours": top_w_hours,
            "critical_hours": top_c_hours,
            "warning_status": top_w_status,
            "critical_status": top_c_status,
        },
    }

    top_time_to_threshold = {
        "warning_hours": top_w_hours,
        "critical_hours": top_c_hours,
        "warning_status": top_w_status,
        "critical_status": top_c_status,
    }

    loaded_artifact = _load_trained_anomaly()
    ts_str = newest_timestamp.isoformat() if newest_timestamp else datetime.now(timezone.utc).isoformat()

    return {
        "timestamp": ts_str,
        "model_version": (MODEL_VERSION if loaded_artifact is not None
                   else BASELINE_MODEL_VERSION),
        "overall": overall,
        "data_sufficiency": {
            "status": "READY" if sufficient else "INSUFFICIENT_HISTORY",
            "required_prior_observations": MINIMUM_PRIOR_OBSERVATIONS,
            "available_prior_observations": min(
                (item.history_count - 1 for item in frame.nodes), default=0),
            "required_history_hours": MINIMUM_HISTORY_HOURS,
            "available_history_hours": min(
                (item.temporal_span_hours for item in frame.nodes), default=0.0),
        },
        "data_quality": {
            "status": "DEGRADED" if is_ood else "NORMAL",
            "out_of_distribution": is_ood,
            "warnings": ood_warnings,
        },
        "risk": {"score": risk_score, "severity": _severity(risk_score),
                 "confidence": confidence},
        "anomaly": {
            "detected": (False if not sufficient else
                         any(anomaly_scores[i] >= 0.6 for i in range(len(anomaly_scores)))),
            "score": max(anomaly_scores, default=0.0),
            "severity": ("INSUFFICIENT_HISTORY" if not sufficient else
                         _severity(max(anomaly_scores, default=0.0))),
            "confirmed_physical": (False if not sufficient else
                                  any(n["anomaly"]["confirmed_physical"] for n in node_outputs)),
            "evidence_status": (
                "CONFIRMED_PHYSICAL" if any(n["anomaly"]["confirmed_physical"] for n in node_outputs)
                else "UNCONFIRMED_SPIKE" if any(n["anomaly"]["evidence_status"] == "UNCONFIRMED_SPIKE" for n in node_outputs)
                else "SENSOR_FAULT" if any(n["anomaly"]["evidence_status"] == "SENSOR_FAULT" for n in node_outputs)
                else "SUSPECT" if any(n["anomaly"]["evidence_status"] == "SUSPECT" for n in node_outputs)
                else "NORMAL"
            ) if sufficient else "INSUFFICIENT_HISTORY",
        },
        "deformation_state": progression.value,
        "forecast": ({str(hour): {"tilt_deg": _aggregate_forecast(frame, hour)}
                  for hour in (1, 6, 12, 24)} if sufficient else None),
        "time_to_threshold": top_time_to_threshold,
        "spatial": {"affected_nodes": list(frame.affected_node_ids),
                     "spreading": frame.spatial_consistency >= 0.5 and len(frame.affected_node_ids) > 1,
                     "consistency": frame.spatial_consistency},
        "physics": _physics_result(derived),
        "sensor_health": {
            "healthy_nodes": sum(health.status.value == "HEALTHY" for health in all_health),
            "suspect_nodes": [health.node_id for health in all_health if health.status.value == "SUSPECT"],
            "faulty_nodes": [health.node_id for health in all_health if health.status.value in {"FAULTY", "SENSOR_FAULT"}],
        },
        "nodes": node_outputs,
        "dominant_factors": factors,
        "explanation": " ".join(factors) if factors else "No significant deformation evidence is available.",
    }


def _risk_score(frame, anomaly_scores, health, critical_tilt: float) -> float:
    tilt = max((item.tilt_deg / critical_tilt for item in frame.nodes), default=0.0)
    anomaly = max(anomaly_scores, default=0.0)
    spatial = 0.25 if frame.spatial_consistency >= 0.5 and len(frame.affected_node_ids) > 1 else 0.0
    healthy_fraction = (sum(item.status.value == "HEALTHY" for item in health) / len(health)
                        if health else 0.0)
    return min(1.0, max(0.0, 0.45 * tilt + 0.35 * anomaly + spatial) * (0.75 + 0.25 * healthy_fraction))


def _severity(score: float) -> str:
    return "CRITICAL" if score >= 0.85 else "HIGH" if score >= 0.6 else "MEDIUM" if score >= 0.35 else "LOW"


def _lead_times(frame, warning: float, critical: float) -> tuple[float | None, float | None]:
    rates = [item.robust_tilt_rate_deg_per_hour for item in frame.nodes]
    positive = [rate for rate in rates if rate and rate > 0]
    if not positive:
        return None, None
    rate = max(positive)
    current = max((item.tilt_deg for item in frame.nodes), default=0.0)
    return (max(0.0, (warning - current) / rate) if current < warning else 0.0,
            max(0.0, (critical - current) / rate) if current < critical else 0.0)


def _check_node_quality(item) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if item.tilt_deg > 75.0:
        warnings.append(f"Node {item.node_id} tilt ({item.tilt_deg:.1f} deg) exceeds physical operational bounds.")
    if item.temperature_c < -25.0 or item.temperature_c > 75.0:
        warnings.append(f"Node {item.node_id} temperature ({item.temperature_c:.1f} C) is out of expected mine range.")
    if item.battery_mv < 2400 or item.battery_mv > 4600:
        warnings.append(f"Node {item.node_id} battery voltage ({item.battery_mv:.0f} mV) is out of nominal bounds.")
    if item.tilt_acceleration_deg_per_hour2 is not None and abs(item.tilt_acceleration_deg_per_hour2) > 10.0:
        warnings.append(f"Node {item.node_id} shows extreme acceleration ({item.tilt_acceleration_deg_per_hour2:.2f} deg/h^2).")
    return bool(warnings), warnings


def _check_data_quality(frame) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    for item in frame.nodes:
        _, item_warnings = _check_node_quality(item)
        warnings.extend(item_warnings)
    return bool(warnings), warnings


def _confidence(frame, health, ood_detected: bool = False) -> float:
    if not frame.nodes:
        return 0.0
    history = min(1.0, mean(item.history_count for item in frame.nodes) / 6.0)
    health_score = mean(item.score for item in health) if health else 0.0
    spatial = frame.spatial_consistency
    base = round(0.4 * history + 0.35 * health_score + 0.25 * spatial, 3)
    if ood_detected:
        base = round(base * 0.5, 3)
    return base


def _factors(frame, progression: DeformationState, health) -> list[str]:
    factors: list[str] = []
    if progression == DeformationState.INSUFFICIENT_HISTORY:
        factors.append("Prediction confidence is reduced because sensor history is insufficient.")
    if progression in (DeformationState.ACCELERATING, DeformationState.RAPID_DEFORMATION):
        factors.append("Tilt rate is increasing or elevated.")
    if len(frame.affected_node_ids) > 1 and frame.spatial_consistency >= 0.5:
        factors.append("Multiple neighbouring nodes show consistent deformation.")
    if any(item.status.value != "HEALTHY" for item in health):
        factors.append("One or more sensor-health indicators reduce confidence.")
    return factors


def _physics_residual(derived) -> float | None:
    if not derived:
        return None
    residuals: list[float] = []
    for item in derived.values():
        if "observed" in item and "expected" in item and item["expected"] is not None:
            obs = float(item["observed"])
            exp = float(item["expected"])
            if 0.0 <= obs <= 1.0 and 0.0 <= exp <= 1.0:
                residuals.append(abs(obs - exp))
            else:
                # Millimeter scale: scale error relative to 100.0 mm reference scale
                residuals.append(abs(obs - exp) / 100.0)
    return min(1.0, sum(residuals) / len(residuals)) if residuals else None


def _physics_result(derived) -> dict[str, Any]:
    residual = _physics_residual(derived)
    if residual is None:
        return {
            "residual_score": None,
            "status": "UNAVAILABLE",
            "explanation": "Knothe expected deformation was not supplied by the backend.",
        }
    return {
        "residual_score": residual,
        "status": "AVAILABLE",
        "explanation": "Observed deformation was compared with the supplied physics expectation.",
    }


def _aggregate_forecast(frame, hour: int) -> float | None:
    values: list[float] = []
    for item in frame.nodes:
        point = next(point for point in forecast(item, (hour,)))
        if point.tilt_deg is not None:
            values.append(point.tilt_deg)
    return max(values) if values else None


def sufficient_history_for_item(item) -> bool:
    return has_sufficient_history(item)


@lru_cache(maxsize=1)
def _load_trained_anomaly():
    try:
        return load_anomaly_artifact(ARTIFACT_DIR)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _trained_anomaly(node_id, nodes, history_records, item):
    loaded = _load_trained_anomaly()
    if loaded is None:
        return None
    bundle, metadata = loaded
    if item.history_count < int(metadata.get("minimum_history_count", 0)):
        return None
    current = next(node for node in nodes if node.node_id == node_id)
    from training.anomaly import FeatureEncoder
    encoder = FeatureEncoder()
    vector = encoder.transform(
        _record_from_node(current),
        [_record_from_node(item) for item in history_records.get(node_id, ())])
    raw_score = -float(bundle["model"].decision_function(vector)[0])
    threshold = float(bundle["threshold"])
    upper = float(bundle.get("score_upper", threshold + 1e-6))
    score = max(0.0, min(1.0, (raw_score - threshold) / max(upper - threshold, 1e-6)))
    severity = "CRITICAL" if score >= 0.85 else "ANOMALOUS" if score >= 0.6 else "UNUSUAL" if score >= 0.35 else "NORMAL"
    from models.estimators import AnomalyResult
    return AnomalyResult(score, score >= 0.6, severity, "TRAINED")


def _record_from_node(node):
    return {
        "node_id": node.node_id, "timestamp": node.timestamp.isoformat(),
        "pitch_deg": node.pitch_deg, "roll_deg": node.roll_deg,
        "vibration_rms_mg": node.vibration_rms_mg,
        "vibration_peak_hz": node.vibration_peak_hz,
        "temperature_c": node.temperature_c, "n_samples": node.n_samples,
        "gnss_status": node.gnss_status, "battery_mv": node.battery_mv,
        "rssi_dbm": node.rssi_dbm, "snr_db": node.snr_db,
        "flags": node.flags, "x_m": node.x_m, "y_m": node.y_m,
    }


def mean(values):
    values = tuple(values)
    return sum(values) / len(values) if values else 0.0
