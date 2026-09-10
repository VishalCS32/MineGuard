# Node Live Telemetry API

A small FastAPI backend that simulates realistic live sensor data for `NODE-001`.

## Data flow

Node simulator -> FastAPI -> WebSocket -> Mobile app / Web dashboard

You also get a REST endpoint for the latest simulated sample.

## 1. Install

```bash
python -m venv .venv
```

### Linux/macOS

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Start the API

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API:
- REST: http://localhost:8000/api/v1/nodes/NODE-001/latest
- WebSocket: ws://localhost:8000/ws/NODE-001
- Swagger docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## 3. JavaScript WebSocket example

```js
const socket = new WebSocket("ws://localhost:8000/ws/NODE-001");

socket.onopen = () => {
  console.log("Connected");
};

socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Live telemetry:", data);

  // Update your dashboard:
  // rollChart.update(data.orientation.roll)
  // pitchChart.update(data.orientation.pitch)
  // map.setPosition(data.gps.latitude, data.gps.longitude)
  // anomalyLabel.textContent = data.ml.condition
};

socket.onclose = () => {
  console.log("Disconnected");
};
```

## 4. Python client example

```python
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws/NODE-001") as ws:
        while True:
            data = json.loads(await ws.recv())
            print(data)

asyncio.run(main())
```

## Production direction

For a real deployed system, replace `simulated_data()` with data received from your physical node, add authentication, TLS/WSS, persistent storage (PostgreSQL/TimescaleDB), device registration, rate limiting, and per-node authorization.
