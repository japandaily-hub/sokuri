"""Review モデルの制約名が、alembic が本番に作った実名と一致することの回帰テスト。

モデルの ``__table_args__`` は、テストの create_all でも本番と同じ制約（二重投稿の一意制約・
評価の値）を効かせるためにある。Base.metadata の命名規約
``"ck_%(table_name)s_%(constraint_name)s"`` は明示名にも前置されるため、書き方を誤ると
名前が本番と食い違う（0040 の実装時に "ck_reviews_ck_reviews_verdict" が実際に出た）。

- 0004 由来（一意制約）: ファイルに書かれた文字列ではなく、0004 をオフライン
  （--sql・PostgreSQL 方言。DB には接続しない）で DDL に変換した結果を正とする。
- 0004 由来（★の範囲）: ★の撤去でモデルの宣言から外した（DB の CHECK と列は 0044 で削除）。
  0004 は create_table に "ck_reviews_rating" と書いたが、alembic の op にも命名規約が掛かるため
  実名は "ck_reviews_ck_reviews_rating"。0044 の upgrade は名前を推測せず DB から読むが、
  downgrade はこの実名で作り直すので、実名そのものはここで引き続き固定する。
- 0040 由来（評価の値）: op.f() による確定名 "ck_reviews_verdict"（SQLite での実 DDL は
  test_0040_review_verdict_migration.py が確認している）。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.config import get_settings
from app.db.models.transaction import Review

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"


def _reviews_ddl_from_0004(monkeypatch) -> str:
    """0004 の reviews の CREATE TABLE を、PostgreSQL 方言のオフライン DDL として返す。"""
    # URL は方言の選択にだけ使う（オフラインモードは接続しない）。
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://offline:offline@localhost:5432/offline"
    )
    get_settings.cache_clear()
    buffer = io.StringIO()
    try:
        # alembic.ini を読ませない理由は tests/test_0028_migration_dedup.py と同じ。
        cfg = Config(output_buffer=buffer)
        cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
        cfg.set_main_option("prepend_sys_path", ".")
        cfg.set_main_option("version_path_separator", "os")
        cfg.set_main_option("path_separator", "os")
        command.upgrade(cfg, "0003_add_albums:0004_katadzuke_schema", sql=True)
    finally:
        get_settings.cache_clear()
    match = re.search(r"CREATE TABLE reviews \((.*?)\n\);", buffer.getvalue(), re.S)
    assert match is not None, "0004 のオフライン DDL に reviews の CREATE TABLE が無い"
    return match.group(1)


def test_review_model_constraint_names_match_alembic_ddl(monkeypatch):
    reviews_ddl = _reviews_ddl_from_0004(monkeypatch)
    constraints = Review.__table__.constraints
    unique_names = [c.name for c in constraints if isinstance(c, UniqueConstraint)]
    check_names = {
        str(c.sqltext): c.name for c in constraints if isinstance(c, CheckConstraint)
    }

    assert unique_names == ["uq_reviews_transaction_reviewer"]
    assert (
        "CONSTRAINT uq_reviews_transaction_reviewer UNIQUE (transaction_id, reviewer_type)"
        in reviews_ddl
    )
    # ★の範囲: モデルは宣言しない（撤去済み）。0004 が実際に作った実名は 0044 の downgrade が
    # 作り直す名前として固定する。
    assert not any("rating" in sqltext for sqltext in check_names)
    assert "rating" not in Review.__table__.c
    assert "CONSTRAINT ck_reviews_ck_reviews_rating CHECK (rating >= 1 AND rating <= 5)" in reviews_ddl
    # 評価の値: 0040 が op.f() で確定させた名前（命名規約で二重化していないこと）。
    assert check_names == {"verdict IN ('good','improve')": "ck_reviews_verdict"}
