"""Phase 2 実装: /albums — 「まとめてソクウリ」アルバム永続化エンドポイント。

ADR-002 Phase 2 の Wizard of Oz 運用に対応する最小実装:
- ユーザーが /album ページで生成した複数 Assessment を 1 つの Album として永続化
- ``lead_email`` を取得（業者非開示、運営からの通知用）
- Phase 3 以降で業者通知 / 入札取り込みエンドポイントを別途追加

セキュリティ:
- FastAPI + Pydantic で型バリデーション、SQL 注入は SQLAlchemy パラメタライズで防止
- ``lead_email`` は ``EmailStr`` で検証
- 不正な ``assessment_id`` は 404 で即弾く（権限境界の代替、Phase 3 で user 認可と統合）
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# email-validator パッケージ依存を避けるため EmailStr を使わず、
# 軽量な正規表現で簡易検証する（送信前にフロントでも検証済み）。
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

from app.db.models.album import Album, AlbumItem
from app.db.models.assessment import Assessment
from app.db.models.enums import AlbumStatus
from app.db.session import get_session

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic スキーマ（このエンドポイント専用、再利用予定なし）
# ---------------------------------------------------------------------------

class AlbumCreateRequest(BaseModel):
    """POST /albums リクエスト。"""

    assessment_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="アルバムに含める assessment ID のリスト。1〜100 件まで",
    )
    total_estimated_jpy: int = Field(
        default=0,
        ge=0,
        description="AI 試算の合計（円）。業者入札の最低価格目安。0 で未指定",
    )
    lead_email: str | None = Field(
        default=None,
        max_length=320,
        pattern=_EMAIL_PATTERN,
        description=(
            "ユーザー連絡先メールアドレス。**業者には絶対開示しない**。"
            "成約確定後にのみ運営から業者へ手動連絡する。"
        ),
    )


class AlbumCreateResponse(BaseModel):
    """POST /albums レスポンス。"""

    album_id: uuid.UUID
    status: AlbumStatus
    item_count: int
    total_estimated_jpy: int


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------

@router.post(
    "/albums",
    response_model=AlbumCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="アルバム作成（一括査定束）",
    description=(
        "ユーザーが /album で生成した複数 Assessment を 1 つのアルバムにまとめ、"
        "業者への一括査定対象として永続化する。\n\n"
        "lead_email が指定された場合は status=SUBMITTED、未指定なら DRAFT。"
    ),
    tags=["Albums"],
)
async def create_album(
    payload: AlbumCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> AlbumCreateResponse:
    # ---- 1. 全 assessment_id の存在検証（部分的に存在しない場合は 404） ----
    stmt = select(Assessment.id).where(Assessment.id.in_(payload.assessment_ids))
    result = await session.execute(stmt)
    found_ids = {row[0] for row in result.all()}
    missing = [str(aid) for aid in payload.assessment_ids if aid not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"次の assessment_id が見つかりません: {', '.join(missing)}",
        )

    # ---- 2. 重複除去（順序は preserve、重複は無視）----
    seen: set[uuid.UUID] = set()
    unique_ordered: list[uuid.UUID] = []
    for aid in payload.assessment_ids:
        if aid not in seen:
            seen.add(aid)
            unique_ordered.append(aid)

    # ---- 3. Album 作成 ----
    initial_status = AlbumStatus.SUBMITTED if payload.lead_email else AlbumStatus.DRAFT
    album = Album(
        lead_email=payload.lead_email,
        status=initial_status,
        total_estimated_jpy=payload.total_estimated_jpy,
    )
    session.add(album)
    await session.flush()  # album.id 確定のため

    # ---- 4. AlbumItem を順序付きで追加 ----
    items = [
        AlbumItem(
            album_id=album.id,
            assessment_id=aid,
            position=idx,
        )
        for idx, aid in enumerate(unique_ordered)
    ]
    session.add_all(items)
    await session.commit()

    return AlbumCreateResponse(
        album_id=album.id,
        status=album.status,
        item_count=len(items),
        total_estimated_jpy=album.total_estimated_jpy,
    )
