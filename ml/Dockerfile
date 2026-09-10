FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY packages/subnet-proto /opt/subnet-proto
COPY ml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt /opt/subnet-proto

COPY ml/ .

# The simulator remains a separate development command. This container serves
# telemetry-derived ML predictions to the backend.
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8100"]
