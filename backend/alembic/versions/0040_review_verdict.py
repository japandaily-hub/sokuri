"""reviews に verdict（よかった／伸びしろ）、operators に good_count / improve_count を追加（評価の2択化・expand）

Revision ID: 0040_review_verdict
Revises: 0039_sessions_revoked_at
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは19文字）。

背景（2026-09-25 ユーザー決定。設計の正本: .agent-state/review-verdict/DESIGN.md）:
- 評価を★1〜5 から、メルカリに倣った「よかった／伸びしろ」の2択へ移す。本リビジョンは
  expand/contract の expand 段階で、列の追加と既存データの変換のみを行う。
  verdict の NOT NULL 化と応答からの rating 削除は後続の 0042（contract・別チケット）。
- reviews.verdict は NULL 可（CHECK 付き）。NULL は CHECK を通るため、本リビジョン適用後
  新コードへ切り替わるまでの間に旧コード（verdict を知らない）が INSERT しても失敗しない。
  NULL の行はアプリ側 Review.verdict のハイブリッド（rating >= 4 → good）で読む。その間に
  旧コードが書いた行の verdict 補完と件数の再計算は 0041（P2 と同梱）が行う。
- 既存行の対応は ★4・5 → good／★1〜3 → improve（reviewer_type・非表示を問わず全行）。
  閾値 4 は app/db/models/transaction.py の LEGACY_GOOD_MIN_RATING と同値
  （マイグレーションは app を import しない方針のため値を複製している。0041 も同じ。変えるなら全て）。
- rating は一度も書き換えない（NOT NULL のまま）。downgrade 後も旧コードがそのまま動く。
- operators.good_count / improve_count を追加し、review_count と同じ母集団
  （依頼者→業者・非表示を除く。services/review_stats.py と同じ）で全業者を再計算する。
  review_count もここで同じ母集団から数え直し、不変条件
  review_count = good_count + improve_count を成立させる（ずれていた業者数は WARNING で残す）。
- SQLite（テスト）と PostgreSQL（本番）の両方で通るよう、集計は相関サブクエリで書く
  （0024 の UPDATE ... FROM / DISTINCT ON は PostgreSQL 専用のため使わない）。
- PostgreSQL では本リビジョン全体が1トランザクション（env.py の
  transaction_per_migration=True）。ACCESS EXCLUSIVE を取る operators の ALTER は
  reviews の変換の後ろに置き、保持時間を最短にする。
- SQLite の batch（テーブル作り直し）で既存の名前付き制約（ck_reviews_rating /
  ck_reviews_reviewer_type / uq_reviews_transaction_reviewer）と FK が残ることは
  tests/test_0040_review_verdict_migration.py で固定している。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_review_verdict"
down_revision: str | None = "0039_sessions_revoked_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0040_review_verdict")

# ★この値以上を「よかった」とみなす（app 側 LEGACY_GOOD_MIN_RATING と同値。上記 docstring 参照）。
_LEGACY_GOOD_MIN_RATING = 4

# 業者1件ぶんの集計対象（依頼者→業者・非表示を除く）を数える相関サブクエリ。
# 母集団は services/review_stats.recalc_operator_review_stats と同じ。外側の operators を
# 別名なしで参照する（PostgreSQL の UPDATE でも SQLite でも同じ文で通る）。
# 以下の SQL 断片は全て定数の連結で、外部入力は一切混ざらない。
_VISIBLE_USER_REVIEW_COUNT_SQL = (
    "SELECT COUNT(*) FROM reviews r"
    " JOIN transactions t ON t.id = r.transaction_id"
    " JOIN bids b ON b.id = t.bid_id"
    " WHERE b.operator_id = operators.id"
    " AND r.reviewer_type = 'user' AND r.hidden_at IS NULL"
)


def _rowcount(result: sa.engine.CursorResult) -> int:
    # ドライバが件数を返さない（-1 / None）場合は 0 として扱う（0038 と同じ方式）。
    return result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0


def upgrade() -> None:
    bind = op.get_bind()
    # U0: ロック待ちで起動を詰まらせない（取れなければ失敗させ start.sh のリトライに任せる）。
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))

    # U1: 列と CHECK の追加。PostgreSQL では ALTER TABLE がそのまま出る（作り直さない）。
    # SQLite は CHECK を ALTER で足せないため batch がテーブルを作り直す。
    # 制約名は op.f() で確定名として渡す: env.py の target_metadata（Base.metadata）の命名規約
    # "ck_%(table_name)s_%(constraint_name)s" が op にも適用され、素の文字列だと
    # "ck_reviews_ck_reviews_verdict" に二重化する（モデル側 name="verdict" の展開結果と揃える）。
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.add_column(sa.Column("verdict", sa.String(length=16), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_reviews_verdict"), "verdict IN ('good','improve')"
        )

    # U2: 既存行の変換（reviewer_type を問わず、非表示の行も含めて全行）。
    converted = _rowcount(
        bind.execute(
            sa.text(
                "UPDATE reviews SET verdict = CASE WHEN rating >= :good_min_rating"
                " THEN 'good' ELSE 'improve' END WHERE verdict IS NULL"
            ).bindparams(good_min_rating=_LEGACY_GOOD_MIN_RATING)
        )
    )
    breakdown = bind.execute(
        sa.text(
            "SELECT"
            " COALESCE(SUM(CASE WHEN reviewer_type = 'user' AND verdict = 'good'"
            " THEN 1 ELSE 0 END), 0),"
            " COALESCE(SUM(CASE WHEN reviewer_type = 'user' AND verdict = 'improve'"
            " THEN 1 ELSE 0 END), 0),"
            " COALESCE(SUM(CASE WHEN reviewer_type = 'user' AND verdict = 'improve'"
            " AND rating = 3 THEN 1 ELSE 0 END), 0),"
            " COALESCE(SUM(CASE WHEN reviewer_type = 'operator' AND verdict = 'good'"
            " THEN 1 ELSE 0 END), 0),"
            " COALESCE(SUM(CASE WHEN reviewer_type = 'operator' AND verdict = 'improve'"
            " THEN 1 ELSE 0 END), 0)"
            " FROM reviews"
        )
    ).one()
    user_good, user_improve, user_improve_from_3, op_good, op_improve = (
        int(v) for v in breakdown
    )

    # U3: 集計列の追加（定数の既定値付き NOT NULL。PostgreSQL 11+ はメタデータ更新のみ）。
    op.add_column(
        "operators",
        sa.Column("good_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "operators",
        sa.Column("improve_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # U4: review_count が実件数とずれている業者数（証跡。U5 で補正される）。
    drifted = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM operators"
                f" WHERE operators.review_count <> ({_VISIBLE_USER_REVIEW_COUNT_SQL})"
            )
        ).scalar_one()
    )

    # U5: 全業者の集計を同じ母集団から再計算（review_count = good_count + improve_count）。
    # U1 の ALTER で reviews は本トランザクション終了まで排他ロック中のため、ここまでの間に
    # verdict が NULL の行が挿入されることはない（全行が good / improve のどちらか）。
    recalculated = _rowcount(
        bind.execute(
            sa.text(
                "UPDATE operators SET"
                f" good_count = ({_VISIBLE_USER_REVIEW_COUNT_SQL} AND r.verdict = 'good'),"
                f" improve_count = ({_VISIBLE_USER_REVIEW_COUNT_SQL} AND r.verdict = 'improve'),"
                f" review_count = ({_VISIBLE_USER_REVIEW_COUNT_SQL})"
            )
        )
    )

    # U6: 証跡（0038 と同じロガー方式。Render のログで件数を確認できる）。
    logger.info(
        "0040: reviews.verdict を %s 件設定（依頼者→業者: よかった %s／伸びしろ %s〔うち★3 %s〕、"
        "業者→依頼者: よかった %s／伸びしろ %s）。業者 %s 件の集計を再計算（review_count の補正 %s 件）。",
        converted,
        user_good,
        user_improve,
        user_improve_from_3,
        op_good,
        op_improve,
        recalculated,
        drifted,
    )
    if drifted > 0:
        logger.warning(
            "0040: review_count が公開中の依頼者レビュー件数とずれていた業者が %s 件ありました"
            "（再計算で補正済み。集計の更新漏れの経路を調べ docs/ops/incidents.md へ記録すること）。",
            drifted,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))

    op.drop_column("operators", "improve_count")
    op.drop_column("operators", "good_count")
    # CHECK が verdict を参照しているため、列より先に制約を落とす（SQLite の batch は
    # CHECK の SQL を解析できず、列だけ落とすと作り直し後の表に壊れた CHECK が残る）。
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_constraint(op.f("ck_reviews_verdict"), type_="check")
        batch_op.drop_column("verdict")
    # rating は upgrade で一度も書き換えていないため戻す処理は不要。
    # review_count の補正（U5）は「正しい値への是正」のため戻さない。
