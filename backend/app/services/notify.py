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

import httpx

from app.config import get_settings
from app.services import alerts

logger = logging.getLogger(__name__)

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
# BREVO_API_KEY 未設定スキップの運営アラートを、プロセス内で最初の1回だけ発火するためのフラグ。
_brevo_missing_key_alerted = False


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
    settings = get_settings()
    if not settings.brevo_api_key:
        logger.error("notify: BREVO_API_KEY 未設定のため送信スキップ - %s / %s", to_email, subject)
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
        return False
    payload = {
        "sender": {"email": settings.mail_from, "name": settings.mail_from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                _BREVO_ENDPOINT,
                json=payload,
                headers={"api-key": settings.brevo_api_key},
            )
            res.raise_for_status()
        return True
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
                key="notify_brevo_send_failed",
            )
        )
        return False


def _wrap(body: str) -> str:
    return (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px;">'
        '<h2 style="color:#14B8A6;margin:0 0 16px;">カタヅケ</h2>'
        f"{body}"
        '<p style="color:#888;font-size:12px;margin-top:24px;">'
        "このメールはカタヅケ運営事務局（神奈川県横浜市）から自動送信されています。"
        "お問い合わせ: katazuke.info@gmail.com</p></div>"
    )


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


async def send_bid_selected(to_email: str, transaction_id: str, amount: int) -> bool:
    """③ 落札通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】入札が落札されました",
        _wrap(
            f"<p>あなたの入札（<strong>{amount:,} 円</strong>）が選ばれました。</p>"
            "<p>住所詳細が開示されています。訪問日の調整を進めてください。</p>"
            f'<p><a href="{url}">落札案件の詳細を確認する</a></p>'
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
            f"<p>落札業者から <strong>{amount:,} 円</strong> への減額のご相談が届いています。</p>"
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
            "<p>アカウントの利用制限を解除しました。これまでどおりご利用いただけます。</p>"
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
