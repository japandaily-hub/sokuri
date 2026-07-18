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
from app.core.client_ip import get_xff_raw, is_private_or_loopback, resolve_client_ip, truncate_ip_for_log
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

# ──────────────────────────── スコープ別メッセージ・文言 ────────────────────────────
# login の2軸（アカウント/IP）はあえて同一文言にする（設計書 §5）。文言を分けると
# 攻撃者が「アカウント軸で止まった＝そのメールアドレスは実在する」と判別でき、
# レート制限自体が新たなアカウント列挙オラクルになるため。
_SCOPE_MESSAGES: dict[str, str] = {
    "login": "ログインの試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "password_change": "パスワード変更の試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "account_delete": "試行回数が上限に達しました。しばらく時間をおいて再度お試しください。",
    "signup": "登録試行が集中しています。しばらく時間をおいて再度お試しください。",
    "line_exchange": "リクエストが集中しています。しばらく時間をおいて再度お試しください。",
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
    if scope == "signup":
        return _ScopeSpec(ip_rule=config.signup_ip, account_rule=None, count_all=True)
    if scope == "line_exchange":
        return _ScopeSpec(ip_rule=config.line_ip, account_rule=None, count_all=True)
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
    - IP が解決できない場合（``resolve_client_ip`` が ``None``）の扱いは
      2通りに分岐する（security review 指摘対応。設計書 §2 時点の単純な
      フェイルオープンから強化）:
        - X-Forwarded-For ヘッダが**そもそも無い**、または ``request.client``
          が ``None``（インフラ構成としてありうる状態） → 従来どおり IP軸を
          スキップする（アカウント軸は通常どおり適用）。
        - X-Forwarded-For ヘッダが**存在するのに**解決できなかった
          （不正値混入等。正規クライアントでは通常起こらない） →
          **フェイルクローズとして 400 で拒否する**。IP軸だけが無効化され
          signup 等（IP軸しか持たないスコープ）が完全に無防備になる経路を
          塞ぐ。
    - **信頼位置（``parts[-trusted_hops]``）の IP がプライベート/ループバック
      の場合、IP軸をスキップする**（security review 指摘・全断防止の要）。
      Render のエッジ〜アプリ間にもう1段プロキシが入る等 ``TRUSTED_PROXY_HOPS``
      が実際の構成より1段少ない場合、信頼位置には内部固定IPが来る。これを
      そのまま IP軸のキーに使うと**全ユーザーが同一バケットを共有し、
      数分で全世界のログインが429になる全断**を起こす。ここでスキップする
      ことで、誤構成時でも「レート制限が緩む」だけで済み、認証全断は構造的に
      起こりえなくなる。これはバイパスにはならない: ``trusted_hops`` が実際の
      プロキシ段数以下である限り（＝正しい設定である限り）、信頼位置の値は
      必ずプロキシが追記した実クライアントIPであり、インターネット経由の
      攻撃者はこれをプライベートIPにできない。
      いずれの分岐もスロットリング（60秒に1回）で WARNING を出し、無言の
      バイパス/スキップ/全体障害の前兆を無くす（security review Medium-2）。
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
            # ヘッダ取得は resolve_client_ip と必ず同じ経路（get_xff_raw）を
            # 通す。個別実装すると乖離が生じ無言バイパスに戻る
            # （security review High-2）。
            xff_present = settings.trusted_proxy_hops > 0 and get_xff_raw(request) is not None
            ip = resolve_client_ip(request, settings.trusted_proxy_hops)
            if ip is None:
                if xff_present:
                    # XFF はあるのに解決できなかった＝不正値混入の疑い。
                    # ここで黙って IP軸をスキップすると signup 等（IP軸しか
                    # 持たないスコープ）が完全に無防備になるため拒否する。
                    _warn_unresolvable_xff(self._scope)
                    raise _INVALID_REQUEST_HEADERS
                _warn_ip_axis_skipped(self._scope)
            elif is_private_or_loopback(ip):
                # 信頼位置のIPがプライベート/ループバック＝ hops 誤設定で
                # 内部プロキシIPを掴んでいる疑い。全断を構造的に防ぐため
                # IP軸をスキップする（アカウント軸は通常どおり適用）。
                _warn_private_ip_skip(self._scope, ip)
            else:
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
