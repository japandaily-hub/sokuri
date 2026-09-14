"""入札未決定リマインドの送信済みマーカーを追加（cases）

Revision ID: 0035_bids_pending_reminder
Revises: 0034_bid_amount_history
Create Date: 2026-09-14

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは26文字）。

背景:
- 入札は届いているのに依頼者が決定しないまま放置される案件は、0033 の
  「入札ゼロ放置」リマインドの対象外（入札が1件でも付けば拾われなくなる）で、
  かつ「訪問日超過」リマインドの対象にもならない（成約前なので visit_date が
  存在しない）——どちらのリマインドにも引っかからない無通知の穴だった。
- 1時間毎の背景ループ（app/services/reminders.py）に3つ目の抽出を追加し、
  この列に送信時刻を書く。送信済み判定をこの列だけに集約する方針は
  no_bid_reminded_at / overdue_reminded_at と同じ（alembic 0033 と同型）。
- 索引は「未送信のみを走査する」部分索引を1本張る（0033 と同方針）。

既存行の埋め戻し（0033 の r12-review H-1 と同じ理由）:
- 列を NULL のまま追加すると、この版を適用した直後の1周目で「サービス開始
  以来、入札未決定のまま2日超放置されている案件すべて」が一斉に対象になる。
  適用時点で既に該当している行は「送信済み」として埋める。
- 埋め戻しの対象は「この版が無ければ1周目に拾われていたはずの行」に限る
  （status='bidding' かつ pending 入札が1件以上あり、その中で最も古い
  pending 入札の created_at が閾値より前）。今後リマインド対象になりうる
  行（作成直後・全入札取り下げ済み等）は NULL のまま残す。
- 日付・時刻はダイアレクト依存の関数を避け、Python 側で確定した値を
  型付きバインドで渡す（0033 と同じ理由）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

#: 入札が届いてから何日、依頼者が未決定なら掘り起こすか
#: （services/reminders.py の BIDS_PENDING_GRACE_DAYS と一致させる）。
_BIDS_PENDING_GRACE_DAYS = 2

revision: str = "0035_bids_pending_reminder"
down_revision: str | None = "0034_bid_amount_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD COLUMN は cases に ACCESS EXCLUSIVE ロックを取り、トランザクション終了
    # まで解放しない。直後の backfill（全表相関サブクエリ UPDATE）が長引くと、
    # その間 cases への全参照（案件一覧・詳細・入札API）がブロックされる
    # （security review Medium-2 対応）。待たされたら短時間で失敗させ、
    # 無期限のブロックで本番を止めるより「オフピークに再実行」を選べるようにする。
    # SQLite にはロックタイムアウトの概念が無いため PostgreSQL のみで設定する。
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))

    op.add_column(
        "cases",
        sa.Column("bids_pending_reminded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_cases_bids_pending_reminder",
        "cases",
        ["status", "created_at"],
        unique=False,
        postgresql_where=sa.text("bids_pending_reminded_at IS NULL"),
        sqlite_where=sa.text("bids_pending_reminded_at IS NULL"),
    )

    _backfill_existing_rows_as_sent()


def _backfill_existing_rows_as_sent() -> None:
    """適用時点で「既に該当している」行を送信済みとしてマークする（0033 H-1 と同じ理由）。

    索引作成の後に流すことで、部分索引に乗った状態で UPDATE を評価させる。
    """
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=_BIDS_PENDING_GRACE_DAYS)

    cases = sa.table(
        "cases",
        sa.column("id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("bids_pending_reminded_at", sa.DateTime(timezone=True)),
    )
    bids = sa.table(
        "bids",
        sa.column("id", sa.String()),
        sa.column("case_id", sa.String()),
        sa.column("operator_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    operators = sa.table(
        "operators",
        sa.column("id", sa.String()),
        sa.column("is_suspended", sa.Boolean()),
        sa.column("vendor_status", sa.String()),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )

    # 「status='bidding' かつ、選択可能な pending 入札のうち最古のものが閾値より
    # 前」の案件id。選択できない入札（停止中・承認取消・退会済み業者のもの）は
    # 母集団から除外する（services/reminders.py の _run_bids_pending_reminders
    # と同じ基準・security review Medium-1 対応。揃えないと「本来は対象外だった
    # 行」を誤って送信済みで埋めてしまう／逆に取りこぼす）。
    oldest_pending_bid = (
        sa.select(sa.func.min(bids.c.created_at))
        .select_from(bids.join(operators, operators.c.id == bids.c.operator_id))
        .where(
            bids.c.case_id == cases.c.id,
            bids.c.status == "pending",
            operators.c.is_suspended.is_(False),
            operators.c.vendor_status == "active",
            operators.c.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    stale_case_ids = sa.select(cases.c.id).where(
        cases.c.bids_pending_reminded_at.is_(None),
        cases.c.status == "bidding",
        oldest_pending_bid.is_not(None),
        oldest_pending_bid < threshold,
    )
    op.execute(
        cases.update()
        .where(cases.c.id.in_(stale_case_ids))
        .values(bids_pending_reminded_at=now)
    )


def downgrade() -> None:
    op.drop_index("ix_cases_bids_pending_reminder", table_name="cases")
    op.drop_column("cases", "bids_pending_reminded_at")
