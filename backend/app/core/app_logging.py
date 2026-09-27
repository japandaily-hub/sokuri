"""アプリ自身（``app.*`` ロガー）のログを本番の stderr（＝Render のログ）へ出す設定。

背景（2026-09-27 に Render のログで実測）:
    本番は backend/start.sh から ``uvicorn app.main:app`` で起動しており、uvicorn の既定の
    ログ設定は ``uvicorn`` / ``uvicorn.error`` / ``uvicorn.access`` しか構成しない。root
    ロガーは未設定（レベル WARNING・ハンドラ無し）のままなので、

    - ``app.*`` の INFO（起動時シード・運営操作の監査ログ等）は root のレベルで捨てられ、
      1行も出ない。過去約7日で "Application startup complete." は起動ごとに23回あるのに、
      起動ごとに出るはずの "seed: チャネルシード完了" は0件だった。
    - WARNING 以上は「ハンドラが1つも見つからない」ときの ``logging.lastResort`` に落ち、
      レベルもロガー名も無い本文だけの行になる。

設計判断:
    - **``app`` ロガーにだけ** ハンドラを付ける（root には付けない）。root に付けると
      httpx（送信先 URL）・botocore・google-genai 等の第三者ライブラリの INFO まで流れ出し、
      ログ量と秘密値の露出面が増える。第三者の WARNING 以上は従来どおり lastResort で出る。
      特に httpx / httpcore は INFO に送信先 URL をクエリごと出す（LINE の検証 API は
      access_token をクエリで渡す＝auth.py）ため、将来 root にハンドラが付いても流れないよう
      WARNING に固定する。
    - ``propagate`` は True のまま。uvicorn は root にハンドラを付けないので本番で二重には
      ならず、``app`` にハンドラがある限り lastResort も使われない（lastResort は階層の
      どこにもハンドラが無いときだけ使われる）。root へ伝播し続けるので、pytest の caplog
      （root に付くハンドラ）も従来どおり記録を拾える。
    - uvicorn の ``--log-config`` は使わない。指定すると uvicorn の既定設定が丸ごと置き換わり、
      uvicorn 自身の書式（"INFO:     Application startup complete." 等）を再現する設定を
      こちらで抱えることになる。起動経路の設定ファイルの誤りは起動失敗＝全断にも直結する。
    - 有効にするのは環境変数 ``APP_LOG_LEVEL`` があるときだけ（本番は start.sh が既定値 INFO
      を渡す）。Settings（.env）ではなくプロセスの環境変数を読むのは、① テストが
      ``create_app(Settings(APP_ENV="production"))`` を直接呼ぶため、Settings の値で切り替えると
      テストのロガーまで書き換わる ② ログの設定を Settings の生成・検証に依存させないため。
      未設定（テスト・ローカル開発）では何もしない＝従来どおり。
    - 呼ぶのは app/main.py の ``create_app()`` の直前（import 時の [startup] ログや本番ガードの
      CRITICAL を拾う）。それより前、main.py が他のモジュールを import している最中に出るログ
      （Settings の検証時の WARNING 等）は設定前のため、従来どおり lastResort で本文だけが出る。
    - 本文の制御文字はエスケープして1行に収める（利用者の入力を含む値で偽のログ行を作られない
      ようにする: CWE-117。改行・CR・ログビューアが改行とみなす NEL・U+2028・U+2029、端末を
      操作できる ESC 等の制御文字と、書式文字＝Cf（表示順を入れ替える双方向制御文字・ゼロ幅文字・
      見えないまま文字列を運べるタグ文字等）。タブはそのまま）。トレースバック等の複数行は各行の
      先頭に ``  | `` を付け、行の中の制御文字も同じくエスケープする（例外文に入った入力で
      ``INFO [app...]`` から始まる偽の行を作れないようにする）。
    - 整形の際、エスケープより先に、文中のメールアドレス・写真の storage_key・LINE の userId を
      :func:`mask_sensitive_in_text` でマスクする（呼び出し側のマスク漏れや、例外文に含まれる値
      への安全網）。uvicorn.error が出す未処理例外のトレースバック（"Exception in ASGI
      application"）にも、uvicorn の書式を変えずに同じ処理を掛ける（こちらは下の「伏せ字」と同じく
      APP_LOG_LEVEL に依らず常に）。呼び出し側では引き続き ``mask_email`` 等で個別にマスクすること。
    - DB 例外（PostgreSQL の DETAIL＝一意制約違反のキーの値・CHECK 違反の行全体を文言に抱える）と
      検証エラー（入力値を抱える）は、メール等のマスクでは氏名・住所・電話番号が残る。トレースバックは
      :func:`app.core.error_summary.format_exception_for_log` で両者の文言だけを要約（型・SQLSTATE・
      制約名等）に差し替えて整形し、本文の引数にこれらの例外オブジェクトがそのまま渡されたときも
      要約に差し替える。呼び出し側では引き続き ``describe_exception(exc)`` を渡すこと（本処理は
      取りこぼし対策。APP_LOG_LEVEL が無く本ハンドラが付かない開発・テストでは効かない）。
    - 整形に失敗したとき（書式と引数の不一致）、標準の ``Handler.handleError`` は引数の生値を
      マスクを通さず stderr へ書くため、例外の種類と発生箇所だけを1行で出す。

uvicorn のログの伏せ字（:func:`install_log_redaction`）:
    uvicorn は1リクエスト1行のアクセスログ（``uvicorn.access``）に、パスとクエリ文字列をそのまま
    出す。写真の ``GET /api/v1/files/{storage_key}`` は無認証の capability URL なので、Render の
    ログ（約7日・ダッシュボードの権限で読める）を読める人が写真を取れてしまう。``/readyz?token=``・
    ``/api/v1/_diag/client-ip?token=`` の DIAG_TOKEN や検索語 ``?q=`` も同じく残る。

    - パスの storage_key を先頭8字＋``...``に丸め、クエリは値を伏せる（書式は uvicorn のまま）。
      引数の位置に依らず文字列の引数すべてに掛ける（uvicorn が引数の並びを変えても伏せる側に倒す。
      パス以外の引数＝接続元・メソッド・HTTP の版には伏せる対象が無いので変わらない）。
      ``uvicorn.error`` の WebSocket の行（``'%s - "WebSocket %s" 403'`` 等）のパスにも掛ける。
    - 未処理例外のトレースバックの整形（上記）も同じ入口で付ける。
    - **``APP_LOG_LEVEL`` に依らず常に付ける。** 上の app.* の設定は「ログを出すか・どのレベルか」
      の切り替えだが、こちらは漏えいを防ぐ対策で、無いと気付かないまま漏れ続ける（app.* の INFO が
      出ていなかった件も数か月気付かれなかった）。起動経路が start.sh を通らない場合（Render の
      開始コマンドの変更等）でも効くよう、app/main.py の import 時に呼ぶ。ローカル開発の
      アクセスログとトレースバックも伏せ字・継続の印付きになるが、テスト（TestClient・httpx の
      ASGITransport）は uvicorn を通らないので影響しない。
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping

from app.core.error_summary import (
    describe_exception,
    format_exception_for_log,
    is_value_bearing_exception,
)
from app.core.masking import mask_request_target_for_log, mask_sensitive_in_text

#: 設定対象のロガー名。``logging.getLogger(__name__)`` を使う app 配下の全モジュールがこの子になる。
APP_LOGGER_NAME = "app"

#: 有効化とレベル指定に使う環境変数名（backend/start.sh が本番の既定値 INFO を export する）。
APP_LOG_LEVEL_ENV = "APP_LOG_LEVEL"

#: 受け付けるレベル名。これ以外（綴り誤り等）は INFO に倒して WARNING を1行出す（起動は止めない）。
_ALLOWED_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

#: 本モジュールが付けたハンドラの目印（何度呼ばれてもハンドラを1つに保つために使う）。
_HANDLER_MARK = "_katazuke_app_log_handler"

#: INFO に送信先 URL（クエリの秘密値を含む）を出す第三者ロガー。WARNING 以上に固定する。
_QUIETED_THIRD_PARTY_LOGGERS = ("httpx", "httpcore")

#: 未処理例外のトレースバックを出す uvicorn のロガー（書式は uvicorn のまま、中身だけ整える）。
_UVICORN_ERROR_LOGGER_NAME = "uvicorn.error"

#: 1リクエスト1行のアクセスログを出す uvicorn のロガー。uvicorn（protocols/http の h11_impl・
#: httptools_impl）は引数 ``(client_addr, method, full_path, http_version, status_code)`` で出す。
#: full_path は ``urllib.parse.quote(scope["path"])`` に生のクエリ文字列をつないだもの（0.48 で確認）。
_UVICORN_ACCESS_LOGGER_NAME = "uvicorn.access"

#: 伏せ字の処理に失敗した引数の代わりに出す文字列（隠す側に倒す）。
_REDACTION_FAILED_PLACEHOLDER = "<hidden>"

#: トレースバック等の継続行の先頭に付ける印（1行目の本文と区別し、偽の行頭を作らせない）。
_CONTINUATION_PREFIX = "  | "

logger = logging.getLogger(__name__)


def _escape_for(code_point: int) -> str:
    """制御文字1字を、見て分かるエスケープ表記（``\\n`` ``\\x1b`` ``\\u2028`` ``\\U000e0041`` 等）にする。"""
    named = {0x0A: "\\n", 0x0D: "\\r"}
    if code_point in named:
        return named[code_point]
    if code_point <= 0xFF:
        return f"\\x{code_point:02x}"
    if code_point <= 0xFFFF:
        return f"\\u{code_point:04x}"
    return f"\\U{code_point:08x}"


#: 一般カテゴリ Cf（書式文字＝画面に出ない文字）の範囲（Unicode 15.1 時点）。表示順を入れ替える
#: 双方向制御文字（CVE-2021-42574 と同じ類型）、ゼロ幅文字、見えないまま文字列を運べるタグ文字
#: （"ASCII smuggling"）、ソフトハイフン等を含む。tests/test_app_logging.py が、実行中の Python の
#: unicodedata で Cf の全文字がこの表に入っていることを確かめる（Python を上げて漏れたら CI が落ちる）。
_FORMAT_CHAR_RANGES: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),
    (0x0600, 0x0605),
    (0x061C, 0x061C),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x180E, 0x180E),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x206F),
    (0xFEFF, 0xFEFF),
    (0xFFF9, 0xFFFB),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
    (0x13430, 0x1343F),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001),
    (0xE0020, 0xE007F),
)

#: 本文のエスケープ対象（``str.translate`` 用の表）。C0 制御文字（タブを除く）・DEL・C1 制御文字
#: （NEL を含む）、``str.splitlines`` やログビューアが行区切りとみなす U+2028・U+2029、書式文字（Cf）。
_MESSAGE_ESCAPES: dict[int, str] = {
    code_point: _escape_for(code_point)
    for code_point in (
        *range(0x00, 0x09),
        *range(0x0A, 0x20),
        *range(0x7F, 0xA0),
        0x2028,
        0x2029,
        *(code_point for start, end in _FORMAT_CHAR_RANGES for code_point in range(start, end + 1)),
    )
}

#: 複数行の塊（トレースバック等）用の表。行区切りの改行だけは残す。
_BLOCK_ESCAPES: dict[int, str] = {
    code_point: escaped for code_point, escaped in _MESSAGE_ESCAPES.items() if code_point != 0x0A
}


def _render_block(block: str) -> str:
    """トレースバック等の複数行を、制御文字をエスケープし各行の先頭に継続の印を付けた形にする。"""
    lines = block.translate(_BLOCK_ESCAPES).split("\n")
    return "\n".join(_CONTINUATION_PREFIX + line for line in lines)


def _summarize_if_value_bearing(value: object) -> object:
    """DB 例外・検証エラーのオブジェクトなら要約の文字列に、それ以外はそのまま返す。"""
    return describe_exception(value) if is_value_bearing_exception(value) else value  # type: ignore[arg-type]


def _render_message(record: logging.LogRecord) -> str:
    """``record.getMessage()`` と同じ文字列を作る。本文・引数が DB 例外・検証エラーのオブジェクトなら
    要約に差し替える（``logger.error("... %s", exc)`` の取りこぼし対策。record 自体は書き換えない）。"""
    message = str(_summarize_if_value_bearing(record.msg))
    args = record.args
    if not args:
        return message
    if isinstance(args, Mapping):
        return message % {key: _summarize_if_value_bearing(value) for key, value in args.items()}
    if isinstance(args, tuple):
        return message % tuple(_summarize_if_value_bearing(value) for value in args)
    return message % args


def escape_control_characters(text: str) -> str:
    """制御文字・行区切り・書式文字（Cf）をエスケープ表記にして1行に収める（app.* のログ本文と同じ表）。

    ログ以外（運営アラートの本文に入れる例外文等）でも、利用者の入力を含みうる文字列で偽の行や
    表示順の入れ替えを作らせないために使う。マスクを掛ける場合はマスクが先（AppLogFormatter 参照）。
    """
    return text.translate(_MESSAGE_ESCAPES)


class AppLogFormatter(logging.Formatter):
    """``LEVEL [ロガー名] 本文`` の1行（例外時はその後ろに ``  | `` 付きのトレースバック）へ整形する。

    書式は start.sh が転写する alembic のログ（``INFO  [alembic.runtime.migration] ...``）と
    同じ並びにそろえる。時刻は Render がログ1行ごとに付けるので含めない。
    """

    def formatException(self, ei) -> str:  # noqa: ANN001 -- logging の exc_info（型・値・トレースバック）
        """標準と同じトレースバック。DB 例外・検証エラーの文言だけを要約に差し替える（error_summary 参照）。"""
        return format_exception_for_log(ei[1] if ei else None)

    def format(self, record: logging.LogRecord) -> str:
        # マスクは生の文字列に先に掛けてからエスケープする（エスケープ後の "\n" 等は英数字で終わり、
        # storage_key・LINE userId の前の境界判定を崩す）。マスクは制御文字を生まない。
        message = mask_sensitive_in_text(_render_message(record)).translate(_MESSAGE_ESCAPES)
        text = f"{record.levelname} [{record.name}] {message}"
        # トレースバックは例外オブジェクト（exc_info）があれば毎回ここで整形し、record のキャッシュ
        # （exc_text）は読まない・書かない。先に別の書式（標準の Formatter 等）が作った生の
        # トレースバック（DB 例外の DETAIL を含む）を使い回さず、こちらの要約も他のハンドラへ
        # 押し付けない。exc_info が無く exc_text だけある record はマスクだけ掛けて出す。
        exception_text = self.formatException(record.exc_info) if record.exc_info else record.exc_text
        if exception_text:
            text = f"{text}\n{_render_block(mask_sensitive_in_text(exception_text))}"
        if record.stack_info:
            stack = self.formatStack(record.stack_info)
            text = f"{text}\n{_render_block(mask_sensitive_in_text(stack))}"
        return text


class _AppLogHandler(logging.StreamHandler):
    """app.* 用の stderr ハンドラ。整形に失敗したときに引数の生値を出さない。

    標準の ``Handler.handleError`` は、書式と引数の不一致などで整形に失敗すると、トレースバックと
    ``Arguments: <引数の生値>``（メールアドレス等を含みうる）をマスクを通さず stderr へ書く。
    例外の種類と発生箇所（ソースの位置）だけを1行で出す。
    """

    def handleError(self, record: logging.LogRecord) -> None:
        if not logging.raiseExceptions:
            return
        error_type = sys.exc_info()[0]
        try:
            self.stream.write(
                f"LOGGING_ERROR [{record.name}] {getattr(error_type, '__name__', error_type)}"
                f" at {record.pathname}:{record.lineno}{self.terminator}"
            )
            self.flush()
        except Exception:  # noqa: BLE001 -- ログのために処理を止めない
            pass


class _UvicornTracebackFilter(logging.Filter):
    """uvicorn.error の未処理例外のトレースバックに、app.* と同じ処理（DB 例外・検証エラーの文言の要約・
    継続の印・エスケープ・マスク）を掛ける。

    uvicorn の Formatter は ``record.exc_text`` のキャッシュをそのまま使うので、先に整えた文字列を
    入れておけば、uvicorn 自身の書式（"ERROR:    Exception in ASGI application"）は変わらない。
    ロガーに付けたフィルタの例外は logging に捕まらず、uvicorn が 500 を返せず接続が宙づりになる
    ため、整形に失敗しても例外は出さない（トレースバックは例外の種類だけに差し替える＝隠す側に倒す）。
    """

    _traceback_formatter = AppLogFormatter()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = _render_block(
                    mask_sensitive_in_text(self._traceback_formatter.formatException(record.exc_info))
                )
            except Exception:  # noqa: BLE001 -- 上記のとおり、ここから例外を出さない
                error_type = record.exc_info[0]
                record.exc_text = (
                    f"{_CONTINUATION_PREFIX}{getattr(error_type, '__name__', error_type)}"
                    "（トレースバックを整形できなかったため省略）"
                )
        return True


def _redact_log_argument(value: object) -> object:
    """ログの引数1つ（文字列のとき）から、写真の鍵とクエリの値を伏せる。失敗したら全体を伏せる。"""
    if not isinstance(value, str):
        return value
    try:
        return mask_request_target_for_log(value)
    except Exception:  # noqa: BLE001 -- フィルタから例外を出さない（下のクラスを参照）
        return _REDACTION_FAILED_PLACEHOLDER


class _RequestTargetRedactionFilter(logging.Filter):
    """uvicorn のログの引数に入るリクエストのパス（``?`` クエリ）から、写真の鍵とクエリの値を伏せる。

    uvicorn.access の AccessFormatter は ``record.args`` を ``(client_addr, method, full_path,
    http_version, status_code)`` として読む。引数の位置に依らず文字列の引数すべてに
    :func:`mask_request_target_for_log` を掛けるので、書式
    （``INFO:     1.2.3.4:5678 - "GET /api/v1/files/0123abcd... HTTP/1.1" 200 OK``）は変えずに、
    uvicorn が引数の並びや数を変えても伏せる側に倒れる（接続元・メソッド・HTTP の版には伏せる対象が
    無いので変わらない）。``mask_bare_message`` のときは、引数の無い記録の本文そのものにも掛ける
    （uvicorn.access の記録はすべてリクエストの行のため。uvicorn.error には付けない＝通常の文言を
    崩さない）。ロガーに付けたフィルタの例外は uvicorn の応答処理まで伝わるため外へ出さない。
    """

    def __init__(self, *, mask_bare_message: bool) -> None:
        super().__init__()
        self._mask_bare_message = mask_bare_message

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if isinstance(args, Mapping):
                record.args = {name: _redact_log_argument(value) for name, value in args.items()}
            elif isinstance(args, tuple) and args:
                record.args = tuple(_redact_log_argument(value) for value in args)
            elif self._mask_bare_message and isinstance(record.msg, str):
                record.msg = _redact_log_argument(record.msg)
        except Exception:  # noqa: BLE001 -- 想定外の引数（独自の Mapping 等）でも例外を出さず、本文ごと伏せる
            record.msg = _REDACTION_FAILED_PLACEHOLDER
            record.args = ()
        return True


def _find_app_handler(app_logger: logging.Logger) -> logging.Handler | None:
    """本モジュールが以前に付けたハンドラを返す（無ければ None）。"""
    for handler in app_logger.handlers:
        if getattr(handler, _HANDLER_MARK, False):
            return handler
    return None


def _quiet_third_party_loggers() -> None:
    """INFO に送信先 URL を出す第三者ロガーを WARNING 以上に固定する（既に高ければそのまま）。"""
    for name in _QUIETED_THIRD_PARTY_LOGGERS:
        third_party = logging.getLogger(name)
        if third_party.level < logging.WARNING:
            third_party.setLevel(logging.WARNING)


def _attach_uvicorn_traceback_filter() -> None:
    """uvicorn.error にトレースバックの整形フィルタを1つだけ付ける。"""
    uvicorn_error = logging.getLogger(_UVICORN_ERROR_LOGGER_NAME)
    if not any(isinstance(existing, _UvicornTracebackFilter) for existing in uvicorn_error.filters):
        uvicorn_error.addFilter(_UvicornTracebackFilter())


def _attach_request_target_filter(logger_name: str, *, mask_bare_message: bool) -> None:
    """uvicorn のロガーにパス（クエリ）の伏せ字フィルタを1つだけ付ける。"""
    target = logging.getLogger(logger_name)
    if not any(isinstance(existing, _RequestTargetRedactionFilter) for existing in target.filters):
        target.addFilter(_RequestTargetRedactionFilter(mask_bare_message=mask_bare_message))


def install_log_redaction() -> bool:
    """uvicorn のログに伏せ字のフィルタを付ける（``APP_LOG_LEVEL`` に依らず常に・何度呼んでも1つ）。

    - uvicorn.access: パスの写真の鍵とクエリの値を伏せる。
    - uvicorn.error: WebSocket の行のパスを同じく伏せ、未処理例外のトレースバックを整形・マスクする。

    Returns:
        フィルタが付いている状態なら True（2回目以降の呼び出しも True）。付けられなければ False。

    ロガー（ハンドラではなく）に付けるので、uvicorn が起動時に ``logging.config.dictConfig`` で
    ハンドラを付け直しても外れない（dictConfig は既存のロガーのフィルタを消さない）。付ける処理の
    失敗で例外は投げない（ログのためにサービスの起動を止めない）。
    """
    try:
        _attach_request_target_filter(_UVICORN_ACCESS_LOGGER_NAME, mask_bare_message=True)
        _attach_request_target_filter(_UVICORN_ERROR_LOGGER_NAME, mask_bare_message=False)
        _attach_uvicorn_traceback_filter()
    except Exception:  # noqa: BLE001 -- 上記のとおり起動を止めない
        logger.warning(
            "logging: uvicorn のログの伏せ字フィルタを付けられませんでした", exc_info=True
        )
        return False
    return True


def configure_app_logging_from_env() -> bool:
    """環境変数 ``APP_LOG_LEVEL`` があれば、``app`` ロガーを stderr へ出す設定にする。

    Returns:
        設定したら True。環境変数が無い・空、または設定に失敗した場合は False。

    何度呼んでもハンドラ・フィルタは1つに保つ（2回目以降はレベルだけ更新する）。設定の失敗で
    例外は投げない（ログのためにサービスの起動を止めない）。
    """
    raw_level = os.environ.get(APP_LOG_LEVEL_ENV, "").strip()
    if not raw_level:
        return False

    level = _ALLOWED_LEVELS.get(raw_level.upper())
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    try:
        if _find_app_handler(app_logger) is None:
            handler = _AppLogHandler(sys.stderr)
            handler.setFormatter(AppLogFormatter())
            setattr(handler, _HANDLER_MARK, True)
            app_logger.addHandler(handler)
        app_logger.setLevel(level if level is not None else logging.INFO)
        _quiet_third_party_loggers()
        _attach_uvicorn_traceback_filter()
    except Exception:  # noqa: BLE001 -- ログ設定の失敗で起動を止めない（従来の出力のまま続行）
        logger.warning("logging: app.* のログ設定に失敗しました（従来どおりの出力で継続）", exc_info=True)
        return False

    if level is None:
        logger.warning(
            "logging: %s=%r は使えない値のため INFO で出力します"
            "（DEBUG / INFO / WARNING / ERROR / CRITICAL のいずれか）",
            APP_LOG_LEVEL_ENV,
            raw_level[:32],
        )
    logger.info(
        "logging: app.* のログを %s 以上で stderr へ出力します",
        logging.getLevelName(app_logger.level),
    )
    return True
