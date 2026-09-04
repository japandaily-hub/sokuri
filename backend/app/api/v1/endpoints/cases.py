"""案件エンドポイント — 作成 / 一覧 / 詳細。

住所詳細（address_detail）の開示制御（品質基準）:
- 所有ユーザー: CaseOut（住所詳細あり）
- 業者:        CaseMaskedOut（prefecture / city のみ。詳細は落札後に
               GET /transactions/{id} で開示する）
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor, get_current_user
from app.api.rate_limit_deps import RateLimitGuard
from app.db.models.bid import BID_STATUS_PENDING, BID_STATUS_REJECTED, BID_STATUS_WITHDRAWN, Bid
from app.db.models.case import (
    CASE_AI_STATUS_DONE,
    CASE_AI_STATUS_FAILED,
    CASE_AI_STATUS_PENDING,
    Case,
    CaseItem,
    CasePhoto,
)
from app.db.models.transaction import Cancellation
from app.db.models.user import User
from app.db import session as db_session_module
from app.db.session import get_session
from app.schemas_katadzuke import (
    BidOut,
    CaseCancelRequest,
    CaseCreateRequest,
    CaseMaskedOut,
    CaseOut,
)
from app.services import notify_dispatch, storage
from app.services.case_lock import lock_case_row
from app.services.case_view import build_case_masked_out
from app.services.summary import (
    ItemAnalysisInput,
    MAX_PHOTOS_FOR_AI,
    build_fallback_summary,
    generate_case_ai,
    generate_case_summary,
    photo_url_for_ai,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: AI 解析（BackgroundTasks 側）の全体デッドライン（秒）。summary.py の1枚あたり
#: タイムアウト（25秒）× 逐次実行の積み上げで最悪約200秒かかりうるため、案件単位で
#: 上限を切る（r6-verify-backend の実測値。超過時は ai_status="failed" に落とし、
#: 案件自体は作成時のフォールバック要約付きで有効なまま残す）。
_AI_ANALYSIS_DEADLINE_SEC = 120

#: 冪等キーの有効窓。プロキシタイムアウト（Cloudflare 100秒）後の手動再送信を
#: 吸収できる長さで、かつ「同じ部屋をもう一度出品したい」正規利用を阻害しない長さ。
_IDEMPOTENCY_WINDOW = timedelta(minutes=10)

#: 業者向け案件一覧の既定件数／上限（r6 M-5。応答形状は list のまま変えない）。
_OPERATOR_LIST_DEFAULT_LIMIT = 100
_OPERATOR_LIST_MAX_LIMIT = 200

#: ai_status="pending" が「解析タスクが失われた」とみなされるまでの経過時間
#: （r6-review H2）。Starlette の BackgroundTasks はプロセス内タスクで永続キューでは
#: ないため、案件作成応答の直後に Render のデプロイ・スリープ復帰・OOM・SIGTERM が
#: 起きると _run_case_ai_analysis が実行されないまま失われ、ai_status は pending の
#: まま恒久的に残り得る（誰も failed に落とさない＝web は「解析中」表示に固定される）。
_AI_STALE_PENDING_WINDOW = timedelta(minutes=10)
_AI_STALE_REASON = "stale"


def _as_utc(value: datetime) -> datetime:
    """naive な日時（SQLite の server_default 経由）を UTC 起点の aware に揃える。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _reap_stale_pending_ai(session: AsyncSession, cases: list[Case]) -> None:
    """pending が ``_AI_STALE_PENDING_WINDOW`` を超えた案件を failed へ倒す（r6-review H2）。

    GET /cases/{id} ・依頼者向け一覧の応答直前に呼ぶ「遅延回収」。DB を更新した上で
    引数の ORM オブジェクト自体も書き換えるため、呼び出し元は追加の再取得無しに
    新しい状態をそのままシリアライズできる。対象が無ければ何もしない（クエリすら
    発行しない）。
    """
    now = datetime.now(timezone.utc)
    stale_ids = [
        c.id
        for c in cases
        if c.ai_status == CASE_AI_STATUS_PENDING
        and now - _as_utc(c.created_at) > _AI_STALE_PENDING_WINDOW
    ]
    if not stale_ids:
        return
    await session.execute(
        update(Case)
        .where(Case.id.in_(stale_ids))
        .values(ai_status=CASE_AI_STATUS_FAILED, ai_failed_reason=_AI_STALE_REASON)
    )
    await session.commit()
    stale_id_set = set(stale_ids)
    for c in cases:
        if c.id in stale_id_set:
            c.ai_status = CASE_AI_STATUS_FAILED
            c.ai_failed_reason = _AI_STALE_REASON
    logger.info(
        "cases: pending 放置（%s分超）の案件を failed へ遅延回収しました - count=%s",
        int(_AI_STALE_PENDING_WINDOW.total_seconds() // 60),
        len(stale_ids),
    )


async def sweep_stale_pending_ai(session: AsyncSession) -> int:
    """起動時スイープ（main.py lifespan から1回だけ呼ぶ、r6-review H2 (b)）。

    ``_reap_stale_pending_ai`` は GET のアクセスがあって初めて回収する遅延回収だが、
    案件詳細に誰もアクセスしないまま放置されると pending が残り続ける。起動のたびに
    pending かつ ``_AI_STALE_PENDING_WINDOW`` 超の案件を一括で failed にする。
    失敗しても起動を止めない（呼び出し元で例外を捕捉する）。戻り値は回収件数。
    """
    cutoff = datetime.now(timezone.utc) - _AI_STALE_PENDING_WINDOW
    result = await session.execute(
        update(Case)
        .where(Case.ai_status == CASE_AI_STATUS_PENDING, Case.created_at < cutoff)
        .values(ai_status=CASE_AI_STATUS_FAILED, ai_failed_reason=_AI_STALE_REASON)
    )
    await session.commit()
    count = result.rowcount or 0
    if count:
        logger.info(
            "cases: 起動時スイープで pending 放置の案件を %s 件 failed へ回収しました。", count
        )
    return count


async def _find_idempotent_case_id(
    session: AsyncSession, user_id: uuid.UUID, idempotency_key: str
) -> uuid.UUID | None:
    """同一ユーザー・同一冪等キーの案件が有効窓内に存在すればその id を返す。

    窓の判定は SQL ではなく Python 側で行う（``created_at`` は SQLite では
    naive、PostgreSQL では aware で返るため、バインド値との型不一致で比較が
    静かに常時 False になるのを避ける）。
    """
    row = (
        await session.execute(
            select(Case.id, Case.created_at)
            .where(Case.user_id == user_id, Case.idempotency_key == idempotency_key)
            .order_by(Case.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    case_id, created_at = row
    if datetime.now(timezone.utc) - _as_utc(created_at) > _IDEMPOTENCY_WINDOW:
        return None
    return case_id


async def _run_case_ai_analysis(case_id: uuid.UUID) -> None:
    """案件作成後の AI 解析を **新しいセッション** で実行し、結果を書き戻す。

    リクエストスコープのセッション（``get_session``）はレスポンス送出時にクローズ
    されるうえ、長時間処理でコネクションをトランザクションごと占有すると無関係な
    API までプール枯渇で巻き込む（r6 ADD-1）。そのため BackgroundTasks からは必ず
    ``get_background_session_factory()`` で別セッションを開く。

    失敗（例外・デッドライン超過）は ``ai_status="failed"`` として記録するだけで
    案件は有効なまま残す（``ai_summary`` には作成時に書いたフォールバック文が入って
    いる）。通知・入札は AI 解析の成否に依存しない。
    """
    session_factory = db_session_module.get_background_session_factory()
    try:
        async with session_factory() as session:
            case = await session.scalar(
                select(Case)
                .where(Case.id == case_id)
                .options(
                    selectinload(Case.photos),
                    selectinload(Case.items).selectinload(CaseItem.photos),
                )
            )
            if case is None:
                # 解析前に削除された等（通常は到達しない）。
                logger.warning("cases: AI 解析対象の案件が見つかりません - case_id=%s", case_id)
                return

            ungrouped_refs = [
                (p.storage_key, p.url) for p in case.photos if p.case_item_id is None
            ]
            try:
                async with asyncio.timeout(_AI_ANALYSIS_DEADLINE_SEC):
                    if case.items:
                        item_inputs = [
                            ItemAnalysisInput(
                                name=item.name,
                                photo_refs=[(p.storage_key, p.url) for p in item.photos],
                            )
                            for item in case.items
                        ]
                        ai_summary, item_results = await generate_case_ai(
                            purpose=case.purpose,
                            housing_type=case.housing_type,
                            floor_plan=case.floor_plan,
                            items=item_inputs,
                            ungrouped_refs=ungrouped_refs,
                        )
                        for item, result in zip(case.items, item_results):
                            item.ai_detected_name = result.ai_detected_name
                            item.ai_condition = result.ai_condition
                            item.ai_summary = result.ai_summary
                    else:
                        # レガシー（items無し）経路: generate_case_summary の既存契約
                        # （解決済み文字列のリストを渡す）は温存する。解析対象は先頭
                        # MAX_PHOTOS_FOR_AI 枚のみのため、その分だけを base64 化する。
                        resolved_refs: list[str] = []
                        for storage_key, url in ungrouped_refs[:MAX_PHOTOS_FOR_AI]:
                            ref = await photo_url_for_ai(storage_key, url)
                            if ref is not None:
                                resolved_refs.append(ref)
                        ai_summary = await generate_case_summary(
                            purpose=case.purpose,
                            housing_type=case.housing_type,
                            floor_plan=case.floor_plan,
                            photo_urls=resolved_refs,
                        )
                case.ai_summary = ai_summary
                case.ai_status = CASE_AI_STATUS_DONE
                case.ai_failed_reason = None
            except Exception as exc:  # noqa: BLE001 -- 解析失敗で案件を壊さない
                # 例外オブジェクトをそのまま文字列化しない（SDK 例外に画像データや
                # リクエスト内容が含まれうる。summary._detect_photo_labels と同方針）。
                reason = f"{type(exc).__name__}: {str(exc)[:180]}"
                logger.error(
                    "cases: AI 解析に失敗（フォールバック要約のまま継続） - case_id=%s - %s",
                    case_id,
                    reason,
                )
                case.ai_status = CASE_AI_STATUS_FAILED
                case.ai_failed_reason = reason[:255]
            await session.commit()
    except Exception:  # noqa: BLE001 -- BackgroundTask の外へ例外を出さない
        logger.exception("cases: AI 解析タスクが異常終了しました - case_id=%s", case_id)


def _to_case_out(case: Case) -> CaseOut:
    out = CaseOut.model_validate(case)
    # 取り下げ済み入札は依頼者側に完全非表示にする方針のため件数からも除外する
    # （業者の入札取り下げ機能は廃止済みだが、過去データの withdrawn 行との
    # 表示整合のためフィルタは残す。tests/test_bid_withdrawn_legacy.py 参照）。
    out.bid_count = sum(1 for b in case.bids if b.status != BID_STATUS_WITHDRAWN)
    out.item_count = len(case.items)
    out.photo_count = len(case.photos)
    return out


def _to_masked_out(case: Case, my_operator_id: uuid.UUID | None = None) -> CaseMaskedOut:
    out = build_case_masked_out(case)
    my_bid = None
    if my_operator_id is not None:
        for bid in case.bids:
            if bid.operator_id == my_operator_id:
                my_bid = BidOut.model_validate(bid)
                if bid.status == "selected" and bid.transaction is not None:
                    my_bid.transaction_id = bid.transaction.id
                break
    # 取り下げ済み入札は依頼者・業者いずれの集計からも除外する（_to_case_out と同じ理由）。
    out.bid_count = sum(1 for b in case.bids if b.status != BID_STATUS_WITHDRAWN)
    out.my_bid = my_bid
    # 最高入札額（自社入札を含む全業者の最高額。取り下げ済みは除く）。入札が無ければ None。
    # 秘匿しない方針（確定済み製品判断）のため全業者に開示する。
    out.top_bid_amount = max(
        (bid.amount for bid in case.bids if bid.status != BID_STATUS_WITHDRAWN),
        default=None,
    )
    return out


_CASE_LOAD = (
    selectinload(Case.photos),
    selectinload(Case.items).selectinload(CaseItem.photos),
    selectinload(Case.bids).selectinload(Bid.operator),
    selectinload(Case.bids).selectinload(Bid.transaction),
)


async def _get_case(session: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await session.scalar(
        select(Case)
        .where(Case.id == case_id)
        .options(*_CASE_LOAD)
        # populate_existing: 同一リクエストスコープ外（同一セッション内での複数回の
        # 呼び出し）でも常に最新の関連（items/photos/bids）へ同期する。identity map
        # 上に既にロード済みの Case が残っている場合、指定しないと eager load が
        # 陳腐化したコレクションを上書きしない（bids.py の同種問題を参照）。
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    return case


@router.post(
    "/cases",
    response_model=CaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="案件作成（写真 + 住居情報 + AI 要約）",
)
async def create_case(
    body: CaseCreateRequest,
    background: BackgroundTasks,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("case_create")),
) -> CaseOut:
    """案件を作成して即座に返す（AI 解析は BackgroundTasks で後追いする）。

    r6 H-1 / ADD-1 対応: 以前はリクエスト内で AI 解析（最悪約200秒）を完了させてから
    commit していたため、(1) プロキシのタイムアウト後もサーバは案件を作り続け、依頼者の
    再送信で同一内容の案件が二重に並ぶ、(2) その間 DB コネクションをトランザクションごと
    占有し、無関係な API までプール枯渇で巻き込む、という2つの障害が同時に起きていた。

    現在は「写真保存 + 案件行の作成」だけを短いトランザクションで commit して 201 を返し、
    解析は ``_run_case_ai_analysis``（別セッション・120秒デッドライン）に委ねる。応答の
    ``ai_status`` は ``pending`` で、フロントは完了まで ``GET /cases/{id}`` をポーリングする。
    ``idempotency_key`` を指定した再送信は、直近10分内なら新規作成せず 200 で既存案件を返す。
    """
    # AI解析(Gemini呼び出し)を伴うコストDoS対策（security review 指摘対応）。
    # IP軸は Depends(RateLimitGuard(...)) が既にカウント・判定済み。アカウント軸は
    # user_id が Depends 解決後にしか判明しないため、ここで明示的にカウントする
    # （成功/失敗を問わず毎リクエストをコストとして数える。login等の失敗時のみ
    # カウント方式とは異なる）。
    request.state.rate_limit.hit_account(str(user.id))

    # 冪等キーによる再送信の吸収（r6 H-1）。既存案件があれば新規作成せず 200 で返す
    # （201 と区別できるようにし、フロントが「作成された」と「既にあった」を判別できる）。
    if body.idempotency_key:
        existing_case_id = await _find_idempotent_case_id(
            session, user.id, body.idempotency_key
        )
        if existing_case_id is not None:
            logger.info(
                "cases: 冪等キーの一致により既存案件を返却 - user_id=%s case_id=%s",
                user.id,
                existing_case_id,
            )
            response.status_code = status.HTTP_200_OK
            return _to_case_out(await _get_case(session, existing_case_id))

    case = Case(
        user_id=user.id,
        purpose=body.purpose,
        status="open",
        prefecture=body.prefecture,
        city=body.city,
        address_detail=body.address_detail,
        housing_type=body.housing_type,
        floor_plan=body.floor_plan,
        floor_number=body.floor_number,
        has_elevator=body.has_elevator,
        ai_status=CASE_AI_STATUS_PENDING,
        idempotency_key=body.idempotency_key,
    )
    # 直下（未分類）写真。case.photos は「案件の全写真（未分類 + 商品紐づけ）」の
    # 合算ビューとして扱う（CasePhoto.item_id 経由の写真も case.photos に含める。
    # case_view.build_case_masked_out の photo_count 計算がこの前提に依存する）。
    # そのため AI 解析用の「未分類写真」参照は case.photos からではなく、この
    # ループで作る flat_photos から独立して集計する。
    flat_photos: list[CasePhoto] = []
    for photo_in in body.photos:
        if not storage.is_valid_key(photo_in.storage_key):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="storage_key が不正です。presign からやり直してください。",
            )
        photo = CasePhoto(
            storage_key=photo_in.storage_key,
            url=storage.public_url(photo_in.storage_key),
            sort_order=photo_in.sort_order,
        )
        case.photos.append(photo)
        flat_photos.append(photo)

    # items[].photos[].storage_key にも既存の is_valid_key() を必ず適用する
    # （新規経路の抜け漏れ防止）。sort_order は items 経路のみサーバ側で配列
    # インデックスに正規化し、クライアント指定値は信用しない（既存のフラット
    # photos 経路の sort_order 挙動は変更しない）。
    #
    # 各写真は item.photos（商品への紐づけ = case_item_id 管理）と case.photos
    # （案件全体の合算ビュー = case_id 管理）の両方へ追加する。CaseItem.photos /
    # CasePhoto.item 関係は foreign_keys=[case_item_id] に限定しているため
    # case_id はここで case.photos 経由の関係が単独で管理し、競合しない。
    for item_idx, item_in in enumerate(body.items):
        item = CaseItem(name=item_in.name, sort_order=item_idx)
        for photo_idx, photo_in in enumerate(item_in.photos):
            if not storage.is_valid_key(photo_in.storage_key):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="storage_key が不正です。presign からやり直してください。",
                )
            photo = CasePhoto(
                storage_key=photo_in.storage_key,
                url=storage.public_url(photo_in.storage_key),
                sort_order=photo_idx,
            )
            item.photos.append(photo)
            case.photos.append(photo)
        case.items.append(item)

    # AI 解析（Gemini 呼び出し）はここでは行わない。作成応答をブロックしないよう
    # BackgroundTasks（_run_case_ai_analysis）へ出し、ここでは暫定の要約だけを埋める
    # （解析が失敗しても案件詳細の要約欄が空にならないようにするため。従来の except
    # フォールバックと同じ役割を、常に先に書いておく形へ移した）。
    case.ai_summary = build_fallback_summary(
        case.purpose, case.housing_type, case.floor_plan, len(case.photos)
    )

    session.add(case)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # DB制約 uq_cases_user_id_idempotency_key の違反（r6-verify-fix M2）: 上の
        # _find_idempotent_case_id は commit 前の in-memory チェックのため同時2
        # リクエスト（二度押し・リトライ）を防げず、真の一意性はDB制約が担保する。
        # 制約名/対象カラム名（SQLiteは "cases.user_id, cases.idempotency_key"、
        # PostgreSQLは制約名そのもの）がエラーメッセージに含まれることを利用して
        # 判別し、reductions.create_reduction と同じ多層防御パターンで既存案件を
        # 200で返す（存在しない場合のみ409へフォールバック）。
        if body.idempotency_key and "idempotency_key" in str(getattr(exc, "orig", exc)).lower():
            existing_case_id = await _find_idempotent_case_id(
                session, user.id, body.idempotency_key
            )
            if existing_case_id is not None:
                logger.info(
                    "cases: 冪等キー競合(DB制約)により既存案件を返却 - user_id=%s case_id=%s",
                    user.id,
                    existing_case_id,
                )
                response.status_code = status.HTTP_200_OK
                return _to_case_out(await _get_case(session, existing_case_id))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一の冪等キーを使った案件が既に存在します。新しい冪等キーで再送信してください。",
            ) from exc
        # case_photos.storage_key の DB UNIQUE制約違反（security review 指摘対応・H-1、
        # case_items.py の add_case_item_photo と同じ多層防御）。他人が既にアップロード
        # 済みの storage_key を新規案件作成時に流用しようとした場合もここで一律拒否する
        # （素通しで500になるのを防ぐ）。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="指定された写真の一部は既に別の案件で使用されています。presign からやり直してください。",
        ) from exc
    # session.refresh(case, attribute_names=["items"]) だけでは CaseItem.photos が
    # ネストしてeager loadされず、商品の写真が0枚のケースで応答シリアライズ時に
    # 未ロードのlazy loadが走りMissingGreenlet(500)になる（items内のphotosが1枚以上
    # あるケースはpre-commitのPython側状態がたまたま生き残り顕在化しないため見逃しやすい）。
    # _get_case() の eager load 定義（_CASE_LOAD）を再利用して確実に全関連をロードする。
    case = await _get_case(session, case.id)

    # 案件登録完了通知（r6-verify-web A1）。従来は notify.send_case_created の直呼びで、
    # LINE専用ユーザー（仮メール保持者）にはメールもLINEも届かなかった。他イベントと同じ
    # notify_dispatch（LINE優先→未連携/失敗時にメール）へ揃える。仮メール判定も dispatch
    # 側へ集約されている。AI 解析より**先に**登録することで、解析完了を待たずに通知する。
    background.add_task(
        notify_dispatch.dispatch_case_created,
        user.line_user_id,
        user.email,
        str(case.id),
    )
    # AI 解析は別セッション・別トランザクションで後追いする（本リクエストの
    # コネクションは既に返却される）。
    background.add_task(_run_case_ai_analysis, case.id)
    return _to_case_out(case)


@router.get(
    "/cases",
    summary="案件一覧（ユーザー: 自分の案件 / 業者: 入札可能案件）",
)
async def list_cases(
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(
        _OPERATOR_LIST_DEFAULT_LIMIT,
        ge=1,
        le=_OPERATOR_LIST_MAX_LIMIT,
        description="業者向け一覧の取得件数（依頼者の自分の案件一覧には適用しない）",
    ),
    offset: int = Query(0, ge=0, description="業者向け一覧の取得開始位置"),
) -> list[CaseOut] | list[CaseMaskedOut]:
    """依頼者は自分の案件、業者は入札可能案件（公開中）の一覧を返す。

    業者分岐にのみ ``limit`` / ``offset`` を適用する（r6 M-5）。公開案件は業者間で
    共有される全体集合であり件数に上限が無い一方、``_CASE_LOAD`` が写真・商品・入札まで
    eager load するため、公開案件数に比例して1リクエストの応答が線形に重くなる。
    依頼者側は「自分の案件が全部見えること」の方が重要なため、従来どおり全件返す
    （応答形状はどちらも list のまま変えない）。
    """
    if actor.typ == "user":
        assert actor.user is not None
        cases = (
            await session.scalars(
                select(Case)
                .where(Case.user_id == actor.user.id)
                .options(*_CASE_LOAD)
                .order_by(Case.created_at.desc())
            )
        ).all()
        # pending 放置の遅延回収（r6-review H2）。依頼者向け一覧のみ ai_status を
        # 応答へ含めるため対象にする（業者向け CaseMaskedOut は ai_status を持たない）。
        await _reap_stale_pending_ai(session, list(cases))
        return [_to_case_out(c) for c in cases]

    assert actor.operator is not None
    # 案件の「閲覧」は vendor_status を問わず許可する（pending/limited/active いずれも可）。
    # 入札のみ get_verified_operator（vendor_status == "active"）で別途ブロックする。
    # is_suspended（アカウント停止）は get_current_actor 側で既に弾かれている。
    cases = (
        await session.scalars(
            select(Case)
            .where(Case.status.in_(["open", "bidding"]))
            .options(*_CASE_LOAD)
            # created_at のみだと同時刻の案件で並びが不定になり、ページ跨ぎで
            # 取りこぼし/重複が起きうるため id を第2キーにする（admin 側と同方針）。
            .order_by(Case.created_at.desc(), Case.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_to_masked_out(c, actor.operator.id) for c in cases]


@router.get(
    "/cases/{case_id}",
    summary="案件詳細（業者には住所詳細をマスク）",
)
async def get_case(
    case_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> CaseOut | CaseMaskedOut:
    case = await _get_case(session, case_id)

    if actor.typ == "user":
        assert actor.user is not None
        if case.user_id != actor.user.id and actor.user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
            )
        # pending 放置の遅延回収（r6-review H2）。案件詳細に ai_status を含めるのは
        # 依頼者向け CaseOut のみのため、業者向け分岐（下）では呼ばない。
        await _reap_stale_pending_ai(session, [case])
        return _to_case_out(case)

    assert actor.operator is not None
    # 一覧同様、閲覧は vendor_status を問わず許可する（入札は別ゲートでブロック）。
    return _to_masked_out(case, actor.operator.id)


@router.post(
    "/cases/{case_id}/cancel",
    response_model=CaseOut,
    summary="出品を取り下げる（依頼者本人のみ・open/bidding のみ）",
)
async def cancel_case(
    case_id: uuid.UUID,
    body: CaseCancelRequest,
    background: BackgroundTasks,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("case_cancel")),
) -> CaseOut:
    # Case行の排他ロック取得・pending入札の一括却下・監査レコード書き込みを
    # 伴うコストDoS対策（旧 bid_withdraw と同じ operator_id 相当の軸で、
    # ここでは user_id 軸をカウントする。security review 指摘対応）。
    request.state.rate_limit.hit_account(str(user.id))

    # 所有権の事前照会（軽量・ロック無し）。認可判定（案件の所有権確認）より
    # 前にCase行の排他ロックを取得すると、他人のcase_idを大量に送りつける
    # だけで正規の出品取り下げ・選択処理を待たせるロック争奪DoSを誘発できて
    # しまうため、ロック取得前に所有権を確認する（bids.py の select_bid と
    # 同じパターン。security review 2周目 Medium指摘対応）。
    owner_id = await session.scalar(select(Case.user_id).where(Case.id == case_id))
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    if owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )

    # select（落札）との競合を防ぐため、所有権確認後にCase行をロックする
    # （TOCTOU対策。bids.py の lock_case_row を共有利用する）。
    await lock_case_row(session, case_id)
    case = await _get_case(session, case_id)
    if case.user_id != user.id:
        # 上記の所有権事前照会とCase行ロックの間の競合に対する多層防御
        # （通常は到達しない）。
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )

    if case.status == "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件はまだ出品されていません。",
        )
    if case.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="成約済みの案件は取引のキャンセルから手続きしてください。",
        )
    if case.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は既に取り下げ済みです。",
        )
    if case.status not in ("open", "bidding"):
        # 将来 status の値が拡張された場合の多層防御（到達しない想定）。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は取り下げできない状態です。",
        )

    # 却下対象（元pending）業者への通知プリミティブ値は、bidsを更新する前
    # （in-memory状態がまだpendingのまま）に収集する（select_bid のlosersループ
    # と同じパターン。ORMオブジェクトをBackgroundTasksへ渡さない。commit後は
    # セッションがdetachされうるため）。依頼者本人への通知は不要
    # （自身の操作のため）。
    #
    # 注意: 下記の一括UPDATE（update(Bid)...）はSQLAlchemyのORM Update構文
    # のデフォルト同期方式（synchronize_session='auto'）により、この時点で
    # 既にセッションのidentity map上のBidオブジェクト（case.bidsが参照する
    # ものと同一）の.statusをその場で書き換えてしまう。そのため losers の
    # 収集は必ず一括UPDATEの**前**に行うこと（後に回すと全滅する）。
    losers: list[tuple[str | None, str]] = [
        (b.operator.line_user_id, b.operator.contact_email)
        for b in case.bids
        if b.status == BID_STATUS_PENDING
    ]

    # pending入札を条件付きUPDATEで一括却下する（select_bidの条件付きUPDATEと
    # 同じ堅牢化パターン。Case行ロックにより通常は排他されるが、多層防御として
    # Bid単位でも状態をWHERE句で再検証してから更新する）。
    await session.execute(
        update(Bid)
        .where(Bid.case_id == case.id, Bid.status == BID_STATUS_PENDING)
        .values(status=BID_STATUS_REJECTED)
    )

    # 条件付きUPDATE（status=open/biddingであることをWHERE句で再検証してから
    # 更新する）。select_bid・create_bid と同じ多層防御パターン。
    result = await session.execute(
        update(Case)
        .where(Case.id == case.id, Case.status.in_(("open", "bidding")))
        .values(status="cancelled")
    )
    if result.rowcount != 1:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="案件の状態が変わったため取り下げできませんでした。",
        )
    case.status = "cancelled"

    session.add(
        Cancellation(
            case_id=case.id,
            transaction_id=None,
            cancelled_by="user",
            reason=body.reason,
        )
    )

    case_id_str = str(case.id)
    case_prefecture = case.prefecture
    case_city = case.city
    case_purpose = case.purpose

    try:
        await session.commit()
    except IntegrityError as exc:
        # Case行ロック＋条件付きUPDATEにより通常は到達しないが、変換しないと
        # 素通しで500になるため保険として捕捉する（create_bid/select_bid と
        # 同じ多層防御パターン）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="案件の状態が変わったため取り下げできませんでした。",
        ) from exc

    case = await _get_case(session, case.id)

    for loser_line_user_id, loser_email in losers:
        background.add_task(
            notify_dispatch.dispatch_bid_lost,
            loser_line_user_id,
            loser_email,
            case_id_str,
            case_prefecture,
            case_city,
            case_purpose,
        )
    return _to_case_out(case)
