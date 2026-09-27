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
    - 本文の改行などの制御文字はエスケープして1行に収める（利用者の入力を含む値で偽のログ行を
      作られないようにする: CWE-117。ログビューアが改行とみなす U+0085・U+2028・U+2029 や
      端末を操作できる ESC も含む。タブはそのまま）。例外のトレースバックは従来どおり複数行で出す。
    - 出力の直前に文中のメールアドレスを :func:`mask_emails_in_text` でマスクする（呼び出し側の
      マスク漏れや、例外文に含まれる値への安全網）。呼び出し側では引き続き
      :func:`app.core.masking.mask_email` で個別にマスクすること。
"""

from __future__ import annotations

import logging
import os
import sys

from app.core.masking import mask_emails_in_text

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


def _escape_for(code_point: int) -> str:
    """制御文字1字を、見て分かるエスケープ表記（``\\n`` ``\\x1b`` ``\\u2028`` 等）にする。"""
    named = {0x0A: "\\n", 0x0D: "\\r"}
    if code_point in named:
        return named[code_point]
    return f"\\x{code_point:02x}" if code_point <= 0xFF else f"\\u{code_point:04x}"


#: 本文のエスケープ対象（``str.translate`` 用の表）。C0 制御文字（タブを除く）・DEL・
#: C1 制御文字（NEL を含む）と、``str.splitlines`` やログビューアが行区切りとみなす
#: U+2028・U+2029。
_MESSAGE_ESCAPES: dict[int, str] = {
    code_point: _escape_for(code_point)
    for code_point in (
        *range(0x00, 0x09),
        *range(0x0A, 0x20),
        *range(0x7F, 0xA0),
        0x2028,
        0x2029,
    )
}

logger = logging.getLogger(__name__)


class AppLogFormatter(logging.Formatter):
    """``LEVEL [ロガー名] 本文`` の1行（例外時はその後ろにトレースバック）へ整形する。

    書式は start.sh が転写する alembic のログ（``INFO  [alembic.runtime.migration] ...``）と
    同じ並びにそろえる。時刻は Render がログ1行ごとに付けるので含めない。
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage().translate(_MESSAGE_ESCAPES)
        text = f"{record.levelname} [{record.name}] {message}"
        # トレースバックの文字列は標準の Formatter と同じく record にキャッシュする（他の
        # ハンドラも同じ文字列を使う）。マスクは戻り値にだけ掛け、record 自体は書き換えない。
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            text = f"{text}\n{record.exc_text}"
        if record.stack_info:
            text = f"{text}\n{self.formatStack(record.stack_info)}"
        return mask_emails_in_text(text)


def _find_app_handler(app_logger: logging.Logger) -> logging.Handler | None:
    """本モジュールが以前に付けたハンドラを返す（無ければ None）。"""
    for handler in app_logger.handlers:
        if getattr(handler, _HANDLER_MARK, False):
            return handler
    return None


def configure_app_logging_from_env() -> bool:
    """環境変数 ``APP_LOG_LEVEL`` があれば、``app`` ロガーを stderr へ出す設定にする。

    Returns:
        設定したら True。環境変数が無い・空、または設定に失敗した場合は False。

    何度呼んでもハンドラは1つに保つ（2回目以降はレベルだけ更新する）。設定の失敗で
    例外は投げない（ログのためにサービスの起動を止めない）。
    """
    raw_level = os.environ.get(APP_LOG_LEVEL_ENV, "").strip()
    if not raw_level:
        return False

    level = _ALLOWED_LEVELS.get(raw_level.upper())
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    try:
        if _find_app_handler(app_logger) is None:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(AppLogFormatter())
            setattr(handler, _HANDLER_MARK, True)
            app_logger.addHandler(handler)
        app_logger.setLevel(level if level is not None else logging.INFO)
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
