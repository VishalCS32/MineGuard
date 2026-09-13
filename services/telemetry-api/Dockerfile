FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so a code change does not re-resolve the whole tree.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Most hosts hand the port over in $PORT and expect the app to take it.
ENV PORT=8000
EXPOSE 8000

# One worker on purpose. The live WebSocket fan-out is per-process state, so
# a second worker would serve half the dashboards and broadcast to neither
# the other half's readings. Scale with Redis pub/sub, not with workers.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
