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
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import NoReturn

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

_INVALID_REQUEST_HEADERS = HTTPException(
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
    生 IP はログに残さず ``truncate_ip_for_log()`` で丸めた値のみ出す。
    """
    _private_ip_skip_throttle.emit(
        lambda: logger.warning(
            "rate_limit: 信頼位置のIPがプライベート/ループバックのため IP軸をスキップ"
            "しました（scope=%s ip_net=%s）。TRUSTED_PROXY_HOPS の誤設定で内部プロキシIPを"
            "掴んでいる疑いがあります。/api/v1/_diag/client-ip で実測して確認してください。",
            scope,
            truncate_ip_for_log(ip),
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
    起こりえなくなる）。生 IP はログに残さず ``truncate_ip_for_log()`` で
    丸めた値のみ出す。
    """
    _special_address_skip_throttle.emit(
        lambda: logger.warning(
            "rate_limit: 信頼位置のIPが未指定/マルチキャスト/予約済みアドレスのため"
            "IP軸をスキップしました（scope=%s ip_net=%s）。プロキシ/LB構成が変更された"
            "可能性があります。/api/v1/_diag/client-ip で実測して確認してください。",
            scope,
            truncate_ip_for_log(ip),
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
            truncate_ip_for_log(ip),
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
    "signup": "登録試行が集中しています。しばらく時間をおいて再度お試しください。",
    "line_exchange": "リクエストが集中しています。しばらく時間をおいて再度お試しください。",
    "case_create": "案件の作成が集中しています。しばらく時間をおいて再度お試しください。",
    "bid_withdraw": "入札の取り下げの試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
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
    # False: IP 軸は事前は peek のみ、実カウントは失敗時の record_failure で行う（login）。
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
    使っても、``check_account``/``record_failure``/``reset_account`` に渡す
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
    if scope == "bid_withdraw":
        # 入札取り下げ: Case行の排他ロック取得・監査レコード書き込みを伴う
        # コストDoS対策（security review 指摘対応）。認証済み業者のみが
        # 呼べるエンドポイントのため IP 軸は持たず、operator_id 軸のみで
        # 全リクエストをカウントする（新規の数値設定は追加せず、既存の
        # sensitive_account ルール — password_change/account_delete と
        # 同一 — を流用する。設計指示に基づく）。
        return _ScopeSpec(ip_rule=None, account_rule=config.sensitive_account, count_all=False)
    raise ValueError(f"未知の rate limit scope です: {scope!r}")


@dataclass
class RateLimitContext:
    """1リクエスト分のレート制限操作窓口。

    ``RateLimitGuard``（Depends）が IP 軸の事前判定を済ませた上で
    ``request.state.rate_limit`` に格納する。アカウント軸の判定は body の
    email 等が判明した直後にハンドラ側が明示的に呼び出す
    （Depends の実行時点ではリクエストボディが未解析のため）。

    呼び出し規約（設計書 §6）:
        ctx = request.state.rate_limit
        ctx.check_account(account_key)      # 超過なら 429 を raise
        ... 認証判定 ...
        ctx.record_failure(account_key)     # IP軸・アカウント軸の両方をカウント
        raise _LOGIN_FAILED                 # 失敗パス
        ctx.reset_account(account_key)      # 成功パス（アカウント軸のみリセット）
    """

    limiter: RateLimiter
    scope: str
    account_rule: RateLimitRule | None
    ip_key: str | None
    ip_rule: RateLimitRule | None

    def check_account(self, account_raw: str) -> None:
        """アカウント軸の事前チェック（peek）。超過なら 429 を raise する。"""
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

    def record_failure(self, account_raw: str) -> None:
        """失敗を記録する（IP軸・アカウント軸の両方をカウント）。

        ここでは 429 を raise しない（呼び出し元がこの後で本来の失敗
        HTTPException（401等）を raise する契約のため。超過判定は次回リクエスト
        時の事前チェックで行われる）。IP軸は意図的にリセットしない（設計書 §4:
        同一IPから「自分のアカウントに成功→他人を攻撃」を繰り返すと IP軸が
        無意味化するため）。
        """
        if self.ip_key is not None and self.ip_rule is not None:
            self.limiter.record(_build_key(self.scope, "ip", self.ip_key), self.ip_rule)
        if self.account_rule is not None:
            digest = _hash_identity(account_raw)
            self.limiter.record(_build_key(self.scope, "acct", digest), self.account_rule)

    def reset_account(self, account_raw: str) -> None:
        """成功時にアカウント軸のみリセットする（IP軸はリセットしない）。"""
        if self.account_rule is None:
            return
        digest = _hash_identity(account_raw)
        self.limiter.reset(_build_key(self.scope, "acct", digest))

    def hit_account(self, account_raw: str) -> None:
        """アカウント軸を無条件でカウントし、超過なら 429 を raise する。

        ``record_failure`` （失敗時のみカウントする login 等の方式）とは異なり、
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


class NoopRateLimitContext:
    """``RATE_LIMIT_ENABLED=false``（キルスイッチ ON）時に使う no-op 実装。

    IP 解決すら行わない完全バイパス。ハンドラ側は常に
    ``request.state.rate_limit.record_failure(...)`` 等を呼ぶだけでよく、
    ``if enabled:`` 分岐がハンドラに一切現れない（DRY／可読性維持）。
    """

    def check_account(self, account_raw: str) -> None:
        return None

    def record_failure(self, account_raw: str) -> None:
        return None

    def reset_account(self, account_raw: str) -> None:
        return None

    def hit_account(self, account_raw: str) -> None:
        return None


# モジュール内で使い回すシングルトン（状態を持たないため共有して問題ない）。
NOOP_RATE_LIMIT_CONTEXT = NoopRateLimitContext()


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
      （非消費の事前判定）のみを行う。実カウントはハンドラ側の
      ``ctx.record_failure()`` で行われる。
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

        ip_key: str | None = None
        if spec.ip_rule is not None:
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
                    raise _INVALID_REQUEST_HEADERS
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
                    ip_key = _hash_identity(ip)
                    key = _build_key(self._scope, "ip", ip_key)
                    verdict = (
                        limiter.record(key, spec.ip_rule)
                        if spec.count_all
                        else limiter.check(key, spec.ip_rule)
                    )
                    if not verdict.allowed:
                        _raise_429(
                            scope=self._scope,
                            axis="ip",
                            rule=spec.ip_rule,
                            verdict=verdict,
                            key_prefix=ip_key[:12],
                            ip_net=truncate_ip_for_log(ip),
                        )

        ctx = RateLimitContext(
            limiter=limiter,
            scope=self._scope,
            account_rule=spec.account_rule,
            ip_key=ip_key,
            ip_rule=spec.ip_rule,
        )
        request.state.rate_limit = ctx
        return ctx
