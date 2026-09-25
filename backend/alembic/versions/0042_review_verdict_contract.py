"""評価の2択化の後片付け（contract）: reviews.verdict を NOT NULL に、reviews.rating を NULL 可にする

Revision ID: 0042_review_verdict_contract
Revises: 0041_review_verdict_recount
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは28文字）。

背景（2026-09-25 ユーザー指示「★は要らない。よかった／伸びしろの合計数が分かれば良い」。
設計の正本: .agent-state/review-verdict/DESIGN-0042.md）:
- 0040（expand）・0041（ずれの補正）・web の反映が済んだため、★（rating）を応答・入力・集計から
  外す。本リビジョンはその DB 側の後片付けで、verdict を NOT NULL に、rating を NULL 可にする
  （段B のコードは rating を書かない＝以後の新しい評価は NULL）。
- DB の★列（reviews.rating・operators.rating）は削除しない（取り消せない操作のため。
  operator_profiles の is_public 等と同じく「撤去済み・DB 列は残置」）。
- 反映は2段: 本リビジョン（段A）は現行コード（verdict と互換の rating を必ず書く）と両立する。
  段B（rating を書かないコード）は本リビジョンの本番適用を確認してから出す（逆順だと rating に
  NULL を書いて NOT NULL 違反＝投稿が 500 になる）。
- PostgreSQL では最初に lock_timeout と ``LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE`` を取る。
  後段の ALTER（NOT NULL 化）が ACCESS EXCLUSIVE を要するため、最初から最も強いロックを取り、
  ロックの格上げによるデッドロックを避ける。reviews は極小で保持は数ミリ秒。アプリの経路は
  いずれも reviews に触れてから operators の行を掴む（投稿・非表示の集計）ため、operators の
  行ロックを握ったまま reviews を待つ経路は無く、R3 との間に循環は生じない。LOCK の待ち
  だけは lock_timeout 3s で打ち切る（ACCESS EXCLUSIVE を待つ間は後から来た読み手もその後ろに並ぶ
  ため、待つ時間を短くして読み取りを止める時間を抑える。取れなければ失敗させ start.sh の
  リトライに任せる）。取得後は他のマイグレーションと同じ 10s に戻す（後段の ALTER・UPDATE 用）。
  SQLite には無い構文のため発行しない（2026-09-25 security review L-1）。
- R1: verdict が NULL の行を 0040 と同じ式（★4以上＝good）で補完する（段A 時点の本番コードは
  verdict を必ず書くので通常 0 件。NOT NULL 化の前提を満たすための保険）。
- R2: batch で verdict を NOT NULL、rating を NULL 可にする（rating の CHECK 1〜5 は NULL を
  通すので触らない。PostgreSQL は ALTER COLUMN、SQLite は表の作り直し）。
- R3: 0041 と同じ「ずれている業者だけ」の再計算（母集団は依頼者→業者・非表示を除く＝
  services/review_stats.py と同じ。verdict は NOT NULL になったので素の列で数える）。
- downgrade: rating が NULL の行（段B 以降に書かれた行）を互換値（good=5／improve=2。0040〜0041 期の
  アプリの COMPAT_RATING_BY_VERDICT と同値）で埋めてから、rating を NOT NULL・verdict を NULL 可へ
  戻す。operators.rating（★平均）は段B 以降は更新されないため、戻した旧コードの次の集計まで古い
  値のまま残る。
- app のコードは import しない（閾値・互換値は値を複製している）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_review_verdict_contract"
down_revision: str | None = "0041_review_verdict_recount"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0042_review_verdict_contract")

# ★この値以上を「よかった」とみなす（0040・0041 と同値）。
_LEGACY_GOOD_MIN_RATING = 4
# downgrade で rating が NULL の行に書く互換値（よかった=5／伸びしろ=2）。
_COMPAT_RATING_GOOD = 5
_COMPAT_RATING_IMPROVE = 2

# 業者1件ぶんの集計対象（依頼者→業者・非表示を除く）の相関サブクエリ。母集団は
# services/review_stats.recalc_operator_review_stats・0040・0041 と同じ。外側の operators を
# 別名なしで参照する（PostgreSQL の UPDATE でも SQLite でも同じ文で通る）。operators にも
# rating 列があるため、reviews 側の列は必ず r. で修飾する。以下は全て定数の連結で、
# 外部入力は混ざらない。
_VISIBLE_USER_REVIEWS_SQL = (
    "SELECT COUNT(*) FROM reviews r"
    " JOIN transactions t ON t.id = r.transaction_id"
    " JOIN bids b ON b.id = t.bid_id"
    " WHERE b.operator_id = operators.id"
    " AND r.reviewer_type = 'user' AND r.hidden_at IS NULL"
)
_GOOD_COUNT_SQL = f"({_VISIBLE_USER_REVIEWS_SQL} AND r.verdict = 'good')"
_IMPROVE_COUNT_SQL = f"({_VISIBLE_USER_REVIEWS_SQL} AND r.verdict = 'improve')"
_REVIEW_COUNT_SQL = f"({_VISIBLE_USER_REVIEWS_SQL})"
# 再計算値と good_count / improve_count / review_count のいずれかがずれている業者
# （件数の確認と更新対象に同じ条件を使う）。
_DRIFTED_OPERATOR_SQL = (
    f"(operators.good_count <> {_GOOD_COUNT_SQL}"
    f" OR operators.improve_count <> {_IMPROVE_COUNT_SQL}"
    f" OR operators.review_count <> {_REVIEW_COUNT_SQL})"
)


def _rowcount(result: sa.engine.CursorResult) -> int:
    # ドライバが件数を返さない（-1 / None）場合は 0 として扱う（0038 と同じ方式）。
    return result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0


def _lock_reviews_for_alter() -> None:
    """PostgreSQL のみ: reviews を最初から ACCESS EXCLUSIVE で掴む（LOCK の待ちだけ 3s。docstring 参照）。"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
        op.execute(sa.text("LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE"))
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))


def upgrade() -> None:
    bind = op.get_bind()
    _lock_reviews_for_alter()

    # R1: verdict が NULL の行を補完（reviewer_type・非表示を問わず全行。NOT NULL 化の前提）。
    filled = _rowcount(
        bind.execute(
            sa.text(
                "UPDATE reviews SET verdict = CASE WHEN rating >= "
                f"{int(_LEGACY_GOOD_MIN_RATING)} THEN 'good' ELSE 'improve' END"
                " WHERE verdict IS NULL"
            )
        )
    )

    # R2: verdict を NOT NULL、rating を NULL 可に（rating の CHECK は NULL を通すので残す）。
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.alter_column("verdict", existing_type=sa.String(length=16), nullable=False)
        batch_op.alter_column("rating", existing_type=sa.Integer(), nullable=True)

    # R3: 件数がずれている業者だけを再計算（ずれの無い業者の行は更新しない）。
    drifted = int(
        bind.execute(
            sa.text(f"SELECT COUNT(*) FROM operators WHERE {_DRIFTED_OPERATOR_SQL}")
        ).scalar_one()
    )
    recalculated = _rowcount(
        bind.execute(
            sa.text(
                "UPDATE operators SET"
                f" good_count = {_GOOD_COUNT_SQL},"
                f" improve_count = {_IMPROVE_COUNT_SQL},"
                f" review_count = {_REVIEW_COUNT_SQL}"
                f" WHERE {_DRIFTED_OPERATOR_SQL}"
            )
        )
    )

    # 証跡（0038〜0041 と同じロガー方式。Render のログで件数を確認できる）。
    logger.info(
        "0042: verdict を %s 件補完し NOT NULL 化、rating を NULL 可に変更。"
        "件数がずれていた業者 %s 件を再計算（更新 %s 件）。",
        filled,
        drifted,
        recalculated,
    )
    if drifted > 0:
        logger.warning(
            "0042: 評価の件数（よかった／伸びしろ／合計）がずれていた業者が %s 件ありました"
            "（再計算で補正済み。0041 以降に集計の更新漏れがあった経路を調べ docs/ops/incidents.md へ"
            "記録すること）。",
            drifted,
        )


def downgrade() -> None:
    bind = op.get_bind()
    _lock_reviews_for_alter()

    # D1: 段B 以降に書かれた rating が NULL の行を互換値で埋める（NOT NULL へ戻す前提）。
    filled = _rowcount(
        bind.execute(
            sa.text(
                "UPDATE reviews SET rating = CASE WHEN verdict = 'good'"
                f" THEN {int(_COMPAT_RATING_GOOD)} ELSE {int(_COMPAT_RATING_IMPROVE)} END"
                " WHERE rating IS NULL"
            )
        )
    )
    # D2: 制約を 0041 時点へ戻す。
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.alter_column("rating", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("verdict", existing_type=sa.String(length=16), nullable=True)
    logger.info(
        "0042 の downgrade: rating が NULL だった評価 %s 件を互換値（よかった=5／伸びしろ=2）で埋め、"
        "rating を NOT NULL・verdict を NULL 可へ戻しました。",
        filled,
    )
