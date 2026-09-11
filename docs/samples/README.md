# MineGuard API Sample JSON

These fixtures are provided for Backend and Web/App development against the MineGuard ML API (`POST /predict`).

---

## 1. Sample Categories

There are two categories of samples in this directory:

### A. Reference 21-Node Fixtures
These represent the reference hardware deployment configuration (21 sensor nodes: `NODE-001` through `NODE-021`). They validate the complete reference layout and regression behavior.

- **Request Fixtures:**
  - [`mineguard-21-node-sample-request.json`](file:///docs/samples/mineguard-21-node-sample-request.json)
  - [`mineguard-21-node-hardware-theft-test.json`](file:///docs/samples/mineguard-21-node-hardware-theft-test.json)
- **Verified Response Fixtures:**
  - [`ml-response-21-node-normal.json`](file:///docs/samples/ml-response-21-node-normal.json)
  - [`ml-response-21-node-hardware-theft.json`](file:///docs/samples/ml-response-21-node-hardware-theft.json)

### B. Dynamic-Node Fixtures
These demonstrate that production ML `/predict` accepts arbitrary node counts ($N \ge 1$) and arbitrary alphanumeric node IDs (e.g. `ROOF-A`, `ROOF-B`, `CENTER-3`, `N42`, `SENSOR-ALPHA`). Production inference has **zero** hardcoded requirement for 21 nodes.

- **Request Fixtures:**
  - [`mineguard-dynamic-5-node-sample-request.json`](file:///docs/samples/mineguard-dynamic-5-node-sample-request.json)
  - [`mineguard-dynamic-5-node-hardware-theft-test.json`](file:///docs/samples/mineguard-dynamic-5-node-hardware-theft-test.json)
- **Verified Response Fixtures:**
  - [`ml-response-dynamic-5-node-normal.json`](file:///docs/samples/ml-response-dynamic-5-node-normal.json)
  - [`ml-response-dynamic-5-node-hardware-theft.json`](file:///docs/samples/ml-response-dynamic-5-node-hardware-theft.json)

---

## 2. Testing `POST /predict`

### Windows Command Prompt (cmd.exe)
```cmd
curl -X POST http://localhost:8001/predict ^
  -H "Content-Type: application/json" ^
  --data-binary "@docs/samples/mineguard-dynamic-5-node-sample-request.json"
```

### Windows PowerShell
```powershell
$body = Get-Content -Raw .\docs\samples\mineguard-dynamic-5-node-sample-request.json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType "application/json" -Body $body

$theftBody = Get-Content -Raw .\docs\samples\mineguard-dynamic-5-node-hardware-theft-test.json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType "application/json" -Body $theftBody
```

### Linux / macOS (bash / zsh)
```bash
curl -X POST http://localhost:8001/predict \
  -H "Content-Type: application/json" \
  --data-binary "@docs/samples/mineguard-dynamic-5-node-sample-request.json"
```

---

## 3. Architecture & Integration Responsibilities

### Backend Responsibilities
- **Data Ingestion & Pipeline:** Backend ingests raw sensor telemetry from hardware nodes via LoRaWAN/MQTT/gateway.
- **State & History Buffering:** Backend buffers chronological telemetry history per active node and constructs the `PredictionRequest` payload for `POST /predict`.
- **Calling ML Service:** Backend invokes the ML service endpoint (`http://localhost:8001/predict`) and receives the `PredictionResponse`.
- **Client Dispatch:** Backend relays or pushes the ML prediction response (via WebSocket, SSE, or REST) to Web and Mobile applications.

### Web / Mobile App Responsibilities
- **Consume ML Response Only:** Web/App must consume the resulting ML response directly; it must **NOT** calculate ML models, deformation metrics, or anomaly scores locally.
- **Dynamic Node Count:** Web/App must **NOT assume 21 nodes**. Node count is dynamic ($N \ge 1$). Web/App must dynamically render however many nodes appear in `response.nodes`.
- **Anti-Theft Handling:** Web/App must read `response.anti_theft.alert`, `response.anti_theft.status`, `response.anti_theft.affected_node_ids`, and `response.anti_theft.events`.
- **No Client-Side Math:** Web/App must **NOT** calculate Haversine distance, implement anti-theft debounce algorithms, or calculate deformation/risk/forecasts itself. The ML pipeline handles all physical, spatial, and anti-theft processing.

---

## 4. Expected API Results for Fixtures

### Dynamic 5-Node Fixtures
- **Normal Fixture (`mineguard-dynamic-5-node-sample-request.json`):**
  - `overall.status`: `NORMAL`
  - `overall.alarm`: `false`
  - `nodes` count: 5 (`ROOF-A`, `ROOF-B`, `CENTER-3`, `N42`, `SENSOR-ALPHA`)
  - `sensor_health.healthy_nodes`: 5
  - `anti_theft.alert`: `false`
  - `anti_theft.status`: `NORMAL`

- **Theft Fixture (`mineguard-dynamic-5-node-hardware-theft-test.json`):**
  - `overall.status`: `NORMAL`
  - `overall.alarm`: `false`
  - `nodes` count: 5
  - `anti_theft.alert`: `true`
  - `anti_theft.status`: `THEFT_SUSPECTED`
  - `anti_theft.affected_node_ids`: `["SENSOR-ALPHA"]`

### Reference 21-Node Fixtures
- **Normal Fixture (`mineguard-21-node-sample-request.json`):**
  - `overall.status`: `WARNING` (Node `NODE-001` exhibits pitch 0.38° ramping toward 0.50°)
  - `overall.alarm`: `true`
  - `nodes` count: 21 (`NODE-001` to `NODE-021`)
  - `anti_theft.alert`: `false`

- **Theft Fixture (`mineguard-21-node-hardware-theft-test.json`):**
  - `overall.status`: `WARNING`
  - `overall.alarm`: `true`
  - `nodes` count: 21
  - `anti_theft.alert`: `true`
  - `anti_theft.status`: `THEFT_SUSPECTED`
  - `anti_theft.affected_node_ids`: `["NODE-001"]`

---

## 5. Generating / Verifying Response Fixtures

To regenerate verified response fixtures using the actual production ML service:

```powershell
python docs/samples/generate-ml-response-fixtures.py
```

This runs against the local ML FastAPI service (at `http://127.0.0.1:8001`) and writes the exact JSON outputs returned by `/predict`.

