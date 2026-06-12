"""Test fixtures - in-memory SQLite DB with JSONB -> JSON override."""
from __future__ import annotations
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import configure_mappers
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from app.db.base import Base

# Override JSONB -> JSON for SQLite (JSONB is PG-specific, SQLite uses JSON)
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

import app.db.models.channel
import app.db.models.item
import app.db.models.routing
import app.db.models.assessment
import app.db.models.defect
# カタヅケ
import app.db.models.case
import app.db.models.operator
import app.db.models.bid
import app.db.models.transaction
import app.db.models.user
import app.db.models.invite
configure_mappers()

@pytest.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(db_engine) -> AsyncSession:
    session_factory = async_sessionmaker(
        bind=db_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
