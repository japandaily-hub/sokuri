"""業者許可証画像（古物商許可証等の審査書類） — 認証必須の専用エンドポイント。

既存の写真アップロード方式（case_photos.py の presign → PUT /upload/{key} →
GET /files/{key}、無認証capability URL）は絶対に再利用しない。審査書類は
機微度が高く、常に認証済みの本人・admin のみが取得できる必要があるため、
画像本体は operators.license_image_data（BYTEA, deferred=True）に直接保存し、
配信も認証必須の専用エンドポイントで完結させる。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.deps import get_current_admin, get_current_operator
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import OperatorLicenseImageUploadResponse
from app.services.storage import MAX_UPLOAD_BYTES, sniff_image_ext

logger = logging.getLogger(__name__)

router = APIRouter()

_CONTENT_TYPE_BY_EXT = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

# multipart のヘッダ・境界文字列のオーバーヘッド分の余裕（実ファイルサイズの
# 上限は後続のストリーミング読み込みで MAX_UPLOAD_BYTES ちょうどに厳格判定する）。
_MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024
_MAX_DECLARED_CONTENT_LENGTH = MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD_ALLOWANCE
# ストリーミング読み込みのチャンクサイズ。
_READ_CHUNK_BYTES = 1024 * 1024

_UNSUPPORTED_FORMAT = HTTPException(
    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    detail="対応していないファイル形式です（jpeg / png / webp のみアップロードできます）。",
)
_TOO_LARGE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="ファイルサイズが上限（10MB）を超えています。",
)
_NO_FILE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="ファイルが指定されていません。",
)
_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="許可証画像が登録されていません。",
)


@router.post(
    "/operator/license-image",
    response_model=OperatorLicenseImageUploadResponse,
    summary="古物商許可証画像のアップロード（既存があれば差し替え）",
)
async def upload_license_image(
    request: Request,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> OperatorLicenseImageUploadResponse:
    """multipart/form-data（file フィールド）で許可証画像を受け取る。

    **未認証の巨大ボディ読み込みDoS対策**: この関数のシグネチャは
    ``UploadFile = File(...)`` をルートパラメータとして宣言していない。
    FastAPI/Starlette は body 型のルートパラメータが1つでもあると、依存関数
    （``get_current_operator`` 等の認証ゲート含む）の解決より前に
    ``await request.form()`` でリクエストボディ全体を読み切ってしまうため
    （認証前の巨大ペイロード読み込みを許してしまう）、ここでは ``Request`` を
    直接受け取り、認証ゲートの解決が完了した後で明示的に ``request.form()``
    を呼び出す。これにより「未認証のまま巨大ボディを読み込む」経路自体を
    構造的に排除する。
    Content-Length ヘッダによる早期拒否も併用する（多重防御。ヘッダ自体が
    無い・偽装されている場合はストリーミング読み込み時のハード上限で捕捉する）。
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > _MAX_DECLARED_CONTENT_LENGTH:
            raise _TOO_LARGE

    # max_part_size: Starlette の request.form() が受け付けるキーワード引数
    # （このバージョンでは対応済み。inspect.signature で確認済み）。
    # 明示指定しておくこと自体は無害だが、**実際の防御範囲には限界がある点に
    # 注意（security review M-3対応・現状の限界）**: 現行 Starlette 実装の
    # MultiPartParser.on_part_data は ``self._current_part.file is None``
    # の場合（＝filename を持たない通常のフォームフィールド値）にのみ
    # max_part_size を適用しており、filename ありのファイルパート（今回の
    # "file" フィールド）の受信バイト数には一切適用されない（ソース確認済み。
    # ファイル本体は SpooledTemporaryFile へ無制限に書き込まれ、1MB
    # （spool_max_size）を超えた分はディスクへスピルする）。
    # つまり Content-Length ヘッダ省略/chunked転送で迂回された場合、
    # request.form() 自体がファイル全体をディスクへ書き切るまで、本関数の
    # ハード上限（下記のチャンク読み込みループ・MAX_UPLOAD_BYTES）は効かない
    # （＝一時ディスク使用量に対する迂回不能な多重防御にはなっていない）。
    # 恒久対策にはアプリ層ではなく ASGIサーバー/リバースプロキシ側の
    # リクエストボディ上限（例: uvicorn の --limit-max-requests系ではなく
    # Nginx/Render 側の client_max_body_size 相当の設定）が必要（別途要対応・
    # [要確認] 本番プロキシ設定の現況）。
    form = await request.form(max_part_size=MAX_UPLOAD_BYTES)
    upload = form.get("file")
    # request.form()（Starlette実装）が生成するファイルフィールドは
    # starlette.datastructures.UploadFile（fastapi.UploadFile はそのサブクラス）。
    if upload is None or not isinstance(upload, StarletteUploadFile):
        raise _NO_FILE

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
    data = b"".join(chunks)

    if not data:
        raise _NO_FILE

    ext = sniff_image_ext(data)
    if ext is None:
        raise _UNSUPPORTED_FORMAT

    now = datetime.now(timezone.utc)
    operator.license_image_data = data
    operator.license_image_content_type = _CONTENT_TYPE_BY_EXT[ext]
    operator.license_image_uploaded_at = now

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "operator_license: 許可証画像の保存に失敗 - operator_id=%s - %s",
            operator.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="許可証画像の保存に失敗しました。時間をおいて再度お試しください。",
        ) from exc

    return OperatorLicenseImageUploadResponse(uploaded_at=now)


async def _load_license_image(
    session: AsyncSession, operator_id: uuid.UUID
) -> tuple[bytes, str]:
    """許可証画像の本体を Core-style の列指定 select で取得する。

    ORM の ``Operator`` インスタンス経由で deferred 属性へアクセスすると
    AsyncSession では明示的な undefer/refresh なしに MissingGreenlet で
    失敗しうるため、ここでは列だけを直接問い合わせる（BLOB を必要とする
    このエンドポイントに限定した経路であり、他の業者関連クエリの負荷には
    一切影響しない）。
    """
    row = (
        await session.execute(
            select(Operator.license_image_data, Operator.license_image_content_type).where(
                Operator.id == operator_id
            )
        )
    ).first()
    if row is None or row[0] is None:
        raise _NOT_FOUND
    data, content_type = row
    return data, content_type or "application/octet-stream"


@router.get(
    "/operator/license-image",
    summary="自社の許可証画像を取得（本人のみ）",
)
async def get_my_license_image(
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> Response:
    data, content_type = await _load_license_image(session, operator.id)
    return Response(content=data, media_type=content_type)


@router.get(
    "/admin/operators/{operator_id}/license-image",
    summary="業者の許可証画像を取得（admin限定）",
)
async def get_operator_license_image_admin(
    operator_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    data, content_type = await _load_license_image(session, operator_id)
    logger.info(
        "admin: 許可証画像を閲覧しました - operator_id=%s admin_id=%s admin_email=%s",
        operator_id,
        admin.id,
        admin.email,
    )
    return Response(content=data, media_type=content_type)
