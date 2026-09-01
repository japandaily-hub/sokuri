"""汎用テキスト無害化ユーティリティ — NFKC正規化・制御文字/Unicode双方向制御文字の除去。

複数箇所（``services/summary.py`` の ``_safe_attr``、``schemas_katadzuke.py`` の
``CaseItemIn.name`` バリデータ等）で共通に必要となる「表示前の最低限の無害化」
処理をここに集約する（DRY。ロジックのズレ・改修漏れの防止）。
"""

from __future__ import annotations

import unicodedata


def strip_control_and_bidi_chars(text: str) -> str:
    """Unicode カテゴリ C*（制御文字・書式文字/Unicode双方向制御文字・
    私用領域・サロゲート・未割り当て）を全て除去する。

    表示崩れ・なりすまし（RLO/LRO 等の双方向制御文字による見た目偽装）対策。
    """
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")


def normalize_and_strip_control_chars(value: str) -> str:
    """NFKC正規化した上で制御文字・双方向制御文字を除去し、前後の空白を取り除く。"""
    text = unicodedata.normalize("NFKC", value).strip()
    return strip_control_and_bidi_chars(text).strip()
