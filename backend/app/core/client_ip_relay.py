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
``PATH`` は ``request.scope["path"]``（クエリを含まない・ルーティングが実際に
使う値そのもの）。**``request.url.path`` は使わない（security review I-1）**:
``request.url`` は Host ヘッダから URL 文字列を組み立て直してから再パースした
結果であり、署名照合という完全性を要する処理にルーティングと無関係な文字列
往復を持ち込みたくないため（詳細は ``verify_request_client_ip_relay``
docstring）。IP はヘッダの生文字列の
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

**既知の割り切り（v1）: 再送（リプレイ）耐性を持たない。** 有効なヘッダ値を
盗聴・記録できた第三者は、時刻ずれが ``MAX_CLOCK_SKEW_SECONDS`` 以内であれば
同じヘッダ値をそのまま再送するだけで同じ利用者IPとしてカウントさせられる
（ノンスやリクエスト本文のハッシュを署名対象に含めていないため。
``tests/test_client_ip_relay_api.py`` の該当テストに固定化してある）。この
ヘッダは HTTPS（TLS）区間内でのみ送受信され、web 側・backend 側とも生の
ヘッダ値をログや APM に記録しない前提で設計しているため、実務上の悪用可能性は
小さいと判断した上での意図的な割り切りである。将来 APM 等でリクエストヘッダを
記録する仕組みを導入する場合は、v2 でノンスまたはリクエスト本文ハッシュを
署名対象に加えて1回限りの使用を強制する必要がある（運用手順は
``docs/ops/admin-operations.md`` の「署名付き中継IPの鍵」節も参照）。
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
    is_cloudflare_range,
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
# request.scope["path"] が取りうる形式（クエリを含まない絶対パス）。
_PATH_RE = re.compile(r"/[A-Za-z0-9/_.\-]{0,255}")
# 大文字化後の HTTP メソッド名。
_METHOD_RE = re.compile(r"[A-Z]{1,16}")

# ──────────────── 既知のテスト鍵・弱い鍵の拒否（security review L-2） ────────────────
# 公開済みのテストベクトル鍵（本ファイル・tests/test_client_ip_relay.py の
# TestKnownVectors が使う固定値そのもの）が本番の CLIENT_IP_RELAY_SECRETS に
# 誤って設定されると、署名が誰でも計算可能になり本機能が無意味になる。
# 完全一致で拒否する。
_REJECTED_EXACT_KEYS: frozenset[str] = frozenset(
    {
        "katazuke-relay-test-vector-A-0123456789abcdefghijklmnopqrstuvwxyz",
        "katazuke-relay-test-vector-B-0123456789abcdefghijklmnopqrstuvwxyz",
    }
)
# 上記以外にも、テスト用の命名規則で作られた鍵を丸ごと弾く接頭辞（比較前に
# ``str.lower()`` するため大文字小文字は区別しない）。新しいテストベクトルを
# 増やしても個別に ``_REJECTED_EXACT_KEYS`` へ追記する手間を減らす。
_REJECTED_PREFIXES: tuple[str, ...] = ("katazuke-relay-test-", "http-relay-test-key-")
# 鍵に含まれる文字の種類数（distinct count）の最小値。"a" * 32 のような
# 人為的に偏った値は、正規のランダム生成（``secrets.token_urlsafe(48)`` は
# 実測で最低29種類の文字を含む）とは明確に区別できる一方、16進数表記の鍵
# （0-9a-f の16種類）はごく低確率（32文字中の異なり数が9以下になる確率は
# 概算で約1/9000）で偶然この下限を割り込みうるため、拒否時のログで
# 推奨の生成コマンドを案内する。
_MIN_DISTINCT_CHARS = 10


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


class RelaySecretsInspection(NamedTuple):
    """``inspect_relay_secrets`` の返り値。

    - ``keys``: 有効な鍵（順序保持・重複除去・``MAX_KEYS`` 以内）。
    - ``rejected_count``: 除外された候補の本数（短すぎる・非ASCII・空白混入・
      既知のテスト鍵/弱い鍵パターンとの一致、のいずれか）。**``MAX_KEYS``
      超過による切り捨ては含まない**（切り捨てられた鍵それ自体は無効では
      なく、正当なローテーション運用（一時的に5本以上を並べる等）を「不正な
      鍵が混じっている」という劣化判定に混同させないため）。重複も含まない
      （同じ有効な鍵を2回書いても「不正」ではない）。
    """

    keys: tuple[bytes, ...]
    rejected_count: int


def _relay_secret_rejection_reason(token: str) -> str | None:
    """``token`` を ``CLIENT_IP_RELAY_SECRETS`` の1本として使えない理由
    （ログ用の短い日本語。値・長さは一切含まない）を返す。使える場合は
    ``None``。

    判定順序（先に該当したものを理由として確定する。全て満たして初めて
    ``None``）:
      1. 基本要件（``MIN_SECRET_LENGTH`` 文字以上・ASCII印字可能・空白なし）。
      2. 公開済みのテストベクトル鍵との完全一致（``_REJECTED_EXACT_KEYS``）。
      3. 既知のテスト鍵の接頭辞との一致（``_REJECTED_PREFIXES``。大文字小文字
         を区別しない）。
      4. 使用文字の種類数が ``_MIN_DISTINCT_CHARS`` 未満（人為的に偏った値。
         security review L-2）。
    """
    if (
        len(token) < MIN_SECRET_LENGTH
        or not token.isascii()
        or not token.isprintable()
        or any(ch.isspace() for ch in token)
    ):
        return (
            f"要件（{MIN_SECRET_LENGTH}文字以上・ASCII印字可能文字のみ・"
            "空白を含まない）を満たさない"
        )
    if token in _REJECTED_EXACT_KEYS:
        return "公開済みのテストベクトル鍵と一致する"
    if token.lower().startswith(_REJECTED_PREFIXES):
        return "既知のテスト鍵の命名パターン（接頭辞）と一致する"
    if len(set(token)) < _MIN_DISTINCT_CHARS:
        return (
            f"使用している文字の種類が{_MIN_DISTINCT_CHARS}種類未満で偏っている"
            '（`python -c "import secrets; print(secrets.token_urlsafe(48))"` 等'
            "で生成した値を推奨します）"
        )
    return None


@lru_cache(maxsize=8)
def inspect_relay_secrets(raw: str) -> RelaySecretsInspection:
    """``CLIENT_IP_RELAY_SECRETS``（カンマ区切り・先頭が新しい鍵）を解析する。

    各候補は次の全てを満たさなければ無効として除外し、``logger.error`` で
    「何番目の候補か・除外理由」のみを記録する（**値そのものも長さも
    ログに残さない**。鍵はログ経由で漏洩させてはならない秘密情報のため）:

      - ``MIN_SECRET_LENGTH`` 文字以上。
      - ``str.isascii()``（非ASCII文字を含まない）。
      - ``str.isprintable()``（制御文字を含まない）。
      - 空白文字を含まない（``isprintable()`` は半角スペース単体を通して
        しまうため、別途明示的にチェックする）。
      - 公開済みのテストベクトル鍵・既知のテスト鍵の接頭辞のいずれとも
        一致しない（security review L-2。誤って本番に投入される事故を防ぐ。
        判定の詳細は ``_relay_secret_rejection_reason`` 参照）。
      - 使用文字の種類が ``_MIN_DISTINCT_CHARS`` 種類以上（同上）。

    有効な候補のみを対象に、順序を保ったまま重複を除去し、``MAX_KEYS`` を
    超える分は末尾を切り捨てて ``logger.error`` を出す（無効な候補の重複は
    対象外＝無効な候補は毎回独立に除外・ログされる。切り捨ても
    ``rejected_count`` には含めない。理由は ``RelaySecretsInspection``
    docstring 参照）。

    ``raw`` を分割・空要素除去した時点で候補が1つも無い場合（空文字列・
    空白のみ・カンマのみ）は「そもそも設定されていない」通常運用として
    扱い、エラーは出さない（``rejected_count`` も 0）。候補は存在したが
    有効な鍵が1本も残らなかった場合のみ、「署名付き中継を無効化する
    （従来どおり hops で数える）」旨の ``logger.error`` を出す（設定ミスに
    気付けるようにするため）。

    **起動を止めない**: この関数はどのような ``raw`` を渡されても例外を
    送出せず、常に ``RelaySecretsInspection``（鍵が無い場合は ``keys=()``）を
    返す。中継は「無くても今どおり動く」上書き機能であるため、鍵の設定ミス
    1つで認証系 API 全体の起動を失敗させることは避ける。

    ``@lru_cache`` によりプロセス内で ``raw`` の値ごとに1度だけ解析する
    （``settings.client_ip_relay_secrets`` は毎リクエスト同じ文字列を返すため、
    HMAC 鍵オブジェクトの再構築コストを避けられる）。テストで
    ``monkeypatch`` により新しい値を注入した場合は、その新しい文字列が
    そのままキャッシュキーになるため、明示的な ``cache_clear()`` は不要
    （値が変われば別エントリとして扱われる。同じ ``raw`` をテスト間で使い回す
    場合のみ明示的な ``cache_clear()`` が必要）。

    ログ出力・不正鍵の検知をこの関数に一本化しているのは、``/readyz`` が
    「鍵は設定されているが不正な鍵が混じっている」ことを ``rejected_count``
    経由で検知できるようにするため（security review L-4。``app.main.
    _config_readiness`` 参照）。``parse_relay_secrets`` は鍵の中身だけを
    必要とする既存の呼び出し側向けの薄いラッパーとして残す。
    """
    tokens = [token.strip() for token in raw.split(",")]
    tokens = [token for token in tokens if token]
    if not tokens:
        # 空・空白のみ・カンマのみ。「未設定」と同じ通常運用のため無音。
        return RelaySecretsInspection(keys=(), rejected_count=0)

    valid_ordered: list[str] = []
    seen: set[str] = set()
    rejected_count = 0
    for position, token in enumerate(tokens, start=1):
        reason = _relay_secret_rejection_reason(token)
        if reason is not None:
            rejected_count += 1
            logger.error(
                "client_ip_relay: CLIENT_IP_RELAY_SECRETS の%d番目の鍵が%sため"
                "除外します（値・長さは記録しません）。",
                position,
                reason,
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

    return RelaySecretsInspection(
        keys=tuple(token.encode("ascii") for token in valid_ordered),
        rejected_count=rejected_count,
    )


@lru_cache(maxsize=8)
def parse_relay_secrets(raw: str) -> tuple[bytes, ...]:
    """``inspect_relay_secrets(raw).keys`` を返す薄いラッパー。

    既存の呼び出し側（``rate_limit_deps._relayed_client_ip`` 等）は鍵の中身
    だけを必要とするため、シグネチャ・戻り値の型を変えない。ログ出力・
    不正鍵の検知（``rejected_count``）は ``inspect_relay_secrets`` に一本化
    した（理由は同関数の docstring 参照）。自身も ``@lru_cache`` を持つが、
    ``inspect_relay_secrets`` 側のキャッシュがヒットしていればここでの
    キャッシュミスは属性アクセス1回分のコストに過ぎない。
    """
    return inspect_relay_secrets(raw).keys


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

    **``path`` は ``request.url.path`` ではなく ``request.scope.get("path", "")``
    を使う（security review I-1）**: ``starlette.datastructures.URL`` は
    ``scope["path"]`` と Host ヘッダから ``f"{scheme}://{host}{path}"`` という
    文字列を組み立て、それを ``urlsplit()`` で再パースした結果から ``.path``
    を取り出す実装になっている。現行の Starlette は Host ヘッダの文字種を
    正規表現で検証してこの手の食い違いを塞いでいるが、ルーティング自体は
    ``scope["path"]`` を直接見て一致判定するため、署名照合もそれと完全に
    同じ値を使うべきである（Host ヘッダの検証・URL 文字列の組み立てという
    ルーティングと無関係な依存を、完全性が要求される署名対象に持ち込まない
    ようにする防御的な設計判断。将来 Starlette 側の実装が変わっても影響を
    受けない）。``request.scope`` は ``Mapping`` であり ``"path"`` キーは
    ASGI 仕様上 HTTP スコープに必須のため通常は欠落しないが、念のため
    ``.get("path", "")`` とし、欠落時は空文字列（＝``_PATH_RE`` に一致せず
    ``"malformed"`` になる）にフォールバックする。
    """
    header_values = request.headers.getlist(RELAY_HEADER_NAME)
    return verify_client_ip_relay(
        header_values=header_values,
        method=request.method,
        path=request.scope.get("path", ""),
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
      INFO をスロットリング（60秒に1回）。**加えて、採用した中継IPが
      Cloudflare の公開レンジ内だった場合は、判定は変えず（採用・カウントは
      継続）scope ごとにスロットリング付き WARNING を別途出す**
      （security review M-2。Vercel の前段に Cloudflare 等のプロキシが
      挟まり、web 側が受け取る「実クライアントIP」が実は利用者ではなく
      そのプロキシの IP になっている疑いを検知するため。
      ``app.core.client_ip.is_cloudflare_range`` は判定に使ってはならない
      値だが、``RateLimitGuard`` の hops 方式側の同種の WARNING
      （``rate_limit_deps._warn_cf_range_at_trust_position``）と同じ
      トレードオフでカウントは継続する）。
    - ``"unconfigured"``: 中継ヘッダは来ているのに鍵が1本も無い、設定漏れの
      可能性が高い状態。スロットリング付き WARNING。
    - それ以外の不採用理由: スロットリング付き WARNING。理由別に安全な
      補足（生値を含まない）を付ける。
    """
    if v.reason == "absent":
        return

    if v.reason == "ok":
        ip_net = truncate_ip_for_log(v.ip) if v.ip else "-"
        # reason=="ok" は必ず署名照合（matched_slot の確定）を経由しているため
        # key_slot は理論上常に非 None のはず。-1 はここに到達しないはずの
        # 防御的なフォールバック値（型が ``int | None`` である以上、静的な
        # None チェックを省略しないための保険であり、実際に -1 が出力された
        # 場合はそれ自体が verify_client_ip_relay 側のバグを示す）。
        key_slot = v.key_slot if v.key_slot is not None else -1
        if v.ip is not None and is_cloudflare_range(v.ip):
            _relay_throttle("ok_cloudflare_range", scope).emit(
                lambda: logger.warning(
                    "client_ip_relay: 中継IPが Cloudflare の公開レンジです"
                    "（scope=%s ip_net=%s）。Vercel の前段に Cloudflare 等の"
                    "プロキシが入り x-real-ip がプロキシの IP になっている"
                    "疑いがあります（利用者が WARP 等を使っている場合にも"
                    "出ます）。カウントは継続します。",
                    scope,
                    ip_net,
                )
            )
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
