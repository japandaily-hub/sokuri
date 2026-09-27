"""本番の DB 例外の文言に SQL のパラメータ値を載せないこと（app/db/session.py の hide_parameters）。

SQLAlchemy は既定で例外文に ``[parameters: (...)]``（INSERT/UPDATE した値そのもの＝メール・氏名・
住所・メッセージ本文など）を含める。それが ``logger.error(... %s, exc)``・トレースバック・運営
アラートの本文を通って Render のログへ残るため、本番では隠す（2026-09-27 のログ点検で対処）。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("app_env", "expected"), [("production", "True"), ("development", "False")])
def test_engine_hides_sql_parameters_only_in_production(app_env: str, expected: str):
    """エンジンはモジュールの読み込み時に作られるため、環境変数を変えた別プロセスで確かめる。"""
    env = {key: value for key, value in os.environ.items() if key not in {"APP_ENV", "DATABASE_URL"}}
    env.update(
        {"APP_ENV": app_env, "DATABASE_URL": "sqlite+aiosqlite:///:memory:", "PYTHONUTF8": "1"}
    )
    result = subprocess.run(
        [sys.executable, "-c", "from app.db.session import engine; print(engine.sync_engine.hide_parameters)"],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("hide_parameters", [False, True])
async def test_hide_parameters_removes_values_from_error_text(hide_parameters: bool):
    """hide_parameters の有無で、例外文に入れた値が載る／載らないことを実際の例外で確かめる。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", hide_parameters=hide_parameters)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE people (email TEXT UNIQUE, name TEXT)"))
            values = {"email": "taro@example.com", "name": "山田太郎"}
            await conn.execute(text("INSERT INTO people VALUES (:email, :name)"), values)
            with pytest.raises(IntegrityError) as excinfo:
                await conn.execute(text("INSERT INTO people VALUES (:email, :name)"), values)
    finally:
        await engine.dispose()

    message = str(excinfo.value)
    assert "INSERT INTO people" in message  # SQL 文は残る（原因の切り分けはできる）
    assert ("taro@example.com" in message) is not hide_parameters
    assert ("山田太郎" in message) is not hide_parameters
