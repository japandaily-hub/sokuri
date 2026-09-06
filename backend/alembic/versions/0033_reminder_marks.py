"""リマインド定期処理の送信済みマーカーを追加（transactions / cases）

Revision ID: 0033_reminder_marks
Revises: 0032_contact_messages
Create Date: 2026-09-06

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは19文字）。

背景（r12 決定3）:
- 訪問日を過ぎても誰も完了確定をせず、成約が visiting のまま放置される導線と、
  入札が1件も付かないまま open で埋もれる案件の2つが、どちらも「誰も気づけない」
  無通知の穴になっていた。
- 1時間毎の背景ループ（app/services/reminders.py）が対象を抽出して通知し、
  この列に送信時刻を書く。**送信済み判定をこの列だけに集約する**ことで、
  ループが何度回っても（再デプロイ・手動実行 POST /admin/jobs/reminders を含め）
  同一の成約・案件へ二重に通知が飛ばない。
- 索引は「未送信のみを走査する」部分索引を1本ずつ張る。定期ループは
  「reminded_at IS NULL かつ status/日付条件」でしか引かないため、送信済み行が
  積み上がっても走査対象は常に未送信分に留まる（全走査を避ける）。
  PostgreSQL / SQLite いずれも部分索引を解する（0028 の
  uq_reduction_requests_pending と同方針）。

既存行の埋め戻し（r12-review H-1）:
- 列を NULL のまま追加すると、**この版を適用した直後の1周目**で「サービス開始
  以来の該当行すべて」が一斉に対象になる（訪問日を過ぎた古い成約・古い open 案件）。
  リマインドは行動を促す催促であり、過去分の一斉送信は実害（大量の LINE/メール・
  問い合わせ増）になるため、**適用時点の該当行は「送信済み」として埋める**。
- 埋め戻しの対象は「この版が無ければ1周目に拾われていたはずの行」に限る。
  未来日の訪問予定・入札済みの案件など、今後リマインド対象になりうる行は
  NULL のまま残す（将来の通知は正常に飛ぶ）。
- ``services/reminders.py`` 側にも遡り窓（14日）と LIMIT があり二重の歯止めに
  なっているが、窓は「古すぎる放置を諦める」ためのもので、埋め戻しが無いと
  直近14日分は依然として一斉送信されるため両方が必要。
- 日付・時刻はダイアレクト依存の関数（PG の now() / SQLite の datetime()）を
  避け、Python 側で確定した値を型付きバインドで渡す（SQLite でも
  DateTime バインド処理が効くよう ``sa.column`` に型を与える）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

#: 日本時間。visit_date は日本の暦で入力された日付のため「今日」の判定を JST で行う
#: （services/reminders.py の JST と同じ理由）。
_JST = timezone(timedelta(hours=9), name="Asia/Tokyo")

#: 入札ゼロ放置とみなすまでの日数（services/reminders.py の NO_BID_GRACE_DAYS と一致）。
_NO_BID_GRACE_DAYS = 3

revision: str = "0033_reminder_marks"
down_revision: str | None = "0032_contact_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("overdue_reminded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column("no_bid_reminded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_transactions_overdue_reminder",
        "transactions",
        ["status", "visit_date"],
        unique=False,
        postgresql_where=sa.text("overdue_reminded_at IS NULL"),
        sqlite_where=sa.text("overdue_reminded_at IS NULL"),
    )
    op.create_index(
        "ix_cases_no_bid_reminder",
        "cases",
        ["status", "created_at"],
        unique=False,
        postgresql_where=sa.text("no_bid_reminded_at IS NULL"),
        sqlite_where=sa.text("no_bid_reminded_at IS NULL"),
    )

    _backfill_existing_rows_as_sent()


def _backfill_existing_rows_as_sent() -> None:
    """適用時点で「既に該当している」行を送信済みとしてマークする（H-1）。

    索引作成の後に流すことで、部分索引に乗った状態で UPDATE を評価させる
    （既存データ量に対する全表更新を避ける）。
    """
    now = datetime.now(timezone.utc)
    today_jst = now.astimezone(_JST).date()

    transactions = sa.table(
        "transactions",
        sa.column("status", sa.String()),
        sa.column("visit_date", sa.Date()),
        sa.column("overdue_reminded_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        transactions.update()
        .where(
            transactions.c.overdue_reminded_at.is_(None),
            transactions.c.visit_date.is_not(None),
            transactions.c.visit_date < today_jst,
        )
        .values(overdue_reminded_at=now)
    )

    cases = sa.table(
        "cases",
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("no_bid_reminded_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        cases.update()
        .where(
            cases.c.no_bid_reminded_at.is_(None),
            cases.c.status == "open",
            cases.c.created_at < now - timedelta(days=_NO_BID_GRACE_DAYS),
        )
        .values(no_bid_reminded_at=now)
    )


def downgrade() -> None:
    op.drop_index("ix_cases_no_bid_reminder", table_name="cases")
    op.drop_index("ix_transactions_overdue_reminder", table_name="transactions")
    op.drop_column("cases", "no_bid_reminded_at")
    op.drop_column("transactions", "overdue_reminded_at")
