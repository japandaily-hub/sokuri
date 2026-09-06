"""ローカル Docker の PostgreSQL へ実マイグレーションを当てる（cp932 問題の回避付き）。

Windows（日本語ロケール）では ``alembic -c alembic.ini upgrade head`` が
``UnicodeDecodeError: 'cp932' codec can't decode byte ...`` で落ちる。原因は
alembic が ini を ``configparser.read(..., encoding="locale")`` で読むこと。
PEP 686 のとおり ``encoding="locale"`` は **UTF-8 モード（PYTHONUTF8=1 / -X utf8）の
影響を受けない**明示指定のため、`alembic.ini` に日本語コメントがあると必ず失敗する。

回避策として、ini から非 ASCII 文字を落とした一時コピーを作って ``-c`` で渡す
（`alembic.ini` 本体の日本語コメントは資産なので消さない）。`script_location` は
相対指定のため、本スクリプトは必ず `backend/` を cwd にして実行すること。

使い方（`docs/ops/e2e.md`「PG 同時実行チェック」の手順2）:
    cd backend
    DATABASE_URL=postgresql+asyncpg://postgres:kdz@127.0.0.1:55432/kdz \
      .venv/Scripts/python.exe scripts/pg_alembic_upgrade.py

引数はそのまま alembic のコマンドとして渡る（既定は ``upgrade head``）。
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent

if not os.environ.get("DATABASE_URL"):
    print(
        "[env] DATABASE_URL が未設定です（実 DB への誤適用を防ぐため既定値は使いません）。",
        file=sys.stderr,
    )
    raise SystemExit(2)
# alembic/env.py -> app.config.get_settings() は APP_ENCRYPTION_KEY を必須にするため、
# マイグレーション実行にだけ使う使い捨て鍵をここで用意する（DB へは書き込まれない）。
if not os.environ.get("APP_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet

    os.environ["APP_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")
os.environ.setdefault("APP_ENV", "development")


def main() -> int:
    os.chdir(BACKEND_DIR)  # script_location=alembic / prepend_sys_path=. が cwd 相対
    src = BACKEND_DIR / "alembic.ini"
    ascii_ini = src.read_text(encoding="utf-8").encode("ascii", "ignore").decode("ascii")
    with tempfile.TemporaryDirectory() as tmp:
        # NOTE: 一時 ini は backend/ 直下ではなく temp に置く（リポジトリを汚さない）。
        # alembic は script_location を cwd 相対で解決するため、置き場所は問題にならない。
        cfg_path = pathlib.Path(tmp) / "alembic.ascii.ini"
        cfg_path.write_text(ascii_ini, encoding="ascii")

        from alembic.config import main as alembic_main

        argv = sys.argv[1:] or ["upgrade", "head"]
        alembic_main(argv=["-c", str(cfg_path), *argv], prog="alembic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
