# MineGuard — AI-enabled mine subsidence monitoring and early warning

SIH 2026. A low-cost, real-time subsidence monitoring, prediction and early-warning
system for Indian underground coal mines, built around a **wireless surface mesh**
of sensor nodes over the mine panel.

```
 NODE ×21  ──LoRa 865MHz mesh──►  GATEWAY  ──HTTP/MQTT──►  API  ──WS/REST──►  DASHBOARD
 ESP32-S3 mini                    ESP32-S3 mini            FastAPI            React
 LIS3DH tilt + vibration + temp   E220 LoRa (SPI)          TimescaleDB        Leaflet 2-D
 vibration sensor (wake IRQ)      SIM800L 2G SMS           PostGIS            Three.js 3-D
 NEO-6M GNSS                      microSD store+forward    risk + alerts
 E220-900M22S (LLCC68, SPI)       local rule engine        field reconstruction
                                  on-site web UI (own AP)
                                  realtime JSON push
                                  status LED + on-box diagnostics
        ◄────────────── config downlink ──────────────────────┘
```

**The nodes measure tilt. Everything else is derived from the array.** There is
no crack gauge and no ranger, because there does not need to be: over a
subsidence trough, strain and displacement are the neighbouring derivatives of
the same curve that tilt sits on. Differentiate a line of tilt sensors and you
get strain; integrate it and you get subsidence. See `docs/WORKFLOW.md`.

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
| `firmware/node`, `firmware/gateway` | ESP-IDF applications on the same ESP32-S3 board: duty cycle, mesh relay, deep sleep; spool, uplink, offline SMS, on-site web UI |
| `firmware/host_test` | The firmware's portable core, tested with `cc` and no hardware |
| `ml/simulator` | Physics, sensor error model, labelled scenarios, mesh routing, virtual gateway |
| `backend` | FastAPI: ingest, risk scoring, alerting, config downlink, REST + WebSocket |
| `web` | React dashboard — Leaflet 2-D map, Three.js 3-D terrain |
| `docs` | Protocol spec, end-to-end workflow, and the hardware build sheet |

## Tests

```bash
make test
```

| Suite | Covers |
|---|---|
| `packages/subnet-proto` (32) | Frame round-trips, corruption handling, C↔Python byte identity |
| `ml` (122) | Subsidence physics, sensor error model, scenario labels, mesh self-healing |
| `backend` (63) | Ingest, baselines, field reconstruction, alerts, config downlink, topology |
| `firmware/host_test` (325) | Frame codec under bit flips, mesh flood termination, NMEA, node thresholds and rates, gateway alerting rules, indicator priority |

## Design notes worth knowing

**Strain is reconstructed, not measured.** No node carries a crack gauge. The
physics says `strain = B · dT/dx` and `subsidence = ∫T dx`, so a line of tilt
sensors recovers both — and the tests assert it against the analytic model, not
against the reconstruction's own output. Two layout rules fall out of that and
both are enforced in code: spacing must be under a third of the radius of
influence (or the difference between neighbours stops representing the local
curvature), and the line must be anchored on ground a full radius beyond the
panel (or the integration constant is unknown and every depth reads low).

**The node budget decides the layout, not the other way round.** Covering the
whole panel as a grid at the spacing strain needs would take ~105 nodes here.
The same 21 nodes arranged as one survey line across the panel resolve the full
profile — strain correlation 0.995 against the analytic field, subsidence within
2%. That is also how subsidence has been monitored for a century: survey lines,
not grids.

**Temperature is a measurement channel, not a nicety.** Thermal expansion of the
mounting post swings apparent tilt by roughly five times the sensor noise across
an ordinary day, and it is systematic, so averaging never removes it. The LIS3DH
die temperature rides in every frame for exactly one purpose: subtracting that
drift. Without it the system raises a false alarm every afternoon.

**GNSS does not measure subsidence.** A NEO-6M is accurate to metres; subsidence
is millimetres. It self-localises nodes, disciplines the clock, supplies the
inter-node baselines the strain calculation divides by, and catches a node that
has physically moved — a collapse or a theft. The tests assert the limitation
rather than glossing it.

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
