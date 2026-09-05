-- SUBSIDENCE-NET schema.
-- Runs automatically on first container start (docker-entrypoint-initdb.d).
-- One database serves both roles: TimescaleDB hypertables for sensor streams,
-- PostGIS geometry for the GIS/deformation-map layer.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================ sites & panels
-- A site is one monitored underground panel plus the surface field above it.
-- The mining parameters here are what drive the physics model in ml/simulator.
CREATE TABLE sites (
    id                      SERIAL PRIMARY KEY,
    slug                    TEXT UNIQUE NOT NULL,
    name                    TEXT NOT NULL,
    coalfield               TEXT,
    panel_geom              GEOMETRY(Polygon, 4326),   -- extraction panel outline
    seam_depth_m            REAL    NOT NULL DEFAULT 150,   -- H
    extraction_thickness_m  REAL    NOT NULL DEFAULT 3.0,   -- m
    subsidence_factor       REAL    NOT NULL DEFAULT 0.65,  -- a  (S_max = a * m)
    angle_of_draw_deg       REAL    NOT NULL DEFAULT 35,    -- beta
    face_advance_m_per_day  REAL    NOT NULL DEFAULT 4.0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sites_panel_gix ON sites USING GIST (panel_geom);

-- =================================================================== nodes
CREATE TABLE nodes (
    id                 BIGSERIAL PRIMARY KEY,
    site_id            INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    addr               INT NOT NULL,            -- 16-bit LoRa mesh address
    label              TEXT NOT NULL,
    geom               GEOMETRY(Point, 4326),   -- surface position
    elevation_m        REAL,
    hw_revision        TEXT DEFAULT 'esp32s3-lis3dh-e220-v1',
    installed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen          TIMESTAMPTZ,
    active_cfg_version INT NOT NULL DEFAULT 0,
    -- Baselines captured at commissioning; deformation is measured against these,
    -- which is why a re-levelled node must be re-baselined, not just re-zeroed.
    baseline_pitch_mdeg INT,
    baseline_roll_mdeg  INT,
    baseline_tof_mm     INT,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (site_id, addr)
);
CREATE INDEX nodes_geom_gix ON nodes USING GIST (geom);
CREATE INDEX nodes_site_idx ON nodes (site_id) WHERE is_active;

-- =============================================================== telemetry
CREATE TABLE telemetry (
    time         TIMESTAMPTZ NOT NULL,
    node_id      BIGINT      NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    pitch_mdeg   INT,
    roll_mdeg    INT,
    tilt_mdeg    REAL,          -- derived magnitude, denormalised for fast queries
    vib_rms_mg   INT,
    vib_peak_hz  INT,
    tof_mm       INT,
    crack_ohm    INT,
    vbat_mv      INT,
    rssi         SMALLINT,
    snr_db       REAL,
    flags        SMALLINT NOT NULL DEFAULT 0,
    hops         SMALLINT,
    seq          INT,
    PRIMARY KEY (node_id, time)
);
SELECT create_hypertable('telemetry', 'time', chunk_time_interval => INTERVAL '1 day');
ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'node_id',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('telemetry', INTERVAL '7 days');

-- Downsampled rollup so the dashboard can draw months without scanning raw rows.
CREATE MATERIALIZED VIEW telemetry_5m
WITH (timescaledb.continuous) AS
SELECT node_id,
       time_bucket('5 minutes', time) AS bucket,
       avg(tilt_mdeg)  AS tilt_mdeg_avg,
       max(tilt_mdeg)  AS tilt_mdeg_max,
       avg(vib_rms_mg) AS vib_rms_mg_avg,
       max(vib_rms_mg) AS vib_rms_mg_max,
       avg(tof_mm)     AS tof_mm_avg,
       avg(crack_ohm)  AS crack_ohm_avg,
       min(vbat_mv)    AS vbat_mv_min,
       count(*)        AS samples
FROM telemetry
GROUP BY node_id, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('telemetry_5m',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes');

-- ================================================================== events
-- Node-side threshold breaches. These arrive out of band, ahead of the duty cycle.
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,
    time        TIMESTAMPTZ NOT NULL,
    node_id     BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    event_code  SMALLINT NOT NULL,
    severity    SMALLINT NOT NULL,
    value       INT,
    threshold   INT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX events_time_idx ON events (time DESC);
CREATE INDEX events_node_idx ON events (node_id, time DESC);

-- ================================================================== alerts
-- Backend/ML-raised warnings, distinct from raw node events: an alert is a
-- judgement about the field, an event is a reading from one node.
CREATE TABLE alerts (
    id             BIGSERIAL PRIMARY KEY,
    site_id        INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    node_id        BIGINT REFERENCES nodes(id) ON DELETE SET NULL,
    raised_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity       SMALLINT NOT NULL,          -- 0 info .. 3 critical
    category       TEXT NOT NULL,              -- anomaly | threshold | forecast | health
    title          TEXT NOT NULL,
    detail         TEXT,
    anomaly_score  REAL,
    hours_to_threshold REAL,                   -- NULL when not forecastable
    damage_class   TEXT,                       -- NCB-style severity band
    zone_geom      GEOMETRY(Polygon, 4326),
    state          TEXT NOT NULL DEFAULT 'open',   -- open | acked | resolved
    acked_by       TEXT,
    acked_at       TIMESTAMPTZ,
    resolved_at    TIMESTAMPTZ,
    notified_sms   BOOLEAN NOT NULL DEFAULT FALSE,
    notified_push  BOOLEAN NOT NULL DEFAULT FALSE,
    notified_email BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX alerts_open_idx ON alerts (site_id, raised_at DESC) WHERE state <> 'resolved';
CREATE INDEX alerts_zone_gix ON alerts USING GIST (zone_geom);

-- =========================================================== node configs
-- Versioned so the dashboard can show exactly what a node is running versus
-- what was pushed, and so a failed downlink is visible rather than silent.
CREATE TABLE node_configs (
    id                 BIGSERIAL PRIMARY KEY,
    node_id            BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    cfg_version        INT NOT NULL,
    sample_interval_s  INT  NOT NULL DEFAULT 60,
    wor_period_ms      INT  NOT NULL DEFAULT 2000,
    tx_power_dbm       INT  NOT NULL DEFAULT 22,
    tilt_alert_mdeg    INT  NOT NULL DEFAULT 2000,
    vib_alert_mg       INT  NOT NULL DEFAULT 500,
    crack_alert_ohm    INT  NOT NULL DEFAULT 100,
    tilt_offset_pitch  INT  NOT NULL DEFAULT 0,
    tilt_offset_roll   INT  NOT NULL DEFAULT 0,
    flags              INT  NOT NULL DEFAULT 15,
    cfg_hash           INT,
    status             TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|applied|rejected|timeout
    created_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at            TIMESTAMPTZ,
    applied_at         TIMESTAMPTZ,
    attempts           INT NOT NULL DEFAULT 0,
    UNIQUE (node_id, cfg_version)
);
CREATE INDEX node_configs_pending_idx ON node_configs (node_id, created_at DESC)
    WHERE status IN ('pending', 'sent');

-- ============================================================== mesh links
-- Neighbour reports, kept as a time-series so the topology graph can be replayed
-- and so route re-heal after a node failure is provable, not just claimed.
CREATE TABLE mesh_links (
    time      TIMESTAMPTZ NOT NULL,
    src_addr  INT NOT NULL,
    dst_addr  INT NOT NULL,
    site_id   INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    rssi      SMALLINT,
    snr_db    REAL
);
SELECT create_hypertable('mesh_links', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX mesh_links_recent_idx ON mesh_links (site_id, time DESC);

-- ========================================================== ML inference
-- One row per node per inference pass: what the model saw and what it concluded.
CREATE TABLE inference (
    time               TIMESTAMPTZ NOT NULL,
    node_id            BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    anomaly_score      REAL,     -- 0..1, normalised reconstruction error
    is_anomaly         BOOLEAN,
    subsidence_mm      REAL,     -- estimated cumulative vertical displacement
    tilt_rate_mdeg_hr  REAL,
    predicted_tilt_24h REAL,
    hours_to_threshold REAL,
    damage_class       TEXT,
    model_version      TEXT,
    PRIMARY KEY (node_id, time)
);
SELECT create_hypertable('inference', 'time', chunk_time_interval => INTERVAL '1 day');

-- =============================================================== risk zones
-- Interpolated deformation surface, polygonised into bands for the GIS layer.
CREATE TABLE risk_zones (
    id            BIGSERIAL PRIMARY KEY,
    site_id       INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity      SMALLINT NOT NULL,
    damage_class  TEXT,
    max_tilt_mdeg REAL,
    max_strain_mm_m REAL,
    geom          GEOMETRY(Polygon, 4326) NOT NULL
);
CREATE INDEX risk_zones_gix ON risk_zones USING GIST (geom);
CREATE INDEX risk_zones_latest_idx ON risk_zones (site_id, computed_at DESC);

-- ============================================================== gateways
CREATE TABLE gateways (
    id           BIGSERIAL PRIMARY KEY,
    site_id      INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    slug         TEXT UNIQUE NOT NULL,
    label        TEXT,
    lan_ip       INET,                 -- for the app's direct-over-router path
    last_seen    TIMESTAMPTZ,
    firmware     TEXT,
    sim_balance_checked_at TIMESTAMPTZ,
    is_online    BOOLEAN NOT NULL DEFAULT FALSE
);

-- ========================================================== notifications
CREATE TABLE alert_recipients (
    id         BIGSERIAL PRIMARY KEY,
    site_id    INT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    role       TEXT,                  -- operator | planner | regulator
    phone      TEXT,
    email      TEXT,
    min_severity SMALLINT NOT NULL DEFAULT 2,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE
);
