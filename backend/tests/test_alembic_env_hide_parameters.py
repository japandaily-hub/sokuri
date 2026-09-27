"""alembic のエンジン（alembic/env.py）も、development 以外では失敗した文の SQL パラメータを例外文に載せない。

マイグレーションの失敗の出力は /tmp/alembic-last.log → Render のログ・/readyz の migration_log_tail に
残る（backend/start.sh）。アプリのエンジン（app/db/session.py・tests/test_db_engine_hide_parameters.py）と
同じ判定（隠す側に倒す）であることを、実際に ``alembic upgrade`` から env.py を通して確かめる。
env.py は alembic が読み込むときにだけ実行できるため、別プロセスでエンジンの生成関数を差し替え、
渡された引数を記録して止める（DB には接続しない）。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]

_CHILD_SCRIPT = textwrap.dedent(
    """
    import sqlalchemy.ext.asyncio as sa_asyncio
    from alembic import command
    from alembic.config import Config

    captured = {}


    class _Stop(Exception):
        pass


    def _capture(configuration, prefix="sqlalchemy.", **kwargs):
        captured.update(kwargs)
        raise _Stop()


    # env.py は読み込み時に ``from sqlalchemy.ext.asyncio import async_engine_from_config`` する。
    sa_asyncio.async_engine_from_config = _capture
    # alembic.ini は読まずに組み立てる（alembic は ini を encoding="locale" で読むため、日本語の
    # コメントを含む ini が Windows の cp932 では読めない。本番・CI の Linux では問題にならない）。
    # env.py が使うのは script_location と、env.py 自身が設定する sqlalchemy.url だけ。
    config = Config()
    config.set_main_option("script_location", "alembic")
    try:
        command.upgrade(config, "head")
    except _Stop:
        pass
    print("hide_parameters=%r" % (captured.get("hide_parameters", "<missing>"),))
    """
)


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [
        ("production", True),
        ("development", False),
        # 綴りゆれ・未知の値は隠す側に倒す（表示するのは development のときだけ）。
        ("Production", True),
        ("staging", True),
    ],
)
def test_alembic_engine_hides_sql_parameters_except_in_development(app_env: str, expected: bool):
    env = {key: value for key, value in os.environ.items() if key not in {"APP_ENV", "DATABASE_URL"}}
    env.update(
        {"APP_ENV": app_env, "DATABASE_URL": "sqlite+aiosqlite:///:memory:", "PYTHONUTF8": "1"}
    )
    result = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert result.stdout.strip().splitlines()[-1] == f"hide_parameters={expected!r}"
