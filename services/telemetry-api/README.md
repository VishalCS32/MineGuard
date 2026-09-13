# Telemetry receiver

Accepts the decoded telemetry a SUBSIDENCE-NET gateway pushes, stores it,
serves it back, and streams it live to a dashboard.

Separate from `backend/` on purpose. That one is the system of record and
speaks raw protocol frames; it is not something to expose publicly. This one
takes plain JSON from anything that can POST, holds no opinion about the
codec, and is meant to be deployed on the open internet.

## Run it

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

SQLite by default — a `telemetry.db` file beside the app, no services to
install. Point `DATABASE_URL` at Postgres for anything that must outlive a
container.

## Endpoints

| | |
|---|---|
| `POST /api/v1/telemetry` | One reading, or a list of up to 200 |
| `GET /api/v1/nodes` | Every node, with its latest reading |
| `GET /api/v1/nodes/{id}/latest` | One node's most recent reading |
| `GET /api/v1/nodes/{id}/history?limit=200` | Oldest first, as a chart wants |
| `GET /health` | Liveness, row count, whether auth is on |
| `WS /ws` | Every reading as it arrives |
| `GET /docs` | Swagger, generated from the models |

Point the gateway at it:

```
set push https://your-host/api/v1/telemetry
save
```

## Configuration

| Variable | Default | |
|---|---|---|
| `INGEST_TOKEN` | *(unset)* | Bearer token on the write path. **Unset means open** |
| `DATABASE_URL` | `sqlite+aiosqlite:///./telemetry.db` | `postgres://` and `postgresql://` are rewritten to the async driver |
| `CORS_ORIGINS` | `*` | Comma-separated |
| `PORT` | `8000` | Honoured by the Dockerfile |

## Before you expose it

**Set `INGEST_TOKEN`.** An open ingest endpoint on the public internet is a
database anyone can fill, and fabricated telemetry is worse than none — it
still draws a line on the chart. The service logs a warning at startup while
the token is unset, because forgetting is the normal way this ends up open.

The gateway does not send an `Authorization` header today. Either leave the
token unset behind a private network, or say the word and I will add header
support to `uplink_push_json()`.

**Use Postgres if the data matters.** Most hosts give a container an ephemeral
disk, so a SQLite file is gone at the next deploy.

**HTTPS is fine.** The gateway attaches ESP-IDF's certificate bundle, so a
normal public certificate works — a self-signed one will not.

## Deploying

Docker, and it runs anywhere that takes a container:

```bash
docker build -t telemetry-api .
docker run -p 8000:8000 -e INGEST_TOKEN=... telemetry-api
```

On Render / Railway / Fly, point the service at this directory and set the
environment variables above; the Dockerfile reads `$PORT` the way they expect.
One worker is deliberate — the live WebSocket fan-out is per-process state, so
a second worker would serve half the dashboards and broadcast to neither the
other half's readings. Scale that with Redis pub/sub, not with `--workers`.
