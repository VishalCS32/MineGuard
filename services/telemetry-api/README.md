# Telemetry receiver

One file, two dependencies. Takes the JSON a gateway pushes, keeps it in a
SQLite file, and serves it back — as JSON for a dashboard, and as a flat CSV
table the ML side can read straight off the URL.

Separate from `backend/` on purpose. That one is the system of record and
speaks raw protocol frames; it is not something to expose publicly. This one
takes plain JSON from anything that can POST and is meant to be deployed on
the open internet.

## Run it

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8020
```

That is the whole setup — no database to install, nothing to configure. It
runs the same on a laptop next to the gateway and in a container.

Then on the gateway:

```
set push http://<this-machine>:8020/api/v1/telemetry
save
```

## Endpoints

| | |
|---|---|
| `POST /api/v1/telemetry` | One reading, or a list of up to 500 |
| `GET /api/v1/nodes` | Every node with its latest reading |
| `GET /api/v1/nodes/{id}/latest` | One node's most recent reading |
| `GET /api/v1/readings?node_id=&since_id=&limit=` | Flat rows, oldest first |
| `GET /api/v1/readings.csv` | The same, as CSV |
| `DELETE /api/v1/nodes/{id}` | Remove every reading for one node |
| `GET /health` | Row count, db path, whether auth is on |
| `GET /docs` | Swagger |

There is deliberately no bulk delete: a `DELETE /api/v1/readings` would be one
typo away from erasing a field's entire history.

## Feeding the ML side

The table is flat — one row per reading, one column per field, nothing
nested — so there is no unpacking step:

```python
import pandas as pd
df = pd.read_csv("http://localhost:8020/api/v1/readings.csv")
df = pd.read_csv("http://localhost:8020/api/v1/readings.csv?node_id=NODE-001")
```

The ML repo has a client that does the unit conversions for you —
`ml/data/api_client.py`:

```python
from data.api_client import TelemetryAPI
from inference.pipeline import predict

with TelemetryAPI("https://your-host") as api:
    current, history = api.predict_inputs(history_limit=200)
    result = predict(current, history)
```

Use it rather than reading the JSON by hand. Three fields do not line up with
what the pipeline expects, and each fails silently rather than loudly:
vibration is m/s² here and milli-g there (a factor of ~9.8, in the direction
that cries wolf); `ts` is the node's clock while `received_at` is when the
backhaul recovered; and `peak_hz` is never measured at all.

For a job that runs repeatedly, page with `since_id` rather than re-reading
everything. Keep the largest `id` you have seen and ask for what came after:

```python
cursor = 0
while True:
    rows = requests.get(url, params={"since_id": cursor, "limit": 5000}).json()
    if not rows:
        break
    cursor = rows[-1]["id"]
```

An id cursor rather than a timestamp on purpose: paging by time repeats or
skips rows whenever two readings share a second, and at a five-second
interval across twenty-one nodes they do.

Nothing is ever rejected for a missing sensor — a field the node cannot
measure arrives as null and is stored as NULL. Only a missing `node_id` is an
error.

## Configuration

| Variable | Default | |
|---|---|---|
| `INGEST_TOKEN` | *(unset)* | Bearer token on writes and deletes. **Unset means open** |
| `DB_PATH` | `telemetry.db` | Where the SQLite file lives |
| `PORT` | `8000` | Read by the Dockerfile |

With a token set, the gateway needs the same string:

```
set push-token <token>
save
```

A mismatch is not silent — the gateway logs the 401 and names the command to
fix it.

## Deploying

```bash
docker build -t telemetry-api .
docker run -p 8000:8000 -v telemetry:/data -e INGEST_TOKEN=... telemetry-api
```

Render, Railway, Fly: point at this directory, use the Dockerfile, set the
variables above. `$PORT` is picked up automatically.

**Mount a volume at `/data`, or the database is erased on every deploy** —
container disks are ephemeral almost everywhere. For a demo that does not
matter; for a training set it does.
