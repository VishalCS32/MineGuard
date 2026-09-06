FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY packages/subnet-proto /opt/subnet-proto
COPY ml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt /opt/subnet-proto

COPY ml/ .

# Default role: drive the stack with physics-backed frames over the real
# protocol, so the whole system can be demonstrated without hardware.
CMD ["python", "-m", "simulator.virtual_gateway", "--api", "http://api:8000"]
