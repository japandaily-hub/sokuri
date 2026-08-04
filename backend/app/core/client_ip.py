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

**設計判断の履歴（撤回済み案・重要）**: ``TRUSTED_PROXY_HOPS`` の段数設定に
依存しない「信頼済みプロキシレンジ（Cloudflare 公開IP + 内部プロキシ）の
右端スキャン」方式を解決方式そのものの代替として採用することを一度実装したが、
security review で Critical 判定を受け **撤回した**。理由:
Cloudflare Workers 等、Cloudflare の公開IPレンジ内から任意にアウトバウンド
``fetch()`` できるサービスを攻撃者が無料で利用でき、「CFレンジ内＝信頼できる
中間ホップ」という前提そのものが成立しない。
  - padding あり: ``spoofA, <Worker のCF egress>, <本物のCFエッジ>, <10.x>``
    を送ると、右端スキャンは信頼済み（と誤認した）ホップを全てスキップして
    攻撃者制御の ``spoofA`` まで遡り、IP軸を完全に偽装できる。
  - padding なし: 全要素が「信頼済み」と誤認され、実クライアントIPを含まない
    XFF を送るだけで IP軸をまるごとスキップさせられる（IP軸しか持たない
    signup / line_exchange が無防備になる）。
  - さらに本番実測（2026-07-20）で確認済み: 本番の ``Server: cloudflare`` /
    ``x-render-origin-server: uvicorn`` は **Render 側が管理する CF ゾーン**
    であり自ゾーンではない。したがって Cloudflare の Transform Rule による
    秘密ヘッダ注入や Authenticated Origin Pulls（証明書ベースでオリジンへの
    到達元を CF のみに限定する仕組み）は使えず、``CF-Connecting-IP`` ヘッダも
    同じ理由（CF の同一テナント内であれば誰でもオリジンに到達し細工できる）
    で信頼できない。**「CFレンジに属する」という判定は「共有テナント基盤に
    属する」ことの証明にしかならず、暗号学的な送信元証明（mTLS・署名済み
    ヘッダ等）を持たない本構成では、レート制限やその他のセキュリティ判断の
    根拠にはできない。**

このため、右端スキャン（``scan_client_ip_for_diagnostics``）は**診断表示・
CDN構成ドリフトの早期検知シグナル専用**に格下げし、レート制限の判定経路
（``resolve_client_ip_with_reason`` / ``RateLimitGuard``）からは完全に排除
している。正本は引き続き固定段数の hops 方式（``resolve_client_ip_with_reason``）
である。
"""

from __future__ import annotations

import ipaddress
import logging
from typing import NamedTuple

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

    **``resolve_client_ip_with_reason`` と ``rate_limit_deps.RateLimitGuard``
    は必ずこの関数を経由すること。** ヘッダ取得を個別に実装すると、両者の
    判定が乖離し無言のバイパスに戻る（security review 指摘）。
    """
    values = request.headers.getlist("X-Forwarded-For")
    if not values:
        return None
    return ",".join(values)


def _parse_and_cap_xff(xff_raw: str) -> list[str]:
    """XFF の生値を分割・正規化して返す（hops 経路・診断専用 scan 経路で共有）。

    手順（この順序を守ること。逆にすると保持件数が減りうる。security review
    L-4）:
      1. "," 分割 → 前後空白 strip。
      2. 空要素を除去する。
      3. **除去した後に**末尾 ``_MAX_XFF_ENTRIES`` 件へ切り詰める（除去前の
         生トークン数で切ると、意味のある要素が32件未満しか残らない場合が
         ある）。

    qa 指摘 M-3: 以前は hops 経路と scan 経路でこのロジックが重複していた。
    解決方式が2系統ある間は特に、パース仕様の乖離が「診断結果と実挙動が
    食い違う」バグを生みやすいため、単一の実装に統合する。
    """
    meaningful_parts = [p.strip() for p in xff_raw.split(",") if p.strip()]
    return meaningful_parts[-_MAX_XFF_ENTRIES:]


def _unwrap_ipv4_mapped(
    parsed: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """IPv4 射影 IPv6 アドレス（``::ffff:a.b.c.d`` 形式）を IPv4 アドレスへ展開する。

    security review Critical: プロキシ実装や OS のソケットスタックによっては、
    デュアルスタック環境で IPv4 接続を IPv6 ソケット上で受けた際に
    ``::ffff:10.0.0.1`` のような射影表記で XFF に追記することがある。
    展開せずに判定すると、``is_private_or_loopback("::ffff:10.0.0.1")`` が
    ``False`` を返し（``_PRIVATE_NETWORKS`` は IPv4Address としてしか
    比較しないため）、``TRUSTED_PROXY_HOPS`` 誤設定時の全断防止スキップを
    すり抜けてしまう。展開して IPv4 表現に正規化することで、この抜け穴を
    塞ぐと同時に、表記揺れ（``10.0.0.1`` と ``::ffff:10.0.0.1`` が別の
    バケットキーになる問題。security review Medium-2）も解消する。
    """
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return parsed.ipv4_mapped
    return parsed


def _parse_single_ip(raw: str) -> str | None:
    """1つの候補値を検証・正規化する（hops 経路・診断専用 scan 経路・
    ``request.client.host`` フォールバックの全てで共有する。qa 指摘 M-3）。

    手順: ``_strip_port`` でポート表記を除去 → ``ipaddress.ip_address()`` で
    検証（失敗時は ``None``）→ ``_unwrap_ipv4_mapped`` で IPv4 射影 IPv6 を
    展開 → 正規化済み文字列（``str(parsed)``。IPv6 は圧縮表記に統一される）
    を返す。戻り値は以降 ``is_private_or_loopback`` 等にそのまま渡せる。
    """
    candidate = _strip_port(raw)
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    parsed = _unwrap_ipv4_mapped(parsed)
    return str(parsed)


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


def _is_private_or_loopback_addr(
    parsed: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """``is_private_or_loopback`` / ``is_trusted_proxy_ip`` が共有する内部判定
    （IPv4 射影展開済みの ``parsed`` を受け取る。qa 指摘 M-3 DRY）。"""
    if parsed.is_loopback:
        return True
    return any(
        parsed.version == net.version and parsed in net for net in _PRIVATE_NETWORKS
    )


def is_private_or_loopback(ip: str) -> bool:
    """IP が（RFC1918 の意味での）プライベート、またはループバックかどうかを判定する。

    レート制限ガード側（``rate_limit_deps.RateLimitGuard``）が「信頼位置の
    IP（``parts[-trusted_hops]``）がプライベート/ループバック＝
    ``TRUSTED_PROXY_HOPS`` 誤設定で内部プロキシIPを掴んでいる疑い」を判定し、
    IP軸をスキップする（＝全ユーザーが同一バケットを共有する全体障害を
    構造的に防ぐ）ために使う（security review 指摘）。信頼位置は攻撃者が
    値を選べない位置（CF/プロキシが追記する）のため、この判定でスキップに
    倒しても悪用経路にはならない（設計根拠の詳細は ``RateLimitGuard`` の
    docstring 参照）。

    IPv4 射影 IPv6（``::ffff:10.0.0.1``）も展開して判定する（security review
    Critical。``_unwrap_ipv4_mapped`` 参照）。不正な文字列は ``False`` を
    返す（呼び出し側は既に ``ip_address()`` 検証済みの値のみ渡す想定だが、
    単体でも安全に使えるようにする）。
    """
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    parsed = _unwrap_ipv4_mapped(parsed)
    return _is_private_or_loopback_addr(parsed)


def is_special_use_address(ip: str) -> bool:
    """IP が「未指定アドレス（``0.0.0.0`` / ``::``）・マルチキャスト・IETF
    予約済みアドレス」のいずれかかどうかを判定する（``is_private_or_loopback``
    とは別カテゴリの異常値）。

    **設計根拠（新設・security review 指摘）**: 信頼位置
    （``parts[-trusted_hops]``）は CF / プロキシがリクエストの実接続元として
    追記する位置であり、**攻撃者はこの位置に現れる値を選べない**（攻撃者が
    自由に付与できるのは XFF の左側だけであり、右端スキャンではなく固定段数
    の hops 方式で常にそこは読み飛ばされる）。したがって、信頼位置に
    未指定/マルチキャスト/予約済みという通常のクライアント接続では
    ありえない値が現れた場合、それは攻撃ではなく**プロキシ実装やロード
    バランサの構成変更**（例: unknown な接続元の代替として ``0.0.0.0`` を
    書き込む実装への変更）を意味する。``is_private_or_loopback`` と同様に
    IP軸をスキップしても、攻撃者がこの状態を意図的に誘発してバイパスを
    得ることはできない（誘発する手段そのものが無い）ため、フェイルクローズ
    ではなくスキップに倒してよい。

    IPv4 射影 IPv6 も展開してから判定する（``is_private_or_loopback`` と
    同じ前処理。表記揺れ対策）。不正な文字列は ``False`` を返す。
    """
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    parsed = _unwrap_ipv4_mapped(parsed)
    return bool(parsed.is_unspecified or parsed.is_multicast or parsed.is_reserved)


# ── Cloudflare 公開IPレンジ ─────────────────────────────────────────
#
# 出典: https://www.cloudflare.com/ips-v4 （v4） / https://www.cloudflare.com/ips-v6
# （v6）。取得日 2026-07-20。
#
# **用途は診断表示（``scan_client_ip_for_diagnostics``）と、hops 方式での
# 「信頼位置の値が CF レンジ内＝TRUSTED_PROXY_HOPS が実構成より小さい疑い」
# を検知する WARNING 専用の判定に限定する。このレンジ判定結果を IP軸の
# スキップ/カウントの可否など、いかなるセキュリティ上の意思決定にも
# 使ってはならない**（security review Critical・High-1 指摘。詳細は本モジュール
# 冒頭の「設計判断の履歴」を参照）。
#
# **CF がレンジを追加/変更した場合はこの定数の更新が必要。更新漏れは
# 両方向に破綻しうる**（以前は「粗くなるだけで偽装は許さない」と記載して
# いたが誤りだったため訂正する。security review High-1）:
#   - CF が新しいレンジを追加した場合: そのレンジ経由の全リクエストが
#     「CF ではない＝クライアントIP」と誤判定され、当該エッジを通る全ユーザーが
#     同一の（未知の）ホップIPを共有し、全断方向のリスクになりうる。
#   - CF が既存レンジを手放した場合: 第三者がそのレンジを取得すると、
#     「CF レンジ内＝信頼できる中間ホップ」という診断表示上の前提が崩れる。
# ただし本モジュールの設計判断（上記）により、このレンジは**判定に一切
# 使わない診断専用**の情報であるため、更新漏れの実害は「診断表示・WARNING
# の精度低下」に留まり、レート制限の安全性（フェイルクローズ/カウント継続の
# 挙動）そのものには影響しない。
_CLOUDFLARE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        # v4 (https://www.cloudflare.com/ips-v4)
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        # v6 (https://www.cloudflare.com/ips-v6)
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def is_cloudflare_range(ip: str) -> bool:
    """IP が Cloudflare の公開IPレンジ内かどうかを判定する（``is_private_or_loopback``
    とは独立した判定）。

    **[判定に使用禁止・WARNING/診断専用] このレンジ判定結果は、レート制限の
    IP軸のスキップ/カウント可否など、いかなるセキュリティ上の意思決定にも
    使ってはならない。** Cloudflare Workers 等、CF公開レンジ内から任意に
    アウトバウンド接続できるサービスを攻撃者が無料で利用できるため、
    「CFレンジ内＝信頼できる」という前提は成立しない（security review
    Critical。詳細は本モジュール冒頭の「設計判断の履歴」を参照）。

    用途は2つに限定する:
      1. ``scan_client_ip_for_diagnostics``（診断・ドリフト検知専用）。
      2. ``RateLimitGuard`` が「信頼位置の値が CF レンジ内＝
         ``TRUSTED_PROXY_HOPS`` が実構成より小さい疑い」を検知して
         **カウントは継続したまま** WARNING のみ出すための判定
         （スキップはしない。スキップするとバイパスになるため）。

    IPv4 射影 IPv6 も展開してから判定する。不正な文字列は ``False`` を返す。
    """
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    parsed = _unwrap_ipv4_mapped(parsed)
    return any(
        parsed.version == net.version and parsed in net for net in _CLOUDFLARE_NETWORKS
    )


def is_trusted_proxy_ip(ip: str) -> bool:
    """[診断・ドリフト検知専用。レート制限・認可・その他あらゆるセキュリティ
    判断に使ってはならない] IP が「信頼済みプロキシ」（内部プロキシ、または
    Cloudflare）かどうかを判定する。

    ``scan_client_ip_for_diagnostics`` の右端スキャン（診断表示専用）が
    「まだプロキシ段の中にいる」か「実クライアントIPに到達した」かを
    見分けるためだけに使う。Cloudflare Workers 等から CF 公開レンジ内の
    egress IP を攻撃者が無料で取得できるため、この判定結果を信頼して
    レート制限や認可の判断に使うと偽装を許してしまう（security review
    Critical。詳細は本モジュール冒頭の「設計判断の履歴」を参照）。

    ``is_private_or_loopback``（内部プロキシIP）に加えて、``is_cloudflare_range``
    （Cloudflare の公開IPレンジ）内であれば True を返す。不正な文字列は
    ``False`` を返す。
    """
    return is_private_or_loopback(ip) or is_cloudflare_range(ip)


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


class ClientIpResolution(NamedTuple):
    """IP 解決結果と、``ip`` が ``None`` になった理由（またはその成功）。

    「不正値混入（フェイルクローズすべき）」と「実クライアントIPを特定
    できない構成異常（IP軸スキップすべき）」が両方とも ``ip is None`` に
    潰れてしまうと、呼び出し側（``RateLimitGuard``）が両者を区別できず、
    後者を誤って 400 フェイルクローズに合流させてしまう可能性がある
    （security review Critical 指摘）。本 NamedTuple で理由を明示的に分離し、
    呼び出し側が正しい分岐を選べるようにする。

    - ``"ok"``: ``ip`` に解決済みの実クライアントIP（正規化済み文字列）が
      入っている。
    - ``"no_xff"``: XFF ヘッダが無い（``trusted_hops<=0`` で意図的に無視した
      場合を含む）、または ``request.client`` も無くフォールバック先すら
      無い。正規クライアントで通常起こりうる状態のため、呼び出し側は
      IP軸をスキップする（アカウント軸は通常どおり適用）。
    - ``"empty_xff"``: XFF ヘッダは存在するが、パース結果が空（カンマのみ等）。
      正規クライアントでは通常起こらない異常な入力のため、呼び出し側は
      フェイルクローズ（400）する。
    - ``"invalid"``: 検証対象の値が ``ipaddress.ip_address()`` で弾かれた
      （不正値混入、hops 方式での要素数不足を含む）。呼び出し側はフェイル
      クローズ（400）する。
    - ``"all_trusted"``: ``scan_client_ip_for_diagnostics``（診断専用）限定。
      走査した全要素が信頼済みプロキシ（内部プロキシまたは Cloudflare
      レンジ）だった＝実クライアントIPを特定できなかった。**この値は
      レート制限の決定経路（``resolve_client_ip_with_reason``）からは
      生成されない。** 診断エンドポイントの表示にのみ使う。
    """

    ip: str | None
    reason: str


def resolve_client_ip_with_reason(request: Request, trusted_hops: int) -> ClientIpResolution:
    """クライアントの実 IP を解決する（正本。``RateLimitGuard`` はこの関数を
    経由すること）。``ip`` に加えて、``None`` になった理由（``reason``）も返す。

    手順（設計書 §2、security review 指摘を反映）:
      1. ``trusted_hops <= 0`` の場合は XFF を一切信頼せず ``request.client.host``
         を採用する（"XFF を信頼しない" の明示的な意味）。
      2. XFF ヘッダが無ければ ``request.client.host`` を採用する
         （``get_xff_raw()`` 経由。重複ヘッダは "," 結合される）。
      3. XFF を ``_parse_and_cap_xff`` で分割・正規化する（"," 分割 → strip →
         空要素除去 →（除去した後に）末尾 ``_MAX_XFF_ENTRIES`` 件に切り詰め。
         security review L-4）。要素数が ``trusted_hops`` 以上あれば右から
         ``trusted_hops`` 番目（``parts[-trusted_hops]``）を採用する。
         **不足時は ``ip=None, reason="invalid"`` を返す**（以前は左端
         ``parts[0]``＝攻撃者が完全に制御できる値にフォールバックしていたが
         廃止した。呼び出し側の ``RateLimitGuard`` で400フェイルクローズに
         合流する。security review High-1 是正）。
      4. ``_parse_single_ip`` でポート表記除去 → 検証 → IPv4 射影 IPv6 の
         展開 → 正規化文字列化を行う（qa 指摘 M-3 で hops/scan/フォールバック
         経路の全てで共有する共通処理に抽出済み）。

    ``reason`` が ``"invalid"`` / ``"empty_xff"`` になるのは、**XFF ヘッダが
    存在し、かつ ``trusted_hops > 0``（＝XFF を信頼する設定）の場合のみ**に
    限定する（``trusted_hops<=0`` や XFF ヘッダ自体が無い場合は、最終的な
    IP 検証に失敗しても常に ``"no_xff"`` として扱い、フェイルクローズしない。
    以前の ``xff_present = trusted_proxy_hops > 0 and get_xff_raw(request)
    is not None`` という判定条件と等価になるよう設計している）。

    プライベート / ループバック / 特殊用途アドレス（未指定・マルチキャスト・
    予約済み）か否かの判定・対処はここでは行わずそのまま返す（呼び出し側が
    ``is_private_or_loopback()`` / ``is_special_use_address()`` で判断し、
    IP軸をスキップするかどうかを決める。診断エンドポイントはこの値をそのまま
    実測結果として表示する必要があるため、本関数はポリシー判断を持たない）。
    """
    xff_trusted_present = False
    if trusted_hops <= 0:
        # "XFF を信頼しない" の明示的な意味。request.client.host のみを使う。
        candidate_raw = request.client.host if request.client else None
    else:
        xff_raw = get_xff_raw(request)
        if xff_raw is None:
            candidate_raw = request.client.host if request.client else None
        else:
            xff_trusted_present = True
            parts = _parse_and_cap_xff(xff_raw)
            if not parts:
                # ヘッダは存在するが空/カンマのみ等でパース結果が空。
                # "XFF 自体が無い" 場合（request.client.host へフォールバック）
                # とは意図的に区別し、不正な入力として扱う。
                return ClientIpResolution(None, "empty_xff")
            if len(parts) >= trusted_hops:
                candidate_raw = parts[-trusted_hops]
            else:
                # 以前は左端 parts[0]（攻撃者が完全に制御できる値）に
                # フォールバックしていたが廃止した（security review High-1）。
                _warn_short_xff(len(parts), trusted_hops)
                return ClientIpResolution(None, "invalid")

    if candidate_raw is None:
        return ClientIpResolution(None, "no_xff")

    resolved = _parse_single_ip(candidate_raw)
    if resolved is None:
        return ClientIpResolution(None, "invalid" if xff_trusted_present else "no_xff")

    return ClientIpResolution(resolved, "ok")


def resolve_client_ip(request: Request, trusted_hops: int) -> str | None:
    """``resolve_client_ip_with_reason`` の ``ip`` のみを返す薄いラッパー。

    既存の呼び出し元（診断エンドポイントの ``resolved_ip`` 表示等）との
    後方互換のため ``str | None`` のシグネチャを維持する。**理由
    （``reason``）付きの解決結果が必要な呼び出し側（``RateLimitGuard`` 等）
    は必ず ``resolve_client_ip_with_reason`` を直接使うこと。** ``ip is None``
    だけでは「フェイルクローズすべきか」「スキップすべきか」を判断できない
    （``ClientIpResolution`` の docstring 参照）。
    """
    return resolve_client_ip_with_reason(request, trusted_hops).ip


def scan_client_ip_for_diagnostics_with_reason(request: Request) -> ClientIpResolution:
    """``scan_client_ip_for_diagnostics`` の ``ip`` に加えて理由（``reason``）
    も返す版。診断エンドポイントの ``scan_reason`` 表示に使う。

    **[診断・ドリフト検知専用。レート制限・認可・その他あらゆるセキュリティ
    判断に使ってはならない]** 詳細は ``scan_client_ip_for_diagnostics`` の
    docstring を参照。
    """
    xff_raw = get_xff_raw(request)
    if xff_raw is None:
        candidate_raw = request.client.host if request.client else None
        if candidate_raw is None:
            return ClientIpResolution(None, "no_xff")
        resolved = _parse_single_ip(candidate_raw)
        if resolved is None:
            return ClientIpResolution(None, "no_xff")
        return ClientIpResolution(resolved, "ok")

    parts = _parse_and_cap_xff(xff_raw)
    if not parts:
        return ClientIpResolution(None, "empty_xff")

    for raw_candidate in reversed(parts):
        resolved = _parse_single_ip(raw_candidate)
        if resolved is None:
            # フェイルクローズ的な意味は持たない（診断専用のため呼び出し側の
            # 判定には使われない）が、hops 経路と同じ「不正値に到達したら
            # そこで停止する」振る舞いは踏襲する。
            return ClientIpResolution(None, "invalid")
        if is_trusted_proxy_ip(resolved):
            continue
        return ClientIpResolution(resolved, "ok")

    # 全要素が信頼済みプロキシだった（＝実クライアントIPを特定できなかった）。
    return ClientIpResolution(None, "all_trusted")


def scan_client_ip_for_diagnostics(request: Request) -> str | None:
    """**[診断・CDN構成ドリフト検知専用。この関数の戻り値をレート制限・認可・
    その他あらゆるセキュリティ判断に使ってはならない]**

    ``TRUSTED_PROXY_HOPS`` の段数設定に依存せず、X-Forwarded-For を右端から
    左へ走査して「信頼済みプロキシ（内部プロキシ or Cloudflare 公開レンジ）
    ではない最初の要素」を返す。

    **なぜレート制限の判定に使えないか（security review Critical・撤回済み
    設計の教訓。詳細は本モジュール冒頭の「設計判断の履歴」を参照）**:
    Cloudflare Workers 等、CF 公開レンジ内から任意にアウトバウンド接続
    できるサービスを攻撃者が無料で利用できるため、「CFレンジ内＝信頼できる
    中間ホップ」という前提が成立しない。
      - padding あり: ``spoofA, <Worker のCF egress>, <本物のCFエッジ>,
        <10.x>`` を送ると、右端スキャンは信頼済みと誤認したホップを全て
        スキップして攻撃者制御の ``spoofA`` まで遡ってしまい、IP軸を完全に
        偽装できる。
      - padding なし: 全要素が「信頼済み」と誤認され、IP軸しか持たない
        signup / line_exchange 等のスコープをまるごと無防備にできる。
    また ``CF-Connecting-IP`` を代替として信頼する案も採用しない: 本番の
    CF ゾーンは Render 側が管理しており自ゾーンではないため、Transform Rule
    による秘密ヘッダ注入や Authenticated Origin Pulls が使えず、このヘッダ
    自体が CF の同一テナント内であれば誰でも細工可能である。

    **許容される用途は次の2つに限定する**:
      1. ``/api/v1/_diag/client-ip`` での表示（``TRUSTED_PROXY_HOPS`` の
         実測時に、hops 方式の結果と突き合わせるための参考値）。
      2. ``RateLimitGuard`` が hops 方式の解決結果と本関数の結果を比較し、
         不一致ならスロットリング付き WARNING を出す「CDN構成ドリフトの
         早期検知シグナル」（**判定結果には一切影響させない**）。

    手順（診断表示の再現性のため、hops 方式と対応する概念は極力揃える）:
      1. ``get_xff_raw()`` で取得する（重複ヘッダ結合は必ずこの関数経由）。
      2. XFF が無ければ ``request.client.host`` を採用する（hops 方式と
         同じフォールバック。``_parse_single_ip`` による検証も行う）。
      3. ``_parse_and_cap_xff`` で分割・正規化する。
      4. パース結果が空なら ``None`` を返す（理由: ``"empty_xff"``）。
      5. **右端から左へ**走査し、各要素を ``_parse_single_ip`` で検証する。
           - 検証成功かつ ``is_trusted_proxy_ip`` が True（内部プロキシ or
             Cloudflare レンジ）→ そのプロキシ自身が付与したホップとみなし
             スキップして次（左）へ進む。
           - 検証成功かつ非信頼 → その値を返す（走査を停止する）。
           - 検証失敗（不正値）→ ``None`` を返す（理由: ``"invalid"``）。
      6. 全要素が信頼済みプロキシだった場合 → ``None``（理由:
         ``"all_trusted"``）。

    理由（``reason``）付きの結果が必要な呼び出し側（診断エンドポイントの
    ``scan_reason`` 表示等）は ``scan_client_ip_for_diagnostics_with_reason``
    を使うこと。本関数は ``str | None`` の薄いラッパー。
    """
    return scan_client_ip_for_diagnostics_with_reason(request).ip


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
