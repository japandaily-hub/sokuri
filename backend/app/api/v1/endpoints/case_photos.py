"""写真アップロード — presign（疑似署名）/ PUT 本体 / GET 配信。

ゼロコスト方針のためローカルディスク保存（services/storage.py）。
presign はユーザー認証必須。アップロード本体は storage_key 自体が
推測不能（UUID hex）なため capability URL として機能する。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.db.models.user import User
from app.schemas_katadzuke import PresignRequest, PresignResponse
from app.services import storage

router = APIRouter()


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
    summary="写真本体のアップロード",
)
async def upload(storage_key: str, request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="画像ファイルのみアップロードできます。",
        )
    data = await request.body()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ファイルが空です。"
        )
    try:
        storage.save_bytes(storage_key, data)
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
