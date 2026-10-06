"""業者退会時の個人情報の消去（プライバシーポリシー第8条「遅滞なく削除」の実装）。

個人事業主の業者では、会社名・許可番号・許可証画像・申込フォームの代表者名／所在地／
電話／口座がそのまま個人情報になる。退会（本人・運営の強制退会とも）の時にこれらを
**NULL／空にする**。行そのものは、取引・メッセージ・入札履歴の整合（紛争対応）のため残す。

消さないもの（運営が保存期間を決める事項）:
  取引・メッセージ・入札履歴・口コミ・キャンセル記録、運営の監査ログ。
  これらは依頼者側の記録でもあり、業者の連絡先そのものは含まない。

operator_applications は NOT NULL 列が多く、新規マイグレーション無しで済ませるため
文字列列は空文字にする（NULL 可の列は NULL）。

呼び出し側（operator_profile._delete_and_anonymize_operator）が行ロック・進行中取引の
判定・commit を担う。本関数は flush までで、commit しない（同一トランザクションで
退会本体と原子的に反映するため）。冪等：何度呼んでも同じ状態になる。
個人情報の値はログに出さない（件数のみ）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.operator_profile import OperatorProfile

logger = logging.getLogger(__name__)

# 成約済み取引の表示（依頼者の取引画面の company_name）に使う退会後の表示名。
DELETED_OPERATOR_DISPLAY_NAME = "退会済み業者"


async def erase_operator_personal_data(
    session: AsyncSession,
    operator: Operator,
    original_contact_email: str,
    invite_code: str | None,
) -> None:
    """業者の個人情報列を消す。``original_contact_email`` は墓標化する前の値。"""
    operator_id: uuid.UUID = operator.id

    # ① 許可証画像（BLOB は deferred のため Core UPDATE で確実に消す）と許可番号。
    await session.execute(
        update(Operator)
        .where(Operator.id == operator_id)
        .values(
            license_image_data=None,
            license_image_content_type=None,
            license_image_uploaded_at=None,
            license_number=None,
            company_name=DELETED_OPERATOR_DISPLAY_NAME,
        )
    )

    # ② 事前申込。operator_id・招待コード・申込時メール（大文字小文字無視）のどれかで特定する。
    conditions = [
        OperatorApplication.operator_id == operator_id,
        func.lower(OperatorApplication.contact_email) == original_contact_email.lower(),
    ]
    if invite_code:
        conditions.append(OperatorApplication.invite_code == invite_code)
    app_result = await session.execute(
        update(OperatorApplication)
        .where(or_(*conditions))
        .values(
            company_name=DELETED_OPERATOR_DISPLAY_NAME,
            representative_name="",
            registered_address="",
            contact_name="",
            contact_email="",
            contact_phone="",
            license_number="",
            invoice_number=None,
            bank_account_enc=None,
            message=None,
            categories=None,
            service_area=None,
            reject_reason=None,
            client_ip=None,
        )
        .execution_options(synchronize_session=False)
    )

    # 招待に控えたメールアドレス。
    await session.execute(
        update(Invite)
        .where(or_(Invite.operator_id == operator_id, func.lower(Invite.email) == original_contact_email.lower()))
        .values(email=None)
        .execution_options(synchronize_session=False)
    )

    # ③ プロフィールの自由記述・営業情報。
    await session.execute(
        update(OperatorProfile)
        .where(OperatorProfile.operator_id == operator_id)
        .values(
            areas=None,
            categories=None,
            strong_categories=None,
            staff_count=None,
            business_hours=None,
            intro_message=None,
            is_public=False,
            show_message=False,
        )
    )
    await session.flush()
    logger.info(
        "operator_pii_erased operator=%s applications=%s",
        operator_id,
        app_result.rowcount,
    )
