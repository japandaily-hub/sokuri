"""機微データの表示用マスキングユーティリティ。

元々 ``admin.py`` にプライベート関数として実装されていたが、
``users.py`` / ``user_identity.py`` 側の依頼者向け口座マスク表示でも
同一ロジックが必要になったため、共通モジュールへ切り出す（DRY原則）。
"""

from __future__ import annotations

import re

#: 自由文に紛れ込んだメールアドレスを拾う正規表現（:func:`mask_emails_in_text` 用）。
#: ローカル部は文字・数字（Unicode を含む）と ``. _ + - '`` に限る。RFC 5322 は ``=`` や ``/``
#: 等も許すが、ログやアラート本文は ``email=<addr>``・``admin-grant:<addr>`` の形で書かれる
#: ため、それらを含めると ``email=`` 等のラベルまで巻き込んで潰し、照合の手掛かりが消える。
#: ドメイン部はドットを1つ以上要求する（``@router`` のような語や ``user@localhost`` は対象外）。
_EMAIL_IN_TEXT_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def mask_account_number(account_number: str) -> str:
    """口座番号の下4桁のみ残しマスクする。4桁以下はそのまま返さず全マスクする。"""
    if len(account_number) <= 4:
        return "*" * len(account_number)
    return "*" * (len(account_number) - 4) + account_number[-4:]


def mask_email(email: str) -> str:
    """メールアドレスをログ出力用にマスクする（先頭1文字 + ``***`` + ドメイン部）。

    例: ``"user@example.com"`` -> ``"u***@example.com"``。宛先メールアドレスは
    ログ集約基盤（外部 SaaS 含む）へ平文のまま流出しうる PII のため、
    エラーログ等の非構造化出力へ載せる際は本関数を経由すること
    （security review 2026-09-18 Low: BREVO_API_KEY 未設定スキップの
    ログが宛先を平文出力していた）。``@`` を含まない/空文字列等の不正な
    値は全体をマスクして返す（フォールバックで平文が漏れないようにする）。
    """
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_emails_in_text(text: str) -> str:
    """自由文に含まれるメールアドレスをすべて :func:`mask_email` の形式に置き換える。

    例: ``"email=user@example.com\\nuser_id=1"`` -> ``"email=u***@example.com\\nuser_id=1"``。
    運営アラートの本文（``email=...`` を含む）をそのままログへ書く箇所や、ログ出力の
    直前の安全網（app/core/app_logging.py）で使う。呼び出し側で値が分かっている場合は、
    従来どおり :func:`mask_email` で個別にマスクすること（本関数は取りこぼし対策）。
    """
    if not text or "@" not in text:
        return text
    return _EMAIL_IN_TEXT_RE.sub(lambda match: mask_email(match.group(0)), text)
