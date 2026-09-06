"""Database schema, as SQLAlchemy Core tables.

Written to run on both SQLite (development, and the gateway's own offline
buffer) and PostgreSQL/TimescaleDB (the deployed stack). Nothing here is
dialect-specific; the Timescale hypertable and PostGIS geometry conversions are
applied separately in ``db.py`` and only when the dialect supports them.

Node positions are stored as plain lat/lon columns rather than a PostGIS
geometry so the same rows work in SQLite. The PostGIS geometry column is added
alongside on Postgres for spatial queries -- the GIS layer gains capability
without the core schema losing portability.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

sites = sa.Table(
    "sites", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("slug", sa.String(64), unique=True, nullable=False),
    sa.Column("name", sa.String(128), nullable=False),
    sa.Column("coalfield", sa.String(128)),
    sa.Column("origin_lat", sa.Float, nullable=False),
    sa.Column("origin_lon", sa.Float, nullable=False),
    # Mining parameters -- these drive the physics model.
    sa.Column("seam_depth_m", sa.Float, nullable=False, server_default="150"),
    sa.Column("extraction_thickness_m", sa.Float, nullable=False, server_default="3.0"),
    sa.Column("subsidence_factor", sa.Float, nullable=False, server_default="0.65"),
    sa.Column("angle_of_draw_deg", sa.Float, nullable=False, server_default="35"),
    # Operational state the mine already tracks: where the working face has
    # reached, and how fast it is advancing. The deformation model is driven by
    # these, so an operator updating the face position updates the prediction.
    sa.Column("face_x_m", sa.Float, nullable=False, server_default="0"),
    sa.Column("face_advance_m_per_day", sa.Float, nullable=False, server_default="12"),
    sa.Column("panel_x_start", sa.Float, nullable=False, server_default="0"),
    sa.Column("panel_x_end", sa.Float, nullable=False, server_default="600"),
    sa.Column("panel_y_min", sa.Float, nullable=False, server_default="-200"),
    sa.Column("panel_y_max", sa.Float, nullable=False, server_default="200"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)

nodes = sa.Table(
    "nodes", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("addr", sa.Integer, nullable=False),      # 16-bit LoRa mesh address
    sa.Column("label", sa.String(32), nullable=False),
    sa.Column("zone", sa.String(64)),
    sa.Column("lat", sa.Float),
    sa.Column("lon", sa.Float),
    sa.Column("x_m", sa.Float),                          # local metric position
    sa.Column("y_m", sa.Float),
    sa.Column("hw_revision", sa.String(64), server_default="esp32s3-lis3dh-e220-v1"),
    sa.Column("installed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("last_seen", sa.DateTime(timezone=True)),
    sa.Column("active_cfg_version", sa.Integer, nullable=False, server_default="0"),
    # Commissioning baselines: deformation is measured against these, which is why
    # a re-levelled node must be re-baselined rather than merely re-zeroed.
    sa.Column("baseline_pitch_mdeg", sa.Integer),
    sa.Column("baseline_roll_mdeg", sa.Integer),
    sa.Column("baseline_tof_mm", sa.Integer),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.UniqueConstraint("site_id", "addr", name="uq_node_site_addr"),
)

telemetry = sa.Table(
    "telemetry", metadata,
    sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
    sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="CASCADE"),
              nullable=False, primary_key=True),
    sa.Column("pitch_mdeg", sa.Integer),
    sa.Column("roll_mdeg", sa.Integer),
    sa.Column("tilt_mdeg", sa.Float),          # derived magnitude, denormalised
    sa.Column("vib_rms_mg", sa.Integer),
    sa.Column("vib_peak_hz", sa.Integer),
    sa.Column("tof_mm", sa.Integer),
    sa.Column("crack_ohm", sa.Integer),
    sa.Column("vbat_mv", sa.Integer),
    sa.Column("rssi", sa.Integer),
    sa.Column("snr_db", sa.Float),
    sa.Column("flags", sa.Integer, nullable=False, server_default="0"),
    sa.Column("hops", sa.Integer),
    sa.Column("seq", sa.Integer),
    sa.Index("ix_telemetry_node_time", "node_id", "time"),
)

events = sa.Table(
    "events", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("event_code", sa.Integer, nullable=False),
    sa.Column("severity", sa.Integer, nullable=False),
    sa.Column("value", sa.Integer),
    sa.Column("threshold", sa.Integer),
    sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Index("ix_events_time", "time"),
)

alerts = sa.Table(
    "alerts", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="SET NULL")),
    sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("severity", sa.Integer, nullable=False),     # 0 info .. 3 critical
    sa.Column("category", sa.String(32), nullable=False),  # threshold|anomaly|forecast|health
    sa.Column("title", sa.String(128), nullable=False),
    sa.Column("detail", sa.Text),
    sa.Column("tilt_deg", sa.Float),
    sa.Column("crack_mm", sa.Float),
    sa.Column("vibration_mg", sa.Float),
    sa.Column("damage_class", sa.String(32)),
    sa.Column("hours_to_threshold", sa.Float),
    sa.Column("state", sa.String(16), nullable=False, server_default="open"),
    sa.Column("acked_by", sa.String(64)),
    sa.Column("acked_at", sa.DateTime(timezone=True)),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("notified_sms", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Index("ix_alerts_raised", "site_id", "raised_at"),
)

node_configs = sa.Table(
    "node_configs", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("cfg_version", sa.Integer, nullable=False),
    sa.Column("sample_interval_s", sa.Integer, nullable=False, server_default="60"),
    sa.Column("wor_period_ms", sa.Integer, nullable=False, server_default="2000"),
    sa.Column("tx_power_dbm", sa.Integer, nullable=False, server_default="22"),
    sa.Column("tilt_alert_mdeg", sa.Integer, nullable=False, server_default="2000"),
    sa.Column("vib_alert_mg", sa.Integer, nullable=False, server_default="500"),
    sa.Column("crack_alert_ohm", sa.Integer, nullable=False, server_default="100"),
    sa.Column("tilt_offset_pitch", sa.Integer, nullable=False, server_default="0"),
    sa.Column("tilt_offset_roll", sa.Integer, nullable=False, server_default="0"),
    sa.Column("flags", sa.Integer, nullable=False, server_default="15"),
    sa.Column("cfg_hash", sa.Integer),
    # pending -> sent -> applied / rejected / timeout. Kept explicit so a failed
    # downlink is visible in the UI rather than silently lost.
    sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("created_by", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("sent_at", sa.DateTime(timezone=True)),
    sa.Column("applied_at", sa.DateTime(timezone=True)),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.UniqueConstraint("node_id", "cfg_version", name="uq_cfg_node_version"),
)

mesh_links = sa.Table(
    "mesh_links", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("src_addr", sa.Integer, nullable=False),
    sa.Column("dst_addr", sa.Integer, nullable=False),
    sa.Column("rssi", sa.Integer),
    sa.Column("snr_db", sa.Float),
    sa.Index("ix_mesh_recent", "site_id", "time"),
)

gateways = sa.Table(
    "gateways", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("slug", sa.String(64), unique=True, nullable=False),
    sa.Column("label", sa.String(128)),
    sa.Column("lan_ip", sa.String(64)),          # the app's direct-over-router path
    sa.Column("firmware", sa.String(64)),
    sa.Column("last_seen", sa.DateTime(timezone=True)),
    sa.Column("battery_mv", sa.Integer),
)
