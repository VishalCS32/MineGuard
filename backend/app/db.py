"""Database engine and bootstrap.

The core schema is dialect-neutral so the same code runs on SQLite (development,
and the gateway's own offline buffer) and on PostgreSQL. When the dialect is
Postgres we additionally enable TimescaleDB and PostGIS: telemetry becomes a
hypertable with a compression policy, and nodes gain a real geometry column for
spatial queries. Those are enhancements layered on top, never requirements --
losing them costs performance and spatial SQL, not correctness.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import metadata

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"echo": False, "future": True}
        if not settings.is_postgres:
            # SQLite: allow use across the event loop's threads.
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_async_engine(settings.database_url, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def session_dep():
    """FastAPI dependency yielding a session."""
    async with get_sessionmaker()() as session:
        yield session


# Timescale/PostGIS extras, applied only where the dialect supports them.
_PG_EXTRAS = [
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    "CREATE EXTENSION IF NOT EXISTS postgis",
    "SELECT create_hypertable('telemetry', 'time', "
    "  chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE, migrate_data => TRUE)",
    "SELECT create_hypertable('mesh_links', 'time', "
    "  chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE, migrate_data => TRUE)",
    "ALTER TABLE telemetry SET (timescaledb.compress, "
    "  timescaledb.compress_segmentby = 'node_id', timescaledb.compress_orderby = 'time DESC')",
    "SELECT add_compression_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE)",
    "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326)",
    "CREATE INDEX IF NOT EXISTS nodes_geom_gix ON nodes USING GIST (geom)",
]


async def init_db(drop: bool = False) -> None:
    """Create the schema, then apply Postgres-only enhancements if available."""
    engine = get_engine()
    settings = get_settings()

    async with engine.begin() as conn:
        if drop:
            await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)

    if not settings.is_postgres:
        log.info("Using %s -- Timescale/PostGIS extras skipped", engine.dialect.name)
        return

    async with engine.begin() as conn:
        for statement in _PG_EXTRAS:
            try:
                await conn.execute(sa.text(statement))
            except Exception as exc:  # pragma: no cover - depends on server build
                # A stock Postgres without the extensions is still perfectly
                # usable; log loudly and carry on rather than refusing to start.
                log.warning("Optional DDL skipped (%s): %s", statement.split()[0], exc)


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
