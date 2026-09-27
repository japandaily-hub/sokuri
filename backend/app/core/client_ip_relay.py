"""web サーバー（Vercel）が署名付きで中継する利用者 IP の検証・採用の仕組み。

**背景（設計確定版）**: 本番の web（Vercel）はサーバー側から
``/api/v1/auth/login`` / ``/api/v1/auth/operator/login`` /
``/api/v1/auth/line/exchange`` を呼び出すため、backend の IP 軸
（``app.core.client_ip.resolve_client_ip_with_reason`` の固定段数 hops 方式）
が利用者ではなく Vercel の送信元 IP で数えられてしまい、scope "login"
（失敗20回/15分・パスワード照合前に止まる）と "line_exchange"
（全件20回/15分）が全利用者で共有される問題があった。web が Vercel の
実クライアントIP（x-real-ip 相当）を HMAC 署名付きヘッダで中継し、backend は
署名が正しい場合に限り、この2 scope（``rate_limit_deps._RELAY_ELIGIBLE_SCOPES``
参照）でのみ hops 方式の代わりに採用する。

**hops 方式は依然として正本であり、本モジュールはあくまで2 scope 限定の
上書き手段に過ぎない。** 不採用（ヘッダ無し・鍵未設定・署名不一致・
期限切れ・形式不正・非公開IP等、いずれの理由でも）の場合は、必ず
呼び出し側（``rate_limit_deps.RateLimitGuard``）が hops 方式へフォールバック
する。``app.core.client_ip`` モジュール冒頭の「設計判断の履歴」（信頼済み
プロキシレンジの右端スキャン方式が偽装を許し撤回された経緯）とは独立した
機構であり、hops 方式の判定経路自体には一切手を加えない。

**このモジュールは「検証の仕組み」のみを持ち、どの scope で使うか・
``app.config`` の設定値をどう読み出すかには一切関与しない**
（呼び出し側の ``app.api.rate_limit_deps`` に一本化する）。``app.config`` を
import しないのは、この検証ロジック自体を HTTP・設定に依存しない純関数
として単体テストできるようにするための制約であり、崩してはならない
（``app.core.rate_limit`` が FastAPI を import しないのと同じ設計判断）。

**ヘッダ形式**: ``X-Katazuke-Client-Ip-Relay: v1;<10桁UNIX秒>;<IPの生文字列>;
<HMAC-SHA256 小文字hex64桁>``。署名対象（ASCII限定）は
``"\\n".join((SIGNING_CONTEXT, METHOD大文字, PATH, TS文字列, IPの生文字列))``。
``PATH`` は ``request.url.path``（クエリを含まない）。IP はヘッダの生文字列の
まま署名し、検証成功後にのみ正規化する（正規化ロジックのバグや表記揺れが
署名検証をすり抜ける経路を作らないため。IPv4射影IPv6の展開・プライベート/
特殊用途判定は署名検証を通過した後にのみ行う）。

**署名照合はタイミングサイドチャネル対策のため全鍵を早期終了せず走査する**
（``hmac.compare_digest`` 自体は定数時間比較だが、「最初に一致した鍵で
ループを打ち切る」実装だと鍵の位置によってループ回数＝処理時間が変わり、
外部から観測可能な場合に鍵のローテーション状況（何番目の鍵が現在有効か）
を推測される余地を残すため、一致後も残り全鍵の比較を続ける）。

**鍵の設定不備は起動を止めない**（``parse_relay_secrets`` 参照）。本機能は
「無くても今どおり hops で動く」上書きに過ぎないため、不正な
``CLIENT_IP_RELAY_SECRETS`` の設定ミスで認証系 API 全体が起動不能になる
（＝全断）ことは絶対に避ける。同様に、検証処理自体の予期しない例外も
呼び出し側（``rate_limit_deps._relayed_client_ip``）で握りつぶし hops へ
フォールバックする。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import re
import time
from functools import lru_cache
from typing import Callable, Literal, NamedTuple, Sequence

from fastapi import Request

from app.core.client_ip import (
    _unwrap_ipv4_mapped,
    is_private_or_loopback,
    is_special_use_address,
    truncate_ip_for_log,
)
from app.core.log_throttle import ThrottledLogger

logger = logging.getLogger(__name__)

# ──────────────────────────── 定数 ────────────────────────────

RELAY_HEADER_NAME = "X-Katazuke-Client-Ip-Relay"
RELAY_VERSION = "v1"
# HMAC 署名対象文字列の先頭要素。用途ラベル付きにすることで、この署名鍵が
# 万一別用途の HMAC 署名と混同されても（同じ秘密文字列を使い回した場合）
# 生成されるダイジェストが一致しないようにする（鍵の用途分離。
# rate_limit_deps._rate_limit_hmac_key の派生鍵設計と同じ考え方）。
SIGNING_CONTEXT = "katazuke-client-ip-relay/v1"
# 許容する最大の時刻ずれ（秒）。web からのリクエストは即座に中継されるため
# 60秒あれば通常のネットワーク遅延・多少の時刻ずれを吸収できる一方、
# 漏洩したヘッダ値の再送攻撃（リプレイ）を長時間許してしまわない値として選ぶ。
MAX_CLOCK_SKEW_SECONDS = 60
# CLIENT_IP_RELAY_SECRETS の各鍵に要求する最小長。短い鍵は総当たりで
# 署名偽造される現実的なリスクがあるため、起動時の生成コマンド
# （``secrets.token_urlsafe(48)``）が生成する鍵長に対して十分な余裕を持たせる。
MIN_SECRET_LENGTH = 32
# 同時に有効化できる鍵の本数上限。ローテーション（新旧2本）を想定した数に
# 余裕を持たせた値。無制限にすると設定ミスで大量の鍵を書いた場合に
# 検証コストが線形に増える（署名照合は毎リクエスト全鍵を走査するため）。
MAX_KEYS = 4
# ヘッダ値の最大長。正規のヘッダ値は IPv6 表記を含めても124文字程度に収まる
# （"v1;" + 10桁 + ";" + 最大45文字のIP + ";" + 64桁hex）。極端に長い値を
# 正規表現でフルスキャンさせないための事前防御的な上限。
_MAX_HEADER_VALUE_LENGTH = 128
# ヘッダ値全体の書式（4フィールド）を一括検証する。IP フィールドは
# 「0-9・A-F・a-f・コロン・ドット」のみを許可する緩い文字クラスとし、実際の
# IP としての妥当性（桁数・値域・射影表記等）は ipaddress.ip_address() に
# 委ねる（正規表現側は「そもそも IP らしくない文字（空白・角括弧・%等）を
# 早期に弾く」役割に限定する）。
_HEADER_RE = re.compile(r"(v[0-9]{1,3});([0-9]{10});([0-9A-Fa-f:.]{2,45});([0-9a-f]{64})")
# request.url.path が取りうる形式（クエリを含まない絶対パス）。
_PATH_RE = re.compile(r"/[A-Za-z0-9/_.\-]{0,255}")
# 大文字化後の HTTP メソッド名。
_METHOD_RE = re.compile(r"[A-Z]{1,16}")


RelayReason = Literal[
    "ok",
    "absent",
    "unconfigured",
    "malformed",
    "unsupported_version",
    "bad_signature",
    "expired",
    "ip_unparseable",
    "ip_not_public",
]


class RelayVerification(NamedTuple):
    """``verify_client_ip_relay`` の判定結果。

    - ``ip``: 採用可能な場合のみ正規化済みの IP 文字列（それ以外は ``None``）。
    - ``reason``: 判定結果の理由。``"ok"`` 以外は全て不採用（hops へ
      フォールバックすべき）を意味する。
    - ``key_slot``: 署名が一致した鍵の ``keys`` 内でのインデックス
      （0始まり）。署名照合まで到達しなかった場合（absent/unconfigured/
      malformed/unsupported_version）は ``None``。
    - ``skew_seconds``: ``now_epoch_seconds - int(timestamp)``。署名照合を
      通過した場合（expired/ip_unparseable/ip_not_public/ok）にのみ設定する。
    - ``rejected_ip_net``: ``ip_not_public`` の場合のみ、丸めた IP
      （``truncate_ip_for_log`` 済み）を設定する。ログ出力専用で、生 IP は
      一切保持しない。
    """

    ip: str | None
    reason: RelayReason
    key_slot: int | None = None
    skew_seconds: int | None = None
    rejected_ip_net: str | None = None


@lru_cache(maxsize=8)
def parse_relay_secrets(raw: str) -> tuple[bytes, ...]:
    """``CLIENT_IP_RELAY_SECRETS``（カンマ区切り・先頭が新しい鍵）を解析する。

    各候補は次の全てを満たさなければ無効として除外し、``logger.error`` で
    「何番目の候補か・除外理由」のみを記録する（**値そのものも長さも
    ログに残さない**。鍵はログ経由で漏洩させてはならない秘密情報のため）:

      - ``MIN_SECRET_LENGTH`` 文字以上。
      - ``str.isascii()``（非ASCII文字を含まない）。
      - ``str.isprintable()``（制御文字を含まない）。
      - 空白文字を含まない（``isprintable()`` は半角スペース単体を通して
        しまうため、別途明示的にチェックする）。

    有効な候補のみを対象に、順序を保ったまま重複を除去し、``MAX_KEYS`` を
    超える分は末尾を切り捨てて ``logger.error`` を出す（無効な候補の重複は
    対象外＝無効な候補は毎回独立に除外・ログされる）。

    ``raw`` を分割・空要素除去した時点で候補が1つも無い場合（空文字列・
    空白のみ・カンマのみ）は「そもそも設定されていない」通常運用として
    扱い、エラーは出さない。候補は存在したが有効な鍵が1本も残らなかった
    場合のみ、「署名付き中継を無効化する（従来どおり hops で数える）」旨の
    ``logger.error`` を出す（設定ミスに気付けるようにするため）。

    **起動を止めない**: この関数はどのような ``raw`` を渡されても例外を
    送出せず、常に ``tuple[bytes, ...]``（空の場合は ``()``）を返す。中継は
    「無くても今どおり動く」上書き機能であるため、鍵の設定ミス1つで
    認証系 API 全体の起動を失敗させることは避ける。

    ``@lru_cache`` によりプロセス内で ``raw`` の値ごとに1度だけ解析する
    （``settings.client_ip_relay_secrets`` は毎リクエスト同じ文字列を返すため、
    HMAC 鍵オブジェクトの再構築コストを避けられる）。テストで
    ``monkeypatch`` により新しい値を注入した場合は、その新しい文字列が
    そのままキャッシュキーになるため、明示的な ``cache_clear()`` は不要
    （値が変われば別エントリとして扱われる）。
    """
    tokens = [token.strip() for token in raw.split(",")]
    tokens = [token for token in tokens if token]
    if not tokens:
        # 空・空白のみ・カンマのみ。「未設定」と同じ通常運用のため無音。
        return ()

    valid_ordered: list[str] = []
    seen: set[str] = set()
    for position, token in enumerate(tokens, start=1):
        if (
            len(token) < MIN_SECRET_LENGTH
            or not token.isascii()
            or not token.isprintable()
            or any(ch.isspace() for ch in token)
        ):
            logger.error(
                "client_ip_relay: CLIENT_IP_RELAY_SECRETS の%d番目の鍵が要件"
                "（%d文字以上・ASCII印字可能文字のみ・空白を含まない）を満たさない"
                "ため除外します（値・長さは記録しません）。",
                position,
                MIN_SECRET_LENGTH,
            )
            continue
        if token in seen:
            continue
        seen.add(token)
        valid_ordered.append(token)

    if len(valid_ordered) > MAX_KEYS:
        logger.error(
            "client_ip_relay: CLIENT_IP_RELAY_SECRETS に有効な鍵が%d本ありますが"
            "上限（%d本）を超えるため、先頭%d本のみ使用します。",
            len(valid_ordered),
            MAX_KEYS,
            MAX_KEYS,
        )
        valid_ordered = valid_ordered[:MAX_KEYS]

    if not valid_ordered:
        logger.error(
            "client_ip_relay: CLIENT_IP_RELAY_SECRETS に有効な鍵が1本もないため、"
            "署名付き中継を無効化します（login/line_exchange とも従来どおり "
            "hops のみで数えます）。"
        )

    return tuple(token.encode("ascii") for token in valid_ordered)


def canonical_relay_message(*, method: str, path: str, timestamp: str, ip: str) -> str:
    """署名対象の正準文字列を組み立てる（ASCII限定）。

    ``method`` はここで必ず大文字化する（署名生成・検証の両方が必ずこの
    関数を経由するため、呼び出し側の大文字小文字表記に関わらず一貫した
    署名対象が得られる）。
    """
    return "\n".join((SIGNING_CONTEXT, method.upper(), path, timestamp, ip))


def compute_relay_signature(key: bytes, *, method: str, path: str, timestamp: str, ip: str) -> str:
    """``key`` で ``canonical_relay_message`` の HMAC-SHA256 hex ダイジェスト（小文字64桁）を計算する。"""
    message = canonical_relay_message(method=method, path=path, timestamp=timestamp, ip=ip)
    return hmac.new(key, message.encode("ascii"), hashlib.sha256).hexdigest()


def build_relay_header_value(key: bytes, *, method: str, path: str, timestamp: int, ip: str) -> str:
    """ヘッダ値そのもの（``v1;<ts>;<ip>;<sig>``）を組み立てる（参照実装・テスト専用）。

    本番の署名生成は web 側（別セッションが管理するリポジトリ範囲）が行うため、
    backend の本番経路からこの関数が呼ばれることはない。単体テスト・HTTP
    統合テストがヘッダ値を機械的に組み立てるための参照実装として提供する。
    """
    ts_str = str(timestamp)
    signature = compute_relay_signature(key, method=method, path=path, timestamp=ts_str, ip=ip)
    return f"{RELAY_VERSION};{ts_str};{ip};{signature}"


def verify_client_ip_relay(
    *,
    header_values: Sequence[str],
    method: str,
    path: str,
    now_epoch_seconds: int,
    keys: tuple[bytes, ...],
) -> RelayVerification:
    """署名付き中継ヘッダを検証する（純関数。HTTP・``app.config`` を一切参照しない）。

    判定順序は固定する（デバッグ・テストの両面で「なぜこの reason になったか」
    を一意に説明できるようにするため。上から順に評価し、最初に該当した
    理由で確定して返す。これより後の判定は一切行わない）:

      1. ``header_values`` が空 → ``"absent"``
      2. ``keys`` が空 → ``"unconfigured"``
      3. ``header_values`` が複数件 → ``"malformed"``
      4. 長さ超過、または書式（``_HEADER_RE``）不一致 → ``"malformed"``
      5. version が ``RELAY_VERSION`` 以外 → ``"unsupported_version"``
      6. method / path の形式不正 → ``"malformed"``
      7. 署名不一致（全鍵を早期終了せず走査。タイミングサイドチャネル対策は
         モジュール docstring 参照）→ ``"bad_signature"``
      8. 時刻ずれが ``MAX_CLOCK_SKEW_SECONDS`` を超過（ちょうどは許容）
         → ``"expired"``
      9. IP がパース不能（``_strip_port`` 相当のポート除去は行わない。
         中継ヘッダの IP フィールドはポートを含まない契約のため）
         → ``"ip_unparseable"``
      10. IP がプライベート/ループバック/特殊用途 → ``"ip_not_public"``
      11. 上記いずれにも該当しない → ``"ok"``

    偽物の署名がたまたま期限切れのタイムスタンプを含んでいても
    ``"bad_signature"`` を返す（署名照合が時刻チェックより先にあるため。
    「偽造されたヘッダの中身」を信用して理由を決めることはない）。
    """
    if not header_values:
        return RelayVerification(None, "absent")
    if not keys:
        return RelayVerification(None, "unconfigured")
    if len(header_values) != 1:
        return RelayVerification(None, "malformed")

    value = header_values[0]
    if len(value) > _MAX_HEADER_VALUE_LENGTH:
        return RelayVerification(None, "malformed")

    match = _HEADER_RE.fullmatch(value)
    if match is None:
        return RelayVerification(None, "malformed")

    version, timestamp_raw, ip_raw, signature_hex = match.groups()
    if version != RELAY_VERSION:
        return RelayVerification(None, "unsupported_version")

    method_upper = method.upper()
    if _METHOD_RE.fullmatch(method_upper) is None or _PATH_RE.fullmatch(path) is None:
        return RelayVerification(None, "malformed")

    expected_message = canonical_relay_message(
        method=method_upper, path=path, timestamp=timestamp_raw, ip=ip_raw
    ).encode("ascii")

    matched_slot: int | None = None
    for slot, key in enumerate(keys):
        candidate_signature = hmac.new(key, expected_message, hashlib.sha256).hexdigest()
        # 早期終了しない: 一致後も残り全鍵の比較を続けることで、鍵の位置に
        # よって総処理時間が変わるタイミングサイドチャネルを避ける
        # （モジュール docstring 参照）。
        is_match = hmac.compare_digest(candidate_signature, signature_hex)
        if is_match and matched_slot is None:
            matched_slot = slot
    if matched_slot is None:
        return RelayVerification(None, "bad_signature")

    skew_seconds = now_epoch_seconds - int(timestamp_raw)
    if abs(skew_seconds) > MAX_CLOCK_SKEW_SECONDS:
        return RelayVerification(
            None, "expired", key_slot=matched_slot, skew_seconds=skew_seconds
        )

    try:
        parsed_ip = ipaddress.ip_address(ip_raw)
    except ValueError:
        return RelayVerification(
            None, "ip_unparseable", key_slot=matched_slot, skew_seconds=skew_seconds
        )

    normalized_ip = str(_unwrap_ipv4_mapped(parsed_ip))
    if is_private_or_loopback(normalized_ip) or is_special_use_address(normalized_ip):
        return RelayVerification(
            None,
            "ip_not_public",
            key_slot=matched_slot,
            skew_seconds=skew_seconds,
            rejected_ip_net=truncate_ip_for_log(normalized_ip),
        )

    return RelayVerification(
        normalized_ip, "ok", key_slot=matched_slot, skew_seconds=skew_seconds
    )


def verify_request_client_ip_relay(
    request: Request,
    keys: tuple[bytes, ...],
    *,
    clock: Callable[[], float] = time.time,
) -> RelayVerification:
    """FastAPI の ``Request`` から中継ヘッダを取り出し ``verify_client_ip_relay`` に委譲する。

    ``request.headers.getlist()`` を使う（``Headers.get()`` は同名ヘッダが
    複数存在する場合に先頭1件のみを返すため、"複数行=malformed" の判定を
    素通りさせてしまう。``app.core.client_ip.get_xff_raw`` の docstring で
    説明されている落とし穴と同種の理由）。
    """
    header_values = request.headers.getlist(RELAY_HEADER_NAME)
    return verify_client_ip_relay(
        header_values=header_values,
        method=request.method,
        path=request.url.path,
        now_epoch_seconds=int(clock()),
        keys=keys,
    )


# ──────────────────────────── ログ出力（プロセス内状態を持つ） ────────────────────────────
#
# ok の初回（プロセス起動後、scope ごとに1回）だけ WARNING で出す理由:
# 本番は app.* のロガーにレベルが明示設定されておらず、デフォルトの
# WARNING 以上しか実際には出力されない（2026-09-27 実測: 本番起動23回分の
# ログを確認したが、main.py の起動時 seed 処理が出す INFO ログが1件も
# 見つからなかった）。したがって本番反映後に「実際に署名付き中継IPが
# 採用されたか」を確かめる手段が INFO ログでは機能せず、初回だけ WARNING に
# 格上げすることが唯一の確実な確認手段になる。2回目以降は reason・scope
# ごとに独立した ThrottledLogger で INFO（採用時）/WARNING（不採用時）に
# 落ち着かせ、ログ量を抑える。
_relay_first_ok_logged_scopes: set[str] = set()
_relay_log_throttles: dict[tuple[str, str], ThrottledLogger] = {}


def _relay_throttle(reason: str, scope: str) -> ThrottledLogger:
    """``(reason, scope)`` ごとに独立した ``ThrottledLogger`` を遅延生成して返す。

    独立させる理由: 同一インスタンスを複数の reason/scope で共有すると
    互いのスロットリングに干渉する（``ThrottledLogger`` docstring 参照）。
    scope（login/line_exchange）を跨いで共有すると、片方の scope で直近
    発生した WARNING が、もう片方の scope の初回異常検知を隠してしまう。
    """
    key = (reason, scope)
    throttle = _relay_log_throttles.get(key)
    if throttle is None:
        throttle = ThrottledLogger()
        _relay_log_throttles[key] = throttle
    return throttle


def log_relay_outcome(scope: str, v: RelayVerification) -> None:
    """``verify_client_ip_relay`` / ``verify_request_client_ip_relay`` の判定結果をログへ記録する。

    **ヘッダ値・署名・鍵・生 IP は絶対に出さない。** ``ip_net`` は常に
    ``truncate_ip_for_log`` で /24（IPv4）・/48（IPv6）に丸めた値のみを使う。

    - ``"absent"``: 中継ヘッダを使わない大多数のリクエスト（web 経由以外の
      直接アクセス、または本機能の未反映段階）でログを埋め尽くさないため、
      何も出力しない。
    - ``"ok"``: 起動後 scope ごとの初回のみ WARNING（前述の理由）。以後は
      INFO をスロットリング（60秒に1回）。
    - ``"unconfigured"``: 中継ヘッダは来ているのに鍵が1本も無い、設定漏れの
      可能性が高い状態。スロットリング付き WARNING。
    - それ以外の不採用理由: スロットリング付き WARNING。理由別に安全な
      補足（生値を含まない）を付ける。
    """
    if v.reason == "absent":
        return

    if v.reason == "ok":
        ip_net = truncate_ip_for_log(v.ip) if v.ip else "-"
        key_slot = v.key_slot if v.key_slot is not None else -1
        if scope not in _relay_first_ok_logged_scopes:
            _relay_first_ok_logged_scopes.add(scope)
            logger.warning(
                "client_ip_relay: 起動後初めて署名付き中継の利用者IPを採用しました"
                "（scope=%s ip_net=%s key_slot=%d）。以後の採用は INFO で60秒に1回"
                "だけ記録します。",
                scope,
                ip_net,
                key_slot,
            )
            return
        _relay_throttle("ok", scope).emit(
            lambda: logger.info(
                "client_ip_relay: 署名付き中継の利用者IPで数えます"
                "（scope=%s ip_net=%s key_slot=%d）",
                scope,
                ip_net,
                key_slot,
            )
        )
        return

    if v.reason == "unconfigured":
        _relay_throttle("unconfigured", scope).emit(
            lambda: logger.warning(
                "client_ip_relay: 中継ヘッダを受け取りましたが backend に有効な鍵"
                "（CLIENT_IP_RELAY_SECRETS）がありません（scope=%s）。"
                "従来どおり hops で数えます。",
                scope,
            )
        )
        return

    # その他の不採用理由（malformed/unsupported_version/bad_signature/
    # expired/ip_unparseable/ip_not_public）。理由別に安全な補足を付ける。
    if v.reason == "bad_signature":
        suffix = "（鍵の食い違いか偽造の疑いがあります）"
    elif v.reason == "expired":
        suffix = f"（skew_sec={v.skew_seconds}）"
    elif v.reason == "ip_not_public":
        suffix = f"（ip_net={v.rejected_ip_net}）"
    else:  # "malformed" / "unsupported_version" / "ip_unparseable"
        suffix = "（値は記録しません）"

    reason = v.reason
    _relay_throttle(reason, scope).emit(
        lambda: logger.warning(
            "client_ip_relay: 中継ヘッダを採用しませんでした（reason=%s scope=%s）。"
            "従来どおり hops で数えます。%s",
            reason,
            scope,
            suffix,
        )
    )


def _reset_relay_log_state_for_tests() -> None:
    """テスト専用: プロセス内ログ状態（初回済み scope 集合・スロットラ辞書）を初期化する。"""
    _relay_first_ok_logged_scopes.clear()
    _relay_log_throttles.clear()
