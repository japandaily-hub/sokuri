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
  content-type 無しは ``strict_content_type`` 既定 True のため本体は JSON として
  読まない）。本ガードは本体より**広く**判定する（``_should_attempt_json_decode``。
  content-type 無しも検査対象にする）ため、``strict_content_type`` の設定や
  FastAPI のバージョンに依存せず読み漏れが起きない（security review B1）。
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

from fastapi import HTTPException, params
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
_TOO_LARGE_MESSAGE = "送信内容が大きすぎます。"

#: find_unsafe_char_path が走査するノード数（dict の項目・list の要素の累計）の上限
#: （security review B2。fail-closed）。認証前に巨大な JSON（余分なキーに大量の要素を
#: 積んだ配列等）を送られると、Python ループでの走査が json.loads の数倍の時間
#: イベントループを占有しうるため、上限を超えたら走査を打ち切って 413 で拒否する。
#: 案件作成（``POST /cases``。app/core/limits.py 参照）の正規のペイロードを実測すると
#: 2通りの数字がある（security review C3 対応。両者を区別しないと過大評価になる）:
#: - 上限値の単純な積による上界: 1,661 ノード（``MAX_ITEMS_PER_CASE`` 30 商品 ×
#:   （name/sort_order/photos の3キー＋商品ごとの ``MAX_PHOTOS_PER_ITEM`` 12 枚 ×2キー）
#:   ＋ 直下 ``MAX_PHOTOS_PER_CASE`` 150 枚 ×2キー ＋ トップレベル11キー）。この構成は
#:   写真合計が 30×12+150=510 枚になり、``CaseCreateRequest._validate_total_photo_count``
#:   が合計 150 枚（``MAX_PHOTOS_PER_CASE``）超過で 422 にするため実際には受理されない。
#: - 合計写真数の上限（150枚。商品ごと最低1枚必須の ``CaseItemIn.photos``
#:   ``min_length=1`` も満たす）を加味して実際に受理される最大: 581 ノード
#:   （トップレベル11キー＋商品30×4（items の enumerate 分＋name/sort_order/photos の
#:   3キー）＋写真150×3（各写真リストの enumerate 分＋storage_key/sort_order の2キー。
#:   150枚がどう配分されても写真1枚あたり3ノードは変わらない））。実測して確認済み
#:   （tests/test_request_char_guard.py の該当テストが両方の数字を固定する）。
#: どちらの数字でも 10,000 は十分な余裕（上界の 1,661 に対しても約 6 倍）を持つ。
_MAX_INSPECTED_JSON_NODES = 10_000

# 警告の種類ごとに別インスタンスにする（core/log_throttle.py の方針。1つのインスタンスを
# 複数の警告種別で共有すると互いのスロットリングに干渉するため）。テストからは
# ``.reset()`` で状態を初期化できる。
_route_missing_throttle = ThrottledLogger()
_json_decode_failure_throttle = ThrottledLogger()
_disallowed_char_throttle = ThrottledLogger()
_too_large_throttle = ThrottledLogger()

# 間引いた分もプロセス内累計件数として次に出る WARNING 行に含める
# （case_photos.py の _upload_strip_failure_count と同じ流儀。security review B4）。
_disallowed_char_count = 0
_too_large_count = 0


class JsonTooLargeToInspectError(Exception):
    """find_unsafe_char_path の走査対象ノード数が max_nodes を超えた（fail-closed 用の専用例外）。"""


def _is_explicit_json_content_type(content_type: str | None) -> bool:
    """Content-Type ヘッダが明示的に JSON 系（``application/json`` または ``*/*+json``）と
    宣言されているかを判定する。

    FastAPI 本体のボディ読み込み（``fastapi.routing.get_request_handler`` 内、
    ``strict_content_type`` 既定 True）と全く同じ判定基準（Content-Type 無しは
    対象外）。本関数単体は JSON デコード失敗時に WARNING を出すかどうかの判定
    （``_should_attempt_json_decode`` が本体より広く検査対象を取るため、失敗時に
    「本当に JSON のつもりだったのに壊れていた」場合だけログを残す）にのみ使う。
    ボディを読むかどうかの判定には ``_should_attempt_json_decode`` を使うこと
    （security review B1: Content-Type 無しのケースを取り違えないため関数を分離）。
    """
    if not content_type:
        return False
    message = email.message.Message()
    message["content-type"] = content_type
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


def _should_attempt_json_decode(content_type: str | None) -> bool:
    """本ガードがボディを JSON としてデコードして走査すべきかを判定する。

    FastAPI 本体（``_is_explicit_json_content_type``。``strict_content_type``
    既定 True）よりも広く、Content-Type ヘッダが無い場合も対象にする
    （security review B1）。

    根拠: 旧実装は本体の判定に完全に一致させていたが、これは本体の
    ``strict_content_type`` が既定 True であることと、pyproject.toml が
    ``fastapi>=0.115`` とバージョンを固定していない（``requirements.txt`` 等の
    ロックファイルが無い）ことに暗黙に依存していた。運用でアプリ側が
    ``strict_content_type=False`` を指定した場合や、将来 FastAPI が既定値を
    変えた場合、本体は Content-Type 無しでも ``request.json()`` を呼んで JSON
    として読むのに、本ガードだけが読まずに素通す迂回が生まれる（認証不要の
    ``/auth/signup`` の ``name`` に Content-Type 無しで NUL を送っても本ガードが
    検知できず、実 PG で 500 になる経路が塞がれないまま残る）。プロジェクト内に
    ``strict_content_type`` を明示的に False にしているルートは現状無い
    （2026-09-27 時点で grep 確認済み）ため実害は無いが、設定やバージョンに
    依存しない安全側の判定にする。

    Content-Type 無しで JSON としてデコードできない本文（例: プレーンテキスト）は、
    ``reject_unsafe_request_chars`` 側で ``ValueError``/``RecursionError`` を握って
    例外もログも出さず素通す（本体側も Content-Type 無しでは JSON として読まず、
    後続の Pydantic 検証が「ボディが辞書でない」等の 422 を返すため、本ガードが
    「JSON でないボディ」を弾く責務は持たない。既存の 422 に任せる）。
    """
    if not content_type:
        return True
    return _is_explicit_json_content_type(content_type)


def find_unsafe_char_path(
    payload: object, *, max_nodes: int | None = None
) -> tuple[str | int, ...] | None:
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

    ``max_nodes``（既定 ``None``＝無制限。深さ10万・要素20万件の既存の単体テストは
    指定しないため無制限のまま影響を受けない）を指定すると、辿った子（dict の
    items()・list の enumerate() から取り出した各 (key, value) ペア。ルート自身は
    数えない）の累計がこれを超えた時点で ``JsonTooLargeToInspectError`` を投げて
    打ち切る（security review B2。fail-closed）。認証前に走査できる巨大な JSON
    （例: 余分なキーに大量の要素を積んだ配列）でイベントループを長時間占有させる
    DoS を防ぐ。**上限超過時に走査を打ち切って素通しにする（＝None を返す）と、
    余分なキーで上限を埋めた後ろに NUL を隠す迂回**（違反が実際にあっても検出前に
    打ち切られ通過してしまう）**が成立するため、必ず例外にして呼び出し側で拒否させる
    ことが安全側の要件である。**
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
    visited_nodes = 0

    while stack:
        _, iterator = stack[-1]
        try:
            key, value = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        visited_nodes += 1
        if max_nodes is not None and visited_nodes > max_nodes:
            raise JsonTooLargeToInspectError(
                f"走査対象のノード数が上限（{max_nodes}）を超えました。"
            )
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
    間引いた分もプロセス内累計件数として次に出る WARNING 行に含める
    （case_photos.py の ``_note_upload_strip_failure`` と同じ流儀。security review B4）。

    ``RequestValidationError`` に ``input``・``ctx`` キーは含めない（引数を渡さず
    既定のまま）。これらを含めると、FastAPI 既定の RequestValidationError ハンドラ
    （``fastapi.exception_handlers.request_validation_exception_handler``）・本アプリ
    独自ハンドラ（``app.main._validation_error_handler``）のどちらも当該キーを
    そのまま JSON へシリアライズしようとするため、無害化していない値が万一
    紛れ込んだ場合にシリアライズ失敗で 500 化する恐れがある（本ガードが防ぎたい
    500 を別の形で再発させないため、そもそも危険な値を持たせない）。
    """
    global _disallowed_char_count
    _disallowed_char_count += 1
    failure_count = _disallowed_char_count
    safe_loc = tuple(
        replace_unsafe_storage_chars(part) if isinstance(part, str) else part for part in loc
    )
    _disallowed_char_throttle.emit(
        lambda: logger.warning(
            "reject_unsafe_request_chars: 使用できない文字（NUL・孤立サロゲート）を検出し"
            "422で拒否しました - method=%s route=%s loc=%s（プロセス内累計 %s 件）",
            method,
            route_path,
            repr(safe_loc)[:200],
            failure_count,
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


def _raise_too_large(*, method: str, route_path: str | None) -> NoReturn:
    """走査対象のノード数が上限を超えた場合の共通処理: WARNING ログを出し、413 を投げる。

    ``_raise_disallowed`` と対称的な構造にする（プロセス内累計件数を添えるログの
    流儀は case_photos.py の ``_note_upload_strip_failure`` と同じ。security review B4）。
    ``JsonTooLargeToInspectError`` は内部実装の詳細のため、``from None`` で例外連鎖を
    切り、クライアントへ返す ``HTTPException`` だけを主因として扱う。
    """
    global _too_large_count
    _too_large_count += 1
    failure_count = _too_large_count
    _too_large_throttle.emit(
        lambda: logger.warning(
            "reject_unsafe_request_chars: 走査対象のノード数が上限を超えたため"
            "413で拒否しました - method=%s route=%s（プロセス内累計 %s 件）",
            method,
            route_path,
            failure_count,
        )
    )
    raise HTTPException(status_code=413, detail=_TOO_LARGE_MESSAGE) from None


async def reject_unsafe_request_chars(connection: HTTPConnection) -> None:
    """全ルート共通の依存本体（``app.api.v1.router.api_router`` のコンストラクタで登録）。

    処理順:

    1. ``scope["type"] != "http"`` か ``connection`` が ``Request`` でなければ何もしない
       （websocket 等の想定外経路のフェイルオープン。``APIRouter`` の依存は HTTP
       ルートにしか付かないため通常は到達しない防御的分岐）。
    2. パスパラメータ: ``connection.path_params`` の str 値を ``has_unsafe_storage_chars``
       で検査し、見つかれば ``("path", キー)`` で拒否する（security review B3）。
       Starlette のルーティングはエンドポイント関数の型ヒント（``case_id: uuid.UUID``
       等）に関わらず、既定では全パラメータを ``StringConvertor`` でマッチさせ、
       ``scope["path_params"]`` には常に str のまま格納する（UUID 等への変換は
       この依存より後、``solve_dependencies`` 内の ``request_params_to_args`` が
       Pydantic で行う。starlette/routing.py の ``Route.matches`` と
       api_router.routes の ``param_convertors`` を実読して確認済み）。したがって
       本検査は実質的に全パスパラメータへ及ぶ（意図した副次効果。現状は DB に届く
       パラメータが admin.py 等の UUID 変換失敗時 422 か storage_key の完全一致検査
       で守られているが、将来 str のまま DB へ渡すパスパラメータを追加したときの
       穴を事前に塞ぐ）。
    3. クエリ文字列: ``connection.query_params.multi_items()`` の全キー・値を
       ``has_unsafe_storage_chars`` で検査し、見つかれば ``("query", キー)`` で拒否する。
       ``route`` の有無に関わらず実行する（クエリの読み取りは ``body_field`` のような
       ルート依存の前提判定を必要としないため）。
    4. ボディ検査の要否判定: ``scope["route"]`` が無ければ WARNING を出して終了
       （フェイルオープン）。``route.body_field`` が無い（アップロード系など
       ボディパラメータを持たないルート。``Request.stream()``/``request.form()``
       を手動で読む）なら読まずに終了する。
    5. ``Form`` 定義（multipart・urlencoded）なら ``connection.form()`` を呼び、
       ``multi_items()`` の str キー・str 値（``UploadFile`` は見ない）を検査して
       終了する（security review C1）。本体側は依存解決より前に
       ``await request.form()`` を呼んでおり、Starlette は ``self._form`` に
       キャッシュする（``_get_form`` は ``self._form is None`` のときだけ実際に
       パースする。starlette/requests.py 実読で確認済み）ため、ここで呼んでも
       再パース・``RuntimeError`` にはならない（``connection.body()``/``json()``
       は Form のストリームを直接読もうとして "Stream consumed" ``RuntimeError``
       になるが、``form()`` はキャッシュされた ``FormData`` を返すだけの実装の
       ため影響を受けない）。
    6. Content-Type が無いか JSON 系でなければ終了する（security review B1:
       FastAPI 本体の判定より広く、Content-Type 無しも検査対象にする。
       ``_should_attempt_json_decode`` 参照）。ボディが空なら終了する。
    7. ``connection.json()`` を呼ぶ（本体側が既にデコード済みならキャッシュを再利用
       するだけで再パースは起きない）。``ValueError``（JSON デコード失敗）・
       ``RecursionError``（極端に深いネスト）は、Content-Type が明示的に JSON 系
       だった場合のみスロットル WARNING して終了する（Content-Type 無しで JSON
       として読めない本文は異常ではないため、ログもエラーも出さず素通す）。
       ``MemoryError``（Content-Type 無しの経路では本ガードが最初の JSON パーサに
       なりうるため、``json.loads`` が巨大な本文で ``MemoryError`` を投げると
       ここで初めて捕捉する）は 413 に変換する（security review C2。
       ``find_unsafe_char_path`` の ``max_nodes`` 上限と同じ fail-closed 方針）。
    8. ``find_unsafe_char_path`` を ``max_nodes=_MAX_INSPECTED_JSON_NODES`` 付きで呼ぶ。
       ``JsonTooLargeToInspectError`` は 413 に変換する（security review B2。
       fail-closed）。違反が見つかれば ``("body", *path)`` で拒否する。
       最初の1件のみを報告する。
    """
    if connection.scope.get("type") != "http" or not isinstance(connection, Request):
        return

    method = str(connection.scope.get("method", ""))
    route = connection.scope.get("route")
    route_path: str | None = getattr(route, "path", None)

    # ② パスパラメータ。Starlette は既定で全パラメータを str のまま
    # scope["path_params"] に格納するため（型ヒント上の UUID 変換は後続の
    # solve_dependencies が行う）、isinstance チェックは事実上常に True になる。
    # 将来 int 等の型付きコンバータ（{id:int} 構文）を使うルートが増えた場合の
    # 保険として残す。
    for path_key, path_value in connection.path_params.items():
        if isinstance(path_value, str) and has_unsafe_storage_chars(path_value):
            _raise_disallowed(("path", path_key), method=method, route_path=route_path)

    # ③ クエリ文字列（運営の検索 q 等）。フィールドバリデータの外側なので、
    # この依存でしか塞げない（q の NUL は ILIKE のバインド値として PG に届き 500 になる）。
    for key, value in connection.query_params.multi_items():
        if isinstance(key, str) and has_unsafe_storage_chars(key):
            _raise_disallowed(("query", key), method=method, route_path=route_path)
        if isinstance(value, str) and has_unsafe_storage_chars(value):
            _raise_disallowed(("query", key), method=method, route_path=route_path)

    # ④ ボディ検査の要否判定。
    if route is None:
        # scope["route"] は APIRoute.matches が設定する（FastAPI 内部実装への依存）。
        # 前提が崩れてもこのガードを 500 の原因にしない（フェイルオープン）。
        # url.path は出さない（%0A での行分割・storage_key 等の露出を避ける。
        # security review B4）。
        _route_missing_throttle.emit(
            lambda: logger.warning(
                "reject_unsafe_request_chars: scope['route'] が未設定のため"
                "ボディ検査をスキップしました - method=%s",
                method,
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
        # security review C1: Form ルート（現状 endpoints 配下に定義は無いが、将来
        # x: str = Form(...) が追加された場合に備える）。本体側（fastapi.routing）は
        # 依存解決より前に await request.form() を呼んでいる。Starlette の
        # Request._get_form は self._form is None のときだけ実際にパースし、以後は
        # キャッシュした FormData をそのまま返す（starlette/requests.py 実読で確認済み）
        # ため、ここで await connection.form() を呼んでも再パース・RuntimeError には
        # ならない（connection.body()/json() は Form のストリームを直接読もうとして
        # "Stream consumed" RuntimeError になるが、form() は影響を受けない）。
        # FormData の値は UploadFile | str（starlette/datastructures.py）なので、
        # str のキー・値だけを検査し UploadFile の中身は見ない（ファイルアップロードは
        # 別途 case_photos.py 側でマジックバイト判定・メタデータ除去を行う）。
        form = await connection.form()
        for form_key, form_value in form.multi_items():
            if isinstance(form_key, str) and has_unsafe_storage_chars(form_key):
                _raise_disallowed(("body", form_key), method=method, route_path=route_path)
            if isinstance(form_value, str) and has_unsafe_storage_chars(form_value):
                _raise_disallowed(("body", form_key), method=method, route_path=route_path)
        return

    content_type = connection.headers.get("content-type")
    if not _should_attempt_json_decode(content_type):
        # 本体側 (fastapi.routing) が request.json() を呼ばないケースのうち、
        # Content-Type が明示的に JSON 系以外（text/plain 等）のもの。
        return

    body = await connection.body()
    if not body:
        # 空ボディは json.loads が例外になるだけで検査対象にならない。
        return

    try:
        payload = await connection.json()
    except MemoryError:
        # security review C2: Content-Type 無しの経路（_should_attempt_json_decode
        # が True を返すケース）では本体側が request.json() を呼ばないため、本ガードが
        # 最初で唯一の JSON パーサになりうる。json.loads は巨大な本文（Content-Length
        # を偽らずとも極端に大きいボディ）を渡されると内部で MemoryError を投げうるが、
        # これを捕まえず伝播させると Starlette の既定例外ハンドラが 500 にし、
        # ServerErrorAlertMiddleware の Critical アラートを誤って発報する
        # （FastAPI 本体は本体側の解析中の Exception を 400 にしているため、
        # 本体が先に読むケースではこの経路自体を通らない）。find_unsafe_char_path の
        # max_nodes 超過（B2）と同じ fail-closed 方針で 413 に倒す。
        _raise_too_large(method=method, route_path=route_path)
    except (ValueError, RecursionError):
        # Request.json() の結果はキャッシュされるため、通常は本体側の読み込みで
        # 既に成功したデコード結果を再取得するだけで例外は起きない。body_field が
        # 無く本体側が読まない経路（本依存が最初の読み手になる場合）でのみ実際に
        # 発生し得るため、フェイルオープンで検知する
        # （ValueError=json.JSONDecodeError、RecursionError=極端に深いネスト）。
        # Content-Type が明示的に JSON 系だった場合のみ WARNING を出す
        # （Content-Type 無しで JSON として読めない本文は異常ではないため、
        # ログも例外も出さず FastAPI/Pydantic 側の既存の 422 に任せる）。
        if _is_explicit_json_content_type(content_type):
            _json_decode_failure_throttle.emit(
                lambda: logger.warning(
                    "reject_unsafe_request_chars: JSON デコードに失敗したためボディ検査を"
                    "スキップしました - method=%s route=%s",
                    method,
                    route_path,
                )
            )
        return

    try:
        violation = find_unsafe_char_path(payload, max_nodes=_MAX_INSPECTED_JSON_NODES)
    except JsonTooLargeToInspectError:
        _raise_too_large(method=method, route_path=route_path)
    if violation is None:
        return
    _raise_disallowed(("body", *violation), method=method, route_path=route_path)
