"""業者プロフィール — 自社編集（/operator/profile）と公開参照（/vendors/{operator_id}）。

審査確定項目（company_name, license_number, verified_at, vendor_status, rating等）は
Operator 本体でのみ管理し、本エンドポイントの PUT では更新できない。
編集可能項目（areas, categories, strong_categories, staff_count, business_hours,
intro_message, show_message, accept_unsellable）
は operator_profiles テーブルで管理する。
評価・口コミは常時公開（2026-09-04 決定）。is_public / show_stats / show_reviews は
API から撤去済み（列は残置・未参照）。

閲覧・編集は vendor_status を問わず許可する（get_current_operator を使用）。
チャット同様「承認待ちでも会話・プロフィール確認自体は可能」という方針に揃える
（入札のみ get_verified_operator で別途ブロックされる非対称設計を踏襲）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.rate_limit_deps import RateLimitGuard
from app.core.security import (
    REAUTH_TOKEN_EXPIRE_MINUTES,
    create_reauth_token,
    verify_password,
)
from app.db.models.bid import BID_STATUS_PENDING, BID_STATUS_REJECTED, Bid
from app.db.models.operator import Operator
from app.db.models.operator_profile import OperatorProfile
from app.db.models.transaction import Review, Transaction
from app.db.session import get_session
from app.schemas_katadzuke import (
    LineLinkUnlinkRequest,
    OperatorAccountDeleteRequest,
    OperatorProfileOut,
    OperatorProfileUpdateRequest,
    OperatorPublicListItemOut,
    OperatorPublicProfileOut,
    PublicReviewOut,
    ReauthTokenRequest,
    ReauthTokenResponse,
)
from app.services.case_lock import lock_operator_row
from app.services.message_guard import contains_contact_info

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_or_create_profile(session: AsyncSession, operator_id: uuid.UUID) -> OperatorProfile:
    profile = await session.get(OperatorProfile, operator_id)
    if profile is None:
        profile = OperatorProfile(operator_id=operator_id)
        session.add(profile)
        try:
            await session.commit()
        except IntegrityError:
            # 同時リクエストが先に作成済み（operator_id は主キー）。
            # 自分の INSERT は諦めて既存レコードを取り直す。
            await session.rollback()
            profile = await session.get(OperatorProfile, operator_id)
            if profile is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="プロフィールの初期化に失敗しました。",
                ) from None
            return profile
        except Exception as exc:
            await session.rollback()
            logger.error(
                "operator_profile: 初回プロフィール自動作成に失敗 - operator_id=%s - %s",
                operator_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="プロフィールの初期化に失敗しました。",
            ) from exc
        await session.refresh(profile)
    return profile


def _to_profile_out(operator: Operator, profile: OperatorProfile) -> OperatorProfileOut:
    return OperatorProfileOut(
        operator_id=operator.id,
        company_name=operator.company_name,
        license_number=operator.license_number,
        verified_at=operator.verified_at,
        vendor_status=operator.vendor_status,
        rating=operator.rating,
        areas=profile.areas or [],
        categories=profile.categories or [],
        strong_categories=profile.strong_categories or [],
        staff_count=profile.staff_count,
        business_hours=profile.business_hours,
        intro_message=profile.intro_message,
        show_message=profile.show_message,
        accept_unsellable=profile.accept_unsellable,
        review_count=operator.review_count,
        license_image_uploaded_at=operator.license_image_uploaded_at,
    )


@router.get(
    "/operator/profile",
    response_model=OperatorProfileOut,
    summary="自社プロフィール取得（審査確定項目 + 編集可能項目）",
)
async def get_my_operator_profile(
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> OperatorProfileOut:
    profile = await _get_or_create_profile(session, operator.id)
    return _to_profile_out(operator, profile)


@router.put(
    "/operator/profile",
    response_model=OperatorProfileOut,
    summary="自社プロフィール更新（編集可能項目のみ。審査確定項目は無視する）",
)
async def update_my_operator_profile(
    body: OperatorProfileUpdateRequest,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> OperatorProfileOut:
    if not set(body.strong_categories).issubset(set(body.categories)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="strong_categories は categories の部分集合である必要があります。",
        )

    # intro_message は公開プロフィール（show_message=True時）で無認証ユーザーにも
    # 表示されるため、選定前ユーザーへの脱プラットフォーム勧誘経路になり得る。
    # bids.py の入札メッセージガードと同様の趣旨で作成時に拒否する。
    if contains_contact_info(body.intro_message):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="自己紹介文に連絡先（電話番号・メールアドレス）やURLは記載できません。",
        )

    profile = await _get_or_create_profile(session, operator.id)
    profile.areas = body.areas
    profile.categories = body.categories
    profile.strong_categories = body.strong_categories
    profile.staff_count = body.staff_count
    profile.business_hours = body.business_hours
    profile.intro_message = body.intro_message
    profile.show_message = body.show_message
    profile.accept_unsellable = body.accept_unsellable

    await session.commit()
    await session.refresh(profile)
    await session.refresh(operator)
    return _to_profile_out(operator, profile)


@router.get(
    "/vendors/{operator_id}",
    response_model=OperatorPublicProfileOut,
    summary="業者公開プロフィール取得（評価・口コミは常時公開。停止中の業者は404）",
)
async def get_vendor_public_profile(
    operator_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("public_read")),
) -> OperatorPublicProfileOut:
    operator = await session.get(Operator, operator_id)
    # 退会済み（deleted_at）も停止中と同様に 404 とする（r8-M6）。
    if operator is None or operator.is_suspended or operator.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="業者が見つかりません。")

    profile = await session.get(OperatorProfile, operator_id)
    if profile is None:
        # プロフィール行は業者が自分のプロフィール画面を開いた時に遅延作成される。
        # 行が無いだけの業者を 404 にしない（チャットの「プロフィールを見る」導線が
        # 壊れる）。既定値の仮想プロフィールとして扱う（GET で行は作成しない）。
        profile = OperatorProfile(
            operator_id=operator_id,
            show_message=True,
            accept_unsellable=False,
        )

    # 口コミは常時公開（業者側の非表示スイッチは撤去済み）。
    rows = (
        await session.scalars(
            select(Review)
            .join(Transaction, Review.transaction_id == Transaction.id)
            .join(Bid, Transaction.bid_id == Bid.id)
            .where(
                Bid.operator_id == operator_id,
                # 公開するのは「顧客→業者」の評価のみ。業者が顧客について
                # 書いたレビュー（reviewer_type="operator"）は公開しない。
                Review.reviewer_type == "user",
                Review.hidden_at.is_(None),
            )
            .order_by(Review.created_at.desc(), Review.id.desc())
            .limit(50)
        )
    ).all()
    reviews_out = [PublicReviewOut.model_validate(r) for r in rows]

    return OperatorPublicProfileOut(
        operator_id=operator.id,
        company_name=operator.company_name,
        verified_at=operator.verified_at,
        is_approved=operator.vendor_status == "active",
        areas=profile.areas or [],
        categories=profile.categories or [],
        strong_categories=profile.strong_categories or [],
        staff_count=profile.staff_count,
        business_hours=profile.business_hours,
        intro_message=profile.intro_message if profile.show_message else None,
        accept_unsellable=profile.accept_unsellable,
        rating=operator.rating,
        review_count=operator.review_count,
        reviews=reviews_out,
    )


@router.get(
    "/vendors",
    response_model=list[OperatorPublicListItemOut],
    summary="業者一覧（承認済み・停止中でない業者。評価の高い順・件数順）",
)
async def list_vendors(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1000),
    _rl: object = Depends(RateLimitGuard("public_read")),
) -> list[OperatorPublicListItemOut]:
    """業者一覧。個人情報（連絡先・許可番号）は含めない。
    並び順は「評価あり→評価の高い順→件数の多い順→登録の古い順」。

    API は無認証（画面側 /vendors は middleware でユーザーログイン必須）。公開情報のみを
    返す前提で、IP 軸のレート制限（public_read）と offset 上限で走査コストを抑える。"""
    rows = (
        await session.execute(
            select(Operator, OperatorProfile)
            .outerjoin(OperatorProfile, OperatorProfile.operator_id == Operator.id)
            .where(
                Operator.vendor_status == "active",
                Operator.is_suspended.is_(False),
                # 退会済み業者は公開一覧から除外する（r8-M6）。
                Operator.deleted_at.is_(None),
            )
            .order_by(
                Operator.rating.is_(None),
                Operator.rating.desc(),
                Operator.review_count.desc(),
                Operator.created_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        OperatorPublicListItemOut(
            operator_id=operator.id,
            company_name=operator.company_name,
            is_approved=True,
            areas=(profile.areas if profile is not None else None) or [],
            strong_categories=(profile.strong_categories if profile is not None else None) or [],
            accept_unsellable=bool(profile.accept_unsellable) if profile is not None else False,
            rating=operator.rating,
            review_count=operator.review_count,
            latest_review_comment=operator.latest_review_comment,
        )
        for operator, profile in rows
    ]


# ──────────────────────────── LINE連携（再認証トークン・連携解除） ────────────────────────────
# users.py の同名エンドポイント（/users/me/reauth-token・/users/me/line-link）と
# 対称の実装。業者側にも再認証・解除手段を提供する（security review H-1対応:
# 従来は operator 側にこれらの手段が一切無く、LINE連携後に本人が解除できない
# ・auth/line/exchange のoperator分岐に再認証要求も無かった）。

_OPERATOR_REAUTH_LINE_ONLY = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="このアカウントはパスワード未設定のため、この操作はご利用いただけません。",
)
_OPERATOR_REAUTH_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="現在のパスワードが正しくありません。",
)


@router.post(
    "/operator/reauth-token",
    response_model=ReauthTokenResponse,
    summary="LINE連携用の短命再認証トークンを発行する（purpose=line_link・5分間有効・業者向け）",
)
async def issue_operator_reauth_token(
    body: ReauthTokenRequest,
    request: Request,
    operator: Operator = Depends(get_current_operator),
    _rl: object = Depends(RateLimitGuard("line_link_reauth")),
) -> ReauthTokenResponse:
    ctx = request.state.rate_limit
    account_key = str(operator.id)
    ctx.check_account(account_key)

    # operator は operator_signup で必ず password_hash を持つため、実際には
    # 到達しない想定だが、user側と対称の構造を保つため念のため判定する。
    if operator.password_hash is None:
        raise _OPERATOR_REAUTH_LINE_ONLY
    if not verify_password(body.current_password, operator.password_hash):
        ctx.record_failure(account_key)
        raise _OPERATOR_REAUTH_WRONG_PASSWORD
    ctx.reset_account(account_key)

    token = create_reauth_token(operator.id, "operator")
    return ReauthTokenResponse(
        reauth_token=token, expires_in=REAUTH_TOKEN_EXPIRE_MINUTES * 60
    )


_OPERATOR_LINE_UNLINK_NO_PASSWORD = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="パスワード未設定のためLINE連携を解除できません（ログイン手段が失われるため）。",
)
_OPERATOR_LINE_UNLINK_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="現在のパスワードが正しくありません。",
)


@router.delete(
    "/operator/line-link",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="LINE連携の解除（current_password必須。解除するとログイン手段が消滅するため未設定業者は409）",
)
async def unlink_operator_line(
    body: LineLinkUnlinkRequest,
    request: Request,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("line_link_reauth")),
) -> None:
    ctx = request.state.rate_limit
    account_key = str(operator.id)
    ctx.check_account(account_key)

    # パスワード未設定（実際には到達しない想定だが念のため。user側と対称）の
    # うちは、解除するとログイン手段が完全に消滅するため解除自体を許可しない。
    if operator.password_hash is None:
        raise _OPERATOR_LINE_UNLINK_NO_PASSWORD
    if not verify_password(body.current_password, operator.password_hash):
        ctx.record_failure(account_key)
        raise _OPERATOR_LINE_UNLINK_WRONG_PASSWORD
    ctx.reset_account(account_key)

    operator.line_user_id = None
    await session.commit()


# ──────────────────────────── 退会（論理削除・匿名化） ────────────────────────────
# 依頼者側（users.py の DELETE /users/me）と同じ方針。物理削除はしない
# （完了済み取引・レビュー・キャンセル記録は依頼者側の記録として保持する）。

_OPERATOR_DELETE_ACTIVE_TRANSACTION = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="進行中の取引があるため退会できません。取引の完了またはキャンセル後に再度お試しください。",
)
_OPERATOR_DELETE_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="パスワードが正しくありません。",
)
# 退会（cancelled / completed 以外）を妨げる進行中ステータス。将来 status が
# 増えた場合も「終端でなければ進行中」と解釈されるよう、終端側を列挙する。
_TERMINAL_TXN_STATUSES = ("cancelled", "completed")


@router.delete(
    "/operator/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="業者アカウントの退会（パスワード再照合必須・匿名化。進行中取引があれば409）",
)
async def delete_my_operator_account(
    body: OperatorAccountDeleteRequest,
    request: Request,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("account_delete")),
) -> None:
    """業者の退会（r8-M6 / r8-review H-1・H-4対応）。

    従来は業者が自分でアカウントを閉じる手段が API・UI とも無く、privacy ページの
    「退会された場合…遅滞なく削除します」が業者に対しては空手形になっていた。

    処理は依頼者退会（users.delete_my_account）と同型:
    ①パスワード再照合＋レート制限（account_delete・アカウント軸を実際に効かせる）
    ②メールのトムストン化（＝ログイン不能化・再登録時の unique 衝突回避）
    ③パスワード無効化 ④LINE 連携解除 ⑤公開プロフィール非公開化
    ⑥未決（pending）入札の一括取り下げ ⑦``deleted_at`` による旧トークン即時失効。

    r8-review H-1（退会と落札の競合が直列化されていない）対応 — **Operator行を
    共通の直列化点にする**（r8-verify-fix で残っていた窓の閉塞）:

    直前の実装は「入札の一括rejected化 → flush → 進行中取引数の再判定」の順で、
    ``select_bid`` の条件付きUPDATEが取る**Bid行ロック**に直列化を依存していた。
    既存の pending 入札に対しては機能するが、一括UPDATE〜commit の間に同一業者が
    **新規に INSERT した入札**は当該行ロックの対象外で、その入札を掴んだ
    ``select_bid`` は未コミットの ``deleted_at`` を読めない（READ COMMITTED）ため
    素通りし、退会済み業者の進行中Transactionが成立しえた。

    そこで本関数と ``bids.select_bid`` の双方が**同一のOperator行**を
    ``SELECT ... FOR UPDATE`` で掴む規約にする（``_lock_operator_row``）。
    - select_bid が先にOperator行を掴んでいれば、本関数のロック取得がブロックされ、
      解放後の進行中取引数の判定でその成約が可視化される → rollback + 409。
    - 本関数が先に掴んでいれば、select_bid 側のロック取得がブロックされ、
      解放後に読む ``deleted_at`` は必ずコミット済み → select_bid が409。
    どちらの順序でも「退会済み業者の進行中成約」は成立しない。入札が**どのCaseに
    付くか**に依存しないため、新規入札のINSERTが同時着弾しても窓が開かない。

    ロック順序は既存規約（Case → Transaction）の後段に Operator を足す形で
    **Case → Operator** に統一する（select_bid は lock_case_row の後に取得する）。
    本関数はCase行を掴まないため、両者の間にロック循環は生じない。
    多層防御として select_bid 側にも ``deleted_at`` の409ガードを残す。

    注: SQLite（テスト）では ``FOR UPDATE`` が no-op のため、この直列化が実効を
    持つのは PostgreSQL 本番のみ（r8-review 未解決2 と同じ制約）。
    """
    ctx = request.state.rate_limit
    account_key = str(operator.id)
    ctx.check_account(account_key)

    # operator は operator_signup で必ず password_hash を持つ想定だが、user側
    # （LINE専用ユーザーはパスワード確認不要）と同型に念のため分岐する。
    if operator.password_hash is not None:
        if not verify_password(body.password, operator.password_hash):
            ctx.record_failure(account_key)
            raise _OPERATOR_DELETE_WRONG_PASSWORD
        ctx.reset_account(account_key)

    # 落札（bids.select_bid）との直列化点。以降の判定・更新は全てこのロックの
    # 内側で行う（上記docstring参照）。
    await lock_operator_row(session, operator.id)

    # 未決入札は取り下げる（退会後に落札されると連絡不能の成約が生まれる）。
    # 依頼者への落選通知は出さない: 案件は open のまま残り、他業者の入札で
    # 通常どおり成立しうるため「落選」ではない。
    await session.execute(
        update(Bid)
        .where(Bid.operator_id == operator.id, Bid.status == BID_STATUS_PENDING)
        .values(status=BID_STATUS_REJECTED)
    )
    await session.flush()

    active_txn_count = await session.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Bid, Transaction.bid_id == Bid.id)
        .where(
            Bid.operator_id == operator.id,
            Transaction.status.not_in(_TERMINAL_TXN_STATUSES),
        )
    )
    if active_txn_count:
        await session.rollback()
        raise _OPERATOR_DELETE_ACTIVE_TRANSACTION

    profile = await session.get(OperatorProfile, operator.id)
    if profile is not None:
        profile.is_public = False
        profile.show_message = False
        # 自由文（自己紹介）は退会後に公開経路へ残さない。
        profile.intro_message = None

    operator.contact_email = f"deleted-{operator.id}@deleted.katazuke.internal"
    operator.password_hash = None
    operator.line_user_id = None
    operator.deleted_at = datetime.now(timezone.utc)

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "operator/me delete: 退会処理のコミットに失敗 - operator_id=%s - %s",
            operator.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="退会処理に失敗しました。時間をおいて再度お試しください。",
        ) from exc

    # 監査ログ（依頼者退会と同様、誰がいつ退会したかを追えるようにする）。
    logger.info("operator_withdraw operator=%s", operator.id)
