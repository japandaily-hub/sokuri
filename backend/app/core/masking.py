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
