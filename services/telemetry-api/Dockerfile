FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV PORT=8000 DB_PATH=/data/telemetry.db
# /data so a host that gives you a mountable volume keeps the database across
# deploys. Without one it is still a container path and still ephemeral --
# mount something at /data if the readings matter.
VOLUME ["/data"]
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
