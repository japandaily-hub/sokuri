"""機微データの表示用マスキングユーティリティ。

元々 ``admin.py`` にプライベート関数として実装されていたが、
``users.py`` / ``user_identity.py`` 側の依頼者向け口座マスク表示でも
同一ロジックが必要になったため、共通モジュールへ切り出す（DRY原則）。
"""

from __future__ import annotations


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
