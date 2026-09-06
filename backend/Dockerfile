FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# The protocol codec is shared with the simulator, so it installs as a package
# rather than being copied twice and drifting apart.
COPY packages/subnet-proto /opt/subnet-proto
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt /opt/subnet-proto

COPY backend/ .

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
