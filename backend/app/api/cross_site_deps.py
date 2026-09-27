"""クロスサイト要求ゲート（第三者のページが訪問者のブラウザから送らせた要求に、
レート制限の枠を消費させないための共通依存）。

## 目的
IP 軸で全リクエストをカウントするレート制限スコープのうち、本文を持たない GET の
public_read（``GET /vendors``・``GET /vendors/{operator_id}``）は、JSON 必須ゲート
（``app.api.json_body_deps``）では守れない。ブラウザは第三者のページに埋め込まれた
``<img src>``・``<script src>``・``<iframe src>``・``fetch(url, {mode: "no-cors"})``、
あるいは CORS モードの単純な GET（プリフライト不要）を、クロスサイトでもそのまま
送る。``RateLimitGuard`` は応答より前に数えるため、第三者のページが訪問者のブラウザ
から1分に上限（既定 120 回）を超えて送らせるだけで、訪問者と同じ IP（オフィスの
NAT・携帯の CGNAT）の利用者は、そのページが開かれている間ずっと業者一覧・公開
プロフィールで 429 になる。

このゲートは、ブラウザが付けるヘッダ（``Origin``・``Sec-Fetch-Site``。どちらも
ページのスクリプトからは書き換えられない）から「ブラウザが他のサイトの代わりに
送った要求」を見分け、``RateLimitGuard`` が数える前に 403 で止める。

## 判定（上から順に評価。``_rejection_reason`` が正本）
1. ``Origin``・``Sec-Fetch-Site`` のどちらかが複数行ある → 拒否（ブラウザは1行しか
   送らない。先頭だけを読むと、どの値で判定したかが曖昧になる）。
2. ``Sec-Fetch-Site: same-origin`` → 通す（backend 自身のページ。例: /docs）。
3. ``Origin`` がある → 許可オリジン（CORS と同じ ``settings.allowed_origins`` との
   完全一致）なら通し、それ以外（``null`` を含む）は拒否。ブラウザは CORS モードの
   クロスオリジン要求（fetch の既定・XHR）と、GET・HEAD 以外の要求に Origin を付け、
   第三者のページはその値を選べない。正規の web（本番は https://sokuri.vercel.app →
   sokuri-backend.onrender.com のクロスサイト fetch）はここで通る。
4. ``Origin`` も ``Sec-Fetch-Site`` も無い → 通す（SSR・スクリプト・監視・テストの
   HTTP クライアント、および Fetch Metadata 非対応の旧ブラウザ。下記「残るリスク」）。
5. ``Origin`` が無く ``Sec-Fetch-Site: none`` → 通す（アドレスバーへの直接入力・
   ブックマーク等、利用者自身の操作。ページからは発生させられない）。
6. それ以外（``Origin`` が無く、``Sec-Fetch-Site`` が cross-site・same-site・未知の値）
   → 拒否。no-cors の GET（img・script・style・fetch の no-cors 等）とナビゲーション
   （iframe・window.open・リンク・GET のフォーム送信）は Origin を付けないので、
   ここで止まる。

``Sec-Fetch-Mode`` は判定に使わない（ログの分類にだけ使う）。クロスオリジンの cors
モードの要求には必ず Origin が付くので 3 で決まり、Origin の無いクロスサイト要求は
モードによらず（no-cors でもナビゲーションでも）6 で止まるため、モードを見ても
判定は変わらない。クロスサイトのナビゲーションも拒否する（Fetch Metadata の一般的な
方針はトップレベルのナビゲーションを通すが、対象は JSON の API で、リンクから開く
正規の用途が無い一方、第三者のページは iframe を作り直すだけでナビゲーションを
何度でも送れる）。same-site も cross-site と同じく拒否する（本番の onrender.com・
vercel.app は Public Suffix List に載っているため、他人のサービスが same-site に
なることは無いが、ローカル開発の localhost 同士のように same-site になる構成でも、
Origin の無い要求を通す理由が無い）。

## 残るリスク（Fetch Metadata 非対応ブラウザ）
Safari 16.3 以前（iOS 16.3 以前の全ブラウザを含む）・Chrome 75 以前・Firefox 89 以前は
``Sec-Fetch-Site`` を送らない（MDN の互換性データで確認、2026-09-27）。これらの
no-cors の GET とナビゲーションには Origin も付かないため、4 で SSR・スクリプトと
区別できずに通り、第三者のページはその訪問者の IP の枠を引き続き使い切れる。
正規の web は Origin 付きの CORS 要求なので影響を受けない。User-Agent で旧ブラウザを
見分けて止める案は、ブラウザ風の User-Agent を名乗る監視・ツールを巻き添えにするため
採らない（2026-09-27 判断）。

## 経緯
2026-09-27 のセキュリティレビューで判明。JSON 必須ゲートの共通化（b529e4c）の際に、
本文の無い GET の public_read は対象外として残っていた。

## 許可オリジンの正本
``get_settings().allowed_origins``。``app.main.create_app`` が ``CORSMiddleware`` の
``allow_origins`` に渡すのと同じ値（``*`` を含む値と ``null`` は設定の段階で除外
される）なので、CORS で読める正規のオリジンは必ずこのゲートも通る。web を新しい
ドメインへ移すときは、Render の ``ALLOWED_ORIGINS``（render.yaml の envVars は既存
サービスへ同期されないため dashboard で設定する）に足せば両方に効く。
``CORSMiddleware`` に ``allow_origin_regex`` 等の別の許可経路を足す場合は、このゲートも
同じ判定に揃えること（``backend/tests/test_cross_site_guard.py`` が、CORS の許可
リストとこのゲートの正本の一致を検査する）。

## 置き方の規約（必須・CI で機械検査される）
``_no_cross_site: None = Depends(reject_cross_site_browser_request)`` は、全件カウント
方式の ``_rl: object = Depends(RateLimitGuard(...))`` より**前**に宣言すること（JSON
必須ゲートと同じく、慣例として直前に置く）。引数は ``Request`` だけに保つこと
（ヘッダ等の引数を足すと、その検証に失敗した要求では FastAPI がゲートを呼ばずに
後続のガードへ進み、数えてから 422 を返す。``app.api.json_body_deps`` の同じ節を参照）。

``backend/tests/test_cross_site_guard.py`` の構造検査が、``app.main.create_app()`` の
全ルートのうち、IP 軸で全件カウントするスコープのガードを持つ GET・HEAD 専用の
ルートについて、この規約を CI で強制する。本文を持つ POST は JSON 必須ゲートの
構造検査（``backend/tests/test_json_body_guard.py``）の対象で、application/json の
クロスオリジン POST は CORS のプリフライト（許可オリジン以外は拒否）を経ないと
送れないため、このゲートは付けない（Fetch Metadata に依存しないぶん、旧ブラウザも
含めて JSON 必須ゲートの方が強い）。

## 運用上の注意
- 緊急停止スイッチ（``RATE_LIMIT_ENABLED=false``）はレート制限だけを止め、この
  ゲートは止めない（JSON 必須ゲートと同じ）。ゲートを外すにはコードの変更が要る。
- 拒否は理由ごとに 60 秒スロットリングの WARNING を出す。出すのはルートの
  テンプレート・理由・Fetch Metadata の既知の値だけで、Origin は形式が正しい
  オリジン（scheme://host[:port]）のときだけそのまま出す（正規の web の Origin が
  拒否されていれば、それが ``ALLOWED_ORIGINS`` の設定漏れだと特定できるように
  するため）。それ以外の値は ``invalid`` に丸める。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection

from fastapi import Request, status

# ルートのテンプレートをログに使う判断（実際のパスには ID が入る）は JSON 必須
# ゲートと同一にするため、同じ実装を使う。
from app.api.json_body_deps import _route_path_for_log
from app.config import get_settings
from app.core.http_errors import http_exception_factory
from app.core.log_throttle import ThrottledLogger

logger = logging.getLogger(__name__)

_FORBIDDEN_CROSS_SITE = http_exception_factory(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="他のサイトから送られたリクエストは受け付けていません。",
)

#: 拒否理由（ログの分類ラベル。``_rejection_reason`` の戻り値）。
REASON_DUPLICATE_HEADER = "duplicate_header"
REASON_ORIGIN_NOT_ALLOWED = "origin_not_allowed"
REASON_CROSS_SITE_WITHOUT_ORIGIN = "cross_site_without_origin"

#: Origin が無くても通す ``Sec-Fetch-Site`` の値（判定の 2・5）。
_SITES_ALLOWED_WITHOUT_ORIGIN = frozenset({"same-origin", "none"})

# 拒否理由ごとに独立したスロットリング（1つを共有すると、継続中の攻撃
# （cross_site_without_origin）のログが ALLOWED_ORIGINS の設定漏れ
# （origin_not_allowed）のログを抑え込み、後者を見落とすため）。
# 「プロセス内1回きり」にしない理由は json_body_deps と同じ。
_duplicate_header_reject_throttle = ThrottledLogger()
_origin_reject_throttle = ThrottledLogger()
_cross_site_reject_throttle = ThrottledLogger()

#: ログにそのまま出してよい Fetch Metadata の値（仕様・主要ブラウザが送る値）。
#: それ以外は "other"、ヘッダ自体が無ければ "absent" に丸める。
_KNOWN_SEC_FETCH_SITE = frozenset({"cross-site", "same-site", "same-origin", "none"})
_KNOWN_SEC_FETCH_MODE = frozenset(
    {"cors", "navigate", "nested-navigate", "no-cors", "same-origin", "websocket"}
)
_KNOWN_SEC_FETCH_DEST = frozenset(
    {
        "audio", "audioworklet", "document", "embed", "empty", "fencedframe", "font",
        "frame", "iframe", "image", "json", "manifest", "object", "paintworklet",
        "report", "script", "serviceworker", "sharedworker", "style", "track", "video",
        "webidentity", "worker", "xslt",
    }
)

# ログに出してよいオリジンの形（ブラウザがシリアライズする scheme://host[:port]。
# ホストは小文字の DNS ラベルか角括弧の IPv6）。照合前に長さで打ち切るので、
# 正規表現の走査量は入力の長さに比例する範囲に収まる。
_ORIGIN_FOR_LOG_PATTERN = re.compile(
    r"https?://(?:[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})*|\[[0-9a-f:.]{2,45}\])(?::[0-9]{1,5})?"
)
_ORIGIN_FOR_LOG_MAX_LENGTH = 300


def _rejection_reason(
    origins: list[str], sites: list[str], allowed_origins: Collection[str]
) -> str | None:
    """拒否理由を返す（通すなら ``None``）。判定の順序はモジュール docstring の 1〜6。

    Args:
        origins: ``Origin`` ヘッダの全行の値（``request.headers.getlist("origin")``）。
        sites: ``Sec-Fetch-Site`` ヘッダの全行の値。
        allowed_origins: 許可オリジン（CORS と同じ正本。完全一致で照合する）。
    """
    if len(origins) > 1 or len(sites) > 1:
        return REASON_DUPLICATE_HEADER
    site = sites[0] if sites else None
    if site == "same-origin":
        return None
    if origins:
        origin = origins[0]
        # null は設定の段階で許可リストから除外されている（config._is_dangerous_origin_token）
        # が、設定の読み方が変わっても通さないよう、ここでも明示的に拒否する。
        if origin.lower() != "null" and origin in allowed_origins:
            return None
        return REASON_ORIGIN_NOT_ALLOWED
    if site is None or site in _SITES_ALLOWED_WITHOUT_ORIGIN:
        return None
    return REASON_CROSS_SITE_WITHOUT_ORIGIN


def _token_label(values: list[str], known: frozenset[str]) -> str:
    """ログに出す Fetch Metadata の分類ラベル（先頭の値。生の未知の値は出さない）。"""
    if not values:
        return "absent"
    return values[0] if values[0] in known else "other"


def _origin_label(origins: list[str]) -> str:
    """ログに出す Origin（形式が正しいオリジンと ``null`` だけそのまま、他は ``invalid``）。

    正規の web の Origin が拒否されていることが ``ALLOWED_ORIGINS`` の設定漏れを
    特定する最短の手がかりになるため、オリジンの形をしている値は出す。形の違う値
    （ブラウザ以外が送った任意の文字列）は素性を残さない。
    """
    if not origins:
        return "absent"
    origin = origins[0]
    if origin == "null":
        return "null"
    if len(origin) <= _ORIGIN_FOR_LOG_MAX_LENGTH and _ORIGIN_FOR_LOG_PATTERN.fullmatch(origin):
        return origin
    return "invalid"


def _warn_rejected(request: Request, reason: str) -> None:
    headers = request.headers
    path = _route_path_for_log(request)
    site_label = _token_label(headers.getlist("sec-fetch-site"), _KNOWN_SEC_FETCH_SITE)
    if reason == REASON_DUPLICATE_HEADER:
        _duplicate_header_reject_throttle.emit(
            lambda: logger.warning(
                "cross_site: Origin または Sec-Fetch-Site が複数行あるため 403 で拒否しました"
                "（path=%s origin_lines=%d sec_fetch_site_lines=%d）。ブラウザは1行しか"
                "送らないため、ブラウザ以外の送信元の可能性があります。",
                path,
                len(headers.getlist("origin")),
                len(headers.getlist("sec-fetch-site")),
            )
        )
        return
    if reason == REASON_ORIGIN_NOT_ALLOWED:
        _origin_reject_throttle.emit(
            lambda: logger.warning(
                "cross_site: 許可オリジン以外の Origin を 403 で拒否しました（path=%s "
                "origin=%s sec_fetch_site=%s）。第三者のページから送らせた要求か、正規の web の"
                "オリジンが ALLOWED_ORIGINS に入っていない可能性があります。",
                path,
                _origin_label(headers.getlist("origin")),
                site_label,
            )
        )
        return
    _cross_site_reject_throttle.emit(
        lambda: logger.warning(
            "cross_site: 他のサイトからの Origin の無い要求を 403 で拒否しました（path=%s "
            "sec_fetch_site=%s sec_fetch_mode=%s sec_fetch_dest=%s）。第三者のページに埋め込まれた"
            "画像・スクリプト・iframe 等から送らせた要求の可能性があります。",
            path,
            site_label,
            _token_label(headers.getlist("sec-fetch-mode"), _KNOWN_SEC_FETCH_MODE),
            _token_label(headers.getlist("sec-fetch-dest"), _KNOWN_SEC_FETCH_DEST),
        )
    )


async def reject_cross_site_browser_request(request: Request) -> None:
    """ブラウザが他のサイトの代わりに送った要求を、数える前に 403 で止める。

    判定はモジュール docstring の 1〜6（``_rejection_reason``）。I/O を持たないため
    ``async def`` にしている（同期関数の依存は FastAPI がスレッドプールで実行する）。

    全リクエストを数えるガード（``RateLimitGuard``）より前に置き、引数は ``Request``
    だけに保つこと（配置の規約はモジュール docstring 参照）。
    """
    reason = _rejection_reason(
        request.headers.getlist("origin"),
        request.headers.getlist("sec-fetch-site"),
        get_settings().allowed_origins,
    )
    if reason is None:
        return
    _warn_rejected(request, reason)
    raise _FORBIDDEN_CROSS_SITE()
