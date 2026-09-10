# MineGuard AI/ML Implementation Audit

Date: 2026-09-09
Repository: `VishalCS32/MineGuard`
Scope: repository audit before implementing the AI/ML subsystem

## Executive Summary

The repository already has a complete sensor-to-backend protocol path and a tested physics-backed simulator, but it does not yet contain an ML service or ML inference pipeline. The safest implementation boundary is:

```text
Physical sensor or simulator
  -> packed SUBSIDENCE-NET telemetry frame
  -> gateway /api/ingest or MQTT
  -> backend protocol decode and persistence
  -> backend baseline + thermal correction + field reconstruction
  -> ML input adapter using the same stored/derived measurements
  -> ML prediction and risk intelligence
  -> backend snapshot, alerts, dashboard, and simulator demo
```

The simulator must remain an upstream emulator. ML must consume telemetry-shaped data and derived measurements, not simulator scenario names, hidden truth, or simulator classes.

## Existing Repository Surface

### ML directory

Existing files:

- `ml/simulator/field.py`: site presets, node layout, local-to-WGS84 helpers.
- `ml/simulator/mesh.py`: radio topology, routing, loss, RSSI, SNR, hop simulation.
- `ml/simulator/physics.py`: analytic Knothe influence-function physics and derived ground truth.
- `ml/simulator/scenarios.py`: five labelled development scenarios and `FieldSimulator`.
- `ml/simulator/sensors.py`: sensor corruption model that emits the real `Telemetry` object.
- `ml/simulator/virtual_gateway.py`: frames telemetry through the real protocol and posts to the backend.
- `ml/tests/*`: simulator, physics, scenarios, and mesh tests.

Missing:

- telemetry/data adapter for ML
- shared feature pipeline
- model training/evaluation pipeline
- anomaly, progression, forecasting, spatial, health, fusion, confidence, and explanation modules
- ML inference state/history
- FastAPI service
- ML API schemas
- model artifact management
- backend ML client/integration
- ML-specific tests and scenario evaluation reports

### Protocol and firmware

Canonical protocol implementation: `packages/subnet-proto/subnet_proto/proto.py`, mirrored by `firmware/common/mesh_proto.h`.

A telemetry payload is 22 bytes and is wrapped in a 12-byte protocol header. The exact telemetry fields are:

| Field         | Encoding / unit                            |
| ------------- | ------------------------------------------ |
| `t_epoch`     | unsigned 32-bit epoch seconds              |
| `pitch_mdeg`  | signed 16-bit, millidegrees                |
| `roll_mdeg`   | signed 16-bit, millidegrees                |
| `vib_rms_mg`  | unsigned 16-bit, milligravity              |
| `vib_peak_hz` | unsigned 16-bit, Hz                        |
| `temp_c_x100` | signed 16-bit, centi-degrees Celsius       |
| `n_samples`   | unsigned 8-bit sample count                |
| `gnss_status` | packed fix quality and satellite count     |
| `vbat_mv`     | unsigned 16-bit, millivolts                |
| `rssi`        | signed 8-bit                               |
| `snr`         | unsigned 8-bit, encoded as `(dB + 20) * 4` |
| `flags`       | unsigned 8-bit protocol flags              |
| `reserved`    | unsigned 8-bit                             |

The codec exposes engineering properties including `pitch_deg`, `roll_deg`, `tilt_deg`, `temp_c`, `gnss_fix`, `gnss_sats`, `has_fix`, `snr_db`, and `vbat_volts`. ML must use these exact fields and units or an explicit, tested adapter. No replacement JSON telemetry protocol should be introduced at the radio boundary.

GNSS is suitable for node placement and detecting metre-scale physical movement. It is not a precision millimetre-scale subsidence measurement.

### Backend ingestion

`backend/app/ingest.py` is the production boundary for both real and simulated gateways:

1. raw bytes are decoded with `subnet_proto.decode`
2. malformed frames are rejected
3. `Telemetry` frames are baseline corrected and persisted
4. first telemetry establishes commissioning pitch, roll, and temperature baselines
5. `tilt_mdeg` is stored as a derived magnitude
6. telemetry retains vibration, temperature, sample count, GNSS, battery, radio, flags, hops, and sequence
7. field scoring runs after a batch has landed

The simulator HTTP gateway posts base64 frames to `POST /api/ingest`; the deployed gateway may publish equivalent frames over MQTT. This is the same logical input path for physical and simulated data.

### Deformation reconstruction

`backend/app/deformation.py` owns the existing numerical reconstruction and must be reused:

- corrected tilt components are represented in `NodeTilt`
- local tilt is converted to mm/m
- strain is reconstructed by spatial differentiation with the existing node layout
- subsidence is reconstructed by trapezoidal integration along rows
- validity flags distinguish unavailable strain or unanchored subsidence
- geometry uses seam depth, panel start, and angle of draw

`ml/simulator/physics.py` is the analytic Knothe model used to generate synthetic ground truth. It is not a replacement for the backend reconstruction. ML should compare observed/backend-derived values with physics expectations through an adapter, without duplicating either engine unnecessarily.

### Existing deterministic risk

`backend/app/risk.py` owns current engineering risk scoring:

- configurable thresholds for tilt, strain, vibration, and tilt rate
- thermal and commissioning-baseline correction
- risk bands: `low`, `medium`, `high`, `critical`
- NCB-style damage classes from strain
- vibration is corroborating evidence, not the sole decision signal

`backend/app/ingest.py::_field_pass` computes recent tilt rates, reconstructs the field, applies deterministic risk, raises cooldown-controlled alerts, and estimates a simple straight-line threshold lead time. AI/ML must augment this logic and preserve it unless a deliberate, tested integration replaces a specific surface.

### Backend and dashboard contracts

`backend/app/state.py` builds the dashboard snapshot. It currently includes node deformation/risk values, alerts, KPIs, and a simple three-day extrapolated prediction. The frontend consumes this snapshot through the API/WebSocket. There is no ML response field or ML client yet.

The database already has relevant persistence surfaces:

- `telemetry` stores raw/derived node readings
- `nodes` stores positions and commissioning baselines
- `sites` stores panel and mining parameters
- `alerts` stores deterministic warning information including `hours_to_threshold`

A later integration should add a versioned ML result representation only where required by the existing backend/API contract, avoiding a second incompatible dashboard API.

### Service and deployment configuration

`docker-compose.yml` already defines an `ml` service on port `8100`, mounts `./ml`, and provides `DATABASE_URL` and `MODEL_DIR`. The API service receives `ML_SERVICE_URL=http://ml:8100`. However:

- `ml/Dockerfile` currently starts `simulator.virtual_gateway`, not a service
- `ml/requirements.txt` contains only `numpy`, `scipy`, and `httpx`
- no FastAPI endpoint exists
- no backend request to `ML_SERVICE_URL` exists

The ML Docker command and dependencies will need to change only when the service implementation is ready. The simulator gateway should remain available as a separate development command/entry point.

## Simulator Audit

The simulator is synthetic sensor generation for development and evaluation only.

`FieldSimulator` first evaluates the analytic Knothe model, then `NodeSensorModel` converts the resulting tilt and vibration into the exact packed `Telemetry` contract. It adds installation offsets, thermal drift, random walk, noise, battery evolution, radio values, GNSS status, and explicit fault flags. `VirtualGateway` then routes and posts frames through the real protocol.

The five scenarios are:

- `stable`: thermal drift and noise without extraction
- `slow_creep`: gradual normal face advance
- `accelerating`: super-linear face advance and rising deformation rate
- `sudden_collapse`: localized rapid deformation and low-frequency vibration
- `false_alarm`: vibration disturbances without ground movement

Scenario names and `GroundTruth` are valid only for synthetic labels and evaluation. They must never become inference features or production ML dependencies.

## Existing Tests and Dependencies

Existing suites cover:

- protocol codec and C header conformance
- simulator sensors, scenarios, physics, and mesh
- backend API, ingest, deformation, and risk behavior

The current ML dependency baseline is lightweight: NumPy, SciPy, and HTTPX. The planned implementation can add scikit-learn, pandas, FastAPI, and Pydantic only as needed and should avoid deep-learning dependencies until measured evidence justifies them.

The Makefile runs `test-proto`, `test-ml`, and `test-backend` separately and together. Existing tests must remain unchanged and passing.

## Required Implementation Surface

Recommended additions inside `ml/`:

```text
ml/
  data/          telemetry input records and loaders
  schemas/       request/response models
  features/      shared preprocessing and feature engineering
  models/        anomaly, progression, forecasting, spatial, health, fusion
  inference/     stateful end-to-end inference pipeline
  training/      chronological training and artifact creation
  evaluation/    scenario evaluation and honest metrics
  service/       FastAPI application
  tests/         unit, API, and integration tests
  artifacts/     runtime model artifacts (ignored or explicitly managed)
```

Exact interfaces should be introduced incrementally, with the shared feature pipeline used by both training and inference. The first service contract should accept telemetry-shaped node observations plus optional backend-derived deformation values and return structured ML intelligence. It must return insufficient-data/null lead times rather than fabricate forecasts.

## Data and Processing Boundary

```text
REAL SENSOR TELEMETRY
  - packed Telemetry frame
  - decoded by existing protocol
  - persisted by backend

SIMULATED SENSOR TELEMETRY
  - generated by NodeSensorModel
  - packed as the same Telemetry frame
  - routed by VirtualGateway
  - ingested identically

EXISTING PROCESSING
  - commissioning baseline
  - thermal correction
  - tilt calculation
  - recent tilt rate
  - spatial strain/subsidence reconstruction
  - deterministic engineering risk

ML INPUT
  - exact per-node telemetry fields
  - history produced only from observations available up to inference time
  - backend-derived tilt, rate, strain, subsidence, validity
  - node geometry and neighbour relationships
  - physics expectation/residual where available

ML PROCESSING
  - anomaly detection
  - progression state
  - temporal forecast
  - spatial consistency and spreading
  - sensor health
  - physics residual
  - transparent AI/physics fusion
  - confidence, explanation, and threshold lead-time estimates

FINAL ML OUTPUT
  - versioned structured prediction
  - risk intelligence, not guaranteed collapse prediction
  - consumed by backend state/alerts and displayed by dashboard/demo
```

## Missing Integration Decisions to Implement

1. Define a typed ML request that represents decoded telemetry/history and optional existing deformation estimates without importing simulator modules.
2. Decide whether the first integration is a synchronous backend call during field processing or a persisted/asynchronous result path. It must fail open for telemetry persistence if ML is unavailable.
3. Add a backend ML client using the already configured `ML_SERVICE_URL`.
4. Extend the dashboard snapshot only with additive, backward-compatible ML fields.
5. Preserve deterministic engineering alerts as the baseline and make AI/physics fusion thresholds configurable.
6. Ensure model state is keyed by site/node and bounded by explicit history windows.
7. Use chronological splits for synthetic training/evaluation and report only executed metrics.
8. Mark simulator-derived datasets and evaluation reports as synthetic.

## Audit Conclusion

The repository is ready for phased ML implementation. The existing protocol, simulator, backend reconstruction, and deterministic risk code provide the required foundation. The missing work is a new, modular ML subsystem plus a narrow backend service/client integration; replacing the simulator, protocol, deformation engine, or frontend is neither required nor justified by the current architecture.
