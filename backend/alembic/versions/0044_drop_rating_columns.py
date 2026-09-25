"""★（rating）の DB 列の削除: reviews.rating（と★の範囲の CHECK）・operators.rating を落とす

Revision ID: 0044_drop_rating_columns
Revises: 0043_audit_active_no_license
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは24文字）。

背景（2026-09-25 ユーザー指示「推奨で実行して（＝使っていない★の列を DB から削除）」。
設計の正本: .agent-state/review-verdict/DESIGN-admin.md）:
- ★（rating）は 0042（と同じ日のコード＝段B）で入力・応答・集計から外し、続く段1 でモデルのマップと
  rating CHECK の宣言も撤去した。本リビジョンは残っていた DB 列（reviews.rating・operators.rating）と
  reviews の★の範囲の CHECK を削除する（0042 時点の「DB 列は残置」をユーザー指示で改める）。
- 反映は3段の段2（マイグレーションのみ）。段1 のコード（rating をマップしない）は列がある DB でも
  無い DB でも動くため、段1 の本番稼働を確認してから本リビジョンを出す。逆順（列が無いまま段1 より
  前のコードが動く）だと operators の読み取りが全部 500 になる。
- PostgreSQL では lock_timeout 3s で reviews → operators の順に ACCESS EXCLUSIVE を取り、取得後に
  10s へ戻す（0042 と同じ理由: 後段の DROP が ACCESS EXCLUSIVE を要するので最初から最も強いロックを
  取り、格上げによるデッドロックを避ける。書き込みの経路は reviews → operators の順に掴むので同じ順で
  取る。取れなければ失敗させ start.sh のリトライに任せる）。SQLite には無い構文のため発行しない。
- 冪等: 表ごとに inspector で rating 列の有無を見て、無ければ飛ばす（INFO に残す）。
- 取り消せない操作の手掛かり: 表ごとに非 NULL の件数を数え、1〜50 件なら (id, rating) も INFO に残す
  （downgrade では値は戻らない）。
- CHECK の名前は推測しない: inspector の get_check_constraints("reviews") のうち条件文が rating を参照する
  （単語境界で ``rating``）ものの名前を全て取り（名前の無いものは飛ばす）、batch の中で
  drop_constraint(op.f(名前)) → drop_column("rating") の順に落とす。op.f() は必須（命名規約
  "ck_%(table_name)s_%(constraint_name)s" は明示名にも前置されるため、素の名前だと二重化した別名で
  DROP して失敗する）。本番の実名は 0004 由来の "ck_reviews_ck_reviews_rating"
  （tests/test_review_model_constraints.py が 0004 のオフライン DDL で固定）。
- downgrade: 同じ順でロック → reviews に rating INTEGER NULL と CHECK（1〜5・実名
  ck_reviews_ck_reviews_rating）、operators に rating FLOAT NULL を戻す。値は NULL で戻る（削除した値は
  復元できない。0042 の downgrade は rating が NULL の評価を互換値で埋めるので、さらに前へも戻せる）。
  既に rating 列がある表は飛ばす（upgrade と対称の冪等）。
- app のコードは import しない（列名・制約の実名は値を複製している）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_drop_rating_columns"
down_revision: str | None = "0043_audit_active_no_license"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0044_drop_rating_columns")

# 非 NULL の★がこの件数以下なら (id, rating) も INFO に残す（取り消せない操作の手掛かり）。
_LOG_VALUES_MAX_ROWS = 50
# CHECK の条件文が rating 列を参照しているか（単語境界。reviewer_type 等には当たらない）。
_RATING_REFERENCE = re.compile(r"\brating\b")
# downgrade で作り直す★の範囲の CHECK（0004 が作った実名と条件）。
_RATING_CHECK_NAME = "ck_reviews_ck_reviews_rating"
_RATING_CHECK_CONDITION = "rating >= 1 AND rating <= 5"


def _lock_tables_for_alter() -> None:
    """PostgreSQL のみ: reviews → operators の順に ACCESS EXCLUSIVE を取る（LOCK の待ちだけ 3s）。"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
        op.execute(sa.text("LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE"))
        op.execute(sa.text("LOCK TABLE operators IN ACCESS EXCLUSIVE MODE"))
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))


def _has_rating_column(bind: sa.engine.Connection, table: str) -> bool:
    # inspector は結果をキャッシュするため、表を作り直す前後で都度作る。
    return any(column["name"] == "rating" for column in sa.inspect(bind).get_columns(table))


def _count_and_log_non_null_ratings(bind: sa.engine.Connection, table: str) -> int:
    """rating が非 NULL の件数を返し、1〜50 件なら (id, rating) を INFO に残す。

    table は本モジュール内の定数（"reviews" / "operators"）だけで、外部入力は混ざらない。
    """
    non_null = int(
        bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE rating IS NOT NULL")).scalar_one()
    )
    if 1 <= non_null <= _LOG_VALUES_MAX_ROWS:
        rows = bind.execute(
            sa.text(f"SELECT id, rating FROM {table} WHERE rating IS NOT NULL ORDER BY id")
        ).all()
        logger.info(
            "0044: 削除する %s.rating の値（id=rating・%s 件）: %s",
            table,
            non_null,
            ", ".join(f"{row_id}={rating}" for row_id, rating in rows),
        )
    return non_null


def _rating_check_names(bind: sa.engine.Connection) -> list[str]:
    """reviews の CHECK のうち rating を参照するものの実名（名前の無いものは飛ばす）。"""
    return [
        check["name"]
        for check in sa.inspect(bind).get_check_constraints("reviews")
        if check.get("name") and _RATING_REFERENCE.search(check.get("sqltext") or "")
    ]


def upgrade() -> None:
    bind = op.get_bind()
    _lock_tables_for_alter()

    dropped: list[str] = []
    if _has_rating_column(bind, "reviews"):
        reviews_non_null = _count_and_log_non_null_ratings(bind, "reviews")
        check_names = _rating_check_names(bind)
        with op.batch_alter_table("reviews") as batch_op:
            for check_name in check_names:
                batch_op.drop_constraint(op.f(check_name), type_="check")
            batch_op.drop_column("rating")
        dropped.append(
            f"reviews.rating（非NULL {reviews_non_null} 件・CHECK [{', '.join(check_names)}]）"
        )
    else:
        logger.info("0044: reviews.rating は既に無いため飛ばしました（冪等）。")

    if _has_rating_column(bind, "operators"):
        operators_non_null = _count_and_log_non_null_ratings(bind, "operators")
        with op.batch_alter_table("operators") as batch_op:
            batch_op.drop_column("rating")
        dropped.append(f"operators.rating（非NULL {operators_non_null} 件）")
    else:
        logger.info("0044: operators.rating は既に無いため飛ばしました（冪等）。")

    # 証跡（0038〜0043 と同じロガー方式。Render のログで削除の事実と件数を確認できる）。
    if dropped:
        logger.info("0044: %sを削除。", "と".join(dropped))


def downgrade() -> None:
    bind = op.get_bind()
    _lock_tables_for_alter()

    restored: list[str] = []
    if _has_rating_column(bind, "reviews"):
        logger.info("0044 の downgrade: reviews.rating は既にあるため飛ばしました。")
    else:
        with op.batch_alter_table("reviews") as batch_op:
            batch_op.add_column(sa.Column("rating", sa.Integer(), nullable=True))
            batch_op.create_check_constraint(op.f(_RATING_CHECK_NAME), _RATING_CHECK_CONDITION)
        restored.append(f"reviews.rating（CHECK {_RATING_CHECK_NAME}）")

    if _has_rating_column(bind, "operators"):
        logger.info("0044 の downgrade: operators.rating は既にあるため飛ばしました。")
    else:
        with op.batch_alter_table("operators") as batch_op:
            batch_op.add_column(sa.Column("rating", sa.Float(), nullable=True))
        restored.append("operators.rating")

    if restored:
        logger.info(
            "0044 の downgrade: %sを NULL 可の列として戻しました（削除した値は復元できず NULL のまま）。",
            "と".join(restored),
        )
