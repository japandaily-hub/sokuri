"""写真アップロード — presign（疑似署名）/ PUT 本体 / GET 配信。

ゼロコスト方針のためローカルディスク保存（services/storage.py）。
presign はユーザー認証必須。アップロード本体（PUT）も認証必須にする
（security review 指摘対応: storage_key の推測不能性のみに依存した
capability URL 方式は、アルバム化でstorage_keyの露出面（案件一覧・
入札一覧等のレスポンスに含まれる箇所）が増えたことで優先度が上がった）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.db.models.user import User
from app.schemas_katadzuke import PresignRequest, PresignResponse
from app.services import storage
from app.services.storage import MAX_UPLOAD_BYTES, StorageKeyConflictError

router = APIRouter()

# Content-Lengthヘッダの申告値に対する早期拒否の許容量。ヘッダ自体が無い・
# 偽装されている場合は後続のストリーミング読み込みでのハード上限で捕捉する
# （operator_license.pyの許可証画像アップロードと同じ多重防御パターン）。
_MAX_DECLARED_CONTENT_LENGTH = MAX_UPLOAD_BYTES + 64 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_TOO_LARGE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="ファイルサイズが上限（10MB）を超えています。写真を縮小するか、別の写真をお試しください。",
)
# 非対応形式の 415。web は detail をそのまま表示する契約のため、実際に多い失敗
# （iPhone の HEIC を「すべてのファイル」で選択して accept を回避した場合）に
# 次の行動が分かる文言にする（r8-H4）。判定は storage.sniff_image_ext の
# マジックバイト方式（jpeg/png/webp のみ）と1対1で対応させること。
_UNSUPPORTED_IMAGE = HTTPException(
    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    detail=(
        "この形式の画像には対応していません。"
        "JPEG・PNG・WebP のいずれかでアップロードしてください"
        "（iPhone の HEIC 形式は「設定 > カメラ > フォーマット > 互換性優先」で"
        "JPEG として保存できます）。"
    ),
)


@router.post(
    "/upload/presign",
    response_model=PresignResponse,
    summary="写真アップロード URL の発行",
)
async def presign(
    body: PresignRequest,
    user: User = Depends(get_current_user),
) -> PresignResponse:
    try:
        key = storage.new_storage_key(body.content_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return PresignResponse(
        storage_key=key,
        upload_url=storage.upload_url(key),
        public_url=storage.public_url(key),
    )


@router.put(
    "/upload/{storage_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="写真本体のアップロード（認証必須）",
)
async def upload(
    storage_key: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    # 認証（Depends）は本関数の呼び出し前に解決済みのため、未認証のまま巨大
    # ボディを読み込む経路は無い。ただし認証済みユーザーが巨大なボディを送信
    # した場合のメモリDoSは別問題として残るため、Content-Lengthヘッダによる
    # 早期拒否＋ストリーミング読み込みでのハード上限を適用する
    # （security review 指摘対応。operator_license.pyと同じ多重防御パターン）。
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > _MAX_DECLARED_CONTENT_LENGTH:
            raise _TOO_LARGE

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise _TOO_LARGE
        chunks.append(chunk)
    data = b"".join(chunks)

    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ファイルが空です。写真を選び直してお試しください。",
        )
    # Content-Type ヘッダ・拡張子は詐称可能なため信用せず、実バイト列の先頭
    # シグネチャ（マジックバイト）で画像形式を判定する（security review 指摘対応。
    # operator_license.py の許可証画像アップロードと同じ方式に統一する）。
    if storage.sniff_image_ext(data) is None:
        raise _UNSUPPORTED_IMAGE
    try:
        storage.save_bytes(storage_key, data)
    except StorageKeyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/files/{storage_key}", summary="写真の配信")
async def serve_file(storage_key: str) -> FileResponse:
    path = storage.file_path(storage_key)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ファイルが見つかりません。"
        )
    return FileResponse(path)
