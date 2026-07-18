"""クライアント IP の解決（X-Forwarded-For の右から N ホップ）とログ用の匿名化。

設計書（認証系レート制限）§2 の実装。**この方式選定の根拠を必ず理解した上で
変更すること**（誤ると全体障害、または偽装によるレート制限の完全無効化に
直結する）。

- ``request.client.host`` をそのまま使う → リバースプロキシ配下では常に
  プロキシ自身の IP になり、全ユーザーが同一バケットを共有して数分で
  全世界のログインが 429 になる全体障害を起こす。
- ``X-Forwarded-For`` の**先頭（左端）**を無検証で使う → 攻撃者が
  ``X-Forwarded-For: 1.2.3.4`` を自由に付与でき、リクエスト毎に別 IP を
  名乗ってレート制限を無限回避できる。先頭要素は常に「最も信用できない値」
  である。
- 各プロキシは自分が接続を受けた相手の IP をリストの**末尾に追記**する
  （RFC 7239 / MDN の追記セマンティクス）。よって「信頼するホップ数 N を
  固定し、右から N 番目を取る」方式のみが唯一の偽装耐性を持つ。
  **左から取る実装は原理的に偽装可能であり、採用してはならない。**
"""

from __future__ import annotations

import ipaddress
import logging

from fastapi import Request

from app.core.log_throttle import ThrottledLogger

logger = logging.getLogger(__name__)

# XFF のエントリ数が trusted_hops 未満だった場合の WARNING は、プロキシの
# 構成変更（＝全体障害の前兆）の可能性がある一方、リクエスト毎に出すと
# ログを埋め尽くす。「1回きり」の抑制は攻撃者が起動直後に1回不正な短い
# XFF を送るだけで永久に消費でき、以後本物の異常が起きても二度と出せなく
# なるため、60秒スロットリングに統一する（security review Medium-2）。
_short_xff_throttle = ThrottledLogger()

# XFF の要素数の上限（security review L-4 対応）。実効的な DoS ではないが、
# 悪意ある極端に長いヘッダでの処理コストを抑える防御的な上限。実運用で
# これを超える段数のプロキシ構成は想定していない。
_MAX_XFF_ENTRIES = 32


def get_xff_raw(request: Request) -> str | None:
    """X-Forwarded-For の生値を取得する（重複ヘッダを "," 結合してから返す）。

    Starlette の ``Headers.get()`` は同名ヘッダが複数存在する場合、**先頭1件
    のみ**を返す（RFC 7230 が定めるカンマ結合を行わない）。実機検証で
    確認済み: ``Headers(raw=[(b"x-forwarded-for", b"9.9.9.9"),
    (b"x-forwarded-for", b"203.0.113.5")]).get(...)`` は ``"9.9.9.9"``
    （攻撃者側の値）のみを返し、プロキシが追記した実IPが消える
    （security review High-2、実機で再現確認済み）。

    上流プロキシが「既存ヘッダへの追記」ではなく「別行として XFF ヘッダを
    追加」する実装だと、``trusted_hops=1`` でも右端保持のロジックが
    攻撃者の値を指してしまい、偽装耐性が完全に失われる（値としては正当な
    IP なので 400 フェイルクローズにも掛からない）。``getlist()`` で全ての
    値を取得し ``","`` 結合することで、単一行の XFF と同じ処理経路に正規化する。

    **``resolve_client_ip`` と ``rate_limit_deps.RateLimitGuard`` は必ず
    この関数を経由すること。** ヘッダ取得を個別に実装すると、両者の判定が
    乖離し無言のバイパスに戻る（security review 指摘）。
    """
    values = request.headers.getlist("X-Forwarded-For")
    if not values:
        return None
    return ",".join(values)


# 「内部プロキシIPを掴んでいる疑い」の判定対象は、実運用の内部ネットワークで
# 実際に使われるレンジのみに限定する。**``ipaddress.IPv4Address.is_private`` は
# 使わない**（意図的な設計判断・両方向に外れるため）:
#
# (1) 広すぎる方向: 標準の ``is_private`` は「グローバルに到達可能でない」と
#     いう広い定義で、RFC 5737 のドキュメント/テスト用レンジ
#     （192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24）まで ``True`` を返す。
#     これらは例示・テストで「実在しない公開IP」として広く使われる値であり、
#     内部プロキシ誤検知の指標にはならない（そのまま使うと、これらを送信元と
#     する通常のクライアント／テストで IP軸が常時スキップされてしまう）。
# (2) 狭すぎる方向: 標準の ``is_private`` は **RFC 6598（100.64.0.0/10、
#     Shared Address Space）を ``False`` と判定する**。しかしこのレンジは
#     Kubernetes / 各種クラウドがコンテナ間の内部ネットワークに最も一般的に
#     使う帯であり、**本判定が最も守りたい「内部プロキシIPを掴んでいる」
#     ケースの筆頭候補**である。ここを取りこぼすと、TRUSTED_PROXY_HOPS
#     誤設定時に全ユーザーが同一バケットを共有する全体障害を検知できない。
#
# したがって標準判定に依存せず、対象レンジを明示列挙する。
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
    ipaddress.ip_network("100.64.0.0/10"),  # RFC6598 (k8s/クラウド内部で多用)
    ipaddress.ip_network("169.254.0.0/16"),  # リンクローカル（メタデータ等）
    ipaddress.ip_network("fc00::/7"),  # IPv6 ユニークローカルアドレス
    ipaddress.ip_network("fe80::/10"),  # IPv6 リンクローカル
)


def is_private_or_loopback(ip: str) -> bool:
    """IP が（RFC1918 の意味での）プライベート、またはループバックかどうかを判定する。

    レート制限ガード側（``rate_limit_deps.RateLimitGuard``）が「信頼位置の
    IP（``parts[-trusted_hops]``）がプライベート/ループバック＝
    ``TRUSTED_PROXY_HOPS`` 誤設定で内部プロキシIPを掴んでいる疑い」を判定し、
    IP軸をスキップする（＝全ユーザーが同一バケットを共有する全体障害を
    構造的に防ぐ）ために使う（security review 指摘）。不正な文字列は
    ``False`` を返す（呼び出し側は既に ``ip_address()`` 検証済みの値のみ
    渡す想定だが、単体でも安全に使えるようにする）。
    """
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if parsed.is_loopback:
        return True
    return any(
        parsed.version == net.version and parsed in net for net in _PRIVATE_NETWORKS
    )


def _strip_port(candidate: str) -> str:
    """"1.2.3.4:5678" / "[2001:db8::1]:443" からポート表記を除去する。

    IPv6 の素の表記（コロンを複数含む）を誤って "host:port" と解釈しない
    よう、コロンがちょうど1個の場合のみ "host:port" とみなす。
    """
    candidate = candidate.strip()
    if candidate.startswith("["):
        end = candidate.find("]")
        if end != -1:
            return candidate[1:end]
        return candidate
    if candidate.count(":") == 1:
        host, _, port = candidate.partition(":")
        if port.isdigit():
            return host
    return candidate


def _warn_short_xff(xff_count: int, trusted_hops: int) -> None:
    _short_xff_throttle.emit(
        lambda: logger.warning(
            "client_ip: X-Forwarded-For のエントリ数(%d)が TRUSTED_PROXY_HOPS(%d)未満です。"
            "プロキシ構成が変更された可能性があります（全体障害の前兆になりえるため要確認）。",
            xff_count,
            trusted_hops,
        )
    )


def resolve_client_ip(request: Request, trusted_hops: int) -> str | None:
    """クライアントの実 IP を解決する。

    手順（設計書 §2、security review 指摘を反映）:
      1. ``trusted_hops <= 0`` の場合は XFF を一切信頼せず ``request.client.host``
         を採用する（"XFF を信頼しない" の明示的な意味）。
      2. XFF ヘッダが無ければ ``request.client.host`` を採用する
         （``get_xff_raw()`` 経由。重複ヘッダは "," 結合される）。
      3. XFF を "," 分割 → strip → 空要素除去 →（除去した後に）末尾
         ``_MAX_XFF_ENTRIES`` 件に切り詰める（順序が逆だと、除去前の生トークン
         数で切ってしまい実質的な保持件数が32件未満になりうるため、
         **必ず除去してから切り詰める**。security review L-4 是正）。
         要素数が ``trusted_hops`` 以上あれば右から ``trusted_hops`` 番目
         （``parts[-trusted_hops]``）を採用する。**不足時は ``None`` を返す**
         （以前は左端 ``parts[0]`` にフォールバックしていたが、左端は攻撃者が
         完全に制御できる値であるため廃止した。呼び出し側の
         ``RateLimitGuard`` で「XFFはあるのに解決不能」として400フェイル
         クローズに合流する。security review High-1 是正。``trusted_hops=1``
         ではこの分岐は到達不能＝挙動変化なし。``trusted_hops`` を上げた
         場合の保険）。
      4. "[...]:port" / "1.2.3.4:5678" のポート表記を除去する。
      5. ``ipaddress.ip_address()`` で検証し、失敗時は ``None`` を返す
         （不正値・SQL インジェクション的な文字列混入等を含む）。
      6. プライベート / ループバック IP か否かの判定・対処はここでは行わず
         そのまま返す（呼び出し側が ``is_private_or_loopback()`` で判断し、
         IP軸をスキップするかどうかを決める。診断エンドポイントはこの値を
         そのまま実測結果として表示する必要があるため、本関数はポリシー
         判断を持たない）。

    戻り値が ``None`` の場合の方針（呼び出し側の責務）: IP 軸の制限は
    スキップし、アカウント軸の制限は通常どおり適用する（設計書 §2）。
    ただし XFF ヘッダが**存在するのに**解決できなかった場合は、正規クライアント
    では通常起こらない異常な入力のため、呼び出し側（``rate_limit_deps.py`` の
    ``RateLimitGuard``）でリクエスト自体を拒否する（security review 指摘）。
    本関数の戻り値仕様自体は変えない（``None`` のまま。診断エンドポイントは
    問題を「報告」する必要があるため、ここで例外を投げてはならない）。
    """
    if trusted_hops <= 0:
        candidate = request.client.host if request.client else None
    else:
        xff_raw = get_xff_raw(request)
        if xff_raw is None:
            candidate = request.client.host if request.client else None
        else:
            # 空要素の除去を先に行ってから末尾 _MAX_XFF_ENTRIES 件に切り詰める
            # （順序が逆だと保持件数が32件未満になりうる。security review L-4）。
            meaningful_parts = [p.strip() for p in xff_raw.split(",") if p.strip()]
            parts = meaningful_parts[-_MAX_XFF_ENTRIES:]
            if not parts:
                # ヘッダは存在するが空/カンマのみ等でパース結果が空。
                # "XFF 自体が無い" 場合（request.client.host へフォールバック）
                # とは意図的に区別し、不正な入力として None を返す。
                candidate = None
            elif len(parts) >= trusted_hops:
                candidate = parts[-trusted_hops]
            else:
                _warn_short_xff(len(parts), trusted_hops)
                candidate = None

    if candidate is None:
        return None

    candidate = _strip_port(candidate)

    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None

    return candidate


def truncate_ip_for_log(ip: str) -> str:
    """ログ出力用に IP を丸める（IPv4 は /24、IPv6 は /48）。

    生 IP は GDPR / 日本の個人情報保護法いずれでも個人関連情報として
    扱われうる。Render 無料プランのログは第三者管理下にあり保持設定も
    制御できないため、生 IP をそのまま書かないのが最も安い正解（設計書 §9）。
    """
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    prefix = 24 if isinstance(parsed, ipaddress.IPv4Address) else 48
    network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
    return str(network)
