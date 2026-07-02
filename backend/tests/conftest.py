"""Test fixtures - in-memory SQLite DB with JSONB -> JSON override."""
from __future__ import annotations
import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import configure_mappers
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from app.db.base import Base

# テスト全体で APP_ENCRYPTION_KEY を固定する（operator_applications の口座暗号化テスト用）。
# get_settings() は lru_cache されるため、Settings が最初にインスタンス化される前に
# 環境変数を設定しておく必要がある（モジュールロード時点で設定する）。
os.environ.setdefault("APP_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

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
import app.db.models.operator_application
import app.db.models.operator_profile
import app.db.models.bid
import app.db.models.message
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
