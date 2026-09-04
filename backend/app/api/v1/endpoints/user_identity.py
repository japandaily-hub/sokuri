"""依頼者の本人確認（身分証提出）エンドポイント — 認証必須の専用ファイル配信。

``operator_license.py``（審査書類画像をDBのBYTEAに保存し、認証必須の専用
エンドポイントでのみ配信する設計）を踏襲する。既存の presign/ファイルシステム
方式（case_photos.py の /upload/presign・/files/{key}、無認証capability URL）
は再利用しない。

マイナンバーカード・パスポートは裏面に個人番号・本籍地等の機微情報を含み得るため、
裏面画像を受け取っても一切保存しない（アプリ層で構造的に破棄する）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.deps import get_current_user
from app.api.rate_limit_deps import RateLimitGuard
from app.db.models.user import (
    IDENTITY_STATUS_APPROVED,
    IDENTITY_STATUS_PENDING,
    User,
)
from app.db.models.user_identity_document import (
    DOC_TYPES,
    DOC_TYPES_DISCARDING_BACK,
    DOC_TYPES_REQUIRING_BACK,
    DOCUMENT_STATUS_PENDING,
    UserIdentityDocument,
)
from app.db.session import get_session
from app.schemas_katadzuke import UserIdentityStatusOut
from app.services.storage import MAX_UPLOAD_BYTES, sniff_image_ext

logger = logging.getLogger(__name__)

router = APIRouter()

# 日本標準時（固定 UTC+9・DST無し）。zoneinfo("Asia/Tokyo") は環境によって
# tzdata パッケージ未導入で ZoneInfoNotFoundError になり得るため、
# 固定オフセットで代替する（JSTにDSTは存在しないため正確）。
_JST = timezone(timedelta(hours=9), name="Asia/Tokyo")

_CONTENT_TYPE_BY_EXT = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024
_MAX_DECLARED_CONTENT_LENGTH = MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD_ALLOWANCE
_READ_CHUNK_BYTES = 1024 * 1024
_MIN_AGE_YEARS = 18

_UNSUPPORTED_FORMAT = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="対応していないファイル形式です（jpeg / png / webp のみアップロードできます）。",
)
_TOO_LARGE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="ファイルサイズが上限（10MB）を超えています。",
)
_NO_FRONT_FILE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="表面の画像ファイルが指定されていません。",
)
_INVALID_DOC_TYPE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="書類の種類の指定が正しくありません。",
)
_BACK_REQUIRED = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="この書類の種類は裏面の画像も必要です。",
)
_BIRTH_DATE_REQUIRED = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="先に生年月日を登録してください。",
)
_UNDER_AGE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="本人確認は18歳以上の方のみご利用いただけます。",
)
_PENDING_EXISTS = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="本人確認書類は審査中です。審査結果をお待ちください。",
)
_ALREADY_APPROVED = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="本人確認は承認済みです。",
)
_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="本人確認書類が見つかりません。",
)


def _is_adult(birth_date: date, *, today: date) -> bool:
    """``today`` 時点で18歳以上かどうかを判定する（誕生日当日は18歳とみなす）。"""
    age = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return age >= _MIN_AGE_YEARS


async def _read_upload(upload: StarletteUploadFile) -> bytes:
    """multipart のファイルパートをチャンク単位で読み込み、上限超過を検知する。"""
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await upload.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise _TOO_LARGE
        chunks.append(chunk)
    await upload.close()
    return b"".join(chunks)


@router.get(
    "/users/me/identity",
    response_model=UserIdentityStatusOut,
    summary="本人確認ステータス取得（最新の提出1件）",
)
async def get_my_identity_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserIdentityStatusOut:
    row = (
        await session.execute(
            select(
                UserIdentityDocument.id,
                UserIdentityDocument.doc_type,
                UserIdentityDocument.submitted_at,
                UserIdentityDocument.reviewed_at,
                UserIdentityDocument.reject_reason,
                UserIdentityDocument.back_image_data.isnot(None),
            )
            .where(UserIdentityDocument.user_id == user.id)
            .order_by(UserIdentityDocument.submitted_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return UserIdentityStatusOut(status=user.identity_status)
    document_id, doc_type, submitted_at, reviewed_at, reject_reason, has_back = row
    return UserIdentityStatusOut(
        status=user.identity_status,
        document_id=document_id,
        doc_type=doc_type,
        submitted_at=submitted_at,
        reviewed_at=reviewed_at,
        reject_reason=reject_reason,
        has_back=bool(has_back),
    )


@router.post(
    "/users/me/identity-documents",
    response_model=UserIdentityStatusOut,
    summary="本人確認書類の提出（multipart: doc_type, front必須, back任意）",
)
async def submit_identity_document(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("identity_submit")),
) -> UserIdentityStatusOut:
    """``operator_license.py`` と同じ理由で ``Request`` を直接受け取り、認証ゲート
    （``get_current_user``）解決後にのみ ``request.form()`` を呼び出す
    （未認証の巨大ボディ読み込みDoS対策。詳細は operator_license.py の docstring 参照）。
    """
    request.state.rate_limit.hit_account(str(user.id))

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > _MAX_DECLARED_CONTENT_LENGTH:
            raise _TOO_LARGE

    form = await request.form(max_part_size=MAX_UPLOAD_BYTES)

    doc_type = form.get("doc_type")
    if not isinstance(doc_type, str) or doc_type not in DOC_TYPES:
        raise _INVALID_DOC_TYPE

    front = form.get("front")
    if front is None or not isinstance(front, StarletteUploadFile):
        raise _NO_FRONT_FILE
    back = form.get("back")
    back_upload = back if isinstance(back, StarletteUploadFile) else None

    requires_back = doc_type in DOC_TYPES_REQUIRING_BACK
    discards_back = doc_type in DOC_TYPES_DISCARDING_BACK
    if requires_back and back_upload is None:
        raise _BACK_REQUIRED

    # ── 業務前提の検証（重い画像読み込みの前に済ませる） ──────────────
    if user.birth_date is None:
        raise _BIRTH_DATE_REQUIRED
    if not _is_adult(user.birth_date, today=datetime.now(_JST).date()):
        raise _UNDER_AGE

    existing_status = (
        await session.scalar(
            select(UserIdentityDocument.status)
            .where(UserIdentityDocument.user_id == user.id)
            .order_by(UserIdentityDocument.submitted_at.desc())
            .limit(1)
        )
    )
    if existing_status == DOCUMENT_STATUS_PENDING:
        raise _PENDING_EXISTS
    if user.identity_status == IDENTITY_STATUS_APPROVED:
        raise _ALREADY_APPROVED

    # ── 表面画像 ────────────────────────────────────────────────
    # 画像の読み込み（I/O待ち）に時間がかかるため、TOCTOU対策の行ロックは
    # ここでは取得せず、実際にINSERTする直前（下記）まで遅延させる
    # （ロック保持時間を最小化し、他リクエストの待ち行列を作らないため）。
    front_data = await _read_upload(front)
    if not front_data:
        raise _NO_FRONT_FILE
    front_ext = sniff_image_ext(front_data)
    if front_ext is None:
        raise _UNSUPPORTED_FORMAT
    front_content_type = _CONTENT_TYPE_BY_EXT[front_ext]

    # ── 裏面画像 ────────────────────────────────────────────────
    back_data: bytes | None = None
    back_content_type: str | None = None
    if back_upload is not None:
        raw_back = await _read_upload(back_upload)
        if discards_back:
            # マイナンバーカード・パスポートの裏面は個人番号等の機微情報を
            # 含み得るため、受理はしても保存しない（構造的に破棄する）。
            raw_back = b""
        elif raw_back:
            back_ext = sniff_image_ext(raw_back)
            if back_ext is None:
                raise _UNSUPPORTED_FORMAT
            back_data = raw_back
            back_content_type = _CONTENT_TYPE_BY_EXT[back_ext]
        elif requires_back:
            raise _BACK_REQUIRED

    # ── TOCTOU対策（security review M-2） ─────────────────────────
    # 上のpending/approved判定から画像読み込みの間に、別リクエスト（多重送信・
    # 複数タブ等）が並行してpendingを作成しうる。本人行を SELECT ... FOR UPDATE
    # でロックしてから判定を再実行することで、2件のpending書類が同時に
    # 作られる競合を防ぐ（`with_for_update()` は同一行への書き込みを直列化する
    # ため、後続トランザクションはここで待機し、コミット後の最新状態で
    # 再判定されることになる）。
    locked_user = (
        await session.execute(select(User).where(User.id == user.id).with_for_update())
    ).scalar_one()
    existing_status = (
        await session.scalar(
            select(UserIdentityDocument.status)
            .where(UserIdentityDocument.user_id == locked_user.id)
            .order_by(UserIdentityDocument.submitted_at.desc())
            .limit(1)
        )
    )
    if existing_status == DOCUMENT_STATUS_PENDING:
        raise _PENDING_EXISTS
    if locked_user.identity_status == IDENTITY_STATUS_APPROVED:
        raise _ALREADY_APPROVED

    now = datetime.now(timezone.utc)
    document = UserIdentityDocument(
        user_id=locked_user.id,
        doc_type=doc_type,
        front_image_data=front_data,
        front_image_content_type=front_content_type,
        back_image_data=back_data,
        back_image_content_type=back_content_type,
        status=DOCUMENT_STATUS_PENDING,
        submitted_at=now,
    )
    session.add(document)
    locked_user.identity_status = IDENTITY_STATUS_PENDING

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "user_identity: 本人確認書類の保存に失敗 - user_id=%s - %s",
            user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="本人確認書類の保存に失敗しました。時間をおいて再度お試しください。",
        ) from exc
    await session.refresh(document)

    return UserIdentityStatusOut(
        status=user.identity_status,
        document_id=document.id,
        doc_type=document.doc_type,
        submitted_at=document.submitted_at,
        reviewed_at=document.reviewed_at,
        reject_reason=document.reject_reason,
        has_back=back_data is not None,
    )


@router.get(
    "/users/me/identity-documents/{document_id}/file",
    summary="自分が提出した本人確認書類の画像を取得（本人のみ）",
)
async def get_my_identity_document_file(
    document_id: uuid.UUID,
    side: Literal["front", "back"] = Query(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if side == "front":
        columns = (
            UserIdentityDocument.user_id,
            UserIdentityDocument.front_image_data,
            UserIdentityDocument.front_image_content_type,
        )
    else:
        columns = (
            UserIdentityDocument.user_id,
            UserIdentityDocument.back_image_data,
            UserIdentityDocument.back_image_content_type,
        )
    row = (
        await session.execute(select(*columns).where(UserIdentityDocument.id == document_id))
    ).first()
    # 他人の document_id は「存在しない」と同一の404にする（IDOR経由の在不在オラクル防止）。
    if row is None or row[0] != user.id or row[1] is None:
        raise _NOT_FOUND
    _, data, content_type = row
    return Response(
        content=data,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )
