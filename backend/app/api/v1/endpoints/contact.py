"""お問い合わせエンドポイント — 認証不要。運営（ADMIN_EMAILS）宛にメール通知する。

R3-operator H1 対応: 従来 web 側は送信内容を破棄するのみ（バックエンド未配線）で、
「3営業日以内にご返信します」という文言だけが表示され続けていた。

security review H-1 対応: 無認証で叩ける本エンドポイントが admin メール爆撃・
Brevo クォータ枯渇の直通経路になり得たため、以下の多層防御を追加する。
1. レート制限スコープは専用の ``contact``（IP軸・アカウント軸とも10req/3600s、
   両軸とも全リクエストカウント）を使う。数値ルールは config.py に新規キーを
   追加しない方針のため ``case_create`` のルールを流用するが、scope 名を
   分離しているため実際の案件作成 API ``case_create`` とはバケット実体
   （ストアキー）が独立している（security review N-2対応。以前は scope 文字列
   まで case_create と共用していたため、同一 IP から /cases と /contact の
   リクエストが互いを巻き添えにしていた）。
2. メールアドレス軸でも ``hit_account`` により独立してカウントする
   （cases.py の create_case と同じパターン）。ただしこちらは
   **正規利用者の誤連投抑止であり防御の主軸ではない**（主軸は 1. の IP軸）。
   メールアドレスは自己申告のため、悪意ある送信者は容易に別アドレスへ
   切り替えてこの軸だけを回避できる。
3. プロセス内の簡易キャップ（直近1時間の**リクエスト数**が上限を超えたら、
   以降は 503 を返し受け付けを一時停止する。security review N-4対応:
   従来は「実送信通数」を数えていたため ADMIN_EMAILS の件数によって
   実質的な上限が変動し、上限到達後も依頼者には202を返し続けて
   問い合わせが黙って消えていた。403/429ではなく503にするのは、
   「一時的にサーバー側の都合で受け付けられない」ことを明示し、
   依頼者にメールでの直接連絡を案内するため）。
   R3再レビュー Medium対応: ブロッキング上限は正規トラフィックの誤検知を
   避けるため 300req/hour に引き上げ、従来の 30 はブロックしない「アラート
   閾値」に降格した（到達時に運営へ warning を1回発火するのみで、依頼者への
   応答は202のまま継続する）。503発生時は Retry-After ヘッダ（秒）を付け、
   クライアント側の自動リトライ・監視ツールが待機時間を機械的に把握できる
   ようにする。プロセス内キャップの予約は、IP軸（Depends が本関数呼び出し前に
   既に判定済み）・アカウント軸（``hit_account``）の両方のレート制限を通過
   した後に行う（従来は先にプロセス内キャップを消費していたため、本来は
   アカウント軸で弾かれるべきリクエストが共有キャパシティを消費していた）。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import RateLimitGuard
from app.config import get_settings
from app.db.models.contact_message import ContactMessage
from app.db.session import get_session
from app.schemas_katadzuke import ContactCreateRequest, ContactCreateResponse
from app.services import alerts, notify

logger = logging.getLogger(__name__)

router = APIRouter()

# 運営への問い合わせ窓口メールアドレス（web/src/app/legal/page.tsx の特定商取引法表記に
# 記載の確定値と一致させる）。config.py に新規キーは追加しない方針のため、
# web 側と重複するリテラルとしてここに保持する。
_LEGAL_CONTACT_EMAIL = "katazuke.info@gmail.com"

# プロセス内の簡易キャップ（security review H-1 / N-4対応）。config.py に新規キーを
# 追加しない方針のため定数として保持する（複数 worker プロセス構成では
# worker ごとに独立してカウントされ、全体としての厳密な上限にはならない点に
# 注意。あくまで単一プロセスでの暴走を止める軽量な安全弁）。
# N-4対応: 「実送信通数」ではなく「リクエスト数」を数える（ADMIN_EMAILS の
# 設定件数に上限が左右されないようにする）。
# R3再レビュー Medium対応: ブロッキング上限は 300/hour に引き上げ、正規利用者の
# 誤ブロックを避ける。従来の 30 はブロックしない「アラート閾値」に降格し、
# 到達時に運営へ warning を1回だけ発火する（依頼者へのレスポンスは202のまま）。
_MAX_NOTIFICATIONS_PER_HOUR = 300
_ALERT_THRESHOLD_PER_HOUR = 30
_NOTIFICATION_WINDOW_SEC = 3600.0
_recent_notification_timestamps: deque[float] = deque()
# 直近ウィンドウで既に閾値超過アラートを送ったか（リクエスト数がウィンドウの
# 経過とともに閾値未満へ戻れば False にリセットし、次回超過時に再度1回だけ送る）。
_alert_threshold_notified = False


def _contact_cap_exceeded(retry_after_seconds: int) -> HTTPException:
    """503応答を都度組み立てる（Retry-After は残り秒数で毎回変わるため定数化しない）。"""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "ただいまお問い合わせが混み合っています。時間をおいて再度お送りいただくか、"
            f"{_LEGAL_CONTACT_EMAIL} へ直接ご連絡ください。"
        ),
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _reserve_notification_slot() -> tuple[bool, int]:
    """直近1時間のリクエスト数がブロッキング上限未満なら1件分を予約する。

    ``time.monotonic()`` を使うためシステム時刻の巻き戻しに影響されない。
    呼び出しごとに古いタイムスタンプを掃除してからチェックする
    （sliding window。厳密な精度は不要な安全弁のため単純な実装で足りる）。

    Returns:
        ``(予約できたか, retry_after_seconds)``。``retry_after_seconds`` は
        予約に失敗した場合のみ意味を持ち、最も古いタイムスタンプがウィンドウ外に
        出るまでの残り秒数（切り上げ・最低1秒）を返す（Retry-After ヘッダ用）。
        予約に成功した場合は 0 を返す。
    """
    global _alert_threshold_notified
    now = time.monotonic()
    while (
        _recent_notification_timestamps
        and now - _recent_notification_timestamps[0] > _NOTIFICATION_WINDOW_SEC
    ):
        _recent_notification_timestamps.popleft()
    if len(_recent_notification_timestamps) <= _ALERT_THRESHOLD_PER_HOUR:
        # ウィンドウが空いてリクエスト数が閾値以下へ戻った＝次に閾値を超えたら
        # 再度アラートしてよい状態。
        _alert_threshold_notified = False
    if len(_recent_notification_timestamps) >= _MAX_NOTIFICATIONS_PER_HOUR:
        oldest = _recent_notification_timestamps[0]
        retry_after = max(1, int(_NOTIFICATION_WINDOW_SEC - (now - oldest)) + 1)
        return False, retry_after
    _recent_notification_timestamps.append(now)
    if (
        len(_recent_notification_timestamps) > _ALERT_THRESHOLD_PER_HOUR
        and not _alert_threshold_notified
    ):
        _alert_threshold_notified = True
        logger.warning(
            "contact: プロセス内のリクエスト数がアラート閾値（直近1時間で%d件）を"
            "超えました（ブロッキング上限は%d件のため受け付けは継続中）。",
            _ALERT_THRESHOLD_PER_HOUR,
            _MAX_NOTIFICATIONS_PER_HOUR,
        )
        alerts.fire_and_forget(
            alerts.send_alert(
                "/contact のリクエスト数がアラート閾値を超えました",
                f"直近{int(_NOTIFICATION_WINDOW_SEC)}秒のリクエスト数がアラート閾値"
                f"（{_ALERT_THRESHOLD_PER_HOUR}件）を超えました。ブロッキング上限"
                f"（{_MAX_NOTIFICATIONS_PER_HOUR}件）には未到達のため受け付けは"
                "継続していますが、異常なアクセスか正当なトラフィック増加かを"
                "確認してください。",
                severity="warning",
                key="contact-alert-threshold-exceeded",
            )
        )
    return True, 0


@router.post(
    "/contact",
    response_model=ContactCreateResponse,
    status_code=202,
    summary="お問い合わせ送信（運営宛メール通知・認証不要）",
)
async def create_contact(
    body: ContactCreateRequest,
    background: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    # security review N-2対応: /cases と scope名を分離した専用スコープ（IP軸・
    # アカウント軸とも10req/3600s）を使う。数値ルールは case_create を流用するが
    # バケット実体は独立する（_scope_spec の "contact" 分岐を参照）。
    _rl: object = Depends(RateLimitGuard("contact")),
) -> ContactCreateResponse:
    # R3再レビュー Medium対応: プロセス内キャップの予約は、IP軸（Depends が本関数
    # 呼び出し前に既に判定・カウント済み）・アカウント軸（hit_account）の両方の
    # レート制限を通過した後に行う。メールアドレス軸を独立してカウントする
    # （cases.py の create_case と同じ hit_account パターン。ただし上記の
    # docstring 2. の通り、正規利用者の誤連投抑止が目的であり防御の主軸ではない）。
    # 超過なら hit_account が 429 を raise し、以降のプロセス内キャップ消費に
    # は至らない。
    request.state.rate_limit.hit_account(f"contact:{body.email.lower()}")

    # N-4対応: 上限は「実送信通数」でなく「リクエスト数」で数える。ADMIN_EMAILS
    # 未設定でも枠は消費する（プロセス単位のDoS安全弁のため、宛先の有無とは
    # 独立して機能させる）。
    reserved, retry_after_seconds = _reserve_notification_slot()
    if not reserved:
        logger.error(
            "contact: プロセス内のリクエスト数上限（直近1時間で%d件）に達したため、"
            "お問い合わせの受け付けを一時停止しました。",
            _MAX_NOTIFICATIONS_PER_HOUR,
        )
        # 同一時間窓内での連打を防ぐため、alerts.send_alert 側のクールダウン
        # （key 固定）で最初の1回のみ通知させる。
        alerts.fire_and_forget(
            alerts.send_alert(
                "/contact のプロセス内キャップに到達しました",
                f"直近{int(_NOTIFICATION_WINDOW_SEC)}秒のリクエスト数が上限"
                f"（{_MAX_NOTIFICATIONS_PER_HOUR}件）に達し、お問い合わせの受け付けを"
                "一時的に503で拒否しています。異常なアクセスか、正当なトラフィック増加か"
                "を確認してください。",
                severity="warning",
                key="contact-cap-exceeded",
            )
        )
        raise _contact_cap_exceeded(retry_after_seconds)

    # r10 O-M6: メール送信の前に DB へ保存する（受信台帳）。従来はメールのみで、
    # ADMIN_EMAILS 未設定・Brevo 障害・迷惑メール振り分けのいずれか一つで問い合わせが
    # 痕跡ゼロで消えていた（依頼者には 202 が返るため誰も気づけない）。
    # 保存失敗でもメール送信と 202 は維持する（速報経路を道連れにしない。
    # 「片方でも届く」方が問い合わせの取りこぼしより損失が小さい）。
    contact_id: uuid.UUID | None = None
    try:
        contact_message = ContactMessage(
            name=body.name,
            email=str(body.email),
            category=body.category,
            message=body.message,
        )
        session.add(contact_message)
        await session.commit()
        contact_id = contact_message.id
    except Exception as exc:  # noqa: BLE001 -- 保存失敗でメール送信を止めない
        await session.rollback()
        # 本文・氏名・メールは PII のためログに出さない（例外種別と要旨のみ）。
        logger.error(
            "contact: お問い合わせの保存に失敗しました（メール送信は継続） - %s: %s",
            type(exc).__name__,
            str(exc)[:200],
            exc_info=True,
        )
        alerts.fire_and_forget(
            alerts.send_alert(
                "/contact の DB 保存に失敗しています",
                "お問い合わせの受信台帳（contact_messages）への保存が失敗しました。"
                "メール通知は継続していますが、管理画面の一覧には現れません。"
                f"直近のエラー: {type(exc).__name__}: {str(exc)[:200]}",
                severity="warning",
                key="contact-persist-failed",
            )
        )

    admin_emails = get_settings().admin_emails
    if not admin_emails:
        # 依頼者には「届かなかった」と見せない（202のまま）代わりに、運用ログで
        # 検知可能にする（ADMIN_EMAILS未設定時に問い合わせが黙って消える事故を防ぐ）。
        # r10 O-M6 以降は DB に残るため、この経路でも管理画面から回収できる。
        logger.warning(
            "contact: ADMIN_EMAILS が未設定のため、問い合わせメールを送信できません"
            "（受信台帳への保存は contact_id=%s）。",
            contact_id,
        )
        return ContactCreateResponse(ok=True)

    for to_email in admin_emails:
        background.add_task(
            notify.send_contact_received,
            to_email,
            body.name,
            body.email,
            body.category,
            body.message,
        )
    return ContactCreateResponse(ok=True)
