"""
app/config.py

Configuration settings and operational thresholds for MineGuard.
Kept server-side so clients and gateways cannot diverge on safety limits.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    # Persistence
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./subnet.db")

    # Network / MQTT
    MQTT_HOST: str | None = os.getenv("MQTT_HOST", None)
    MQTT_PORT: int = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_UPLINK_TOPIC: str = os.getenv("MQTT_UPLINK_TOPIC", "subnet/gw/+/up")
    MQTT_DOWNLINK_TOPIC: str = os.getenv("MQTT_DOWNLINK_TOPIC", "subnet/gw/{gateway}/cmd")

    # CORS (Strict origin list without wildcard to support allow_credentials=True cookies)
    CORS_ORIGINS: List[str] = field(default_factory=lambda: [
        origin.strip() for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"
        ).split(",") if origin.strip() and origin.strip() != "*"
    ])

    # Authentication & Sessions
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "mineguard-dev-super-secure-jwt-signing-secret-key-32b-min")
    JWT_ALGORITHM: str = "HS256"
    SESSION_EXPIRE_DAYS: int = int(os.getenv("SESSION_EXPIRE_DAYS", "7"))
    PASSWORD_RESET_EXPIRE_HOURS: int = int(os.getenv("PASSWORD_RESET_EXPIRE_HOURS", "1"))
    SESSION_COOKIE_NAME: str = "mineguard_session"
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1", "yes")

    # Google OAuth 2.0 / OpenID Connect
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_CALLBACK_URL: str = os.getenv("GOOGLE_CALLBACK_URL", "http://localhost:5173/auth/callback")

    # External Provider Configurations (Optional - with explicit graceful degradation)
    SMTP_HOST: str | None = os.getenv("SMTP_HOST", None)
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str | None = os.getenv("SMTP_USER", None)
    SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD", None)
    EMAILS_FROM_EMAIL: str = os.getenv("EMAILS_FROM_EMAIL", "noreply@mineguard.local")

    TWILIO_ACCOUNT_SID: str | None = os.getenv("TWILIO_ACCOUNT_SID", None)
    TWILIO_AUTH_TOKEN: str | None = os.getenv("TWILIO_AUTH_TOKEN", None)
    TWILIO_PHONE_NUMBER: str | None = os.getenv("TWILIO_PHONE_NUMBER", None)

    # Operator thresholds (§14.4)
    TILT_THRESHOLD_DEG: float = float(os.getenv("TILT_THRESHOLD_DEG", "0.60"))
    STRAIN_THRESHOLD_MM_PER_M: float = float(os.getenv("STRAIN_THRESHOLD_MM_PER_M", "3.00"))
    VIBRATION_THRESHOLD_MG: float = float(os.getenv("VIBRATION_THRESHOLD_MG", "400.0"))
    TILT_RATE_THRESHOLD_DEG_PER_H: float = float(os.getenv("TILT_RATE_THRESHOLD_DEG_PER_H", "0.05"))
    TILT_DRIFT_MDEG_PER_C: float = float(os.getenv("TILT_DRIFT_MDEG_PER_C", "18.0"))
    TILT_RATE_WINDOW_HOURS: float = float(os.getenv("TILT_RATE_WINDOW_HOURS", "6.0"))
    NODE_STALE_SECONDS: int = int(os.getenv("NODE_STALE_SECONDS", "180"))

    # Cooldowns and rates
    ALERT_COOLDOWN_MINUTES: int = int(os.getenv("ALERT_COOLDOWN_MINUTES", "20"))
    BROADCAST_MAX_HZ: float = float(os.getenv("BROADCAST_MAX_HZ", "4.0"))
    KEEP_ALIVE_PING_S: float = float(os.getenv("KEEP_ALIVE_PING_S", "25.0"))

    # Embedded simulation runner (default false; standalone virtual gateway drives simulation)
    SIMULATOR_ENABLED: bool = os.getenv("SIMULATOR_ENABLED", "false").lower() in ("true", "1", "yes")
    SIMULATOR_TICK_SECONDS: float = float(os.getenv("SIMULATOR_TICK_SECONDS", "1.5"))


settings = Settings()

