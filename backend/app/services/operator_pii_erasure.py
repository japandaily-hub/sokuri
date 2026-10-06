"""業者退会時の個人情報の消去（プライバシーポリシー第8条「遅滞なく削除」の実装）。

個人事業主の業者では、会社名・許可番号・許可証画像・申込フォームの代表者名／所在地／
電話／口座がそのまま個人情報になる。退会（本人・運営の強制退会とも）の時にこれらを
**NULL／空にする**。行そのものは、取引・メッセージ・入札履歴の整合（紛争対応）のため残す。

消さないもの（運営が保存期間を決める事項）:
  取引・メッセージ・入札履歴・口コミ・キャンセル記録、運営の監査ログ。
  これらは依頼者側の記録でもあり、業者の連絡先そのものは含まない。

operator_applications は NOT NULL 列が多く、新規マイグレーション無しで済ませるため
文字列列は空文字にする（NULL 可の列は NULL）。

事前申込・招待は「本人に紐づくと確認できた行」だけを対象にする（メール一致では
特定しない。erase_operator_personal_data の docstring 参照）。

呼び出し側（operator_profile._delete_and_anonymize_operator）が行ロック・進行中取引の
判定・commit を担う。本関数は flush までで、commit しない（同一トランザクションで
退会本体と原子的に反映するため）。冪等：何度呼んでも同じ状態になる。
個人情報の値はログに出さない（件数のみ）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import and_, or_, update
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
    invite_code: str | None,
) -> None:
    """業者の個人情報列を消す。

    消す対象は「この業者本人に紐づくと確認できた行」だけに限る（security review High）。
    業者登録はメールの所有確認が無く、承認待ちの業者でも退会できるため、メールアドレスの
    一致で事前申込・招待を特定すると、他人の申込中アドレスで登録→退会するだけで
    他人の申込（代表者名・口座・許可番号）を空にし、そのアドレス宛て限定の招待を
    誰でも使える招待（email=NULL）へ変えられてしまう。そのためメール照合は使わない。

    - 事前申込: ``operator_id`` が本人、または本人が登録に使った招待コード
      （``invite_code``。登録時に検証・消込済みの値）に紐づき、かつ他の業者に
      紐づいていない（operator_id が NULL か本人）もの。
    - 招待: ``operator_id`` が本人、または本人が使ったコード。

    招待コードを使わずに登録した業者の事前申込は、本人のものと確認できないため消さない
    （運営が申込一覧から個別に扱う）。
    """
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

    # ② 事前申込。本人の operator_id か、本人が使った招待コード（他の業者に紐づかないもの）
    # だけで特定する。メール一致は使わない（上の docstring 参照）。
    conditions = [OperatorApplication.operator_id == operator_id]
    if invite_code:
        conditions.append(
            and_(
                OperatorApplication.invite_code == invite_code,
                or_(
                    OperatorApplication.operator_id.is_(None),
                    OperatorApplication.operator_id == operator_id,
                ),
            )
        )
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

    # 招待に控えたメールアドレス。本人が使った招待だけ（同じメール宛ての他の招待は消さない）。
    invite_conditions = [Invite.operator_id == operator_id]
    if invite_code:
        invite_conditions.append(Invite.code == invite_code)
    invite_result = await session.execute(
        update(Invite)
        .where(or_(*invite_conditions))
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
        "operator_pii_erased operator=%s applications=%s invites=%s",
        operator_id,
        app_result.rowcount,
        invite_result.rowcount,
    )
