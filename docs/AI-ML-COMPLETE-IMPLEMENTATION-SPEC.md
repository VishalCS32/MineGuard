# MineGuard AI/ML Subsystem — Complete Implementation Specification

## 1. Executive Summary & Authoritative Architecture

MineGuard is an AI-enabled, low-cost real-time mine subsidence monitoring, prediction, and early-warning system designed for underground coal mines in India. 

### Authoritative Architecture Data Flow
```
REAL PHYSICAL SENSOR NODES (Tilt, Vibration, Temp, Battery, GNSS, LoRa)
        ↓
Gateway / LoRaWAN Concentrator
        ↓
Backend Ingestion (decode 22-byte frame, baseline-correct, store in PostgreSQL)
        ↓
Backend State & Deformation Reconstruction (array-level curvature/strain/subsidence)
        ↓
AI/ML Service (FastAPI POST /predict)
        ↓
Preprocessing & Telemetry Validation (NodeTelemetry)
        ↓
Feature Engineering (NodeFeatures, FeatureFrame, temporal/spatial stats)
        ↓
Anomaly Detection (Chronological Isolation Forest, calibrated threshold)
        ↓
Physics / Knothe Deformation Residual (observed vs. theoretical model)
        ↓
Forecasting (Trend-decay & persistence hybrid for 1h, 6h, 12h, 24h horizons)
        ↓
Lead-Time / Time-to-Threshold (Auditable deterministic rate extrapolation)
        ↓
Confidence, OOD & Risk Integration (Model confidence vs. physical risk)
        ↓
Backend State / Alert Engine / Operations Dashboard
```

> **CRITICAL ARCHITECTURAL BOUNDARY**: The simulator is an offline tool for synthetic data generation, physical stress testing, and scenario verification. Production ML inference strictly consumes backend-formatted telemetry representing real sensor feeds.

---

## 2. Component Inventory & Status

| Subsystem Component | Location | Implementation Status | Role & Description |
| :--- | :--- | :--- | :--- |
| **Telemetry Parsing** | `ml/data/telemetry.py` | Complete | Strong parsing of raw dicts into `NodeTelemetry` dataclasses with unit conversions and validation. |
| **Feature Engineering** | `ml/features/engineering.py` | Complete | Leakage-free temporal rates, robust slopes, accelerations, and spatial neighbour statistics. |
| **Anomaly Detection** | `ml/models/estimators.py`, `ml/training/anomaly.py` | Enhanced (Phase 4) | Isolation Forest (`mineguard-anomaly-iforest-v2`). Evaluates temporal vs spatial feature contribution. |
| **Physics Model** | `ml/simulator/physics.py`, `ml/inference/pipeline.py` | Enhanced (Phase 5) | Analytic Knothe influence function & subsidence profile. Linked to production via residual calculation. |
| **Forecasting Engine** | `ml/models/estimators.py`, `ml/inference/pipeline.py` | Enhanced (Phases 1-3) | Multi-horizon exponential rate-decay trend model + 1h persistence baseline hybrid. |
| **Time-to-Threshold** | `ml/models/estimators.py` | Complete | Auditable, deterministic linear lead-time estimation to warning (0.5°) and critical (1.0°) thresholds. |
| **Risk & Confidence** | `ml/inference/pipeline.py` | Enhanced (Phase 8) | Explicit separation between Physical Risk (Safety) and Model Confidence (Data Quality/OOD). |
| **Service API** | `ml/service/app.py` | Enhanced (Phase 6) | Typed Pydantic request/response validation, health checks, model metadata endpoint. |

---

## 3. Data Flow & Interface Contracts

### 3.1 Backend to ML Service Contract (`POST /predict`)
- **`nodes`**: Array of current sensor readings (`node_id`, `timestamp`, `pitch_deg`, `roll_deg`, `vibration_rms_mg`, `vibration_peak_hz`, `temperature_c`, `battery_mv`, `rssi_dbm`, `snr_db`, `flags`, `x_m`, `y_m`).
- **`history`**: Mapping of `node_id` to chronological list of prior readings (up to 8 previous timesteps).
- **`derived`**: Spatial deformation state reconstructed by backend array analysis (`observed` subsidence mm, `expected` Knothe subsidence mm, `strain_mm_per_m`).

### 3.2 ML Response Contract
- **`aggregate_risk`**: Overall hazard classification (`NORMAL`, `WATCH`, `WARNING`, `CRITICAL`).
- **`progression`**: Array deformation state (`STABLE`, `SLOW_CREEP`, `ACCELERATING`, `RAPID_DEFORMATION`, `INSUFFICIENT_HISTORY`).
- **`anomaly`**: Node-level anomaly classification and calibrated scores.
- **`health`**: Node-level sensor hardware & communications health (`HEALTHY`, `SUSPECT`, `FAULTY`).
- **`forecast`**: Maximum expected tilt at 1h, 6h, 12h, 24h horizons with change rates.
- **`time_to_threshold`**: Estimated hours until warning and critical tilt levels.
- **`physics`**: Observed vs. expected Knothe deformation residual score and status (`AVAILABLE`, `UNAVAILABLE`).
- **`confidence`**: Statistical model confidence score (0.0 - 1.0), accounting for history length, OOD distance, sensor faults, and communication dropouts.

---

## 4. Evaluation Methodology & Target Consistency

### 4.1 Forecast Target Definition
- **Physical Quantity**: Total Tilt Magnitude $T = \sqrt{\theta_{pitch}^2 + \theta_{roll}^2}$ in degrees (`tilt_deg`).
- **Field-Level Aggregation**: Maximum tilt across placed nodes ($\max_{i} T_i$), representing the governing structural point of highest hazard.
- **Horizon Definitions**:
  - $1\text{h}$ (4 samples @ 15-min cadence)
  - $6\text{h}$ (24 samples)
  - $12\text{h}$ (48 samples)
  - $24\text{h}$ (96 samples)
- **Metrics**: MAE (Mean Absolute Error) and RMSE (Root Mean Squared Error) compared directly against a Persistence Baseline ($\hat{T}_{t+h} = T_t$).

### 4.2 Anomaly Detection Evaluation
- **Split**: Strict chronological split (50% train normal, 15% validation, 35% test with mixed physical events & sensor faults).
- **Metrics**: Precision, Recall, F1-Score, False Alarm Rate (FAR) on normal periods, and Recall on true physical deformation events.

---

## 5. Real-Data Domain Shift & Robustness Strategy

### 5.1 Differences between Synthetic & Real-Mine Environments
1. Sensor mounting orientation and initial tilt offsets.
2. Ambient and seasonal temperature drift on MEMS accelerometers.
3. LoRa packet loss, frame jitter, and intermittent gateway backhaul.
4. Non-uniform geological strata and localized fault slips not captured by standard isotropic Knothe curves.
5. In-situ machinery vibrations (continuous miners, shearers, haul trucks).

### 5.2 Field Validation Protocol (Phases 1 to 8)
1. **Phase 1: Baseline Establishment**: Continuous observation during pre-mining stable period (minimum 14 days) to capture diurnal thermal cycles.
2. **Phase 2: Sensor-Specific Calibration**: Compute mean zero-offsets and thermal drift coefficients for each node.
3. **Phase 3: Shadow Mode Operation**: Deploy ML service parallel to standard operational monitoring without dispatching autonomous evacuation alerts.
4. **Phase 4: Ground Truth Reconciliation**: Validate flagged anomalies against geotechnical borehole extensometers and surveyor levelling.
5. **Phase 5: Performance Metric Calculation**: Recompute empirical precision, recall, and FAR on real mine data.
6. **Phase 6: Calibrated Retraining**: Offline adjustment of IForest thresholds and Knothe parameters based on documented strata behavior.
7. **Phase 7: Multi-Site Leave-One-Out Validation**: Verify that parameters calibrated on Mine A generalize safely to Mine B.
8. **Phase 8: Production Promotion Gate**: Formal sign-off by DGMS / certified mine safety officers.

---

## 6. Telemetry Data Quality & Out-of-Distribution (OOD) Guardrails

To prevent ungrounded or overconfident predictions during telemetry anomalies:
1. **Physical Operational Bounds & Range Checks**: Checks sensor physical operational limits (tilt magnitude $\le 75.0^\circ$, underground ambient temperature $\in [-25.0^\circ\text{C}, 75.0^\circ\text{C}]$, battery voltage $\in [2400, 4600]\text{ mV}$, and angular acceleration $\le 10.0^\circ/\text{h}^2$).
2. **Confidence Damping**: When out-of-distribution telemetry is detected, model confidence is penalized by 50% and explicit warning entries are added to the diagnostic factors.
3. **Graceful Degraded State Transitions**:
   - Insufficient temporal history ($< 4$ frames / $< 1.0\text{h}$): Forecast and lead-time return `None`; status returns `INSUFFICIENT_HISTORY`.
   - Sensor fault flags or communication dropout: Node flagged as `SUSPECT`/`FAULTY`, isolated from physical deformation scoring.
   - Knothe expected deformation unavailable: Physics status returns `UNAVAILABLE` without breaking the inference pipeline.

---

## 7. Model Governance & Limitations

### 7.1 Permissible vs. Prohibited Claims
- **PERMISSIBLE**:
  - "AI-assisted real-time subsidence monitoring and early-warning decision support system."
  - "Evaluated on physics-calibrated synthetic longwall scenarios."
  - "Combines physical Knothe influence modeling with statistical outlier detection."
  - "Time-to-threshold is a deterministic trend-based lead-time estimate."
- **PROHIBITED (DO NOT CLAIM)**:
  - "100% accurate mine collapse prediction."
  - "Validated on active Indian coalfield production data" (until field trials occur).
  - "Replaces certified geotechnical inspections."
