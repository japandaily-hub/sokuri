"""レート制限のアダプタ層（FastAPI 依存として ``app.core.rate_limit`` を配線する）。

認証依存（``app.api.deps``）とは関心が異なる（SRP）ため、あえて別モジュールに
分離している。

ガードはミドルウェアではなく **依存関数（Depends）** として実装する。
``backend/tests/test_account_api.py`` 等の既存テストの多くは ``create_app()``
を通らず独自に ``FastAPI()`` を組み立てるため、ミドルウェアだと既存テストから
検証不能になる（設計書 冒頭の重要な構造的発見）。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
from dataclasses import dataclass
from functools import lru_cache
from types import TracebackType
from typing import NamedTuple, NoReturn

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings
from app.core.client_ip import (
    is_cloudflare_range,
    is_private_or_loopback,
    is_special_use_address,
    resolve_client_ip_with_reason,
    scan_client_ip_for_diagnostics,
    truncate_ip_for_log,
)
from app.core.client_ip_relay import (
    log_relay_outcome,
    parse_relay_secrets,
    verify_request_client_ip_relay,
)
from app.core.http_errors import http_exception_factory
from app.core.log_throttle import ThrottledLogger
from app.core.rate_limit import (
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
    RateLimitVerdict,
)

logger = logging.getLogger(__name__)

# 以下3種の WARNING は、いずれも「無言のバイパス/スキップ/全体障害の前兆」を
# 観測可能にするためのものだが、リクエスト毎に出すとログを埋め尽くす。
# 「プロセス内1回きり」の抑制は攻撃者が起動直後に1回不正値を送るだけで
# 永久に消費でき、以後本物の異常が起きても二度と出せなくなるため、
# 60秒スロットリングに統一する（security review Medium-2）。
# 警告の種類ごとに独立したインスタンスを持つ（同一インスタンスを使い回すと
# 互いのスロットリングに干渉するため）。
_unresolvable_xff_throttle = ThrottledLogger()
_ip_axis_skipped_throttle = ThrottledLogger()
_private_ip_skip_throttle = ThrottledLogger()
_special_address_skip_throttle = ThrottledLogger()
_cf_range_at_trust_position_throttle = ThrottledLogger()
_scan_drift_throttle = ThrottledLogger()
_unparseable_ip_throttle = ThrottledLogger()

_INVALID_REQUEST_HEADERS = http_exception_factory(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="リクエストの形式が正しくありません。時間をおいて再度お試しください。",
)


def _warn_unresolvable_xff(scope: str) -> None:
    _unresolvable_xff_throttle.emit(
        lambda: logger.warning(
            "rate_limit: X-Forwarded-For ヘッダが存在するのに IP を解決できませんでした"
            "（scope=%s）。フェイルクローズとして 400 で拒否します"
            "（IP軸まるごとスキップによるレート制限バイパスを防ぐため。生のヘッダ値は"
            "ログしない）。",
            scope,
        )
    )


def _warn_ip_axis_skipped(scope: str) -> None:
    _ip_axis_skipped_throttle.emit(
        lambda: logger.warning(
            "rate_limit: IP軸の判定をスキップしました（X-Forwarded-Forヘッダなし、"
            "または request.client 不在。scope=%s）。アカウント軸は通常どおり適用されます。",
            scope,
        )
    )


def _warn_private_ip_skip(scope: str, ip: str) -> None:
    """信頼位置の IP がプライベート/ループバックのため IP軸をスキップした際の警告。

    security review 指摘C: TRUSTED_PROXY_HOPS 誤設定（想定より1段多い
    プロキシがある等）でこれが起きると、内部固定 IP を全ユーザーが共有する
    ことになり、対処しなければ「全ユーザーが同一バケットを共有→数分で
    全世界のログインが429になる」最悪の全体障害に直結する。ここで IP軸を
    スキップすることで、誤構成時でも「レート制限が緩む」だけで済み、
    認証全断は構造的に起こりえなくなる（詳細は RateLimitGuard 参照）。
    生 IP はログに残さず ``_ip_net_for_log()`` で丸めた値（ゾーン ID を含まない）のみ出す。
    """
    _private_ip_skip_throttle.emit(
        lambda: logger.warning(
            "rate_limit: 信頼位置のIPがプライベート/ループバックのため IP軸をスキップ"
            "しました（scope=%s ip_net=%s）。TRUSTED_PROXY_HOPS の誤設定で内部プロキシIPを"
            "掴んでいる疑いがあります。/api/v1/_diag/client-ip で実測して確認してください。",
            scope,
            _ip_net_for_log(ip),
        )
    )


def _warn_special_address_skip(scope: str, ip: str) -> None:
    """信頼位置の IP が未指定/マルチキャスト/予約済みアドレスのため IP軸を
    スキップした際の警告（security review 新設。``is_special_use_address``
    参照）。

    信頼位置は攻撃者が値を選べない位置（CF/プロキシが追記する）ため、
    ここに現れる異常値は攻撃ではなくプロキシ実装・LB構成の変更を意味する。
    ``_warn_private_ip_skip`` と同じ理由でフェイルクローズではなくスキップに
    倒す（誤構成時でも「レート制限が緩む」だけで済み、認証全断は構造的に
    起こりえなくなる）。生 IP はログに残さず ``_ip_net_for_log()`` で
    丸めた値（ゾーン ID を含まない）のみ出す。
    """
    _special_address_skip_throttle.emit(
        lambda: logger.warning(
            "rate_limit: 信頼位置のIPが未指定/マルチキャスト/予約済みアドレスのため"
            "IP軸をスキップしました（scope=%s ip_net=%s）。プロキシ/LB構成が変更された"
            "可能性があります。/api/v1/_diag/client-ip で実測して確認してください。",
            scope,
            _ip_net_for_log(ip),
        )
    )


def _warn_cf_range_at_trust_position(scope: str, ip: str) -> None:
    """信頼位置の IP が Cloudflare 公開レンジ内だった際の警告
    （**スキップしない。カウントは継続する**）。

    信頼位置が CF レンジ内＝``TRUSTED_PROXY_HOPS`` が実際の構成より小さい
    （＝もう1段 CF ホップが挟まっている）疑いを意味する、全断の前兆となり
    うる異常である。しかし ``is_private_or_loopback`` / ``is_special_use_address``
    とは異なり、**この状態は攻撃者が能動的に誘発できる**（Cloudflare
    Workers 等、CF公開レンジ内から任意にアウトバウンド接続できるサービスを
    無料で悪用できるため）。したがってここでスキップすると、攻撃者が
    「信頼位置に自分の CF egress IP を送り込む」だけで恒常的に IP軸を
    無効化できてしまう（signup 等 IP軸しか持たないスコープが常時無防備に
    なる）。

    トレードオフ（**必ず両方を理解した上で判断すること**）:
      - スキップに倒す案: 常時利用可能なバイパスを作ってしまう。不採用。
      - **カウント継続（採用）**: 設定ドリフト時（hops が実際より小さい）は
        信頼位置に本来のクライアントIPではなく CF ホップの IP が来るため、
        複数の異なるクライアントが同一の CF ホップIPを共有し、IP軸が
        誤って過剰にカウントされる（＝レート制限が厳しくなりすぎるリスク）。
        最悪の場合、多数の正規ユーザーが同一バケットを共有し 429 が頻発する
        全断リスクがある。ただしこれは既存の緊急停止スイッチ
        （``RATE_LIMIT_ENABLED=false``）で 1 操作・再起動のみで即座に復旧
        できる（設計書の想定復旧手順そのもの）。攻撃者に常時利用可能な
        バイパスを与えるより、運用者が能動的に対処可能なリスクを選ぶ方が
        安全側であると判断した。
    """
    _cf_range_at_trust_position_throttle.emit(
        lambda: logger.warning(
            "rate_limit: 信頼位置のIPがCloudflare公開レンジ内です（scope=%s ip_net=%s）。"
            "TRUSTED_PROXY_HOPS が実際の構成より小さい疑いがあります（全断の前兆になり"
            "えるため要確認）。カウントは継続します（スキップすると攻撃者がCF egress"
            "から誘発可能なバイパスになるため）。/api/v1/_diag/client-ip で実測して"
            "確認してください。",
            scope,
            _ip_net_for_log(ip),
        )
    )


def _warn_unparseable_ip(scope: str) -> None:
    """IP軸のバケット計算（``_ip_axis_buckets``）で、resolve 済みのはずの値が
    ``ipaddress.ip_address()`` で読めなかった際の警告。

    ``resolve_client_ip_with_reason`` は返す前に必ず ``ipaddress.ip_address()``
    で検証済みのため、ここに到達するのは実装の不具合（正規化ロジックの
    変更漏れや、検証前の値を渡す新しい経路）のみを意味する。それでも例外には
    せず、scope ごとに1つだけの固定のバケットで数え続ける（値ごとに別のキーに
    すると、値を替えるだけで回避でき、キーも増え続けるため）。ログには scope
    のみを出し、値そのものは出さない。
    """
    _unparseable_ip_throttle.emit(
        lambda: logger.warning(
            "rate_limit: IP軸のバケット計算で解決済みの値をパースできませんでした"
            "（scope=%s）。実装の不具合の可能性があります。scope ごとに1つの"
            "固定のバケット（axis=ip_unparseable）で数えます（値そのものはログしません）。",
            scope,
        )
    )


def _check_scan_drift(scope: str, request: Request, hops_ip: str) -> None:
    """診断専用の右端スキャン（``scan_client_ip_for_diagnostics``）の結果と、
    実際に使用している hops 方式の解決結果を比較し、不一致ならスロットリング
    付き WARNING を出す（CDN構成変更・``TRUSTED_PROXY_HOPS`` ドリフトの
    唯一の早期自動検知シグナル）。

    **この比較結果はレート制限の判定に一切影響させない。** scan は
    security review Critical 指摘により判定経路から完全に排除されている
    （``app.core.client_ip`` モジュール冒頭の「設計判断の履歴」参照）。ここで
    行うのは「見るだけ」の観測であり、分岐や早期リターンを一切持たない。
    """
    scan_ip = scan_client_ip_for_diagnostics(request)
    if scan_ip == hops_ip:
        return
    _scan_drift_throttle.emit(
        lambda: logger.warning(
            "rate_limit: hops方式と診断用scanの解決結果が不一致です（scope=%s）。"
            "CDN構成変更や TRUSTED_PROXY_HOPS のドリフトの兆候である可能性があります。"
            "/api/v1/_diag/client-ip で実測して確認してください（この不一致自体は"
            "レート制限の判定には一切影響しません）。",
            scope,
        )
    )


# ──────────────────────────── スコープ別メッセージ・文言 ────────────────────────────
# login の2軸（アカウント/IP）はあえて同一文言にする（設計書 §5）。文言を分けると
# 攻撃者が「アカウント軸で止まった＝そのメールアドレスは実在する」と判別でき、
# レート制限自体が新たなアカウント列挙オラクルになるため。
_SCOPE_MESSAGES: dict[str, str] = {
    "login": "ログインの試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "password_change": "パスワード変更の試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "account_delete": "試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "line_link_reauth": "試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "bank_account_update": "振込先口座の変更試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "notification_settings": "設定変更の試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "identity_submit": "本人確認書類の提出試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "signup": "登録試行が集中しています。しばらく時間をおいて再度お試しください。",
    "line_exchange": "リクエストが集中しています。しばらく時間をおいて再度お試しください。",
    "case_create": "案件の作成が集中しています。しばらく時間をおいて再度お試しください。",
    "case_cancel": "出品の取り下げの試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "public_read": "リクエストが集中しています。しばらく時間をおいて再度お試しください。",
    "analyze": "画像解析のリクエストが集中しています。しばらく時間をおいて再度お試しください。",
    "contact": "お問い合わせが集中しています。時間をおいて再度お送りください。",
    "operator_application": "送信回数の上限に達しました。しばらく時間をおいて再度お試しください。",
}


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """本番用のプロセス内シングルトン ``RateLimiter`` を返す。

    ``get_settings()`` から ``RateLimitConfig`` を構築する。``lru_cache``
    されるため、プロセス内で1度だけ構築される（``InMemoryRateLimitStore``
    もこの中で一度だけ生成されプロセス内シングルトンとなる）。

    **テストではこの関数自体を ``app.dependency_overrides`` で差し替え、
    シングルトンには一切触れないこと**（設計書 §6-(b)）。``get_settings()``
    を差し替える方式は採らない（``lru_cache`` の ``cache_clear()`` を跨ぐ
    テストは順序依存になるため）。
    """
    settings = get_settings()
    config = RateLimitConfig(
        enabled=settings.rate_limit_enabled,
        login_account=RateLimitRule(settings.rl_login_account_max, settings.rl_login_window_sec),
        login_ip=RateLimitRule(settings.rl_login_ip_max, settings.rl_login_window_sec),
        sensitive_account=RateLimitRule(
            settings.rl_sensitive_account_max, settings.rl_sensitive_window_sec
        ),
        signup_ip=RateLimitRule(settings.rl_signup_ip_max, settings.rl_signup_window_sec),
        line_ip=RateLimitRule(settings.rl_line_ip_max, settings.rl_line_window_sec),
        max_keys=settings.rl_max_keys,
        case_create_ip=RateLimitRule(
            settings.rl_case_create_ip_max, settings.rl_case_create_window_sec
        ),
        case_create_account=RateLimitRule(
            settings.rl_case_create_account_max, settings.rl_case_create_window_sec
        ),
        public_read_ip=RateLimitRule(
            settings.rl_public_read_ip_max, settings.rl_public_read_window_sec
        ),
    )
    return RateLimiter(config=config)


@lru_cache
def _rate_limit_hmac_key() -> bytes:
    """レート制限専用の派生鍵（security review M-3 対応）。

    ``jwt_secret`` をレート制限のキー化にそのまま HMAC 鍵として使うと、
    攻撃者が任意の email で意図的に上限超過させられる（＝平文既知）ため、
    超過時 WARNING ログに出す HMAC ダイジェスト先頭12桁が「既知平文に対する
    HMAC 出力」の実例になってしまう。ログが漏洩した場合、これを手がかりに
    ``jwt_secret`` 自体へのオフライン総当たりの足がかりを与えかねず、成功
    すれば任意ユーザー・admin の JWT 偽造に直結する（既定値
    ``dev-secret-change-me`` を運用のまま使ってしまうケースも含め、鍵の
    エントロピーを過信しない設計とする）。

    用途ラベル付きの派生鍵（``HMAC(jwt_secret, "katazuke/rate-limit/v1")``）を
    経由することで、この派生鍵単体が漏洩しても ``jwt_secret`` 自体の推定には
    使えないようにする（鍵分離）。``lru_cache`` で1度だけ計算し、毎リクエスト
    ``get_settings()``+HMAC の計算コストを避ける。
    """
    settings = get_settings()
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), b"katazuke/rate-limit/v1", hashlib.sha256
    ).digest()


def _hash_identity(raw: str) -> str:
    """email / user_id / IP をキー化する（用途分離した派生鍵での HMAC-SHA256 の先頭32桁）。

    - 生の email 等をプロセスメモリの dict キーに長期保持しない
      （メモリダンプ・例外トレース経由の PII 漏洩面を減らす）。
    - 鍵に ``jwt_secret`` を直接使わない（``_rate_limit_hmac_key()`` 参照）。
    - ``.strip().lower()`` 正規化してからハッシュ化する。大文字小文字の
      揺れだけで制限を回避されるのを防ぐ必須要件（email が主対象だが、
      IP/UUID を渡しても副作用はない）。
    """
    normalized = raw.strip().lower()
    digest = hmac.new(_rate_limit_hmac_key(), normalized.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:32]


def _build_key(scope: str, axis: str, digest: str) -> str:
    """``"{scope}:{axis}:{digest}"`` 形式のストアキーを組み立てる。

    scope を含めることでエンドポイント間でバケットが混ざらない。
    """
    return f"{scope}:{axis}:{digest}"


# ──────────────── IPv6 の IP軸: /64・/56・/48 の3段で数える（重要な設計判断） ────────────────
#
# 従来は解決済みの IP の文字列全体をキーにしていた。IPv6 の利用者は /64（日本の IPoE で
# ひかり電話ありの HGW なら /56）を払い出されているため、要求ごとに送信元アドレスを
# 替えるだけで毎回新しいバケットになり、IP軸しか持たないスコープ（signup・
# operator_application・contact・public_read 等）を含む全スコープの IP軸を回避できた。
#
# 採否の理由:
#   - /64 で数える: SLAAC の最小の割当単位で、通常は 1 回線・1 端末に割り当てられる。
#     これより細かい単位（アドレス全体）で数えると、アドレスを替えるだけで回避される。
#   - 広い段（/56・/48）を併用する（採用）: /64 だけだと、/56 の保有者は 256 個、/48 の
#     保有者は 65,536 個の /64 を使い分けられ、上限の最大 256 倍・65,536 倍まで数えられずに
#     済む。Hurricane Electric の tunnelbroker は /48 を無料で配っており（1 アカウント
#     5 本まで）、放置するといつでも使える抜け道が残る。
#   - 段と倍率（/64 は 1 倍・/56 は 2 倍・/48 は 8 倍）の根拠:
#       * /56 は住宅向けによく使われる割当単位（日本の IPoE の HGW も /56）。/56 の保有者は
#         上限の 2 倍までに抑えられる。家庭が同時に使う /64 は 1〜2 個なので、その分は通す。
#         倍率を 2 以上にするのは、HGW なしのフレッツのように /64 ごとに別の契約者が入る
#         割当で、/64 を 1 つしか持たない回線だけでは同じ /56 の他人を塞げないようにする
#         ため。携帯は再接続で別の /64 を得られるので、同じ /56 に /64 が 2 つ以上当たれば
#         1 人でも塞げる（キャリアの割当の方式による。要確認）。
#       * /48 は事業所向けや tunnelbroker の割当単位。/48 の保有者は上限の 8 倍までに
#         抑えられる。倍率を /56 の 4 倍にするのは、/56 を 1 つ持つ世帯だけでは同じ /48 の
#         他の世帯（最大 255）を塞げないようにするため（塞ぐには /56 が 4 つ要る）。
#       * 最も重い業者申込（1 時間 5 件・1 件ごとに運営へメール）でも、/56 あたり 10 件・
#         /48 あたり 40 件に収まる。
#   - 巻き添えと対処: 同じ /56 に /64 を 2 つ以上持つ利用者は同じ /56 の他人を、同じ /48 の
#     4 つ以上の /56 に /64 を持つ利用者は同じ /48 の他人を、上限まで使い切れば窓の残り
#     時間だけ 429 にできる（login はパスワード照合の前に判定するので、正しいパスワード
#     でも 429）。/56 を 1 つ持つ普通の世帯が塞げるのは自分の /56 だけ。IPv4 でも MAP-E・
#     DS-Lite・携帯の CGNAT では 1 台で同じ巻き添えが起きる。本番の backend のホスト名には
#     2026-09-27 時点で AAAA が無く、正規の利用者の IPv6 通信が無いので、今は被害者がいない。
#     本コードベースの前例（``_warn_cf_range_at_trust_position``）と同じく、いつでも使える
#     抜け道より、運用で対処できる数えすぎを選ぶ。429 のログは axis（ip6_64・ip6_56・
#     ip6_48）で区別でき、緊急停止スイッチ（RATE_LIMIT_ENABLED=false）ですぐ止められる。
#   - 見直しの条件: 正規の IPv6 利用者が来たら見直す（Render が AAAA を有効にした時・
#     I8 で login の IP を中継する時）。倍率と、段ごとの停止スイッチの要否を検討する。
#   - IPv4 はアドレス単位のまま変えない。IPv4 を埋め込んだ IPv6（IPv4 射影・6to4・Teredo）
#     は、埋め込まれた IPv4 の 1 段で数える（``_canonical_address``）。
_IPV6_56_LIMIT_MULTIPLIER = 2
_IPV6_48_LIMIT_MULTIPLIER = 8


class _Ipv6Tier(NamedTuple):
    """IPv6 の IP軸の1段（axis 名・プレフィックス長・IP軸の上限に掛ける倍率）。"""

    axis: str
    prefix_len: int
    limit_multiplier: int


# 狭い段 → 広い段の順に並べる（``_apply_ip_axis`` はこの順を前提に、広い段から peek する）。
_IPV6_TIERS: tuple[_Ipv6Tier, ...] = (
    _Ipv6Tier("ip6_64", 64, 1),
    _Ipv6Tier("ip6_56", 56, _IPV6_56_LIMIT_MULTIPLIER),
    _Ipv6Tier("ip6_48", 48, _IPV6_48_LIMIT_MULTIPLIER),
)

# 読めない値を数えるバケット（scope ごとに1つ）の axis 名と、ハッシュの材料。
_UNPARSEABLE_IP_AXIS = "ip_unparseable"
_UNPARSEABLE_IP_MATERIAL = "unparseable"


@dataclass(frozen=True)
class _IpBucket:
    """IP軸の「数える単位」1個分（IPv4 は1個、IPv6 は /64・/56・/48 の3個）。

    ``axis``: ログ・ストアキーに使う軸名（"ip"・"ip6_64"・"ip6_56"・"ip6_48"・
    読めない値の "ip_unparseable"）。
    ``store_key``: ``_build_key(scope, axis, digest)`` の結果。
    ``rule``: この段に適用する上限（広い段は倍率を掛けた値）。
    ``key_prefix``: digest の先頭12桁（超過時ログ用）。
    ``ip_net``: 超過時ログに出す IP の範囲（``_ip_net_for_log``。照合の枠
    ``PasswordAttempt`` が IP軸で弾いたときも、ガードと同じ値をログに出すため）。
    """

    axis: str
    store_key: str
    rule: RateLimitRule
    key_prefix: str
    ip_net: str


def _make_ip_bucket(
    scope: str, axis: str, material: str, rule: RateLimitRule, ip_net: str
) -> _IpBucket:
    """材料（IPv4 アドレス・IPv6 の CIDR 等）をハッシュして ``_IpBucket`` を1つ作る。"""
    digest = _hash_identity(material)
    return _IpBucket(
        axis=axis,
        store_key=_build_key(scope, axis, digest),
        rule=rule,
        key_prefix=digest[:12],
        ip_net=ip_net,
    )


def _canonical_address(ip: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """IP軸で数えるときの正規の形のアドレスを返す（読めない値は ``None``）。

    - IPv4 を埋め込んだ IPv6 は、埋め込まれた IPv4 にする。
        - IPv4 射影（``::ffff:a.b.c.d``）: ``app.core.client_ip`` が展開済みなので本来は
          届かないが、IPv6 のまま /64 に丸めると射影アドレスの全員が1つのバケットに潰れる。
        - 6to4（2002::/16）: /48 が IPv4 1 個に当たるので、IPv6 の段で数えると IPv4 1 個の
          持ち主が IPv4 の枠とは別に上限の 8 倍まで使える。
        - Teredo（2001::/32）: /64 が中継サーバー 1 台に当たり、その利用者全員が1つの枠を
          共有してしまう。クライアントの IPv4 は ``teredo[1]``。
    - IPv6 のゾーン ID（"%eth0" 等）は落とす（int から作り直す）。ゾーン ID は受信側の
      インターフェース名で送信元を区別しないうえ、任意の文字列を書ける。残すとゾーン ID
      ごとに別バケットになり、ログにも任意の文字列が入る。
    - 文字列以外は読めない値として扱う。``ipaddress.ip_address()`` は int や 4・16 バイトの
      bytes もアドレスとして受け付けるため、そのまま通すと、値ごとに別のキーになる入口が
      残る。
    """
    if not isinstance(ip, str):
        return None
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv4Address):
        return parsed
    embedded_ipv4 = parsed.ipv4_mapped or parsed.sixtofour
    if embedded_ipv4 is None and parsed.teredo is not None:
        embedded_ipv4 = parsed.teredo[1]
    if embedded_ipv4 is not None:
        return embedded_ipv4
    return ipaddress.IPv6Address(int(parsed))


def _ip_axis_buckets(scope: str, ip: str, rule: RateLimitRule) -> tuple[_IpBucket, ...]:
    """IP から「数える単位」の並び（狭い段→広い段）を組み立てる（純関数・O(1)）。

    - IPv4（IPv4 を埋め込んだ IPv6 を含む。``_canonical_address``）: 従来どおりアドレス
      単位の1段（axis="ip"）。hops 方式で解決した値はもともと正規の表記なので、キーは
      従来の ``_build_key(scope, "ip", _hash_identity(ip))`` と1ビットも変わらない。
    - IPv6: ``_IPV6_TIERS`` の各段（/64・/56・/48）。材料は int から作る CIDR の文字列
      （例 "2001:db8:1:2::/64"）で、ゾーン ID を含まない（``ip_network(f"{ip}/64",
      strict=False)`` はホスト部が 0 のアドレスでゾーン ID を残す。Python 3.11.9 で確認）。
      段ごとに axis 名を分け、材料にもプレフィックス長を含めるので、ネットワーク
      アドレスが一致する段どうしでもキーは混ざらない。上限は ``rule`` の
      ``limit_multiplier`` 倍（窓の長さは同じ）。
    - 読めない値（resolve 済みの値なので本来は届かない）: 値ごとに別のキーにすると、
      将来ほかの経路から検証前の値が届いたとき、値を替えるだけで回避でき、キーも増え
      続ける。そこで scope ごとに1つだけの固定のバケット（axis="ip_unparseable"）で数え、
      スロットリング付きの WARNING を出す。例外（500）にもスキップ（抜け道）にもしない。
    """
    address = _canonical_address(ip)
    ip_net = _ip_net_for_log(ip)
    if address is None:
        _warn_unparseable_ip(scope)
        return (
            _make_ip_bucket(
                scope, _UNPARSEABLE_IP_AXIS, _UNPARSEABLE_IP_MATERIAL, rule, ip_net
            ),
        )
    if isinstance(address, ipaddress.IPv4Address):
        return (_make_ip_bucket(scope, "ip", str(address), rule, ip_net),)

    address_int = int(address)
    return tuple(
        _make_ip_bucket(
            scope,
            tier.axis,
            str(ipaddress.IPv6Network((address_int, tier.prefix_len), strict=False)),
            rule
            if tier.limit_multiplier == 1
            else RateLimitRule(rule.max_requests * tier.limit_multiplier, rule.window_seconds),
            ip_net,
        )
        for tier in _IPV6_TIERS
    )


def _ip_net_for_log(ip: str) -> str:
    """超過ログに出す IP の範囲（IPv4 は /24・IPv6 は /48）を返す。

    ``_canonical_address`` を通すので、ゾーン ID は出さず、IPv4 を埋め込んだ IPv6 は
    埋め込まれた IPv4 の /24 になる。読めない値は "invalid"。
    """
    address = _canonical_address(ip)
    return "invalid" if address is None else truncate_ip_for_log(str(address))


def _raise_429(
    *,
    scope: str,
    axis: str,
    rule: RateLimitRule,
    verdict: RateLimitVerdict,
    key_prefix: str,
    ip_net: str | None,
) -> NoReturn:
    """429 応答を送出する（既存の ``HTTPException(detail=...)`` スタイルを踏襲）。

    - ``Retry-After`` ヘッダを付与する（残り秒数の切り上げ・整数秒）。
    - 攻撃者への情報漏洩は「窓が残り何秒か」だけに限定し、上限値そのもの
      （``X-RateLimit-*`` 系ヘッダ）は付けない。
    - ログには生の email・生の IP を書かない（HMAC ダイジェストの先頭12桁と
      IP の /24・/48 丸めのみ）。超過時のみ WARNING（通常の失敗カウントは
      ログしない＝ログ量爆発の防止）。
    """
    retry_after = max(verdict.retry_after_seconds, 1)
    logger.warning(
        "rate_limit: 上限超過 - scope=%s axis=%s key_prefix=%s ip_net=%s "
        "limit=%d window_sec=%d retry_after=%d",
        scope,
        axis,
        key_prefix,
        ip_net or "-",
        rule.max_requests,
        rule.window_seconds,
        retry_after,
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_SCOPE_MESSAGES[scope],
        headers={"Retry-After": str(retry_after)},
    )


@dataclass(frozen=True)
class _ScopeSpec:
    """スコープごとの軸構成（設計書 §3 の対象表を機械的に表現したもの）。"""

    ip_rule: RateLimitRule | None
    account_rule: RateLimitRule | None
    # True: 全リクエストを IP 軸で事前カウント（signup / line_exchange）。
    # False: IP 軸は事前は peek のみ、実カウントは照合の枠の失敗時
    # （PasswordAttempt.record_failure）で行う（login）。
    count_all: bool


def _scope_spec(scope: str, config: RateLimitConfig) -> _ScopeSpec:
    """スコープ名から軸構成を解決する。

    login / operator_login はアカウント軸・IP 軸とも同一設定（上限値・窓・
    応答文言・ログ scope 分類）を共有するため scope="login" に統一する
    （signup / operator_signup も scope="signup" に統一）。運用ログの scope
    分類（設計書 §9: login/signup/password_change/account_delete/
    line_exchange の5種）とも一致させている。

    **重要（security review 指摘・再発防止）: 「設定値の共有」と
    「カウンタ実体（ストアキー）の共有」は別物である。** 同一 scope 文字列を
    使っても、``check_account``/``password_attempt`` に渡す
    識別子（account_raw）が同じであれば同一バケットを共有してしまう。
    user 用と operator 用で同一メールアドレスが使われた場合、両者のアカウント軸
    バケットが意図せず共有され、無認証の第三者が相手のメールアドレスを知る
    だけで低コストのログイン妨害（DoS）を成立させられる。**呼び出し側
    （auth.py）で ``f"user:{email}"`` / ``f"operator:{email}"`` のように
    識別子自体を名前空間分離すること。** 上限値・窓・文言は列挙防止のため
    必ず同一のままにする（分離するのはキーの実体のみ）。
    """
    if scope == "login":
        return _ScopeSpec(
            ip_rule=config.login_ip, account_rule=config.login_account, count_all=False
        )
    if scope == "password_change":
        return _ScopeSpec(
            ip_rule=None, account_rule=config.sensitive_account, count_all=False
        )
    if scope == "account_delete":
        return _ScopeSpec(
            ip_rule=None, account_rule=config.sensitive_account, count_all=False
        )
    if scope == "line_link_reauth":
        # LINE連携用の再認証トークン発行。パスワード照合を伴う総当たり対象のため
        # password_change / account_delete と同一のアカウント軸ルールを共有する。
        return _ScopeSpec(
            ip_rule=None, account_rule=config.sensitive_account, count_all=False
        )
    if scope == "bank_account_update":
        # 振込先口座の変更（暗号化保存）。機微データ更新のため
        # password_change 等と同一のアカウント軸ルールを共有する。
        return _ScopeSpec(
            ip_rule=None, account_rule=config.sensitive_account, count_all=False
        )
    if scope == "identity_submit":
        # 本人確認書類の提出（画像保存を伴うコストDoS対策も兼ねる）。
        # 同じくアカウント軸のみで password_change 等と同一ルールを共有する。
        return _ScopeSpec(
            ip_rule=None, account_rule=config.sensitive_account, count_all=False
        )
    if scope == "notification_settings":
        # お知らせメール受け取り設定の変更（PATCH /users/me/notification-settings）。
        # security review M-1対応: 連打・自動化による無意味な書き換え連打を止める
        # のが目的で、パスワード等の総当たり対象ではないため専用の数値は持たず、
        # bank_account_update / identity_submit と同じ sensitive_account
        # （アカウント軸のみ・count_all 方式で毎リクエストをカウント）を流用する。
        return _ScopeSpec(
            ip_rule=None, account_rule=config.sensitive_account, count_all=False
        )
    if scope == "signup":
        return _ScopeSpec(ip_rule=config.signup_ip, account_rule=None, count_all=True)
    if scope == "line_exchange":
        return _ScopeSpec(ip_rule=config.line_ip, account_rule=None, count_all=True)
    if scope == "case_create":
        # 案件作成: AI解析(Gemini呼び出し)を伴うコストDoS対策のため、成功/失敗を
        # 問わず全リクエストをIP軸・アカウント軸の両方でカウントする（signupと
        # 同じ「全リクエストカウント」方式をアカウント軸にも拡張したもの）。
        # IP軸はこの関数の呼び出し元（RateLimitGuard.__call__）が count_all=True
        # により自動でカウント・判定する。アカウント軸はユーザーIDがBody解析後
        # にしか判明しないため、ハンドラ側が明示的に ``ctx.hit_account()`` を
        # 呼び出す（RateLimitContext 参照）。
        return _ScopeSpec(
            ip_rule=config.case_create_ip, account_rule=config.case_create_account,
            count_all=True,
        )
    if scope == "case_cancel":
        # 出品取り下げ: Case行の排他ロック取得・pending入札の一括却下・監査
        # レコード書き込みを伴うコストDoS対策（旧 bid_withdraw と同型。設計指示に
        # 基づく）。認証済みユーザーのみが呼べるエンドポイントのため IP 軸は
        # 持たず、user_id 軸のみで全リクエストをカウントする（新規の数値設定は
        # 追加せず、既存の sensitive_account ルール — password_change/
        # account_delete と同一 — を流用する）。
        return _ScopeSpec(ip_rule=None, account_rule=config.sensitive_account, count_all=False)
    if scope == "public_read":
        # 無認証の公開参照（業者一覧・公開プロフィール）。DB 走査を伴うため IP 軸で
        # 全リクエストをカウントする（security review M-2）。
        return _ScopeSpec(ip_rule=config.public_read_ip, account_rule=None, count_all=True)
    if scope == "analyze":
        # AI Vision（Gemini呼び出し）を伴うコストDoS対策（R3-operator ADD-1対応）。
        # config.py に新規キーは追加せず、既存の case_create 用ルール
        # （IP軸・アカウント軸とも全リクエストカウント）をそのまま流用する
        # （案件作成と同種のコストプロファイルのAI呼び出しのため）。
        return _ScopeSpec(
            ip_rule=config.case_create_ip, account_rule=config.case_create_account,
            count_all=True,
        )
    if scope == "contact":
        # 無認証の /contact（security review N-2対応）: 従来 scope="case_create" を
        # そのまま流用していたため、IP軸のバケット実体が POST /cases と共有され、
        # 同一IP（集合住宅・キャリアNAT等）から案件作成を繰り返したユーザーが
        # 問い合わせできなくなる／その逆の巻き添えが生じていた。analyze と同様
        # config.py に新規キーは追加せず数値ルールのみ case_create から流用しつつ、
        # scope名を "contact" に分離することで _build_key() のバケット実体
        # （"{scope}:{axis}:{digest}"）を独立させる。
        return _ScopeSpec(
            ip_rule=config.case_create_ip, account_rule=config.case_create_account,
            count_all=True,
        )
    if scope == "operator_application":
        # 無認証の業者事前申込（POST /operator-applications・/business の送信先）。
        # 口座情報の暗号化・DB 保存・運営宛メールを伴うため、成否を問わず全リクエストを
        # IP 軸でカウントする（signup と同じ方式。scope 名が別なのでバケットは共有しない）。
        # 以前はエンドポイント側が X-Forwarded-For の先頭（利用者が自由に書ける値）で
        # DB の件数を数えており、ヘッダを付け替えるだけで回避できた。
        return _ScopeSpec(
            ip_rule=config.operator_application_ip, account_rule=None, count_all=True
        )
    raise ValueError(f"未知の rate limit scope です: {scope!r}")


@dataclass
class RateLimitContext:
    """1リクエスト分のレート制限操作窓口。

    ``RateLimitGuard``（Depends）が IP 軸の事前判定を済ませた上で
    ``request.state.rate_limit`` に格納する。アカウント軸の判定は body の
    email 等が判明した直後にハンドラ側が明示的に呼び出す
    （Depends の実行時点ではリクエストボディが未解析のため）。

    ``ip_buckets`` は IP軸の「数える単位」の並び（``_apply_ip_axis`` が
    ``_ip_axis_buckets`` で作る。IPv4 は1個、IPv6 は /64・/56・/48 の3個）。
    空タプルは IP軸スキップ、またはそもそも IP軸を持たないスコープを
    意味する。照合の失敗（``PasswordAttempt.record_failure``）はこの全段を記録する。

    呼び出し規約（失敗のみカウント方式。設計書 §6 を M-3 で改めた）:
        ctx = request.state.rate_limit
        ctx.check_account(account_key)      # 任意: DB を引く前の早期の 429（peek）
        user = await ...                    # 照合の材料をそろえる（await はここまで）
        with ctx.password_attempt(account_key) as attempt:   # 上限なら 429 を raise
            if not verify_password(...):
                attempt.record_failure()    # IP軸の全段・アカウント軸をカウント
                raise _LOGIN_FAILED()       # 失敗パス
            attempt.record_success()        # 成功パス（アカウント軸のみリセット）

    上限の判定の本体は ``password_attempt`` で、``check_account`` は DB を引く前に
    弾くための近道にすぎない。``check_account`` だけで判定して照合すると、その後の
    ``await`` の間に同時に届いた要求がどれも peek を通り、上限を超えて照合できる
    （2026-09-27 セキュリティレビュー M-3。``PasswordAttempt`` 参照）。
    """

    limiter: RateLimiter
    scope: str
    account_rule: RateLimitRule | None
    ip_buckets: tuple[_IpBucket, ...] = ()

    def check_account(self, account_raw: str) -> None:
        """アカウント軸の事前チェック（peek）。超過なら 429 を raise する。

        照合の可否の判定には使わない（``password_attempt`` が行う）。上限に達している
        アカウントについて、DB の照会などの重い処理より前に 429 を返すための近道。
        """
        if self.account_rule is None:
            return
        digest = _hash_identity(account_raw)
        key = _build_key(self.scope, "acct", digest)
        verdict = self.limiter.check(key, self.account_rule)
        if not verdict.allowed:
            _raise_429(
                scope=self.scope,
                axis="account",
                rule=self.account_rule,
                verdict=verdict,
                key_prefix=digest[:12],
                ip_net=None,
            )

    def password_attempt(self, account_raw: str) -> PasswordAttempt:
        """パスワード照合1回分の枠を返す（``with`` 文で使う。``PasswordAttempt`` 参照）。"""
        return PasswordAttempt(self, account_raw)

    def _account_key(self, account_raw: str) -> tuple[str, str]:
        """アカウント軸のストアキーと、ログ用の digest 先頭12桁。"""
        digest = _hash_identity(account_raw)
        return _build_key(self.scope, "acct", digest), digest[:12]

    def hit_account(self, account_raw: str) -> None:
        """アカウント軸を無条件でカウントし、超過なら 429 を raise する。

        ``PasswordAttempt``（失敗時のみカウントする login 等の方式）とは異なり、
        成功/失敗を問わず毎リクエストをコストとして数える方式のスコープ
        （例: case_create のコストDoS対策）向け。**IP軸には一切触れない**
        （count_all 方式のスコープでは IP軸は ``RateLimitGuard.__call__`` が
        既に ``limiter.record()`` でカウント・判定済みのため、ここでも触ると
        二重カウントになってしまう）。
        """
        if self.account_rule is None:
            return
        digest = _hash_identity(account_raw)
        key = _build_key(self.scope, "acct", digest)
        verdict = self.limiter.record(key, self.account_rule)
        if not verdict.allowed:
            _raise_429(
                scope=self.scope,
                axis="account",
                rule=self.account_rule,
                verdict=verdict,
                key_prefix=digest[:12],
                ip_net=None,
            )


# PasswordAttempt の状態（__enter__ 前 → 枠の中 → 成否の確定後 → with を抜けた後）。
_ATTEMPT_NEW = "new"
_ATTEMPT_OPEN = "open"
_ATTEMPT_SETTLED = "settled"
_ATTEMPT_CLOSED = "closed"


class PasswordAttempt:
    """失敗のみカウント方式（login・password_change・account_delete・line_link_reauth）で、
    パスワード照合1回分の上限の判定と記録をまとめる枠。

    ``RateLimitContext.password_attempt()`` が返し、``with`` 文でだけ使う（呼び出し規約は
    ``RateLimitContext`` の docstring）。

    **なぜ必要か（2026-09-27 セキュリティレビュー M-3）**: 以前は「peek で判定 → ``await``
    で DB を照会 → 照合 → 失敗なら記録」の順だった。peek と記録の間に ``await`` があると、
    同時に届いた要求（single-packet attack 等）はどれも、ほかの要求の失敗が記録される前に
    peek を通るため、1 つの窓でアカウント軸・IP軸（IPv6 は各段）の上限を超えて照合できた。

    **仕組み**: ``__enter__`` で IP軸の全段（``ctx.ip_buckets``）→ アカウント軸の順に
    ``RateLimiter.reserve`` で枠を予約する。判定は「窓内の失敗の記録 + 照合中の予約 +
    この1回」が上限以下か。どれかで超えたら、それまでに取った予約を外して、その段・軸の
    429（ガードと同じ ``_raise_429``。文言はスコープ共通なので、アカウント軸と IP軸で同一
    ＝列挙防止を保つ）。予約は ``record_failure``／``record_success`` か、``with`` を抜けた
    とき（例外を含む）に外す。失敗の記録は従来どおり ``hit``、成功はアカウント軸のリセット。
    成否のどちらも呼ばずに抜けた場合（照合前の 409・例外など）は何も数えない（従来と同じ）。

    **正しいパスワードの利用者を 429 にしないための置き場所（重要）**: 枠は照合の材料
    （利用者の行など）をそろえる ``await`` の後に開き、枠の中に ``await`` を置かない。
    そうすれば予約はほかの要求から一度も見えず、判定は「失敗の記録 + この1回」だけに
    なる（修正前の peek と同じ判定を、記録と同じ同期区間で行う）。照合の前の ``await`` から
    予約すると、照合中の要求まで上限に数えるため、同時に届いた正しいパスワードの要求が、
    ほかの要求の照合が終わるまでの一瞬に 429 になりうる。枠の中に ``await`` を置いても
    上限は守られる（予約が見えるようになり、照合中の分だけ早めに 429 になる）ので、
    照合を ``asyncio.to_thread`` 等へ移す場合も、この枠の中で行えば M-3 は再発しない。

    緊急停止スイッチ（RATE_LIMIT_ENABLED=false）のときは ``NoopRateLimitContext`` が
    ``_NoopPasswordAttempt`` を返し、ストアに一切触れない。
    """

    def __init__(self, ctx: RateLimitContext, account_raw: str) -> None:
        self._ctx = ctx
        self._account_raw = account_raw
        self._account_store_key: str | None = None
        # 取った予約（ストアキー, token）。緊急停止中の limiter なら token は None。
        self._held: list[tuple[str, int | None]] = []
        self._state = _ATTEMPT_NEW

    def __enter__(self) -> PasswordAttempt:
        if self._state != _ATTEMPT_NEW:
            raise RuntimeError("PasswordAttempt は1回の with 文でだけ使えます。")
        self._state = _ATTEMPT_OPEN
        ctx = self._ctx
        try:
            for bucket in ctx.ip_buckets:
                self._reserve_or_raise_429(
                    bucket.store_key,
                    bucket.rule,
                    axis=bucket.axis,
                    key_prefix=bucket.key_prefix,
                    ip_net=bucket.ip_net,
                )
            if ctx.account_rule is not None:
                account_store_key, account_key_prefix = ctx._account_key(self._account_raw)
                self._account_store_key = account_store_key
                self._reserve_or_raise_429(
                    account_store_key,
                    ctx.account_rule,
                    axis="account",
                    key_prefix=account_key_prefix,
                    ip_net=None,
                )
        except BaseException:
            # __enter__ が例外で終わると with は __exit__ を呼ばないので、ここで外す。
            self._close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._close()

    def record_failure(self) -> None:
        """照合の失敗を記録する（IP軸の全段・アカウント軸に1回ずつ）。

        ここでは 429 を raise しない（呼び出し元がこの後で本来の失敗 HTTPException
        （401 等）を raise する契約のため。上限に達したかは次の要求の判定で分かる）。
        IP軸は意図的にリセットしない（設計書 §4: 同一IPから「自分のアカウントに成功→
        他人を攻撃」を繰り返すと IP軸が無意味化するため）。
        """
        self._settle()
        ctx = self._ctx
        for bucket in ctx.ip_buckets:
            ctx.limiter.record(bucket.store_key, bucket.rule)
        if self._account_store_key is not None and ctx.account_rule is not None:
            ctx.limiter.record(self._account_store_key, ctx.account_rule)
        self._release_all()

    def record_success(self) -> None:
        """照合の成功。アカウント軸だけをリセットする（IP軸は数えもリセットもしない）。"""
        self._settle()
        if self._account_store_key is not None:
            self._ctx.limiter.reset(self._account_store_key)
        self._release_all()

    def _reserve_or_raise_429(
        self,
        store_key: str,
        rule: RateLimitRule,
        *,
        axis: str,
        key_prefix: str,
        ip_net: str | None,
    ) -> None:
        reservation = self._ctx.limiter.reserve(store_key, rule)
        if not reservation.verdict.allowed:
            _raise_429(
                scope=self._ctx.scope,
                axis=axis,
                rule=rule,
                verdict=reservation.verdict,
                key_prefix=key_prefix,
                ip_net=ip_net,
            )
        self._held.append((store_key, reservation.token))

    def _settle(self) -> None:
        if self._state != _ATTEMPT_OPEN:
            raise RuntimeError(
                "record_failure／record_success は with 文の中で、1回の照合につき1度だけ"
                "呼べます。"
            )
        self._state = _ATTEMPT_SETTLED

    def _release_all(self) -> None:
        held, self._held = self._held, []
        for store_key, token in held:
            self._ctx.limiter.release(store_key, token)

    def _close(self) -> None:
        self._release_all()
        self._state = _ATTEMPT_CLOSED


class _NoopPasswordAttempt:
    """``NoopRateLimitContext.password_attempt()`` が返す、何もしない枠（ストアに触れない）。"""

    def __enter__(self) -> _NoopPasswordAttempt:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def record_failure(self) -> None:
        return None

    def record_success(self) -> None:
        return None


# 状態を持たないため、全要求で共有して問題ない。
_NOOP_PASSWORD_ATTEMPT = _NoopPasswordAttempt()


class NoopRateLimitContext:
    """``RATE_LIMIT_ENABLED=false``（キルスイッチ ON）時に使う no-op 実装。

    IP 解決すら行わない完全バイパス。ハンドラ側は常に
    ``request.state.rate_limit.password_attempt(...)`` 等を呼ぶだけでよく、
    ``if enabled:`` 分岐がハンドラに一切現れない（DRY／可読性維持）。
    """

    def check_account(self, account_raw: str) -> None:
        return None

    def password_attempt(self, account_raw: str) -> _NoopPasswordAttempt:
        return _NOOP_PASSWORD_ATTEMPT

    def hit_account(self, account_raw: str) -> None:
        return None


# モジュール内で使い回すシングルトン（状態を持たないため共有して問題ない）。
NOOP_RATE_LIMIT_CONTEXT = NoopRateLimitContext()


# ──────────────── 署名付き中継IP（login/line_exchange 限定の上書き） ────────────────
#
# web（Vercel）がサーバー側から認証系 API を呼ぶ構成では、hops 方式で解決される
# IP が利用者ではなく Vercel の送信元になり、この2 scope の IP 軸が全利用者で
# 共有されてしまう問題があった（詳細背景は app.core.client_ip_relay モジュール
# 冒頭）。対象を2 scope に限定するのは、万一 CLIENT_IP_RELAY_SECRETS が漏洩
# しても、悪用可能な範囲を「ログイン試行回数」「LINE連携試行回数」の水増しに
# 限定し、他の scope（signup・case_create 等のコストDoS対策）には一切影響
# させないため。
_RELAY_ELIGIBLE_SCOPES: frozenset[str] = frozenset({"login", "line_exchange"})

# 中継の検証処理自体が予期しない例外を投げた場合の WARNING（本来起こらない
# 想定だが、本機能の障害が認証系 API 全体を巻き込まないよう、必ず握りつぶして
# hops へフォールバックする。他の *_throttle と同じ理由でスロットリングする）。
_relay_unexpected_error_throttle = ThrottledLogger()
# ログ出力（log_relay_outcome）自体が例外を投げた場合の WARNING。検証本体の
# 例外（_relay_unexpected_error_throttle）とは意図的に別インスタンスにする
# （QA M-3: 2つの try を分ける理由と対で、スロットリングも独立させないと
# 片方の頻発がもう片方の初回検知を隠してしまうため）。
_relay_log_outcome_error_throttle = ThrottledLogger()


def _relayed_client_ip(scope: str, request: Request) -> str | None:
    """署名付き中継ヘッダを検証し、採用できる場合のみ利用者IPを返す。

    対象外 scope はヘッダを読みもせず ``None`` を返す（``_RELAY_ELIGIBLE_SCOPES``
    参照。鍵が万一漏洩した場合の悪用範囲を2 scope に構造的に限定する最初の
    ゲート）。

    **検証本体とログ出力を別々の try で囲む（QA M-3）。** 1つの try に
    まとめると、``log_relay_outcome``（ログ出力）側の不具合が、既に確定した
    検証結果（``ok`` かどうか）まで巻き込んで握りつぶしてしまう
    ――正しく採用できたはずの中継IPが、ログ処理のバグのせいで hops へ
    フォールバックされる、という本末転倒が起こり得る。したがって:

      1. 1つ目の try: 鍵の読み取り・署名検証本体。ここで例外が起きた場合は
         ``None`` を返す（hops へフォールバック。本来この経路の障害は
         認証系全体を巻き込んではならないため）。
      2. 2つ目の try: ``log_relay_outcome`` の呼び出しのみ。ここで例外が
         起きても握りつぶすだけで、**戻り値には一切影響させない**
         （既に確定した ``verification`` の内容だけで戻り値を決める）。

    どちらの try も、本機能はあくまで「無くても今どおり動く」上書きのため、
    ここでの障害がログイン・LINE連携そのものを 500 に巻き込むことは絶対に
    避ける。
    """
    if scope not in _RELAY_ELIGIBLE_SCOPES:
        return None

    try:
        settings = get_settings()
        keys = parse_relay_secrets(settings.client_ip_relay_secrets.get_secret_value())
        verification = verify_request_client_ip_relay(request, keys)
    except Exception:  # noqa: BLE001 -- 本機能の障害で認証系全体を巻き込まないため
        _relay_unexpected_error_throttle.emit(
            lambda: logger.exception(
                "rate_limit: 署名付き中継IPの検証中に予期しないエラーが発生しました"
                "（scope=%s）。従来どおり hops で数えます。",
                scope,
            )
        )
        return None

    try:
        # keys_configured=bool(keys): verify_request_client_ip_relay に渡したのと
        # 同じ keys から算出する（鍵が設定されているのに absent＝中継ヘッダが
        # 来ない要求を検知する material。2回目 security review L-A。
        # app.core.client_ip_relay.log_relay_outcome docstring 参照）。
        log_relay_outcome(scope, verification, keys_configured=bool(keys))
    except Exception:  # noqa: BLE001 -- ログ処理の不具合で確定済みの検証結果を握りつぶさない
        _relay_log_outcome_error_throttle.emit(
            lambda: logger.exception(
                "rate_limit: 署名付き中継IPの判定ログ出力中に予期しないエラーが"
                "発生しました（scope=%s）。判定結果には影響しません。",
                scope,
            )
        )

    return verification.ip if verification.reason == "ok" else None


def _apply_ip_axis(
    scope: str,
    limiter: RateLimiter,
    rule: RateLimitRule,
    *,
    count_all: bool,
    ip: str,
) -> tuple[_IpBucket, ...]:
    """IP軸のキーを作り、判定する唯一の場所（``RateLimitGuard.__call__`` から
    呼ぶ）。hops 方式以外の経路で得た IP（例: 将来の署名付き中継）であっても、
    レート制限に数える前には必ずこの関数を経由すること。戻り値の段は
    ``RateLimitContext.ip_buckets`` に渡す（失敗のみカウントの login では、
    ``record_failure`` がこの段に記録する）。

    ``_ip_axis_buckets`` で狭い段→広い段の並びを作り、次の順で評価する
    （IPv4 は段が1つのため、呼び出しの並びと結果は従来と同一になる）:
      (a) 広い段（/56・/48）をすべて先に ``limiter.check``（peek。キーを作らない）で
          判定する。弾かれたら 429（広い段が塞がった後は、新しい /64 から来ても
          ストアのキーを増やさない）。
      (b) 狭い段を判定する。``count_all`` なら ``limiter.record``、そうでなければ
          （login 等）``limiter.check``。弾かれたら 429。
      (c) ``count_all`` のときだけ、広い段を狭い順に ``limiter.record`` する
          （狭い段で弾かれた要求は広い段に数えない。1つの /64 の連打で /56・/48 が
          埋まらないようにするため）。(a)〜(c) の間に await が無いため必ず通るはず
          だが、ストアが差し替えられた場合に備えて verdict を確かめ、通らなければ
          429 にする。
    429 は ``_raise_429`` を使い、axis・rule・key_prefix は弾いた段のものを、ip_net は
    ``_ip_net_for_log(ip)``（IPv6 は /48。生の IP・/64・ゾーン ID は出さない）を渡す。
    応答文言はスコープの既存文言のまま（段では変えない）。
    ``count_all`` と ``ip`` はキーワード専用（真偽値と文字列の取り違えを防ぐ）。
    """
    buckets = _ip_axis_buckets(scope, ip, rule)
    narrow, wider = buckets[0], buckets[1:]

    def reject(bucket: _IpBucket, verdict: RateLimitVerdict) -> NoReturn:
        _raise_429(
            scope=scope,
            axis=bucket.axis,
            rule=bucket.rule,
            verdict=verdict,
            key_prefix=bucket.key_prefix,
            ip_net=_ip_net_for_log(ip),
        )

    for bucket in wider:
        verdict = limiter.check(bucket.store_key, bucket.rule)
        if not verdict.allowed:
            reject(bucket, verdict)

    verdict = (
        limiter.record(narrow.store_key, narrow.rule)
        if count_all
        else limiter.check(narrow.store_key, narrow.rule)
    )
    if not verdict.allowed:
        reject(narrow, verdict)

    if count_all:
        for bucket in wider:
            verdict = limiter.record(bucket.store_key, bucket.rule)
            if not verdict.allowed:
                reject(bucket, verdict)

    return buckets


class RateLimitGuard:
    """スコープ別のレート制限ガード（FastAPI の Depends として使用する）。

    IP 軸の事前判定のみをここで行い、結果を ``RateLimitContext`` として
    ``request.state.rate_limit`` に格納する。

    - ``enabled=False`` の場合、IP 解決すら行わず即座に
      ``NOOP_RATE_LIMIT_CONTEXT`` を格納して返る（§6-(c)）。
    - 全リクエスト方式のスコープ（signup / line_exchange）は、ここで
      IP 軸を ``hit``（カウント）し、超過なら即座に 429 を raise する
      （事前に hit 1回で完結する。設計書 §4）。
    - 失敗のみカウント方式のスコープ（login）は、ここでは ``peek``
      （非消費の事前判定）のみを行う。照合の可否の判定と実カウントは、ハンドラ側の
      ``ctx.password_attempt()`` の枠で行われる（``PasswordAttempt`` 参照）。
    - **IP軸の段数（IPv6）**: IP軸のキー生成・判定は ``_apply_ip_axis``
      （内部で ``_ip_axis_buckets`` を使う）に一本化されている。IPv4 は
      従来どおりアドレス単位の1段。IPv6 は要求ごとに送信元アドレスを
      替えるだけで単一アドレス単位のバケットを無限に生成できてしまうため、
      SLAAC の最小割当単位である /64 と、それより広い /56・/48（上限を
      ``_IPV6_56_LIMIT_MULTIPLIER`` 倍・``_IPV6_48_LIMIT_MULTIPLIER`` 倍に緩めて
      併用）の3段で数える。採否の理由は同モジュールの ``_IPV6_TIERS`` 定数
      近くのコメントに詳述する。
    - IP が解決できない場合（``resolve_client_ip_with_reason`` が返す
      ``ClientIpResolution.ip`` が ``None``）の扱いは ``reason`` で分岐する
      （security review 指摘対応。設計書 §2 時点の単純なフェイルオープンから
      強化）:
        - ``reason == "no_xff"``: X-Forwarded-For ヘッダが**そもそも無い**、
          または ``request.client`` が ``None``（インフラ構成としてありうる
          状態） → 従来どおり IP軸をスキップする（アカウント軸は通常どおり
          適用）。
        - ``reason in ("invalid", "empty_xff")``: X-Forwarded-For ヘッダが
          **存在するのに**解決できなかった（不正値混入等。正規クライアント
          では通常起こらない） → **フェイルクローズとして 400 で拒否する**。
          IP軸だけが無効化され signup 等（IP軸しか持たないスコープ）が
          完全に無防備になる経路を塞ぐ。
    - 信頼位置（``parts[-trusted_hops]``）に解決された IP は、**攻撃者が誘発
      できるか否か**で扱いを完全に分ける（security review Critical 是正・
      撤回済み scan 方式からの教訓）:
        1. **攻撃者が誘発できない条件（IP軸スキップ）**: 信頼位置は
           CF/プロキシが実接続元として追記する位置であり、攻撃者はこの位置に
           現れる値を選べない。したがって以下が現れた場合、それは攻撃ではなく
           構成異常のみを意味し、スキップしても悪用経路にならない:
             - ``is_private_or_loopback(ip)``: ``TRUSTED_PROXY_HOPS`` 誤設定で
               内部固定IPを掴んでいる疑い。全ユーザーが同一バケットを共有する
               全断を防ぐ（従来からの判定）。
             - ``is_special_use_address(ip)``: 未指定(0.0.0.0/::)・マルチ
               キャスト・IETF予約済み。プロキシ実装や LB 構成変更（unknown な
               接続元の代替表記等）を意味する新設の判定（IPv4射影IPv6の
               正規化バグ修正と合わせて追加。security review Critical）。
        2. **攻撃者が誘発できる条件（WARNING のみ・カウント継続）**:
           ``is_cloudflare_range(ip)`` が True の場合。信頼位置が CF レンジ内
           ＝``TRUSTED_PROXY_HOPS`` が実構成より小さい疑いだが、Cloudflare
           Workers 等から攻撃者が無料で CF egress IP を送り込めるため、ここで
           スキップすると常時利用可能なバイパスになる。**フェイルクローズも
           スキップもせず、従来どおりカウントを継続した上で WARNING のみ出す**
           （トレードオフの詳細は ``_warn_cf_range_at_trust_position`` の
           docstring 参照。緊急停止スイッチ ``RATE_LIMIT_ENABLED=false`` で
           いつでも1操作で復旧できることが前提）。
      いずれの分岐もスロットリング（60秒に1回）で WARNING を出し、無言の
      バイパス/スキップ/全体障害の前兆を無くす（security review Medium-2）。
    - **ドリフト検知（判定に一切影響しない）**: IP が正常に解決できた場合、
      診断専用の ``scan_client_ip_for_diagnostics`` の結果と比較し、不一致
      ならスロットリング付き WARNING を出す（``_check_scan_drift``）。CDN
      構成変更・``TRUSTED_PROXY_HOPS`` ドリフトを能動的なポーリングなしで
      検知するための唯一の早期シグナル。
    - **署名付き中継による上書き（新設・``login`` / ``line_exchange`` の
      2 scope 限定）**: ``app.core.client_ip_relay`` が検証した署名付き
      中継ヘッダの利用者IPが採用可能（``reason == "ok"``）な場合、hops
      方式の解決・プライベート/特殊アドレス判定・CFレンジ判定・ドリフト
      検知は一切行わず、その中継IPで直接 IP 軸を判定する
      （``_relayed_client_ip`` / ``_apply_ip_axis``）。不採用（ヘッダ無し・
      鍵未設定・署名不一致・期限切れ・形式不正・非公開IP等、理由を問わず）
      の場合は、常に従来どおり hops 方式へフォールバックする。対象外の
      scope（この2つ以外）はヘッダを読みもしない。詳細な判定順序・背景は
      ``app.core.client_ip_relay`` モジュール冒頭を参照。
    """

    def __init__(self, scope: str) -> None:
        self._scope = scope

    async def __call__(
        self,
        request: Request,
        limiter: RateLimiter = Depends(get_rate_limiter),
    ) -> RateLimitContext | NoopRateLimitContext:
        if not limiter.enabled:
            request.state.rate_limit = NOOP_RATE_LIMIT_CONTEXT
            return NOOP_RATE_LIMIT_CONTEXT

        spec = _scope_spec(self._scope, limiter.config)

        ip_buckets: tuple[_IpBucket, ...] = ()
        # 署名付き中継（login/line_exchange 限定・_RELAY_ELIGIBLE_SCOPES）。
        # 対象外 scope、および ip_rule を持たない scope ではヘッダを読みもせず
        # None が返る。
        relayed_ip = (
            _relayed_client_ip(self._scope, request) if spec.ip_rule is not None else None
        )
        if relayed_ip is not None:
            # 中継IPを採用する場合、hops 方式の解決・プライベート/特殊アドレス
            # 判定・CFレンジ判定・ドリフト検知は一切行わない。中継ヘッダの検証
            # （app.core.client_ip_relay.verify_client_ip_relay）が既に非公開
            # アドレスの排除・署名・鮮度を確認済みのため、hops 方式と同じ
            # 追加判定を重ねる必要が無い（むしろ中継IPに hops 用の判定を
            # 適用すると意味的に誤り）。
            # hops で解決した IP の段に「足す」のではなく「置き換える」（ctx.ip_buckets を
            # 中継IPの段だけにする）。足すと login の record_failure が Vercel の送信元の
            # 段にも記録され、全利用者で共有する枠が復活してしまう。
            ip_buckets = _apply_ip_axis(
                self._scope, limiter, spec.ip_rule, count_all=spec.count_all, ip=relayed_ip
            )
        elif spec.ip_rule is not None:
            settings = get_settings()
            # IP 解決は resolve_client_ip_with_reason（正本・単一入口）を
            # 経由する。戻り値は ClientIpResolution（ip, reason）。reason で
            # 「フェイルクローズすべき異常入力」（invalid/empty_xff）と
            # 「IP軸を安全にスキップすべき状態」（no_xff）を区別する
            # （ip is None だけで判定すると両者が区別できない。security
            # review Critical 指摘）。reason は従来の xff_present 判定
            # （trusted_proxy_hops > 0 and get_xff_raw(...) is not None）と
            # 等価になるよう設計されており、実質的な挙動は本リファクタ前と
            # 1bit も変わらない（app.core.client_ip.resolve_client_ip_with_reason
            # 参照）。
            resolution = resolve_client_ip_with_reason(request, settings.trusted_proxy_hops)
            ip = resolution.ip
            if ip is None:
                if resolution.reason in ("invalid", "empty_xff"):
                    # XFF はあるのに解決できなかった＝不正値混入の疑い。
                    # ここで黙って IP軸をスキップすると signup 等（IP軸しか
                    # 持たないスコープ）が完全に無防備になるため拒否する。
                    _warn_unresolvable_xff(self._scope)
                    raise _INVALID_REQUEST_HEADERS()
                # "no_xff": XFF ヘッダ自体が無い、または request.client も
                # 無い（インフラ構成としてありうる正常系）。
                _warn_ip_axis_skipped(self._scope)
            else:
                # ドリフト検知（判定には一切影響させない。診断専用の scan と
                # 比較して不一致なら WARNING のみ）。
                _check_scan_drift(self._scope, request, ip)

                if is_private_or_loopback(ip):
                    # 攻撃者が誘発できない条件その1: 信頼位置のIPがプライベート
                    # /ループバック＝ hops 誤設定で内部プロキシIPを掴んでいる
                    # 疑い。全断を構造的に防ぐため IP軸をスキップする
                    # （アカウント軸は通常どおり適用）。
                    _warn_private_ip_skip(self._scope, ip)
                elif is_special_use_address(ip):
                    # 攻撃者が誘発できない条件その2: 未指定/マルチキャスト/
                    # 予約済みアドレス（新設。security review Critical）。
                    _warn_special_address_skip(self._scope, ip)
                else:
                    if is_cloudflare_range(ip):
                        # 攻撃者が誘発できる条件: CFレンジは Cloudflare
                        # Workers 等から無料で送り込めるため、スキップすると
                        # 常時利用可能なバイパスになる。フェイルクローズも
                        # スキップもせずカウントを継続し WARNING のみ出す
                        # （_warn_cf_range_at_trust_position のトレードオフ
                        # docstring 参照）。
                        _warn_cf_range_at_trust_position(self._scope, ip)
                    ip_buckets = _apply_ip_axis(
                        self._scope, limiter, spec.ip_rule, count_all=spec.count_all, ip=ip
                    )

        ctx = RateLimitContext(
            limiter=limiter,
            scope=self._scope,
            account_rule=spec.account_rule,
            ip_buckets=ip_buckets,
        )
        request.state.rate_limit = ctx
        return ctx
