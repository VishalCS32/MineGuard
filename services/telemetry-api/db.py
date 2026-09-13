"""Storage. SQLite by default so it runs anywhere; Postgres when asked.

One table. Hot fields are promoted to columns because those are the ones
anything queries or charts, and the whole document is kept alongside them --
so a field this schema gains tomorrow is not lost today just because there is
no column for it yet.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

metadata = sa.MetaData()

readings = sa.Table(
    "readings", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("node_id", sa.String(64), nullable=False, index=True),
    # When the reading was taken, per the node.
    sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
    # When we got it. Kept separately: the gap between the two is how you see
    # a gateway that has been spooling through a backhaul outage, and merging
    # them would erase exactly that.
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),

    sa.Column("roll_deg", sa.Float),
    sa.Column("pitch_deg", sa.Float),
    sa.Column("vib_rms", sa.Float),
    sa.Column("temperature_c", sa.Float),
    sa.Column("battery_mv", sa.Integer),
    sa.Column("latitude", sa.Float),
    sa.Column("longitude", sa.Float),
    sa.Column("altitude", sa.Float),
    sa.Column("satellites", sa.Integer),
    sa.Column("rssi_dbm", sa.Integer),
    sa.Column("snr_db", sa.Float),
    sa.Column("flags", sa.Integer, nullable=False, server_default="0"),

    # The document exactly as it arrived.
    sa.Column("raw", sa.JSON, nullable=False),
)

_engine: AsyncEngine | None = None
_session: async_sessionmaker | None = None


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./telemetry.db")
    # Accept the postgres:// form every PaaS hands out, and route it to the
    # async driver this service actually uses.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def session_factory() -> async_sessionmaker:
    global _engine, _session
    if _session is None:
        _engine = create_async_engine(database_url(), pool_pre_ping=True)
        _session = async_sessionmaker(_engine, expire_on_commit=False)
    return _session


async def init_db() -> None:
    factory = session_factory()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    del factory


async def dispose_db() -> None:
    global _engine, _session
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session = None
