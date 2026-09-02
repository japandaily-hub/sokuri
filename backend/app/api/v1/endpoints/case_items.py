"""商品(CaseItem)情報編集・削除、写真(CasePhoto)削除・追加エンドポイント。

既存の bids.py / cases.py の実装パターン（認可 → ステータスゲート → 対象存在確認の順で
チェックし、HTTPException へ変換する）を踏襲する。編集・削除・追加はいずれも案件の
所有ユーザー（または admin）のみに許可し、案件が draft/open の間（AI解析後・入札開始前）
のみ許可する。入札開始後（bidding）・成約後（closed）に商品情報が変わると、既に提示済み
の入札額の前提が崩れるため 409 で拒否する。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.limits import MAX_PHOTOS_PER_CASE, MAX_PHOTOS_PER_ITEM
from app.db.models.case import Case, CaseItem, CasePhoto
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    CaseItemOut,
    CaseItemUpdateRequest,
    CasePhotoIn,
    CasePhotoOut,
)
from app.services import storage

logger = logging.getLogger(__name__)

router = APIRouter()

_CASE_LOAD = (
    selectinload(Case.photos),
    selectinload(Case.items).selectinload(CaseItem.photos),
)


async def _get_case(
    session: AsyncSession, case_id: uuid.UUID, *, for_update: bool = False
) -> Case:
    """案件を取得する。

    Args:
        for_update: True の場合 ``SELECT ... FOR UPDATE`` で行ロックを取得する
            （security review 指摘対応・M-1/M-3）。本モジュールの4つの変更系
            エンドポイント（PUT/DELETE item・DELETE/POST photo）はこれを指定し、
            同一案件への同時更新（ステータス遷移・写真枚数上限チェック）の
            TOCTOU・非原子性を防ぐ。ロック取得後に本関数が返す ``case`` の
            status・photos は呼び出し元がそのままチェックに使うため、
            「ロック取得 → 再評価」は本関数の戻り値をそのまま使うだけで満たされる。
            SQLite（テスト環境）では ``FOR UPDATE`` 句は方言側で単に無視される
            （構文エラーにはならない。selectinload で読む子コレクションは別クエリ
            のため、ロックの対象は cases 行自体のみ）。
    """
    query = select(Case).where(Case.id == case_id).options(*_CASE_LOAD)
    if for_update:
        query = query.with_for_update()
    case = await session.scalar(
        query
        # populate_existing: bids.py/cases.py と同じ理由（テストハーネスのように
        # 単一セッションを複数リクエストで共有する経路での identity map 陳腐化対策）。
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    return case


def _authorize_owner(case: Case, user: User) -> None:
    if case.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )
    if case.user_id != user.id:
        # ここに到達するのは role == "admin" によるバイパスのみ（security review
        # 指摘対応・M-2）。所有者以外による変更は監査目的で必ず記録する。
        logger.warning(
            "case_items: admin権限によるバイパスで他ユーザー案件を操作 - "
            "admin_id=%s case_id=%s case_owner_id=%s",
            user.id,
            case.id,
            case.user_id,
        )


def _ensure_mutable(case: Case) -> None:
    if case.status not in ("draft", "open"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は現在編集できません（入札受付中または成約済みのため）。",
        )


def _get_item_or_404(case: Case, item_id: uuid.UUID) -> CaseItem:
    for item in case.items:
        if item.id == item_id:
            return item
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません。")


def _get_photo_or_404(case: Case, photo_id: uuid.UUID) -> CasePhoto:
    # 未分類写真（case_item_id=NULL）も含めて case.photos（案件全体の合算ビュー）から探す。
    for photo in case.photos:
        if photo.id == photo_id:
            return photo
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="写真が見つかりません。")


async def _delete_storage_if_unreferenced(session: AsyncSession, storage_key: str) -> None:
    """他に同じ storage_key を参照する CasePhoto 行が残っていない場合のみ、
    ストレージ上の実ファイルを物理削除する（参照カウント方式）。

    security review 指摘対応（H-1）: case_photos.storage_key の DB UNIQUE制約
    （0017マイグレーション）により通常運用では重複行は発生しないはずだが、
    「UNIQUE制約が実際に効いているか」に依存しない多層防御として、削除直前にも
    参照カウントを確認する。呼び出し元は対象行のDBコミット（削除）が完了した
    *後* にこの関数を呼ぶこと（削除対象自身の行は既に存在しない前提でカウントする）。
    """
    remaining = await session.scalar(
        select(func.count()).select_from(CasePhoto).where(CasePhoto.storage_key == storage_key)
    )
    if remaining:
        # security review 指摘対応（L-2）: storage_key は無認証capability
        # （GET /files/{storage_key}）のため平文でログに残さない（丸めてログ相関のみ可能にする）。
        logger.info(
            "storage.delete_bytes をスキップ（他の写真行が同じ storage_key を参照中） - "
            "key=%s remaining=%s",
            storage.mask_key_for_log(storage_key),
            remaining,
        )
        return
    try:
        storage.delete_bytes(storage_key)
    except Exception:  # noqa: BLE001 - ベストエフォート削除。失敗してもAPI応答自体は成功のまま返す。
        logger.warning(
            "_delete_storage_if_unreferenced: ストレージ削除に失敗（無視して続行） - key=%s",
            storage.mask_key_for_log(storage_key),
            exc_info=True,
        )


@router.put(
    "/cases/{case_id}/items/{item_id}",
    response_model=CaseItemOut,
    summary="商品情報の編集（名前・ユーザー入力コンディション・説明）",
)
async def update_case_item(
    case_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CaseItemUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CaseItemOut:
    # for_update=True: ステータス遷移（bids.py の入札受付開始等）との TOCTOU を防ぐため
    # 行ロックを取得した上でステータスを再評価する（security review 指摘対応・M-1）。
    case = await _get_case(session, case_id, for_update=True)
    _authorize_owner(case, user)
    _ensure_mutable(case)
    item = _get_item_or_404(case, item_id)

    # exclude_unset は使わず、送られたフィールドをそのまま代入する単純なPUT方式
    # （null を明示送信すればクリアされる。設計確定済み）。ai_condition/ai_summary
    # （AI推定値）はここでは一切触れない。
    item.name = body.name
    item.user_condition = body.user_condition
    item.user_description = body.user_description

    await session.commit()
    await session.refresh(item)
    logger.info(
        "case_item updated - actor=%s role=%s case=%s item=%s",
        user.id,
        user.role,
        case.id,
        item.id,
    )
    return CaseItemOut.model_validate(item)


@router.delete(
    "/cases/{case_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="商品削除（配下写真もカスケード削除）",
)
async def delete_case_item(
    case_id: uuid.UUID,
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    case = await _get_case(session, case_id, for_update=True)
    _authorize_owner(case, user)
    _ensure_mutable(case)
    item = _get_item_or_404(case, item_id)

    # ストレージファイルの削除はDBコミット後にベストエフォートで行う。commit/refresh で
    # ORM オブジェクトが失効する前に削除対象の storage_key を先に収集しておく。
    storage_keys = [photo.storage_key for photo in item.photos]
    item_id_for_log = item.id
    case_id_for_log = case.id

    await session.delete(item)
    await session.commit()
    logger.info(
        "case_item deleted - actor=%s role=%s case=%s item=%s",
        user.id,
        user.role,
        case_id_for_log,
        item_id_for_log,
    )

    # security review 指摘対応（H-1）: 削除対象行のコミット後、同じ storage_key を
    # 参照する行が他に残っていない場合のみ物理削除する（参照カウント方式）。
    for key in storage_keys:
        await _delete_storage_if_unreferenced(session, key)


@router.delete(
    "/cases/{case_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="写真削除（未分類写真も削除可。商品の最後の1枚を消しても商品自体は残す）",
)
async def delete_case_photo(
    case_id: uuid.UUID,
    photo_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    case = await _get_case(session, case_id, for_update=True)
    _authorize_owner(case, user)
    _ensure_mutable(case)
    photo = _get_photo_or_404(case, photo_id)

    storage_key = photo.storage_key
    photo_id_for_log = photo.id
    item_id_for_log = photo.case_item_id
    await session.delete(photo)
    await session.commit()
    logger.info(
        "case_photo deleted - actor=%s role=%s case=%s item=%s photo=%s",
        user.id,
        user.role,
        case.id,
        item_id_for_log,
        photo_id_for_log,
    )

    # security review 指摘対応（H-1）: 削除対象行のコミット後、同じ storage_key を
    # 参照する行が他に残っていない場合のみ物理削除する（参照カウント方式）。
    await _delete_storage_if_unreferenced(session, storage_key)


@router.post(
    "/cases/{case_id}/items/{item_id}/photos",
    response_model=CasePhotoOut,
    status_code=status.HTTP_201_CREATED,
    summary="商品への写真追加",
)
async def add_case_item_photo(
    case_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CasePhotoIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CasePhotoOut:
    # for_update=True: 写真枚数上限チェック（len(item.photos)/len(case.photos)）を
    # 同一案件への同時追加リクエストに対して原子的に行うため、行ロックを取得した
    # 状態で数え直す（security review 指摘対応・M-3）。
    case = await _get_case(session, case_id, for_update=True)
    _authorize_owner(case, user)
    _ensure_mutable(case)
    item = _get_item_or_404(case, item_id)

    if not storage.is_valid_key(body.storage_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="storage_key が不正です。presign からやり直してください。",
        )
    if storage.file_path(body.storage_key) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アップロード済みのファイルが見つかりません。presign → PUT を先に実行してください。",
        )
    if len(item.photos) >= MAX_PHOTOS_PER_ITEM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"商品1点あたりの写真枚数が上限（{MAX_PHOTOS_PER_ITEM}枚）に達しています。",
        )
    if len(case.photos) >= MAX_PHOTOS_PER_CASE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"案件全体の写真枚数が上限（{MAX_PHOTOS_PER_CASE}枚）に達しています。",
        )

    # sort_order はクライアント指定値を信用せず、サーバ側で採番する（欠番があっても
    # 連番に詰め直さず、既存写真の最大値+1を採用する。設計確定済み）。
    next_sort_order = max((p.sort_order for p in item.photos), default=-1) + 1
    photo = CasePhoto(
        case_id=case.id,
        case_item_id=item.id,
        storage_key=body.storage_key,
        url=storage.public_url(body.storage_key),
        sort_order=next_sort_order,
    )
    session.add(photo)
    try:
        await session.commit()
    except IntegrityError as exc:
        # case_photos.storage_key の DB UNIQUE制約違反（security review 指摘対応・H-1）。
        # 他人の案件（他人が既にアップロード済み）の storage_key を流用しようとした
        # ケースと、同一キーへの単純な競合の両方をここで一律に拒否する
        # （どちらに起因するかをここで区別する必要はない。いずれにせよ受理してはならない）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このファイルは既に別の写真として登録されています。",
        ) from exc
    await session.refresh(photo)
    return CasePhotoOut.model_validate(photo)
