# MineGuard — AI-enabled mine subsidence monitoring and early warning

SIH 2026. A low-cost, real-time subsidence monitoring, prediction and early-warning
system for Indian underground coal mines, built around a **wireless surface mesh**
of sensor nodes over the mine panel.

```
 NODE ×21  ──LoRa 865MHz mesh──►  GATEWAY  ──HTTP/MQTT──►  API  ──WS/REST──►  DASHBOARD
 ESP32-S3                         ESP32                    FastAPI            React
 LIS3DH tilt + vibration          E220 LoRa                TimescaleDB        Leaflet 2-D
 VL53L1X displacement             SIM800L SMS              PostGIS            Three.js 3-D
 crack gauge                      SD buffer                risk + alerts
 E220 (wake-on-radio)             local rule engine
        ◄────────────── config downlink ──────────────────────┘
```

## Run it

No services to install — the stack runs on SQLite locally.

```bash
make install
make api        # terminal 1  -> http://localhost:8000/docs
make gateway    # terminal 2  -> streams physics-backed frames over the real protocol
make web        # terminal 3  -> http://localhost:5173
```

`make up` runs the deployed shape instead (TimescaleDB + PostGIS, Mosquitto, Redis).

## What is real here

**The physics.** Ground movement comes from the influence-function (Knothe) model,
which reproduces the published analytical results: subsidence is exactly half of
maximum above the panel edge, tilt peaks there and vanishes at the trough centre,
and strain is tensile at the rim but compressive over the goaf. Analytic
derivatives are checked against finite differences, so an algebra slip cannot
quietly poison the training data.

**The protocol.** One wire format, written in C for the ESP32 and mirrored in
Python for the backend. The conformance suite compiles the real firmware header
and asserts both encoders emit byte-identical frames, so firmware and backend
cannot silently drift apart.

**The mesh.** Multi-hop routing designed and tested in software before any node is
flashed. Under realistic ground-level propagation with terrain in the way, a star
topology delivers 43% of frames and the mesh delivers 100% — the differentiating
claim as a measured number, not a slogan.

**The simulator is not a mock.** It encodes genuine frames, routes them through
the mesh model, and delivers them to the backend exactly as an ESP32 gateway
would. The backend cannot tell the difference — which is the point: if the
simulator can drive it, so can the field.

## Layout

| Path | What it is |
|---|---|
| `packages/subnet-proto` | The wire protocol + its conformance tests. Shared by backend and simulator. |
| `firmware/common/mesh_proto.h` | The same protocol in C, for the ESP32 |
| `ml/simulator` | Physics, sensor error model, labelled scenarios, mesh routing, virtual gateway |
| `backend` | FastAPI: ingest, risk scoring, alerting, config downlink, REST + WebSocket |
| `web` | React dashboard — Leaflet 2-D map, Three.js 3-D terrain |
| `docs` | Protocol spec and architecture notes |

## Tests

```bash
make test
```

| Suite | Covers |
|---|---|
| `packages/subnet-proto` (26) | Frame round-trips, corruption handling, C↔Python byte identity |
| `ml` (116) | Subsidence physics, sensor error model, scenario labels, mesh self-healing |
| `backend` (30) | Ingest, baselines, alert rate-limiting, config downlink round trip, topology |

## Design notes worth knowing

**Nodes are baselined, not zeroed.** A node is hand-planted on uneven ground, so
raw tilt mostly describes how the post was hammered in. Its first frame becomes
its commissioning baseline and every later reading is measured against that.
Without this the system alerts on every node the moment it joins, then goes blind
to the movement it exists to detect.

**Risk is scored server-side.** The web dashboard and the Android app must never
be able to disagree about whether a panel is in trouble, so the judgement is made
once, in the backend, and both clients render the same answer.

**A config downlink is pending until the node ACKs it.** The acknowledgement
echoes the config hash. A command that never reached a sleeping node has to be
visible as such, not assumed.

**Offline is a supported state.** If the backend is unreachable the dashboard
falls back to the built-in physics model and says so in the header; the gateway
buffers frames and reconciles them when the link returns. A monitoring screen
that goes blank when connectivity drops is worse than useless on a mine site.

#test
