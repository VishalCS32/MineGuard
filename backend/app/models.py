"""
app/models.py

SQLAlchemy 2.0 ORM models for MineGuard database schema (§9).
Supports SQLite locally and PostgreSQL/TimescaleDB when deployed.
"""

from __future__ import annotations
from typing import Optional
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    coalfield = Column(String(128), nullable=False)
    origin_lat = Column(Float, nullable=False)
    origin_lon = Column(Float, nullable=False)
    seam_depth_m = Column(Float, default=150.0)
    extraction_thickness_m = Column(Float, default=3.0)
    subsidence_factor = Column(Float, default=0.65)
    angle_of_draw_deg = Column(Float, default=35.0)
    face_x_m = Column(Float, default=0.0)
    face_advance_m_per_day = Column(Float, default=12.0)
    panel_x_start = Column(Float, default=0.0)
    panel_x_end = Column(Float, default=600.0)
    panel_y_min = Column(Float, default=-200.0)
    panel_y_max = Column(Float, default=200.0)

    nodes = relationship("Node", back_populates="site", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="site", cascade="all, delete-orphan")
    mesh_links = relationship("MeshLink", back_populates="site", cascade="all, delete-orphan")


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    addr = Column(Integer, nullable=False, index=True)  # 16-bit mesh address
    label = Column(String(64), nullable=False)
    zone = Column(String(64), nullable=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    x_m = Column(Float, nullable=True)
    y_m = Column(Float, nullable=True)
    hw_revision = Column(String(64), default="esp32s3-lis3dh-neo6m-e220-v2")
    baseline_pitch_mdeg = Column(Integer, nullable=True)
    baseline_roll_mdeg = Column(Integer, nullable=True)
    baseline_temp_c_x100 = Column(Integer, nullable=True)
    position_source = Column(String(32), default="survey")  # 'survey' or 'gnss'
    position_acc_m = Column(Float, default=0.1)
    last_seen = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    active_cfg_version = Column(Integer, default=1)

    site = relationship("Site", back_populates="nodes")
    telemetries = relationship("Telemetry", back_populates="node", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="node", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="node", cascade="all, delete-orphan")
    configs = relationship("NodeConfig", back_populates="node", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("site_id", "addr", name="uq_site_node_addr"),
    )


class Telemetry(Base):
    __tablename__ = "telemetry"

    time = Column(Float, primary_key=True, nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), primary_key=True, nullable=False, index=True)
    pitch_mdeg = Column(Integer, nullable=False)
    roll_mdeg = Column(Integer, nullable=False)
    tilt_mdeg = Column(Float, nullable=False)
    vib_rms_mg = Column(Integer, nullable=False)
    vib_peak_hz = Column(Integer, nullable=False)
    temp_c_x100 = Column(Integer, nullable=False)
    n_samples = Column(Integer, default=32)
    gnss_status = Column(Integer, default=0)
    vbat_mv = Column(Integer, default=3800)
    rssi = Column(Integer, default=-80)
    snr_db = Column(Float, default=6.0)
    flags = Column(Integer, default=0)
    hops = Column(Integer, default=1)
    seq = Column(Integer, default=0)

    node = relationship("Node", back_populates="telemetries")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False, index=True)
    raised_at = Column(Float, nullable=False, index=True)
    severity = Column(Integer, nullable=False)  # 0 info, 1 warning, 2 high, 3 critical
    category = Column(String(32), nullable=False)  # threshold | anomaly | forecast | health
    title = Column(String(128), nullable=False)
    detail = Column(String(256), nullable=False)
    tilt_deg = Column(Float, nullable=False)
    strain_mm_per_m = Column(Float, nullable=True)
    tilt_rate_deg_per_h = Column(Float, default=0.0)
    vibration_mg = Column(Float, default=0.0)
    damage_class = Column(String(32), nullable=True)
    hours_to_threshold = Column(Float, nullable=True)
    state = Column(String(32), default="open", index=True)  # open -> acked -> resolved
    acked_by = Column(String(64), nullable=True)
    acked_at = Column(Float, nullable=True)
    resolved_at = Column(Float, nullable=True)
    notified_sms = Column(Boolean, default=False)

    site = relationship("Site", back_populates="alerts")
    node = relationship("Node", back_populates="alerts")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(Float, nullable=False, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False, index=True)
    event_code = Column(Integer, nullable=False)
    severity = Column(Integer, nullable=False)
    value = Column(Integer, nullable=False)
    threshold = Column(Integer, nullable=False)
    received_at = Column(Float, nullable=False)

    node = relationship("Node", back_populates="events")


class NodeConfig(Base):
    __tablename__ = "node_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False, index=True)
    cfg_version = Column(Integer, nullable=False)
    sample_interval_s = Column(Integer, default=60)
    wor_period_ms = Column(Integer, default=2000)
    tx_power_dbm = Column(Integer, default=22)
    tilt_alert_mdeg = Column(Integer, default=2000)
    vib_alert_mg = Column(Integer, default=500)
    tilt_rate_alert_mdeg_h = Column(Integer, default=150)
    tilt_offset_pitch = Column(Integer, default=0)
    tilt_offset_roll = Column(Integer, default=0)
    flags = Column(Integer, default=15)
    cfg_hash = Column(Integer, default=0)
    status = Column(String(32), default="pending")  # pending -> sent -> applied | rejected | timeout
    created_by = Column(String(64), default="operator")
    created_at = Column(Float, nullable=False)
    sent_at = Column(Float, nullable=True)
    applied_at = Column(Float, nullable=True)

    node = relationship("Node", back_populates="configs")

    __table_args__ = (
        UniqueConstraint("node_id", "cfg_version", name="uq_node_cfg_version"),
    )


class MeshLink(Base):
    __tablename__ = "mesh_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(Float, nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    src_addr = Column(Integer, nullable=False)
    dst_addr = Column(Integer, nullable=False)
    rssi = Column(Float, nullable=False)
    snr_db = Column(Float, nullable=False)

    site = relationship("Site", back_populates="mesh_links")


class Gateway(Base):
    __tablename__ = "gateways"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    label = Column(String(128), nullable=False)
    lan_ip = Column(String(64), default="192.168.1.100")
    firmware = Column(String(64), default="esp32-gw-v1.0.4")
    last_seen = Column(Float, nullable=True)
    battery_mv = Column(Integer, default=12600)


# -------------------------------------------------------------------------
# Authentication & User Management Models
# -------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone_number = Column(String(32), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    google_id = Column(String(128), unique=True, index=True, nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    phone_verified = Column(Boolean, default=False, nullable=False)
    role = Column(String(32), default="user", nullable=False)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)
    last_login_at = Column(Float, nullable=True)

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    verification_codes = relationship("VerificationCode", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)
    created_at = Column(Float, nullable=False)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

    user = relationship("User", back_populates="sessions")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(Float, nullable=False)

    user = relationship("User", back_populates="reset_tokens")


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_type = Column(String(16), nullable=False)  # 'email' or 'phone'
    code = Column(String(64), nullable=False)
    expires_at = Column(Float, nullable=False)
    created_at = Column(Float, nullable=False)

    user = relationship("User", back_populates="verification_codes")

