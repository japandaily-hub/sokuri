"""P1〜P2 の間に旧コードが書いた評価（verdict 未設定）の補完と、業者の評価件数の再計算（データ是正）

Revision ID: 0041_review_verdict_recount
Revises: 0040_review_verdict
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは27文字）。

背景（2026-09-25 security review Medium／QA #7）:
- 0040（expand。P1 で先行デプロイ）の適用から新コード（P2）への切替までの間は旧コードが動く。
  旧コードは verdict を知らないため、その間の投稿は verdict 列が NULL のまま入り（CHECK は
  NULL を通す）、集計も rating / review_count だけを更新して good_count / improve_count を
  更新しない（運営の非表示・再表示も同じ）。結果として review_count ≠ good_count + improve_count
  の業者が、その業者の次の投稿・非表示操作まで残る。
- 本リビジョンは P2（新コード）と同梱で適用し、(1) verdict が NULL の行を 0040 の U2 と同じ式
  （★4以上＝good）で補完し、(2) 全業者の good_count / improve_count / review_count を
  services/review_stats.py と同じ母集団（依頼者→業者・非表示を除く）から再計算する。
  verdict は COALESCE(verdict, ★由来) で数える（(1) の後に NULL は残らないが、アプリ側
  Review.verdict の SQL 式と同じ規則で数えることを明示する）。
- DDL は一切使わない（列・制約は変えない）。
- PostgreSQL では operators に触る前（R1 の前）に ``LOCK TABLE reviews IN SHARE MODE`` を取る
  （2026-09-25 security review Low-1）。P2 のデプロイ中は旧コードが並走し、R3 の相関サブクエリは
  文の開始時点のスナップショットで数えるため、ロックが無いと並走した投稿・非表示を古い件数で
  上書きしうる。SHARE は INSERT/UPDATE/DELETE（ROW EXCLUSIVE）と衝突するので、取得時点で
  書き込み中のトランザクションの commit を待ち、以後は本リビジョンの終わりまで口コミの書き込みを
  待たせる（読み取りは止めない。自分の R1 の UPDATE は同じトランザクションなので衝突しない）。
  ロック順は reviews → operators で、旧コードの投稿・非表示（reviews を書いてから集計で
  operators 行を掴む）と同じ順のためデッドロックの環を作らない。待ちは lock_timeout 10s で
  打ち切り、失敗時は start.sh のリトライに任せる。SQLite には無い構文のため発行しない。
- R3 は R2 と同じ「ずれている業者だけ」を更新する（行ロックと書き込みを最小にする）。
- 冪等: ずれが無ければ何も更新しない（補完 0 件・再計算 0 件）。
- downgrade は no-op（0038 と同じく「正しい値への是正」のため戻す意味が無い。0040 の
  downgrade は verdict 列と集計列ごと落とすため、本リビジョンを戻さなくても支障は無い）。
- app のコードは import しない（閾値 4 は app/db/models/transaction.py の
  LEGACY_GOOD_MIN_RATING・0040 と同値。値を複製している）。
- 残る隙間 [推測]: P2 のデプロイでも、新インスタンスの起動時に本リビジョンが適用されてから
  旧インスタンスが止まるまでは旧コードが動きうる。その間の行は読み出し時はハイブリッドで
  正しく読め、件数はその業者の次の投稿・非表示で直る。0042（contract）で verdict を
  NOT NULL にする前に、同じ補完・再計算をもう一度流すこと。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_review_verdict_recount"
down_revision: str | None = "0040_review_verdict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0041_review_verdict_recount")

# ★この値以上を「よかった」とみなす（app 側 LEGACY_GOOD_MIN_RATING・0040 と同値）。
_LEGACY_GOOD_MIN_RATING = 4


def _verdict_from_rating_sql(rating_column: str) -> str:
    """★から導く評価（0040 の U2 と同じ式）。

    閾値は int の定数（外部入力ではない）のため SQL に埋め込む。同じ値を1文の中で何度も
    参照するため、名前付きパラメータの使い回し（ドライバの paramstyle 依存）を避ける。
    rating_column も本モジュール内の定数しか渡さない。
    """
    return (
        f"CASE WHEN {rating_column} >= {int(_LEGACY_GOOD_MIN_RATING)}"
        " THEN 'good' ELSE 'improve' END"
    )


# 業者1件ぶんの集計対象（依頼者→業者・非表示を除く）の相関サブクエリ。母集団は
# services/review_stats.recalc_operator_review_stats・0040 の U5 と同じ。外側の operators を
# 別名なしで参照する（PostgreSQL の UPDATE でも SQLite でも同じ文で通る）。
# operators にも rating 列があるため、reviews 側の列は必ず r. で修飾する。
_VISIBLE_USER_REVIEWS_SQL = (
    "SELECT COUNT(*) FROM reviews r"
    " JOIN transactions t ON t.id = r.transaction_id"
    " JOIN bids b ON b.id = t.bid_id"
    " WHERE b.operator_id = operators.id"
    " AND r.reviewer_type = 'user' AND r.hidden_at IS NULL"
)
_REVIEW_VERDICT_SQL = f"COALESCE(r.verdict, {_verdict_from_rating_sql('r.rating')})"
_GOOD_COUNT_SQL = f"({_VISIBLE_USER_REVIEWS_SQL} AND {_REVIEW_VERDICT_SQL} = 'good')"
_IMPROVE_COUNT_SQL = f"({_VISIBLE_USER_REVIEWS_SQL} AND {_REVIEW_VERDICT_SQL} = 'improve')"
_REVIEW_COUNT_SQL = f"({_VISIBLE_USER_REVIEWS_SQL})"
# 再計算値と good_count / improve_count / review_count のいずれかがずれている業者
# （R2 の件数と R3 の更新対象に同じ条件を使う）。
_DRIFTED_OPERATOR_SQL = (
    f"(operators.good_count <> {_GOOD_COUNT_SQL}"
    f" OR operators.improve_count <> {_IMPROVE_COUNT_SQL}"
    f" OR operators.review_count <> {_REVIEW_COUNT_SQL})"
)


def _rowcount(result: sa.engine.CursorResult) -> int:
    # ドライバが件数を返さない（-1 / None）場合は 0 として扱う（0038 と同じ方式）。
    return result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # R0: ロック待ちで起動を詰まらせない（取れなければ失敗させ start.sh のリトライに任せる）。
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
        # R0b: 並走する旧コードの口コミの書き込みを本リビジョンの終わりまで止める（docstring 参照）。
        # operators に触る前に取り、ロック順を reviews → operators に揃える。
        op.execute(sa.text("LOCK TABLE reviews IN SHARE MODE"))

    # R1: verdict 未設定の行を補完（reviewer_type・非表示を問わず全行。0040 の U2 と同じ式）。
    filled = _rowcount(
        bind.execute(
            sa.text(
                f"UPDATE reviews SET verdict = {_verdict_from_rating_sql('rating')}"
                " WHERE verdict IS NULL"
            )
        )
    )

    # R2: 件数がずれている業者数（証跡。R3 の更新対象と同じ条件）。
    drifted = int(
        bind.execute(
            sa.text(f"SELECT COUNT(*) FROM operators WHERE {_DRIFTED_OPERATOR_SQL}")
        ).scalar_one()
    )

    # R3: ずれている業者だけを同じ母集団から再計算する（ずれの無い業者の行は更新しない。R1 の後は
    # 全行が good / improve のどちらかのため review_count = good_count + improve_count が成り立つ）。
    # PostgreSQL では R0b のロックにより R2 と R3 の間に口コミは書き換わらない（件数は一致する）。
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

    # R4: 証跡（0038 / 0040 と同じロガー方式。Render のログで件数を確認できる）。
    # 「更新」は R3 で実際に書き換えた業者行の数（R2 の検出数と一致するのが正常）。
    logger.info(
        "0041: verdict が未設定だった評価を %s 件補完しました（P1〜P2 の間に旧コードが書いた行）。"
        "件数がずれていた業者 %s 件の集計を再計算しました（更新 %s 件）。",
        filled,
        drifted,
        recalculated,
    )
    if drifted > 0:
        logger.warning(
            "0041: 評価の件数（よかった／伸びしろ／合計）がずれていた業者が %s 件ありました"
            "（P1〜P2 の間の旧コードによる投稿・非表示が原因の想定。再計算で補正済み）。",
            drifted,
        )


def downgrade() -> None:
    # データ是正のため戻さない（上記 docstring 参照）。
    pass
