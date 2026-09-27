"""全リクエスト共通の防御 — JSON ボディ・クエリ文字列の NUL・孤立サロゲート一括拒否。

``app.services.text_sanitize`` の方針③（保存できない文字）を、個々のフィールド
バリデータでは拾えない箇所（JSON のキー・クエリ文字列・extra="forbid" モデルの
未知フィールド名等）まで含めて経路を問わず一括で塞ぐための、ルーター単位の依存。

実測（docs/ops/e2e.md 参照）: 実 PostgreSQL では NUL を含む文字列を保存しようとすると
asyncpg が ``CharacterNotInRepertoireError`` を投げ 500 になる。孤立サロゲートは
UTF-8 へ符号化できず ``DataError: surrogates not allowed`` で 500 になる。運営の
検索クエリ（``GET /admin/operators?q=...``）の ``q`` に NUL を送っても同じ経路
（ILIKE のバインド値として PG に届く）で 500 になるため、クエリ文字列も対象にする。
修正前の実 PG での実測と判断の経緯は ``.agent-state/free-text-control-chars/REVIEW.md``。

``app.api.v1.router`` は本モジュールの :func:`reject_unsafe_request_chars` を
``APIRouter(dependencies=[Depends(reject_unsafe_request_chars)])`` として
**コンストラクタで**登録する。FastAPI/Starlette の実装（site-packages を実読して確認）:

- ``APIRouter.add_api_route``（fastapi/routing.py）は呼び出し時点の
  ``self.dependencies`` をコピーして各 ``APIRoute`` の先頭依存にする。
  ``include_router`` は内部で ``self.add_api_route(...)`` を呼ぶため、
  **後から** ``include_router`` されるサブルーターの全エンドポイントにも
  ``api_router`` 自身の ``dependencies`` が先頭に付く。逆に、全ルーター登録が
  終わった後で ``api_router.dependencies.append(...)`` しても、既にコピーされた
  ルートには反映されない（コンストラクタで渡す必要がある理由）。
- ``APIRoute.__init__`` は ``self.dependencies`` を逆順に ``dependant.dependencies``
  の先頭へ ``insert(0, ...)`` するため、ルーター単位の依存はエンドポイント自身の
  ``Depends``（認証等）より必ず先に解決される（未認証エンドポイントでも
  NUL・孤立サロゲートを先に 422 で拒否できる／認証依存より前に落ちる）。
- ボディの JSON パースは ``solve_dependencies``（依存解決）より**前**に
  ``fastapi.routing`` 側の ``app()`` 関数が行う（content-type が
  ``application/json`` または ``*/*+json`` のときのみ ``request.json()`` を呼ぶ。
  content-type 無しは ``strict_content_type`` 既定 True のため JSON として読まない）。
  ``Request`` は1リクエストにつき1つで、``body()``/``json()`` の結果は
  ``Request._body``/``_json`` にキャッシュされる（starlette/requests.py）ため、
  本依存が再度 ``connection.json()`` を呼んでも再パースは発生しない。
- ``scope["route"]`` は ``APIRoute.matches`` がマッチ時に設定する。
  ``dependant.http_connection_param_name`` 経由で依存に注入される値は
  型ヒントが ``HTTPConnection`` であっても実体は常に ``Request``
  （fastapi/dependencies/utils.py の ``solve_dependencies``）。

FastAPI 内部実装（``scope["route"]``・``body_field``・content-type 判定・
Starlette のボディキャッシュ）への依存はバージョン変更で崩れうるため、
前提が崩れた場合は例外を投げずログを出して素通す（フェイルオープン）。
``tests/test_request_char_guard.py`` がこの前提のずれを検知する。
"""

from __future__ import annotations

import email.message
import logging
from collections.abc import Iterator
from typing import Any, NoReturn

from fastapi import params
from fastapi.exceptions import RequestValidationError
from starlette.requests import HTTPConnection, Request

from app.core.log_throttle import ThrottledLogger
from app.services.text_sanitize import has_unsafe_storage_chars, replace_unsafe_storage_chars

logger = logging.getLogger(__name__)

#: RequestValidationError の要素に載せる type（Pydantic 標準の型と衝突しない専用の識別子）。
DISALLOWED_CHARACTER_ERROR_TYPE = "disallowed_character"
_DISALLOWED_CHARACTER_MESSAGE = (
    "使用できない文字（NUL 文字または壊れた文字コード）が含まれています。"
)

# 警告の種類ごとに別インスタンスにする（core/log_throttle.py の方針。1つのインスタンスを
# 複数の警告種別で共有すると互いのスロットリングに干渉するため）。テストからは
# ``.reset()`` で状態を初期化できる。
_route_missing_throttle = ThrottledLogger()
_json_decode_failure_throttle = ThrottledLogger()
_disallowed_char_throttle = ThrottledLogger()


def _is_json_content_type(content_type: str | None) -> bool:
    """Content-Type ヘッダが JSON 系（``application/json`` または ``*/*+json``）かを判定する。

    FastAPI 本体のボディ読み込み（``fastapi.routing.get_request_handler`` 内、
    ``strict_content_type`` 既定 True）と全く同じ判定基準にする。ここで本体側より
    緩く判定すると、本体が読まなかったボディを本依存だけが読みに行くことになり
    挙動が食い違う（逆に厳しく判定すると、本体が JSON として読むケースで
    孤立サロゲート等を素通りさせてしまう）。プロジェクト内に ``strict_content_type``
    を明示的に False にしているルートは無い（2026-09-27 時点で grep 確認済み）。
    """
    if not content_type:
        return False
    message = email.message.Message()
    message["content-type"] = content_type
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


def find_unsafe_char_path(payload: object) -> tuple[str | int, ...] | None:
    """JSON デコード後の値（dict/list/str/int/float/bool/None の入れ子）を文書順の
    深さ優先で走査し、NUL・孤立サロゲート（``has_unsafe_storage_chars``）を含む
    最初の位置を dict キー／list 添字の列として返す。見つからなければ ``None``。

    再帰を使わない反復実装（スタックは「(親から見たキー, 残りの子を列挙する
    イテレータ)」の列）。時間計算量は O(ノード数＋文字列総長)、メモリは
    スタックの深さに比例する O(深さ) のみを使うため、深い入れ子（数万段）でも
    Python の再帰上限（``RecursionError``）に到達しない。

    dict は挿入順（＝JSON の記載順）で ``items()``、list は ``enumerate()`` で辿る。
    子を1つ取るたびに「キー（dict のみ str。list の添字は int なので対象外）→値」の
    順に検査し、値が dict/list ならスタックに積んで直下から先に処理する（深さ優先。
    親のキー自身の違反は、その子へ降りる前に検出されるため子より先に返る）。
    数値・真偽値・None は無視する（NUL・孤立サロゲートは str にしか現れない）。

    JSON のキー自体も検査する理由: ``extra="forbid"`` を持つモデル
    （``UserNotificationSettingsUpdateRequest``・``CaseItemUpdateRequest`` 等）へ
    孤立サロゲート入りのキーを送ると、Pydantic の ``extra_forbidden`` エラーの
    ``loc`` に生の孤立サロゲートがそのまま載り、既定ハンドラ・本アプリ独自ハンドラの
    どちらでも応答本文の JSON シリアライズに失敗して 500 になる既存経路がある
    （本関数がこれを事前に検出し 422 へ倒すことで塞ぐ）。

    戻り値のタプル（違反位置）は、スタックの先頭（ルート自身。パスの要素にはならない）
    を除いた各階層のキーに、検出した子のキーを足して**1回だけ**組み立てる
    （ノードを辿るたびに毎回タプルを組み立てるとオーバーヘッドが O(深さ) 分
    積み重なるため、違反が見つかった時にだけ行うことで全体の時間計算量を保つ）。
    最上位が str 自体（JSON ボディがオブジェクト/配列でなく文字列そのもの）の場合は
    ``()`` を返す（トップレベル自体に位置は無い）。
    """
    if isinstance(payload, str):
        return () if has_unsafe_storage_chars(payload) else None
    if not isinstance(payload, (dict, list)):
        return None

    # スタックの各要素: (このコンテナ自身へ辿ったキー, 子を列挙するイテレータ)。
    # 先頭要素（ルート）のキーは使わない（末尾の tuple 組み立てで stack[1:] により除外する）。
    root_iter: Iterator[tuple[Any, Any]] = (
        iter(payload.items()) if isinstance(payload, dict) else iter(enumerate(payload))
    )
    stack: list[tuple[Any, Iterator[tuple[Any, Any]]]] = [(None, root_iter)]

    while stack:
        _, iterator = stack[-1]
        try:
            key, value = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        if isinstance(key, str) and has_unsafe_storage_chars(key):
            return tuple(k for k, _ in stack[1:]) + (key,)
        if isinstance(value, dict):
            stack.append((key, iter(value.items())))
        elif isinstance(value, list):
            stack.append((key, iter(enumerate(value))))
        elif isinstance(value, str) and has_unsafe_storage_chars(value):
            return tuple(k for k, _ in stack[1:]) + (key,)
    return None


def _raise_disallowed(
    loc: tuple[str | int, ...], *, method: str, route_path: str | None
) -> NoReturn:
    """違反検出時の共通処理: 60秒スロットリングで WARNING ログを出し、422 を投げる。

    ``loc`` の str 要素は ``replace_unsafe_storage_chars`` で無害化してからログに
    使う（生の NUL・孤立サロゲートをログへそのまま書き込むと、ログ収集基盤側で
    同じ「保存できない文字」500 を誘発しかねないため）。実際の入力値そのものは
    ログにも応答にも一切含めない（``loc`` はキー名・添字の列であり値ではない）。

    ``RequestValidationError`` に ``input``・``ctx`` キーは含めない（引数を渡さず
    既定のまま）。これらを含めると、FastAPI 既定の RequestValidationError ハンドラ
    （``fastapi.exception_handlers.request_validation_exception_handler``）・本アプリ
    独自ハンドラ（``app.main._validation_error_handler``）のどちらも当該キーを
    そのまま JSON へシリアライズしようとするため、無害化していない値が万一
    紛れ込んだ場合にシリアライズ失敗で 500 化する恐れがある（本ガードが防ぎたい
    500 を別の形で再発させないため、そもそも危険な値を持たせない）。
    """
    safe_loc = tuple(
        replace_unsafe_storage_chars(part) if isinstance(part, str) else part for part in loc
    )
    _disallowed_char_throttle.emit(
        lambda: logger.warning(
            "reject_unsafe_request_chars: 使用できない文字（NUL・孤立サロゲート）を検出し"
            "422で拒否しました - method=%s route=%s loc=%s",
            method,
            route_path,
            repr(safe_loc)[:200],
        )
    )
    raise RequestValidationError(
        [
            {
                "type": DISALLOWED_CHARACTER_ERROR_TYPE,
                "loc": safe_loc,
                "msg": _DISALLOWED_CHARACTER_MESSAGE,
            }
        ],
        body=None,
    )


async def reject_unsafe_request_chars(connection: HTTPConnection) -> None:
    """全ルート共通の依存本体（``app.api.v1.router.api_router`` のコンストラクタで登録）。

    処理順:

    1. ``scope["type"] != "http"`` か ``connection`` が ``Request`` でなければ何もしない
       （websocket 等の想定外経路のフェイルオープン。``APIRouter`` の依存は HTTP
       ルートにしか付かないため通常は到達しない防御的分岐）。
    2. クエリ文字列: ``connection.query_params.multi_items()`` の全キー・値を
       ``has_unsafe_storage_chars`` で検査し、見つかれば ``("query", キー)`` で拒否する。
       ``route`` の有無に関わらず実行する（クエリの読み取りは ``body_field`` のような
       ルート依存の前提判定を必要としないため）。
    3. ボディ検査の要否判定: ``scope["route"]`` が無ければ WARNING を出して終了
       （フェイルオープン）。``route.body_field`` が無い（アップロード系など
       ボディパラメータを持たないルート）、または ``Form`` 定義（multipart・
       urlencoded）なら読まずに終了する（本体側が依存解決より前にストリームを
       消費済み・または消費予定であり、ここで読むと ``RuntimeError`` になるため）。
       Content-Type が JSON 系でなければ終了する（本体側が ``request.json()`` を
       呼ばないケースと同じ判定にする）。ボディが空なら終了する。
    4. ``connection.json()`` を呼ぶ（本体側が既にデコード済みならキャッシュを再利用
       するだけで再パースは起きない）。``ValueError``（JSON デコード失敗）・
       ``RecursionError``（極端に深いネスト）はスロットル WARNING して終了する。
    5. ``find_unsafe_char_path`` で違反位置を探し、見つかれば ``("body", *path)`` で
       拒否する。最初の1件のみを報告する。
    """
    if connection.scope.get("type") != "http" or not isinstance(connection, Request):
        return

    method = str(connection.scope.get("method", ""))
    route = connection.scope.get("route")
    route_path: str | None = getattr(route, "path", None)

    # ② クエリ文字列（運営の検索 q 等）。フィールドバリデータの外側なので、
    # この依存でしか塞げない（q の NUL は ILIKE のバインド値として PG に届き 500 になる）。
    for key, value in connection.query_params.multi_items():
        if isinstance(key, str) and has_unsafe_storage_chars(key):
            _raise_disallowed(("query", key), method=method, route_path=route_path)
        if isinstance(value, str) and has_unsafe_storage_chars(value):
            _raise_disallowed(("query", key), method=method, route_path=route_path)

    # ③ ボディ検査の要否判定。
    if route is None:
        # scope["route"] は APIRoute.matches が設定する（FastAPI 内部実装への依存）。
        # 前提が崩れてもこのガードを 500 の原因にしない（フェイルオープン）。
        _route_missing_throttle.emit(
            lambda: logger.warning(
                "reject_unsafe_request_chars: scope['route'] が未設定のため"
                "ボディ検査をスキップしました - method=%s path=%s",
                method,
                connection.url.path,
            )
        )
        return

    body_field = getattr(route, "body_field", None)
    if body_field is None:
        # ボディパラメータを持たないルート（許可証画像・本人確認書類・写真アップロード
        # は Request.stream()/request.form() を手動で読むため body_field が無い）。
        # ボディは一切読まない。
        return
    if isinstance(body_field.field_info, params.Form):
        # multipart/form-data・x-www-form-urlencoded は本体側（fastapi.routing）が
        # 依存解決より前に request.form() でストリームを消費済みにする。ここで
        # connection.body()/json() を呼ぶと "Stream consumed" RuntimeError になるため
        # 読まない（Form 判定を body_field 有無チェックの直後、他の判定より先に行う）。
        return

    content_type = connection.headers.get("content-type")
    if not _is_json_content_type(content_type):
        # 本体側 (fastapi.routing) が request.json() を呼ばないケースと同じ判定。
        return

    body = await connection.body()
    if not body:
        # 空ボディは json.loads が例外になるだけで検査対象にならない。
        return

    try:
        payload = await connection.json()
    except (ValueError, RecursionError):
        # Request.json() の結果はキャッシュされるため、通常は本体側の読み込みで
        # 既に成功したデコード結果を再取得するだけで例外は起きない。body_field が
        # 無く本体側が読まない経路（本依存が最初の読み手になる場合）でのみ実際に
        # 発生し得るため、フェイルオープンで検知する
        # （ValueError=json.JSONDecodeError、RecursionError=極端に深いネスト）。
        _json_decode_failure_throttle.emit(
            lambda: logger.warning(
                "reject_unsafe_request_chars: JSON デコードに失敗したためボディ検査を"
                "スキップしました - method=%s route=%s",
                method,
                route_path,
            )
        )
        return

    violation = find_unsafe_char_path(payload)
    if violation is None:
        return
    _raise_disallowed(("body", *violation), method=method, route_path=route_path)
