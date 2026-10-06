"""メール通知 — Brevo (Sendinblue) transactional email API。

BREVO_API_KEY 未設定時は送信をスキップしてログのみ残す（開発・テスト安全側）。
送信失敗は呼び出し元の処理を失敗させない（通知はベストエフォート）。

BREVO_API_KEY 未設定によるスキップは、admin 宛の業者申込通知（重要度が高い）を
含む全メール通知が無言で消える事故（ADD-H2）につながるため、プロセス内で最初の
1回だけ運営アラート（alerts.send_alert）を発火して可視化する（同一プロセスでの
連打は行わない。alerts.send_alert 自体も key 単位のクールダウンを持つ）。
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timezone
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.core.masking import mask_email
from app.services import alerts

logger = logging.getLogger(__name__)

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
#: 送信失敗アラートの key（復旧通知 resolve_alert と対で使う）。
_BREVO_SEND_FAILED_KEY = "notify_brevo_send_failed"
# BREVO_API_KEY 未設定スキップの運営アラートを、プロセス内で最初の1回だけ発火するためのフラグ。
_brevo_missing_key_alerted = False
#: 日次の送信数の警告を出す到達点（Brevo 無料枠 300通/日の消費の把握・security review M-1）。
#: 数は**プロセス内の概数**（再起動で 0 に戻り、複数台・複数ワーカーでは台ごとに分かれる。
#: Brevo 側の実消費とは一致しない）。日付の区切りは UTC
#: （Brevo 側の日次枠の切り替わり時刻は [要確認]）。
_DAILY_SEND_WARN_AT: frozenset[int] = frozenset({150, 200, 250, 290})
#: この通数に達した時点で運営アラートを出す（同じ日に1回・本文は件数だけ。QA M-4）。
_DAILY_SEND_ALERT_AT = 250
#: この通数を**超えたら**新着チャット通知メール（send_message_received）だけ送らない。
#: 再設定・成約・キャンセルなど取引に必須のメールに枠を残すため。チャット本文は画面・LINE で
#: 読めるので、メールが止まっても取引は止まらない。
_DAILY_CHAT_MAIL_STOP_ABOVE = 280
#: 日次アラートの key の接頭辞（日付を付けて日ごとに分ける。翌日に復旧通知で閉じる）。
_DAILY_QUOTA_ALERT_KEY_PREFIX = "notify_brevo_daily_quota"
_daily_send_date: date | None = None
_daily_send_count = 0
# 当日アラート・当日チャットメール停止ログを出したか（同じ日に1回に抑える）。
_daily_quota_alerted_date: date | None = None
_daily_chat_mail_stop_logged_date: date | None = None


def _daily_quota_alert_key(day: date) -> str:
    return f"{_DAILY_QUOTA_ALERT_KEY_PREFIX}_{day.isoformat()}"


def _roll_daily_counter(today: date) -> None:
    """日付が変わっていれば数え直す。前日にアラートを出していれば復旧通知で閉じる。"""
    global _daily_send_date, _daily_send_count
    if _daily_send_date == today:
        return
    previous = _daily_send_date
    _daily_send_date = today
    _daily_send_count = 0
    if previous is not None and _daily_quota_alerted_date == previous:
        previous_key = _daily_quota_alert_key(previous)
        if alerts.is_active(previous_key):
            alerts.fire_and_forget(
                alerts.resolve_alert(
                    previous_key,
                    "メール送信数の日次枠が切り替わりました（Brevo）",
                    "日付（UTC）が変わり、メール送信数を数え直しました。"
                    "新着チャット通知メールの送信を再開します。",
                )
            )


def _record_daily_send() -> None:
    """送信成功を日次で数え、到達点で総量だけを警告ログ・運営アラートに出す（宛先・件名は出さない）。"""
    global _daily_send_count, _daily_quota_alerted_date
    today = datetime.now(timezone.utc).date()
    _roll_daily_counter(today)
    _daily_send_count += 1
    if _daily_send_count in _DAILY_SEND_WARN_AT:
        logger.warning(
            "notify: 本日（UTC）のメール送信数が %d 通に達しました（Brevo 無料枠 300通/日・プロセス内の概数）",
            _daily_send_count,
        )
    if _daily_send_count >= _DAILY_SEND_ALERT_AT and _daily_quota_alerted_date != today:
        _daily_quota_alerted_date = today
        alerts.fire_and_forget(
            alerts.send_alert(
                "メール送信数が日次枠に近づいています（Brevo）",
                f"本日（UTC）のメール送信数が {_daily_send_count} 通に達しました"
                "（Brevo 無料枠 300通/日・プロセス内の概数）。"
                f"{_DAILY_CHAT_MAIL_STOP_ABOVE} 通を超えると新着チャット通知メールだけ送信を止めます"
                "（再設定・成約などのメールは止めません）。"
                "これは事前の情報のお知らせです（障害ではないため復旧連絡は出ません）。"
                "数はプロセス内の概数で、再起動すると 0 に戻ります。",
                severity="info",
                key=_daily_quota_alert_key(today),
            )
        )


def is_chat_mail_suppressed() -> bool:
    """本日の送信数（概数）が上限を超え、新着チャット通知メールを止めるべきか。"""
    global _daily_chat_mail_stop_logged_date
    today = datetime.now(timezone.utc).date()
    _roll_daily_counter(today)
    if _daily_send_count <= _DAILY_CHAT_MAIL_STOP_ABOVE:
        return False
    if _daily_chat_mail_stop_logged_date != today:
        _daily_chat_mail_stop_logged_date = today
        logger.warning(
            "notify: 本日（UTC）のメール送信数が %d 通を超えたため、新着チャット通知メールを止めます"
            "（プロセス内の概数・他のメールは送信を続ける）",
            _DAILY_CHAT_MAIL_STOP_ABOVE,
        )
    return True


def reset_daily_send_state_for_tests() -> None:
    """テスト専用: 日次の送信数とアラート・停止ログの記録を初期化する。"""
    global _daily_send_date, _daily_send_count
    global _daily_quota_alerted_date, _daily_chat_mail_stop_logged_date
    _daily_send_date = None
    _daily_send_count = 0
    _daily_quota_alerted_date = None
    _daily_chat_mail_stop_logged_date = None


def reset_brevo_missing_key_alert_state_for_tests() -> None:
    """テスト専用: 「未設定アラート発火済み」フラグを初期化する。"""
    global _brevo_missing_key_alerted
    _brevo_missing_key_alerted = False
# LINE専用ユーザー（実メール未設定）に払い出す仮メールのドメインサフィックス。
# auth.py の line_exchange で `line-{line_user_id}@line.katazuke.internal` として発行される。
_PLACEHOLDER_EMAIL_SUFFIX = "@line.katazuke.internal"
# 退会（匿名化）済みユーザーに払い出すトムストンメールのドメインサフィックス。
# users.py の delete_my_account で `deleted-{user.id}@deleted.katazuke.internal` として発行される。
_DELETED_EMAIL_SUFFIX = "@deleted.katazuke.internal"


def is_placeholder_email(email: str | None) -> bool:
    """実在しない内部専用メール（LINE専用ユーザーの仮メール・退会済みトムストン）かを判定する。

    これらのメールは実際には受信されないため、そのまま送信経路（通知メール送信・
    業者への contact_email 開示等）に流すと配送不能や情報として無意味な
    開示になる。呼び出し元でこの判定を経由してスキップ/文言差し替えを行うこと。
    """
    if not email:
        return False
    lowered = email.lower()
    return lowered.endswith(_PLACEHOLDER_EMAIL_SUFFIX) or lowered.endswith(_DELETED_EMAIL_SUFFIX)


def is_deleted_account_email(email: str | None) -> bool:
    """退会（匿名化）済みユーザーのトムストンメールかどうかを判定する。

    contact_email の表示分岐（「退会済みユーザー」vs「LINEにて連絡」）で
    LINE専用ユーザーの仮メールと区別するために使う。
    """
    if not email:
        return False
    return email.lower().endswith(_DELETED_EMAIL_SUFFIX)


async def _send(to_email: str, subject: str, html: str) -> bool:
    """1通送る（成否のみ）。既存呼び出し元との互換のため bool を保つ。"""
    return (await _send_raw(to_email, subject, html)) is not None


async def _send_raw(to_email: str, subject: str, html: str) -> str | None:
    """1通送り、Brevo の ``messageId`` を返す（失敗・未設定時は ``None``）。

    ``messageId`` は Brevo の送信イベント API（``GET /v3/smtp/statistics/events``）で
    「受理後に実際に配送されたか」を後追い照合する鍵になる（自動運用のメール到達
    プローブ・r13）。応答に ``messageId`` が無い異常系は空文字を返し、送信成功
    （``None`` でない）とだけ扱う。
    """
    settings = get_settings()
    if not settings.brevo_api_key:
        # security review 2026-09-18 Low: 宛先メールアドレスを平文でログへ出さない
        # （本ファイルの他の失敗ログは既に宛先を出さない設計。mask_email で統一）。
        logger.error(
            "notify: BREVO_API_KEY 未設定のため送信スキップ - %s / %s",
            mask_email(to_email),
            subject,
        )
        global _brevo_missing_key_alerted
        if not _brevo_missing_key_alerted:
            _brevo_missing_key_alerted = True
            alerts.fire_and_forget(
                alerts.send_alert(
                    "メール送信キー未設定（BREVO_API_KEY）",
                    "BREVO_API_KEY が未設定のため、メール通知が無言でスキップされています。"
                    "admin宛の業者申込通知（send_operator_application_admin_alert 等）を含む"
                    "全てのメール送信が届いていません。至急、環境変数を設定してください。",
                    severity="critical",
                    key="notify_brevo_api_key_missing",
                )
            )
        return None
    payload = {
        "sender": {"email": settings.mail_from, "name": settings.mail_from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
        # Gmail/Yahoo の一括送信者要件・迷惑メール報告予防のため List-Unsubscribe を
        # 付与する（security review 2026-09-18 Low）。設定変更ページ（要ログイン）と
        # 問い合わせ先メールの両方を候補として提示する。RFC 8058 のワンクリック
        # 解除（List-Unsubscribe-Post: One-Click）はログイン不要の匿名解除エンドポイント
        # が別途必要になるため、本対応では対象外とする（[要確認] 将来的に一括送信量が
        # 増える場合は匿名トークン式の解除エンドポイント新設を検討）。
        "headers": {
            "List-Unsubscribe": (
                f"<{_notification_settings_url()}>, "
                f"<mailto:{_UNSUBSCRIBE_CONTACT_EMAIL}"
                f"?subject={quote('配信停止希望', safe='')}>"
            ),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                _BREVO_ENDPOINT,
                json=payload,
                headers={"api-key": settings.brevo_api_key},
            )
            res.raise_for_status()
        try:
            message_id = res.json().get("messageId")
        except Exception:  # noqa: BLE001 -- 本文が JSON でない/空でも送信自体は成功
            message_id = None
        _record_daily_send()
        # 送信失敗の warning を出していた場合は「復旧」を1回送る（is_active で先に判定し、
        # 通常時に毎送信で Task を作らない）。
        if alerts.is_active(_BREVO_SEND_FAILED_KEY):
            alerts.fire_and_forget(
                alerts.resolve_alert(
                    _BREVO_SEND_FAILED_KEY,
                    "メール送信が復旧しました（Brevo）",
                    "Brevo へのメール送信が再び成功しました。失敗していた間の通知は再送されません。",
                )
            )
        return str(message_id) if message_id else ""
    except Exception as exc:
        # 実行時の送信失敗（Brevo 無料枠 300通/日 到達の 429・キー失効の 401・
        # 送信ドメイン未認証の 402 等）は、従来 logger.error のみで運営に届かず
        # 「画面は正常なのに通知が1通も出ていない」状態が続いた（r6 H-3）。
        # alerts.send_alert は key 単位のクールダウン（既定600秒＝10分）を持つため、
        # 宛先別ではなく固定キーで束ねて連打を防ぐ。宛先・件名は本文に載せない
        # （アラート経路にPIIを流さない）。
        logger.error("notify: メール送信失敗（処理は継続） - %s", exc)
        alerts.fire_and_forget(
            alerts.send_alert(
                "メール送信に失敗しています（Brevo）",
                "Brevo へのメール送信が失敗しました。日次上限（無料枠300通/日）到達、"
                "APIキー失効、送信ドメインの認証切れ等が考えられます。"
                f"直近のエラー: {type(exc).__name__}: {str(exc)[:200]}",
                severity="warning",
                key=_BREVO_SEND_FAILED_KEY,
            )
        )
        return None


#: List-Unsubscribe / フッターの配信停止導線で使う問い合わせ用メールアドレス。
#: mail_from（noreply@…）は返信を受け付けないため、既存フッターの
#: 「お問い合わせ」欄と同じ宛先に揃える（security review 2026-09-18 Low）。
_UNSUBSCRIBE_CONTACT_EMAIL = "katazuke.info@gmail.com"


def _notification_settings_url() -> str:
    """お知らせメールの受信設定変更ページの URL（設定の実体は
    GET/PATCH /users/me/notification-settings）。フッターと List-Unsubscribe
    ヘッダーの両方から共通で参照する。"""
    return f"{get_settings().frontend_base_url}/notifications"


def _wrap(body: str) -> str:
    settings_url = _notification_settings_url()
    return (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px;">'
        '<h2 style="color:#14B8A6;margin:0 0 16px;">カタヅケ</h2>'
        f"{body}"
        '<p style="color:#888;font-size:12px;margin-top:24px;">'
        "このメールはカタヅケ運営事務局（神奈川県横浜市）から自動送信されています。"
        "お問い合わせ: katazuke.info@gmail.com</p>"
        '<p style="color:#888;font-size:12px;margin-top:8px;">'
        f'<a href="{settings_url}" style="color:#888;">お知らせメールの受信設定を変更する</a>'
        "</p></div>"
    )


async def send_mail_probe(to_emails: list[str]) -> list[str]:
    """メール到達プローブ（運営宛・自動運用 r13）。宛先ごとの ``messageId`` を返す。

    定期ジョブ ``POST /admin/jobs/mail-probe`` から呼ばれ、返った ID を Brevo の
    イベント API で「delivered」まで追う。Brevo 受理（201）と実配送は別であり、
    無料枠上限・送信者認証切れ・受信側ブロックは受理後に起きる（r10 の意図的未対応
    「受理後の破棄検知」を機械化）。送信できなかった宛先は結果に含めない。
    """
    ids: list[str] = []
    for to_email in to_emails:
        message_id = await _send_raw(
            to_email,
            "[カタヅケ監視] メール到達プローブ",
            _wrap(
                "<p>これは自動運用ジョブによるメール到達確認です。対応は不要です。</p>"
                "<p>このメールが届いていれば、依頼者・業者向けの通知メールも同じ経路で"
                "配送できています。</p>"
            ),
        )
        if message_id is not None:
            ids.append(message_id)
    return ids


async def send_case_created(to_email: str, case_id: str) -> bool:
    """① 案件化完了（ユーザー宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】案件の登録が完了しました",
        _wrap(
            "<p>お片付け案件の登録が完了しました。</p>"
            "<p>業者からの入札が届き次第、お知らせします（LINE連携済みの方はLINE、未連携の方はメール）。</p>"
            f'<p><a href="{url}">案件の状況を確認する</a></p>'
        ),
    )


async def send_bid_received(to_email: str, case_id: str, company_name: str, amount: int) -> bool:
    """② 入札通知（ユーザー宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】新しい入札が届きました",
        _wrap(
            f"<p><strong>{html.escape(company_name)}</strong> から "
            f"<strong>{amount:,} 円</strong> の入札が届きました。</p>"
            f'<p><a href="{url}">入札一覧を確認して業者を選ぶ</a></p>'
        ),
    )


async def send_bid_updated(
    to_email: str, case_id: str, company_name: str, old_amount: int, new_amount: int
) -> bool:
    """②' 入札額の引き上げ通知（ユーザー宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】入札額が更新されました",
        _wrap(
            f"<p><strong>{html.escape(company_name)}</strong> の入札額が更新されました。</p>"
            f"<p>{old_amount:,} 円 → <strong>{new_amount:,} 円</strong></p>"
            f'<p><a href="{url}">入札一覧を確認する</a></p>'
        ),
    )


async def send_bid_selected(to_email: str, transaction_id: str, amount: int) -> bool:
    """③ 落札通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】入札が選ばれ、成約しました",
        _wrap(
            f"<p>あなたの入札（<strong>{amount:,} 円</strong>）が選ばれました。</p>"
            "<p>住所詳細が開示されています。訪問日の調整を進めてください。</p>"
            f'<p><a href="{url}">成約した案件の詳細を確認する</a></p>'
        ),
    )


async def send_bid_lost(to_email: str, case_id: str, prefecture: str, city: str, purpose: str) -> bool:
    """落札通知（落選業者宛）。案件を特定できるよう地域・利用目的とリンクを本文に含める（M7対応）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】ご入札いただいた案件について",
        _wrap(
            f"<p>ご入札いただいた案件（{html.escape(prefecture)}{html.escape(city)}／"
            f"{html.escape(purpose)}）は、誠に恐れ入りますが今回は成約に至りませんでした。</p>"
            "<p>またの機会がございましたらよろしくお願いいたします。</p>"
            f'<p><a href="{url}">案件の詳細を確認する</a></p>'
        ),
    )


async def send_schedule_confirmed(to_email: str, transaction_id: str, visit_date: str) -> bool:
    """訪問日程が確定した際の通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】訪問日程が確定しました",
        _wrap(
            f"<p>訪問日程が <strong>{visit_date}</strong> に確定しました。</p>"
            f'<p><a href="{url}">成約詳細を確認する</a></p>'
        ),
    )


async def send_visit_overdue(
    to_email: str, transaction_id: str, recipient_party: str
) -> bool:
    """訪問予定日を過ぎても完了確定されていない成約のリマインド（当事者宛・r12 決定3）。

    r12-review H-3: 依頼者側の遷移先は ``/chat/{id}``（web に ``/transactions/{id}``
    は存在しない）。r10 O-H-1 の統一から漏れていた1箇所。
    """
    settings = get_settings()
    if recipient_party == "user":
        url = f"{settings.frontend_base_url}/chat/{transaction_id}"
        body = (
            "<p>作業が終わっていれば完了確定を、"
            "まだなら業者とチャットで日程を確認してください。</p>"
        )
    else:
        url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
        # 完了確定の依頼が取引詳細のボタンになったため、文面をそれに合わせる
        # （2026-09-26。依頼者宛の文面・リンク先は変えない）。
        body = "<p>取引詳細の「完了確定を依頼する」から依頼者に依頼できます。</p>"
    return await _send(
        to_email,
        "【カタヅケ】訪問予定日を過ぎています",
        _wrap(body + f'<p><a href="{url}">成約詳細を確認する</a></p>'),
    )


async def send_no_bid_reminder(to_email: str, case_id: str) -> bool:
    """入札が付かないまま放置されている案件のリマインド（依頼者宛・r12 決定3）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】まだ入札がありません",
        _wrap(
            "<p>まだ入札がありません。"
            "写真の追加や品目の見直しで入札が付きやすくなります。</p>"
            f'<p><a href="{url}">案件を見直す</a></p>'
        ),
    )


async def send_bids_pending_reminder(to_email: str, case_id: str) -> bool:
    """入札が届いたまま未決定の案件のリマインド（依頼者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】入札のご確認はお済みですか？",
        _wrap(
            "<p>届いている入札からまだ決定されていません。"
            "内容を比較のうえ、よろしければ決定手続きにお進みください。</p>"
            f'<p><a href="{url}">入札を確認する</a></p>'
        ),
    )


async def send_bank_account_changed(to_email: str, action: str) -> bool:
    """振込先口座の登録・変更・削除を本人へ通知する（security review M-1）。

    不正アクセスによる振込先の書き換えの早期検知が目的のため、``action``
    （"登録"/"変更"/"削除"）のみを伝え、口座番号等の機微情報は本文に含めない。
    """
    return await _send(
        to_email,
        "【カタヅケ】振込先口座の情報が更新されました",
        _wrap(
            f"<p>お客様の振込先口座情報が<strong>{html.escape(action)}</strong>されました。</p>"
            "<p>お心当たりがない場合は、お手数ですが至急パスワードを変更のうえ、"
            "カタヅケまでご連絡ください。</p>"
        ),
    )


async def send_operator_application_received(to_email: str, company_name: str) -> bool:
    """④ 業者事前申込の受付確認（申込者宛）。"""
    return await _send(
        to_email,
        "【カタヅケ】業者登録のお申込みを受け付けました",
        _wrap(
            f"<p><strong>{html.escape(company_name)}</strong> 様</p>"
            "<p>業者登録のお申込みを受け付けました。審査完了まで今しばらくお待ちください。</p>"
        ),
    )


async def send_operator_application_admin_alert(to_email: str, company_name: str) -> bool:
    """④ 業者事前申込の新規受付通知（admin宛）。"""
    return await _send(
        to_email,
        "【カタヅケ管理】新規業者申込が届きました",
        _wrap(
            f"<p>新規業者申込（<strong>{html.escape(company_name)}</strong>）"
            "が届きました。管理画面から確認してください。</p>"
        ),
    )


async def send_identity_submitted_admin_alert(to_email: str) -> bool:
    """④' 依頼者の本人確認書類の新規提出通知（admin宛。r10 O-M1）。

    提出者の氏名・メール・書類種別は**一切含めない**。宛先は運営だが、経路は
    Brevo（第三者）を通り、件名・本文はメールボックス検索・転送で拡散しうるため、
    本人確認という機微な文脈で PII を載せる利得が無い（管理画面で照合できる）。
    ``send_operator_application_admin_alert`` と同型の1宛先1通・戻り値 bool。
    """
    settings = get_settings()
    url = f"{settings.frontend_base_url}/admin/identity-documents"
    return await _send(
        to_email,
        "【カタヅケ管理】本人確認書類の提出がありました",
        _wrap(
            "<p>依頼者から本人確認書類の提出がありました。管理画面から審査してください。</p>"
            f'<p><a href="{html.escape(url, quote=True)}">本人確認書類の審査へ</a></p>'
        ),
    )


async def send_operator_application_approved(to_email: str, company_name: str, invite_code: str) -> bool:
    """⑤ 業者事前申込の承認通知（申込者宛・招待コード案内）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/signup"
    return await _send(
        to_email,
        "【カタヅケ】業者登録が承認されました",
        _wrap(
            f"<p><strong>{html.escape(company_name)}</strong> 様</p>"
            "<p>業者登録の審査が完了し、承認されました。以下の招待コードで本登録を完了してください。</p>"
            "<p>本登録の後、プロフィール画面から古物商許可証の画像を提出してください。"
            "運営が確認して承認すると入札できるようになります。</p>"
            f'<p style="font-size:20px;font-weight:bold;letter-spacing:1px;">{html.escape(invite_code)}</p>'
            f'<p><a href="{url}">本登録ページへ進む</a></p>'
        ),
    )


async def send_reduction_requested(to_email: str, case_id: str, amount: int) -> bool:
    """減額申請の受付通知（依頼者宛・ADD-2対応）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】減額のご相談が届いています",
        _wrap(
            f"<p>成約した業者から <strong>{amount:,} 円</strong> への減額のご相談が届いています。</p>"
            f'<p><a href="{url}">内容を確認して回答する</a></p>'
        ),
    )


async def send_reduction_decided(to_email: str, transaction_id: str, approved: bool, amount: int) -> bool:
    """減額申請の承認／却下結果通知（申請業者宛・H2対応）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    if approved:
        subject = "【カタヅケ】減額のご相談が承認されました"
        body = (
            f"<p>ご相談いただいた減額（<strong>{amount:,} 円</strong>）が承認されました。"
            "成約金額が更新されています。</p>"
        )
    else:
        subject = "【カタヅケ】減額のご相談について"
        body = "<p>ご相談いただいた減額は、依頼者により見送られました。</p>"
    return await _send(
        to_email,
        subject,
        _wrap(body + f'<p><a href="{url}">成約詳細を確認する</a></p>'),
    )


async def send_transaction_cancelled(to_email: str, transaction_id: str, recipient_party: str) -> bool:
    """成約キャンセル通知（相手方宛・ADD-1対応）。

    r10 O-H-1: リンク先は ``/chat/{id}``（依頼者）/ ``/operator/transactions/{id}``
    （業者）のままとし、キャンセル理由は web 側が当該画面に描画する
    （API は ``TransactionDetailOut.cancellation`` で既に返済み）。メール本文には
    当事者入力の自由文を載せず、「どこで読めるか」だけを案内する。
    """
    settings = get_settings()
    path = (
        f"/chat/{transaction_id}"
        if recipient_party == "user"
        else f"/operator/transactions/{transaction_id}"
    )
    url = f"{settings.frontend_base_url}{path}"
    return await _send(
        to_email,
        "【カタヅケ】成約がキャンセルされました",
        _wrap(
            "<p>進行中だった成約が、相手方によりキャンセルされました。</p>"
            "<p>キャンセルの理由は、下のリンク先の画面でご確認いただけます。</p>"
            f'<p><a href="{url}">詳細と理由を確認する</a></p>'
        ),
    )


async def send_transaction_cancelled_by_admin(
    to_email: str, transaction_id: str, recipient_party: str
) -> bool:
    """運営による成約の強制終了の通知（当事者双方宛・r8-M5）。

    「相手方により」ではなく運営の判断である旨を明示する（当事者が相手を誤解し、
    直接連絡・トラブル化するのを防ぐ）。理由は画面（依頼者はチャット画面、業者は
    成約詳細の cancellation）で確認してもらう（メール本文には運営入力の自由文を
    載せない）。r10 O-H-1: 着地先は変更せず、本文で「理由はその画面で読める」ことを
    明示する（web 側がチャット画面に理由を描画する）。
    """
    settings = get_settings()
    path = (
        f"/chat/{transaction_id}"
        if recipient_party == "user"
        else f"/operator/transactions/{transaction_id}"
    )
    url = f"{settings.frontend_base_url}{path}"
    return await _send(
        to_email,
        "【カタヅケ】成約が運営によりキャンセルされました",
        _wrap(
            "<p>進行中だった成約が、運営の判断によりキャンセルされました。</p>"
            "<p>キャンセルの理由は、下のリンク先の画面でご確認いただけます。</p>"
            f'<p><a href="{url}">詳細と理由を確認する</a></p>'
        ),
    )


# QA M-5対応: 運営宛メールの「種別」に、ContactCategory（英字スラッグ）ではなく
# web/src/app/contact/page.tsx:227-234 の <option> と1対1で一致する日本語ラベルを
# 出す。ContactCategory は schemas_katadzuke.py の Literal で固定8値に限定済みの
# ため、想定外の値は ``.get`` のフォールバックでスラッグをそのまま表示する
# （バリデーションを通過している前提で通常到達しないが、安全側フォールバック）。
_CONTACT_CATEGORY_LABELS: dict[str, str] = {
    "service": "サービスについて",
    "pricing": "料金・費用について",
    "area": "対応エリアについて",
    "privacy": "個人情報の取り扱いについて",
    "trouble": "トラブル・クレーム",
    "partner": "業者登録・提携について",
    "press": "取材・メディア掲載",
    "other": "その他",
}


async def send_contact_received(
    to_email: str, name: str, email: str, category: str, message: str
) -> bool:
    """お問い合わせフォーム（/contact）の受付通知（運営admin宛・H1対応）。"""
    category_label = _CONTACT_CATEGORY_LABELS.get(category, category)
    return await _send(
        to_email,
        f"【カタヅケ】お問い合わせを受け付けました（{category_label}）",
        _wrap(
            f"<p>氏名: {html.escape(name)}</p>"
            f"<p>連絡先メール: {html.escape(email)}</p>"
            f"<p>種別: {html.escape(category_label)}</p>"
            "<p>本文:</p>"
            f'<p style="white-space:pre-wrap;">{html.escape(message)}</p>'
        ),
    )


async def send_withdrawn_contact_review_admin_alert(
    to_email: str, original_email: str, unlinked_count: int
) -> bool:
    """退会者と同じメールアドレスの「紐付かない」問い合わせの削除確認依頼（admin宛）。

    退会時の問い合わせ匿名化は送信者アカウント（contact_messages.user_id）一致の行に
    限定している（メール一致で自動削除すると、他人のアドレスで登録→退会するだけで
    その人の問い合わせを消せてしまうため・security review 指摘対応）。未ログインで
    送られた同一メールの行はプライバシーポリシー第7条（退会時は遅滞なく削除）の
    対象になりうるが送信者の同一性を確認できないため、運営に本人確認のうえでの
    削除を依頼する。宛先は運営のみで、send_contact_received と同じく連絡先メールを
    載せる（該当行を一覧で特定し、本人確認の連絡を取るために必要）。
    """
    settings = get_settings()
    url = f"{settings.frontend_base_url}/admin/contacts"
    return await _send(
        to_email,
        "【カタヅケ管理】退会者と同じメールアドレスのお問い合わせの確認依頼",
        _wrap(
            "<p>依頼者アカウントの退会がありました。退会前のメールアドレス"
            f"（{html.escape(original_email)}）と同じアドレスで、ログインせずに送られた"
            f"お問い合わせが {int(unlinked_count)} 件あります。</p>"
            "<p>送信者がこのアカウントの本人かを確認できないため、自動では削除していません"
            "（他人のアドレスで登録して退会すると、その人のお問い合わせを消せてしまうため）。"
            "このアドレス宛に本人確認を行い、本人からの削除のご希望が確認できた場合のみ、"
            "お問い合わせ一覧から削除してください。</p>"
            f'<p><a href="{html.escape(url, quote=True)}">お問い合わせ一覧へ</a></p>'
        ),
    )


async def send_operator_application_rejected(to_email: str, company_name: str, reason: str) -> bool:
    """⑥ 業者事前申込の却下通知（申込者宛）。"""
    return await _send(
        to_email,
        "【カタヅケ】業者登録のお申込みについて",
        _wrap(
            f"<p><strong>{html.escape(company_name)}</strong> 様</p>"
            "<p>誠に恐れ入りますが、今回のお申込みは承認を見送らせていただきました。</p>"
            f"<p>理由: {html.escape(reason)}</p>"
        ),
    )


async def send_operator_verified(to_email: str, company_name: str, active: bool) -> bool:
    """業者の入札可否切替（vendor_status: active/pending）の通知（業者宛・r6 H3）。

    事前申込の承認（send_operator_application_approved）とは別イベント。実際に入札
    できるようになった／できなくなったタイミングを本人に知らせる唯一の経路。
    """
    settings = get_settings()
    if active:
        url = f"{settings.frontend_base_url}/operator/cases"
        return await _send(
            to_email,
            "【カタヅケ】入札のご利用が可能になりました",
            _wrap(
                f"<p><strong>{html.escape(company_name)}</strong> 様</p>"
                "<p>審査が完了し、案件への入札をご利用いただけるようになりました。</p>"
                f'<p><a href="{url}">公開中の案件を見る</a></p>'
            ),
        )
    url = f"{settings.frontend_base_url}/operator"
    return await _send(
        to_email,
        "【カタヅケ】入札のご利用状況について",
        _wrap(
            f"<p><strong>{html.escape(company_name)}</strong> 様</p>"
            "<p>現在、案件への入札を一時的に停止させていただいております。</p>"
            "<p>ご不明な点はお問い合わせください（katazuke.info@gmail.com）。</p>"
            f'<p><a href="{url}">業者マイページを開く</a></p>'
        ),
    )


async def send_account_unsuspended(to_email: str, party: str) -> bool:
    """アカウント停止の解除通知（本人宛・r6 H1）。

    停止（suspend）時は理由開示の是非が運用ポリシー判断のため通知しない。解除は
    「復帰したことを本人が知る手段がゼロ」になるため必ず通知する。
    停止前に発行されたログインは解除後も無効のまま（deps の sessions_revoked_at）のため、
    再ログインが必要なことを明記する（「使えない」という問い合わせを防ぐ）。
    """
    settings = get_settings()
    url = (
        f"{settings.frontend_base_url}/operator"
        if party == "operator"
        else f"{settings.frontend_base_url}/mypage"
    )
    return await _send(
        to_email,
        "【カタヅケ】アカウントのご利用を再開いただけます",
        _wrap(
            "<p>アカウントの利用制限を解除しました。</p>"
            "<p>安全のため、利用制限の前のログイン状態は解除しています。お手数ですが、"
            "あらためてログインしてからご利用ください。</p>"
            "<p>ご不便をおかけし申し訳ありませんでした。</p>"
            f'<p><a href="{url}">マイページを開く</a></p>'
        ),
    )


async def send_identity_document_reviewed(
    to_email: str, approved: bool, reason: str | None = None
) -> bool:
    """本人確認書類の審査結果通知（依頼者宛・r6 H2）。

    却下時は再提出のために理由を本文へ含める（DB にも保存され /mypage/identity で
    再確認できるが、能動的に再訪しない限り気付けないため）。
    """
    settings = get_settings()
    url = f"{settings.frontend_base_url}/mypage/identity"
    if approved:
        return await _send(
            to_email,
            "【カタヅケ】本人確認が完了しました",
            _wrap(
                "<p>ご提出いただいた本人確認書類の確認が完了しました。</p>"
                f'<p><a href="{url}">本人確認の状況を確認する</a></p>'
            ),
        )
    reason_html = f"<p>理由: {html.escape(reason)}</p>" if reason else ""
    return await _send(
        to_email,
        "【カタヅケ】本人確認書類のご確認のお願い",
        _wrap(
            "<p>ご提出いただいた本人確認書類を確認しましたが、受理できませんでした。</p>"
            f"{reason_html}"
            "<p>お手数ですが、内容をご確認のうえ再度ご提出ください。</p>"
            f'<p><a href="{url}">本人確認書類を再提出する</a></p>'
        ),
    )


async def send_completion_requested(to_email: str, case_id: str) -> bool:
    """完了確定のお願い通知（依頼者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】作業完了の確定をお願いします",
        _wrap(
            "<p>成約した業者から作業完了の確定のお願いが届いています。</p>"
            "<p>引き取りが済んでいれば確定してください。"
            "まだの場合は、業者とチャットでご確認ください。</p>"
            f'<p><a href="{url}">内容を確認して確定する</a></p>'
        ),
    )


async def send_transaction_completed(to_email: str, transaction_id: str, amount: int) -> bool:
    """作業完了の確定通知（業者宛）。

    確定は依頼者本人だけでなく運営（admin）が代行する経路もあるため、文面は
    「誰が確定したか」に依存しない表現にする（確定者の記録は Message.meta.completed_by）。
    """
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】作業完了が確定しました",
        _wrap(
            f"<p>作業完了が確定しました（確定額 <strong>{amount:,} 円</strong>）。</p>"
            "<p>取引の評価をお願いします。</p>"
            f'<p><a href="{url}">成約詳細を確認する</a></p>'
        ),
    )


async def send_schedule_proposed(to_email: str, transaction_id: str) -> bool:
    """訪問日程の候補提示通知（依頼者宛）。候補の文字列は信頼できない差し込み値のため
    本文には載せない（push_schedule_proposed と同じ理由）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/chat/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】訪問日程の候補が届きました",
        _wrap(
            "<p>成約した業者から訪問日程の候補が届きました。</p>"
            "<p>ご都合のよい候補を選ぶと日程が確定します。</p>"
            f'<p><a href="{url}">候補日を確認する</a></p>'
        ),
    )


async def send_message_received(
    to_email: str, transaction_id: str, recipient_party: str = "user"
) -> bool:
    """新着チャットの通知（依頼者宛・pdca seller 高#5）。メッセージ本文・氏名などの
    差し込み値は一切載せず、「新着があります」とログイン先のリンクだけを送る。

    本日の送信数（プロセス内の概数）が _DAILY_CHAT_MAIL_STOP_ABOVE を超えたら送らない
    （Brevo 無料枠を重要メールに残す。QA M-4）。"""
    if is_chat_mail_suppressed():
        return False
    settings = get_settings()
    url = f"{settings.frontend_base_url}/chat/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】チャットに新着メッセージがあります",
        _wrap(
            "<p>やり取り中の取引に、新しいメッセージがあります。</p>"
            "<p>内容はログインしてご確認ください。</p>"
            f'<p><a href="{url}">チャットを開く</a></p>'
        ),
    )


async def send_password_reset(
    to_email: str, account_type: str, raw_token: str, expires_minutes: int
) -> bool:
    """パスワード再設定の案内（本人宛・services/password_reset.py からのみ呼ぶ）。

    件名・本文には氏名・メールアドレス等の個人情報を入れず、再設定リンクと有効期限・
    「心当たりがない場合は無視してください」だけを載せる。``raw_token`` は平文の
    1回限りトークンで、ここ以外（ログ・アラート・DB）には出さない（本関数もログしない。
    送信失敗時の ``_send_raw`` のログは宛先をマスクし、本文を載せない）。

    トークンは URL のクエリではなくフラグメント（``#token=...&type=...``）に載せる
    （security review M-3: フラグメントはサーバーへ送られないため、web 側のアクセスログ・
    Referer・プロキシのログにトークンが残らない）。
    """
    settings = get_settings()
    fragment = f"token={quote(raw_token, safe='')}&type={quote(account_type, safe='')}"
    url = html.escape(
        f"{settings.frontend_base_url}/password-reset/confirm#{fragment}", quote=True
    )
    return await _send(
        to_email,
        "【カタヅケ】パスワード再設定のご案内",
        _wrap(
            "<p>パスワード再設定の手続きを受け付けました。</p>"
            "<p>下のリンクから新しいパスワードを設定してください。"
            f"リンクの有効期限は{expires_minutes}分で、1回だけ使えます。</p>"
            f'<p><a href="{url}">新しいパスワードを設定する</a></p>'
            "<p>このメールに心当たりがない場合は、何もせずに無視してください"
            "（パスワードは変更されません）。</p>"
        ),
    )


async def send_password_changed(to_email: str) -> bool:
    """パスワード再設定の完了通知（本人宛・security review M-2）。

    不正な再設定の早期検知が目的。件名・本文には氏名・メールアドレス・新しいパスワード等を
    入れず、「変更されたこと」と問い合わせ先だけを載せる。
    """
    return await _send(
        to_email,
        "【カタヅケ】パスワードが変更されました",
        _wrap(
            "<p>お客様のアカウントのパスワードが、パスワード再設定の手続きにより変更されました。</p>"
            "<p>心当たりがない場合は、お手数ですが至急カタヅケまでお問い合わせください"
            "（お問い合わせ: katazuke.info@gmail.com）。</p>"
        ),
    )
