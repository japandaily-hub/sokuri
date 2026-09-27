"""JSON 必須ゲート（第三者ページ発のクロスオリジン POST にレート制限の枠を
消費させないための共通依存）。

## 目的
IP 軸で全リクエストをカウントするレート制限スコープ
（``app.api.rate_limit_deps._scope_spec`` で ``ip_rule is not None and
count_all=True`` になっているスコープ。例: signup / line_exchange /
case_create / analyze / contact / operator_application）は、``RateLimitGuard``
が本文の検証（422）より前に IP 軸を消費する。ブラウザは CORS のプリフライト
（許可オリジンの完全一致リスト以外は拒否）を経由しない「単純なリクエスト」として、
``text/plain``・``application/x-www-form-urlencoded``・``multipart/form-data``・
Content-Type なしの POST をクロスオリジンで送れる（CSP の違反報告
（``application/csp-report``）や Reporting API（``application/reports+json``）の
ような、ブラウザ自身が送る本文も含む）。これを素通しすると、最終的には本文の
検証で 422 になるだけとはいえ、``RateLimitGuard`` がその手前で数えてしまうため、
第三者のページに埋め込んだ ``<form>`` や ``fetch(..., {mode: "no-cors"})`` だけで
訪問者のブラウザから訪問者自身の IP の枠を勝手に使い切らせられる。case_create /
analyze は認証必須で、第三者のページは訪問者の Bearer トークンを付けられず
認証依存が先に 401 を返すため、現状この経路では数えられない。認証方式や依存の
順序が将来変わった場合に備えた多層防御として、同じゲートを付ける（配置の規約は
後述）。本文を持たない GET の public_read（業者一覧・公開プロフィール）はそもそも
検査対象の本文が無いため、このゲートでは守れない。こちらはクロスサイト要求ゲート
（``app.api.cross_site_deps``）が、ブラウザの付ける Origin・Sec-Fetch-Site を見て
数える前に止める。

## 経緯
2026-09-27、業者事前申込（``app/api/v1/endpoints/operator_applications.py``、
コミット 4cb6b9a）で最初にこの対策を ``_require_json_body`` としてその場限りで
実装した。同じ弱点は IP 軸を全件カウントする他のスコープ全てに共通するため、
本モジュールへ切り出して共通化し、該当する全エンドポイントへ付け直す。

## なぜ application/json ちょうどだけを許可するか
正規の呼び出し元（web の ``request()``・NextAuth の ``auth.ts``・
``line-link.ts``・E2E の Playwright（data オブジェクト）・scripts の ``httpx``
の ``json=``）はすべて ``application/json`` を送ることを確認済み
（2026-09-27）のため、これ以外を拒否しても正規のトラフィックへの影響は無い。
ブラウザは CORS の
プリフライト無しには任意オリジンへ ``application/json`` の本文を送れないため、
ここを ``application/json`` ちょうどに絞ることがそのまま「第三者ページ発の
リクエストを閉め出す」ことに直結する。FastAPI が JSON として読む
``application/*+json``（例: Reporting API の ``application/reports+json``）
までは広げない。

## なぜ Content-Type なしも拒否するか
現在入っている FastAPI 0.136 系は既定の ``strict_content_type`` により、
Content-Type なしの本文を JSON として読まない。読まれない本文は ``bytes``
のまま依存解決に進み、``RateLimitGuard`` が数えてから 422 になる
（text/plain 等と同じく枠を消費する）。さらに
``pyproject.toml`` は ``fastapi>=0.115`` と幅を持たせており版を固定していない
ため、Content-Type なしの本文を JSON として読む版が入ると、422 にすら
ならず訪問者の IP で登録・申込そのものを作らせることもできる。

## 置き方の規約（必須・CI で機械検査される）
``_json_only: None = Depends(require_json_body)`` は、全件カウント方式の
``_rl: object = Depends(RateLimitGuard(...))`` より**前**に宣言すること（慣例と
して直前に置く。間に別の依存を挟んでも、JSON 以外の本文はこのゲートがそれより
先に止めるので数えられない）。認証が必要なエンドポイント（``POST /cases``・
``POST /analyze``）では認証依存（``get_current_user`` 等）の**後**に置く。依存は
宣言順に解決されるため、これにより「未認証の要求は従来どおり 401 が先に返り、
このゲートにもガードにも到達しない（数えない）」という既存の挙動を変えずに済む。

``require_json_body`` の引数は ``Request`` だけに保つこと。ヘッダ・クエリ等の引数を
足すと、その検証に失敗した要求では FastAPI がゲートを呼ばずに後続の依存（ガード）
へ進み、数えてから 422 を返す（``fastapi.dependencies.utils.solve_dependencies`` は
検証エラーの依存を飛ばして次へ進む）。

この配置規約（ゲートがガードより前・認証依存がガードより前・本文がフォームでも
空でもない・ゲートが引数を持たない）は ``backend/tests/test_json_body_guard.py`` の
構造検査（``app.main.create_app()`` の全ルートを対象に、依存の実行順を静的に検証
する）が CI で強制する。新しく全件カウント方式の IP 軸スコープを追加する際、この
ゲートの付け忘れは同テストが検知する。

## 運用上の注意
緊急停止スイッチ（``RATE_LIMIT_ENABLED=false``）はレート制限だけを止め、この
ゲートは止めない（JSON 以外の本文には 415 を返し続ける）。ゲートを外すにはコードの
変更が要る。
"""

from __future__ import annotations

import logging

from fastapi import Request, status

from app.core.http_errors import http_exception_factory
from app.core.log_throttle import ThrottledLogger

logger = logging.getLogger(__name__)

# 「プロセス内1回きり」の抑制は攻撃者が起動直後に1回不正な Content-Type を送る
# だけで永久に消費でき、以後の本物の異常（第三者ページからの継続的な悪用や
# クライアントの不具合）が二度と検知できなくなるため、他の抑制ログ
# （app.api.rate_limit_deps 参照）と同じく 60 秒スロットリングに統一する。
_non_json_body_reject_throttle = ThrottledLogger()

_UNSUPPORTED_MEDIA_TYPE = http_exception_factory(
    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    detail="リクエストの形式が正しくありません。",
)

#: ログに分類ラベルとしてそのまま出してよい Content-Type（第三者ページ・ブラウザが
#: プリフライト無しで送れる代表的な値のみ）。それ以外は "other" に丸める。
_KNOWN_REJECTED_MEDIA_TYPE_LABELS = frozenset(
    {"text/plain", "application/x-www-form-urlencoded", "multipart/form-data"}
)


def _media_type_label(media_type: str) -> str:
    """WARNING ログに出す Content-Type の分類ラベルを返す（生のヘッダ値は出さない）。

    引数は ``require_json_body`` が判定に使うのと同じ正規化済み値
    （charset 等のパラメータを落とし、前後空白除去・小文字化済み）を受け取る。
    空文字なら ``"none"``、既知の3種（プリフライト無しでブラウザから送れる
    代表的な値: text/plain・application/x-www-form-urlencoded・
    multipart/form-data）ならその値そのもの、それ以外は一律 ``"other"`` に丸める。
    生のヘッダ値をそのままログに出すと、攻撃者が細工した値（内部識別子や
    ペイロードを埋め込んだ Content-Type 等）がログに残ってしまうため、既知の
    値以外は素性を残さない。
    """
    if not media_type:
        return "none"
    if media_type in _KNOWN_REJECTED_MEDIA_TYPE_LABELS:
        return media_type
    return "other"


def _route_path_for_log(request: Request) -> str:
    """ログに出すパス。照合したルートのテンプレート（例: ``/api/v1/cases/{case_id}``）を
    優先する（実際のパスには ID 等が入りうるため）。ルート照合前の要求（単体テスト等）
    では実際のパスを使う。"""
    route_path = getattr(request.scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) else request.url.path


def _warn_rejected(path: str, media_type: str) -> None:
    _non_json_body_reject_throttle.emit(
        lambda: logger.warning(
            "json_body: JSON 以外の本文を 415 で拒否しました（path=%s "
            "content_type=%s）。第三者のページから送らせた要求か、クライアントの"
            "不具合の可能性があります。",
            path,
            _media_type_label(media_type),
        )
    )


async def require_json_body(request: Request) -> None:
    """本文が JSON（Content-Type: application/json）の要求だけを通す。それ以外は 415。

    I/O を持たないため ``async def`` にしている（同期関数の依存は FastAPI が
    スレッドプールで実行する）。

    全リクエストを数えるガード（``RateLimitGuard``）より前に置くこと（配置の
    規約はモジュール docstring 参照）。ブラウザは application/json のクロス
    オリジン POST を CORS のプリフライト（許可オリジン以外は拒否）なしには
    送れないが、text/plain・フォーム・Content-Type なしの「単純なリクエスト」や、
    ブラウザ自身が送る報告（CSP の違反報告等）はプリフライトなしで届きうる。
    これらは本文の検証で 422 になるものの、ガードはその前に数えるため、通すと
    第三者のページが訪問者のブラウザから送らせるだけで訪問者の IP の枠を
    使い切れてしまう。

    受け付けるのは application/json ちょうど（charset 等のパラメータと大小文字は
    無視）。正規の送信元（web の request()・E2E・テスト）はすべてこれを送るため、
    FastAPI が JSON として読む application/*+json（例: Reporting API の
    application/reports+json）までは広げない。Content-Type なしも拒否する
    （理由はモジュール docstring 参照）。
    """
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type == "application/json":
        return
    _warn_rejected(_route_path_for_log(request), media_type)
    raise _UNSUPPORTED_MEDIA_TYPE()
