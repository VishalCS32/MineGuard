# MineGuard AI/ML — Real-Data Readiness & Shadow-Mode Deployment Protocol

## Executive Summary
This document establishes the mandatory operational protocols, site calibration requirements, shadow-mode procedures, and safety boundaries for deploying the MineGuard AI/ML early-warning subsystem onto real ESP32/LoRa hardware in active underground coal mines.

> [!CAUTION]
> **SYNTHETIC BENCHMARK PERFORMANCE IS NOT REAL-MINE VALIDATION.**
> High benchmark performance on physics simulations ($100\%$ physical event recall, $81.2\%$ row precision) does **NOT** constitute proof of safety in real mines. Real mines introduce unmodeled micro-seismic activity, heavy machinery haulage shocks, temperature-humidity diurnal hysteresis, antenna condensation RF fading, and mechanical sensor mounting creep. Direct coupling of ML outputs to emergency sirens/evacuation relays is **STRICTLY PROHIBITED** until all criteria in this protocol are fulfilled.

---

## A. Required Sensor Calibration (Pre-Installation & Commissioning)

Before physical installation on roadway rock bolts:
1. **Six-Axis Inertial Measurement Unit (IMU) Calibration**:
   - Accelerometer and gyroscope zero-rate offset calibration under static level conditions ($25^\circ\text{C} \pm 2^\circ\text{C}$).
   - Thermal calibration coefficients for MPU6050/ICM-series sensors mapped over the $-10^\circ\text{C}$ to $+50^\circ\text{C}$ range.
2. **LoRa RF Link Budget & Antenna Verification**:
   - Minimum RSSI $\ge -110\text{ dBm}$ and SNR $\ge -5\text{ dB}$ at target gateway distance before rock anchor fixation.
   - Moisture-proof IP67 enclosure seal check to prevent relative humidity condensation on radio matching networks.
3. **Firmware Unit Scaling Verification**:
   - Pitch & Roll: Transmitted as milli-degrees (`pitch_mdeg`, `roll_mdeg`) $\to$ divided by $1000.0$ to produce degrees.
   - Temperature: Transmitted as Celsius $\times 100$ (`temp_c_x100`) $\to$ divided by $100.0$ to produce $^\circ\text{C}$.
   - Vibration: Transmitted as RMS milli-g (`vib_rms_mg`) and dominant peak frequency in Hz (`vib_peak_hz`).
   - Battery: Transmitted as milli-volts (`vbat_mv`).

---

## B. Mandatory 48-Hour Baseline Calibration Period

Following physical bolting to mine roof strata:
1. **Mechanical Settling & Grout Curing**:
   - The first 48 hours post-installation are designated as the **Strata Settling Period**.
   - No deformation alerts may be generated during this period.
2. **Per-Node Baseline Vector ($T_0$) Establishment**:
   - Calculate static mounting angle:
     $$\theta_{\text{pitch}, 0} = \text{median}(\theta_{\text{pitch}}[0:192]), \quad \theta_{\text{roll}, 0} = \text{median}(\theta_{\text{roll}}[0:192])$$
     using 192 samples (15-minute telemetry intervals over 48 hours).
3. **Ambient Operational Noise Floor ($\sigma_{\text{ambient}}$)**:
   - Establish Median Absolute Deviation (MAD) for resultant tilt:
     $$\text{MAD} = \text{median}(|T_i - \text{median}(T)|), \quad \sigma_{\text{baseline}} = 1.4826 \times \text{MAD}$$
4. **Thermal Diurnal Drift Mapping**:
   - Measure ambient diurnal temperature swings (ventilation cycling) and compute empirical drift coefficient $\kappa = \Delta \theta / \Delta \text{Temp}$ (mdeg/$^\circ\text{C}$).

---

## C. Mandatory Shadow-Mode Deployment Protocol

1. **Duration**:
   - A minimum of **14 to 30 continuous calendar days** of operational shadow-mode logging during active longwall/continuous miner production.
2. **System Wiring & Isolation**:
   - The ML service executes live over incoming backend telemetry.
   - All ML JSON outputs are logged to the audit database.
   - **Hardware Siren / Evacuation Relays MUST REMAIN DISCONNECTED / MUTED.**
3. **Audit Log Requirements**:
   Each frame must record:
   - Ingest timestamp & node ID
   - Raw sensor features (`pitch_deg`, `roll_deg`, `vib_rms_mg`, `temp_c`, `battery_mv`, `rssi_dbm`, `flags`)
   - Sensor health status (`HEALTHY`, `SUSPECT`, `SENSOR_FAULT`, `STALE_DATA`)
   - Anomaly screen score & severity
   - Deformation status (`NORMAL`, `UNCONFIRMED_ANOMALY`, `CONFIRMED_PHYSICAL`, `SUPPRESSED`, `OOD_LOW_CONFIDENCE`)
   - Multi-signal corroboration flags (`temporal`, `spatial`, `physics`)
   - Time-to-threshold prediction (`warning_hours`, `critical_hours`, `warning_status`, `critical_status`)
   - Reason codes & array-level `overall` summary.

---

## D. Independent Geotechnical References for Ground Truth

Shadow-mode ML outputs must be independently corroborated against trusted geotechnical survey instruments:
1. **Multi-Point Borehole Extensometers (MPBX)**: Anchor displacements anchored in upper roof strata.
2. **Optical Total Station Prisms**: Regular survey of roof displacement monitoring pegs (accuracy $\pm 1.0\text{ mm}$).
3. **Tell-Tale Dual-Height Roof Indicators**: Visual and electronic dual-height mechanical extensometers.
4. **Geotechnical Shift Logs**: Shift records of longwall face advance ($x_{\text{face}}$), pillar extraction, weighting events, roof potting, and continuous miner cutting passes.

---

## E. Shadow-Mode Acceptance Metrics for Operational Promotion

To advance from Shadow Mode to Field-Pilot (Operator Assist) status:

| Metric | Target | Operational Rationale |
| :--- | :---: | :--- |
| **Physical Event Recall** | $\ge 95.0\%$ | Must not miss verified ground convergence events observed on MPBX / optical prisms. |
| **Sensor Fault Rejection Rate** | $100.0\%$ | $0$ false physical alarms caused by battery decay, packet loss, or sensor hardware errors. |
| **False Alarm Clusters / 24h** | $\le 2.0\text{ / day}$ | Across 21 nodes; prevents operator alarm fatigue. |
| **Mean Detection Delay** | $\le 0.50\text{ h}$ | Must detect accelerated ground movement within 2 telemetry frames (30 min). |
| **Forecast 1h MAE** | $\le 0.05^\circ$ | Parity with persistence over short horizons. |
| **Out-of-Distribution Screening**| $100.0\%$ | All corrupted/impossible frames flagged `OOD_LOW_CONFIDENCE`. |

---

## F. Conditions Under Which Model Updates Are Permitted

> [!IMPORTANT]
> **NO BLIND ONLINE RETRAINING.**
> Telemetry streams must never update production ML model weights in an automated closed loop. An unmonitored online model can learn progressive mine roof subsidence as the "new normal" baseline, resulting in catastrophic failure to alert during collapse.

Model updates are permitted **ONLY** via the following offline governance protocol:
1. **Data Aggregation**: Collect shadow-mode telemetry records.
2. **Expert Labeling**: Geotechnical engineers inspect physical survey peg logs and verify ground truth labels (`normal`, `physical_deformation`, `sensor_anomaly`).
3. **Chronological Splitting**: Chronological train (50%), validation (15%), and untouched test (35%) splits. Random k-fold cross-validation is strictly prohibited for time-series subsidence data.
4. **Multi-Seed Stress Benchmark**: Retrained candidate model must pass domain-randomized stress testing with zero drop in physical event recall.
5. **Formal Geotechnical Sign-Off**: Written approval by the Mine Safety Officer prior to deploying the new model artifact to `artifacts/anomaly/model.joblib`.

---

## G. Conditions Under Which Siren/Relay Actuation Is Prohibited

The MineGuard ML service must be automatically locked out from triggering audible/visual evacuation sirens if **ANY** of the following conditions occur:
1. **Pre-Baseline Status**: Node has $< 48\text{ hours}$ of baseline recording post-installation.
2. **Single-Node Uncorroborated Alert**: Only a single node reports an anomaly with zero spatial corroboration, zero Knothe physics agreement, and rate $< 0.05^\circ/\text{h}$. (Treated as an inspection request, not an emergency evacuation).
3. **Sensor Health Degradation**: Associated sensor node flags low battery ($< 3500\text{ mV}$), severe RF loss, or protocol flags (`SENSOR_FAULT`).
4. **Telemetry Stale Window**: Telemetry timestamp is $> 1.0\text{ hour}$ older than server clock (`STALE_DATA`).
5. **Out-of-Distribution Detection**: Input telemetry values exceed physical operational envelopes (`OOD_LOW_CONFIDENCE`).
6. **Active Shadow-Mode Stage**: System has not yet completed the 14-day shadow verification period.
