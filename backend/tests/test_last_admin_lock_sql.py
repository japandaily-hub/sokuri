"""最後の管理者の判定が PostgreSQL で行ロック（FOR NO KEY UPDATE・id 順）を取ることの回帰テスト。

本人の退会（users._is_last_active_admin）と降格（admin._has_other_active_admin）は、有効な
admin の行をロックしてから「最後の1人か」を数え、同時に行われても管理者が 0 人にならないように
している。pytest は SQLite で動き FOR UPDATE が無視されるため、ロック句を消しても既存テストは
落ちない。関数が組み立てる SELECT を PostgreSQL の方言でコンパイルし、ロック句と並び順（id 順＝
両経路で同じ順にロックを取りデッドロックを避ける）を固定する。実際の同時実行は CI の
scripts/pg_concurrency_check.py の S7 で検証する。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.api.v1.endpoints import admin as admin_endpoint
from app.api.v1.endpoints import users as users_endpoint
from app.db.models.user import User


def _capturing_session() -> tuple[MagicMock, dict[str, Any]]:
    """``session.scalars(stmt)`` に渡された文を記録するだけの疑似セッション（結果は空）。"""
    captured: dict[str, Any] = {}
    empty_result = MagicMock()
    empty_result.all.return_value = []

    async def scalars(stmt: Any) -> MagicMock:
        captured["stmt"] = stmt
        return empty_result

    session = MagicMock()
    session.scalars = scalars
    return session, captured


def _postgresql_sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


async def test_self_withdrawal_check_locks_admin_rows_in_id_order_on_postgresql():
    session, captured = _capturing_session()
    admin = User(email="lock-check@example.com", role="admin")
    admin.id = uuid.uuid4()

    assert await users_endpoint._is_last_active_admin(session, admin) is True

    sql = _postgresql_sql(captured["stmt"])
    assert "FOR NO KEY UPDATE" in sql
    assert "ORDER BY users.id" in sql


async def test_demote_check_locks_admin_rows_in_id_order_on_postgresql():
    session, captured = _capturing_session()

    assert await admin_endpoint._has_other_active_admin(session, uuid.uuid4()) is False

    sql = _postgresql_sql(captured["stmt"])
    assert "FOR NO KEY UPDATE" in sql
    assert "ORDER BY users.id" in sql
