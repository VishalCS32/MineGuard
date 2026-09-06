"""Runtime configuration, from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite by default so the stack runs -- and can be demonstrated -- with no
    # services to install. Compose overrides this with TimescaleDB, and the query
    # layer is identical either way; only the hypertable DDL differs.
    database_url: str = "sqlite+aiosqlite:///./subnet.db"

    # MQTT is how real gateways report. Optional: if no broker is reachable the
    # API still serves, and gateways can fall back to the HTTP ingest endpoint,
    # which is also the simpler path for a constrained ESP32.
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_uplink_topic: str = "subnet/gw/+/up"
    mqtt_downlink_topic: str = "subnet/gw/{gateway}/cmd"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Alerting thresholds. These are the operator-facing limits, kept on the
    # server so the dashboard and the mobile app cannot disagree about them.
    tilt_threshold_deg: float = 0.60      # 10 mm/m, the NCB-style disruptive limit
    crack_threshold_mm: float = 3.00
    vibration_threshold_mg: float = 400.0

    # A node unheard from for longer than this is treated as offline.
    node_stale_seconds: int = 180

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
