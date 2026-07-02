"""クライアントIPアドレス抽出ユーティリティ。

Render 等の PaaS はリバースプロキシ経由でアプリに接続するため、
``Request.client.host`` はプロキシ自身のIPになり得る。``X-Forwarded-For``
ヘッダの先頭要素（オリジナルクライアントIP）を優先して採用する。

注意: ``X-Forwarded-For`` はクライアントが任意の値を詐称して送信できるヘッダである。
本アプリはこの値を「認可判定」には使わず、あくまでレート制限・スパム対策という
可用性目的の緩やかな絞り込みにのみ用いる（詐称による完全なバイパスも起こり得るが、
無制限公開よりは大幅に悪用コストを引き上げられるため許容する）。
"""

from __future__ import annotations

from starlette.requests import Request

# DBカラム operator_applications.client_ip の String(64) に収まる長さに切り詰める
# （IPv6でも45文字程度で収まるが、詐称ヘッダによる異常長入力を安全側で防御する）。
_MAX_IP_LENGTH = 64


def get_client_ip(request: Request) -> str | None:
    """リクエストからクライアントIPアドレスを抽出する。取得できない場合は None。"""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip[:_MAX_IP_LENGTH]
    if request.client is not None and request.client.host:
        return request.client.host[:_MAX_IP_LENGTH]
    return None
