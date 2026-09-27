"""app.* ロガーの本番ログ設定（app/core/app_logging.py）と起動経路（start.sh）のテスト。

背景（2026-09-27 に Render のログで実測）: 本番は ``uvicorn app.main:app`` で起動し、uvicorn は
``uvicorn.*`` のロガーしか設定しない。そのため app.* の INFO（起動時シード・運営操作の監査ログ）
が1行も残らず、WARNING 以上もレベル・ロガー名の無い本文だけ（logging.lastResort）で出ていた。

ここでは次を確かめる:
- 設定関数の単体の振る舞い（有効にする条件・ハンドラを増やさない・不正な値・書式・caplog）
- uvicorn の CLI と同じ既定のログ設定の上で app.main を読み込んだとき、起動時の INFO が
  書式付きで1回だけ出ること（別プロセスで実行する: ロガーの設定はプロセス全体に効くため）
- start.sh が uvicorn の起動前に APP_LOG_LEVEL の既定値を渡していること
"""
from __future__ import annotations

import io
import logging
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from app.core import app_logging

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def app_logger(monkeypatch: pytest.MonkeyPatch):
    """テスト中に書き換えたロガーの状態を元に戻す。

    ``app`` のハンドラ・レベル・伝播に加えて、設定関数が触る uvicorn.error のフィルタと
    httpx / httpcore のレベルも戻す（他のテストへ持ち越さない）。
    """
    target = logging.getLogger(app_logging.APP_LOGGER_NAME)
    saved_handlers = list(target.handlers)
    saved_level = target.level
    saved_propagate = target.propagate
    uvicorn_error = logging.getLogger("uvicorn.error")
    saved_uvicorn_filters = list(uvicorn_error.filters)
    saved_third_party_levels = {
        name: logging.getLogger(name).level for name in app_logging._QUIETED_THIRD_PARTY_LOGGERS
    }
    monkeypatch.delenv(app_logging.APP_LOG_LEVEL_ENV, raising=False)
    yield target
    for handler in list(target.handlers):
        if handler not in saved_handlers:
            target.removeHandler(handler)
            handler.close()
    target.setLevel(saved_level)
    target.propagate = saved_propagate
    for added in [f for f in uvicorn_error.filters if f not in saved_uvicorn_filters]:
        uvicorn_error.removeFilter(added)
    for name, level in saved_third_party_levels.items():
        logging.getLogger(name).setLevel(level)


def _marked_handlers(target: logging.Logger) -> list[logging.Handler]:
    return [h for h in target.handlers if getattr(h, app_logging._HANDLER_MARK, False)]


# ──────────────── 設定関数の単体 ────────────────


def test_does_nothing_without_env(app_logger: logging.Logger):
    """テスト・ローカル開発（APP_LOG_LEVEL 未設定）では従来どおり何も変えない。"""
    level_before = app_logger.level
    assert app_logging.configure_app_logging_from_env() is False
    assert _marked_handlers(app_logger) == []
    assert app_logger.level == level_before


def test_blank_env_is_treated_as_unset(app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "  ")
    assert app_logging.configure_app_logging_from_env() is False
    assert _marked_handlers(app_logger) == []


def test_configures_one_handler_and_keeps_propagation(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "info")
    assert app_logging.configure_app_logging_from_env() is True
    handlers = _marked_handlers(app_logger)
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, app_logging.AppLogFormatter)
    assert app_logger.level == logging.INFO
    # root へ伝播し続ける（caplog など root に付くハンドラが従来どおり拾える）。
    assert app_logger.propagate is True
    # root には何も付けない（第三者ライブラリの INFO は流さない）。
    assert not any(getattr(h, app_logging._HANDLER_MARK, False) for h in logging.getLogger().handlers)


def test_repeated_calls_keep_one_handler_and_update_level(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "INFO")
    app_logging.configure_app_logging_from_env()
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "WARNING")
    app_logging.configure_app_logging_from_env()
    assert len(_marked_handlers(app_logger)) == 1
    assert app_logger.level == logging.WARNING


def test_invalid_level_falls_back_to_info_with_warning(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """綴り誤り等の値でも起動は止めず、INFO に倒して分かるように WARNING を出す。"""
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "verbose")
    with caplog.at_level(logging.WARNING, logger=app_logging.__name__):
        assert app_logging.configure_app_logging_from_env() is True
    assert app_logger.level == logging.INFO
    assert any("APP_LOG_LEVEL='verbose'" in r.getMessage() for r in caplog.records)


def test_handler_writes_formatted_line_to_stderr(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "INFO")
    app_logging.configure_app_logging_from_env()
    logging.getLogger("app.tests.probe").info("probe %s", "ok")
    lines = capsys.readouterr().err.splitlines()
    assert lines.count("INFO [app.tests.probe] probe ok") == 1


def test_caplog_still_captures_app_records_exactly_once(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "INFO")
    app_logging.configure_app_logging_from_env()
    with caplog.at_level(logging.INFO):
        logging.getLogger("app.tests.probe").info("probe-caplog")
    assert [r.getMessage() for r in caplog.records].count("probe-caplog") == 1


def test_configure_quiets_url_logging_libraries_and_filters_uvicorn_tracebacks_once(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
):
    """httpx / httpcore は INFO に送信先 URL をクエリごと出す（LINE の検証は access_token をクエリで
    渡す）。将来 root にハンドラが付いても流れないよう WARNING に固定する。何度呼んでも増えない。"""
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "INFO")
    app_logging.configure_app_logging_from_env()
    app_logging.configure_app_logging_from_env()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING
    uvicorn_filters = [
        f for f in logging.getLogger("uvicorn.error").filters if isinstance(f, app_logging._UvicornTracebackFilter)
    ]
    assert len(uvicorn_filters) == 1


def test_uvicorn_error_traceback_is_prefixed_escaped_and_masked(
    app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
):
    """未処理例外のトレースバック（uvicorn.error）にも同じ安全網を掛ける。書式は uvicorn 側のまま。"""
    monkeypatch.setenv(app_logging.APP_LOG_LEVEL_ENV, "INFO")
    app_logging.configure_app_logging_from_env()
    stream = io.StringIO()
    capture = logging.StreamHandler(stream)
    capture.setFormatter(logging.Formatter("%(levelname)s:    %(message)s"))
    uvicorn_error = logging.getLogger("uvicorn.error")
    # 他のテストの logging.config（disable_existing_loggers）で無効化されていても検査できるようにする。
    monkeypatch.setattr(uvicorn_error, "disabled", False)
    uvicorn_error.addHandler(capture)
    try:
        try:
            raise ValueError("Key (email)=(taro@example.com) already exists.\nINFO [app.main] forged")
        except ValueError as exc:
            uvicorn_error.error("Exception in ASGI application\n", exc_info=exc)
    finally:
        uvicorn_error.removeHandler(capture)
    lines = stream.getvalue().splitlines()
    assert lines[0] == "ERROR:    Exception in ASGI application"
    assert lines[1] == "  | Traceback (most recent call last):"
    assert all(line.startswith("  | ") for line in lines[1:])
    assert "  | ValueError: Key (email)=(t***@example.com) already exists." in lines
    assert "  | INFO [app.main] forged" in lines
    assert "taro@example.com" not in stream.getvalue()


def test_handle_error_does_not_write_raw_arguments():
    """書式と引数が合わないとき、標準の handleError は引数の生値を stderr に書く。種類と位置だけにする。"""
    stream = io.StringIO()
    handler = app_logging._AppLogHandler(stream)
    handler.setFormatter(app_logging.AppLogFormatter())
    record = logging.LogRecord(
        "app.tests.probe", logging.INFO, "/app/app/x.py", 12, "%s %s", ("secret-arg@example.com",), None
    )
    handler.handle(record)
    assert stream.getvalue() == "LOGGING_ERROR [app.tests.probe] TypeError at /app/app/x.py:12\n"


# ──────────────── 書式 ────────────────


def test_formatter_escapes_newlines_and_masks_emails():
    """利用者の入力を含む値で偽のログ行を作れないよう、本文の改行は1行に収める。"""
    record = logging.LogRecord(
        "app.main",
        logging.WARNING,
        __file__,
        1,
        "email=%s\nINFO [app.main] forged",
        ("taro@example.com",),
        None,
    )
    text = app_logging.AppLogFormatter().format(record)
    assert text == "WARNING [app.main] email=t***@example.com\\nINFO [app.main] forged"


def test_formatter_escapes_other_line_breaks_and_control_characters():
    """ログビューアが改行とみなす NEL・U+2028・U+2029 や端末を操作できる ESC も1行の中に閉じ込める。

    ツール経由の書き込みでエスケープ表記が実体化する事故を避けるため、入力は chr() で組み立てる。
    """
    backslash = chr(92)
    raw = "".join(chr(code) for code in (0x0D, 0x0B, 0x0C, 0x1B, 0x00, 0x7F, 0x85, 0x2028, 0x2029))
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "a%sb", (raw + chr(9) + "日本語",), None)
    text = app_logging.AppLogFormatter().format(record)
    assert len(text.splitlines()) == 1
    escaped = ["r", "x0b", "x0c", "x1b", "x00", "x7f", "x85", "u2028", "u2029"]
    assert text == "INFO [app.x] a" + "".join(backslash + e for e in escaped) + chr(9) + "日本語b"


def test_formatter_escapes_bidi_and_zero_width_characters():
    """表示順を入れ替える双方向制御文字や、見えないゼロ幅文字も見える表記にする（入力は chr() で作る）。"""
    backslash = chr(92)
    raw = chr(0x202E) + chr(0x2066) + chr(0x200B) + chr(0xFEFF)
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "a%sb", (raw,), None)
    text = app_logging.AppLogFormatter().format(record)
    assert text == "INFO [app.x] a" + "".join(backslash + e for e in ["u202e", "u2066", "u200b", "ufeff"]) + "b"


def test_formatter_masks_storage_keys_and_line_user_ids():
    """storage_key（無認証の capability URL）と LINE の userId（Push の宛先）も出力直前に丸める。"""
    record = logging.LogRecord(
        "app.x",
        logging.WARNING,
        __file__,
        1,
        "key=%s to=%s id=%s",
        ("0123456789abcdef0123456789abcdef.jpg", "U0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
        None,
    )
    text = app_logging.AppLogFormatter().format(record)
    # 拡張子の無い 32 桁 hex（案件等の ID）はそのまま残す。
    assert text == "WARNING [app.x] key=01234567... to=U012… id=0123456789abcdef0123456789abcdef"


def test_formatter_keeps_traceback_and_masks_emails_in_it():
    try:
        raise ValueError("Key (email)=(taro@example.com) already exists.")
    except ValueError:
        record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "保存に失敗", (), sys.exc_info())
    text = app_logging.AppLogFormatter().format(record)
    first, *rest = text.split("\n")
    assert first == "ERROR [app.x] 保存に失敗"
    assert rest[0] == "  | Traceback (most recent call last):"
    assert all(line.startswith("  | ") for line in rest)
    assert "taro@example.com" not in text
    assert "(t***@example.com)" in text
    # record 側のキャッシュ（他のハンドラと共有する）は書き換えない。
    assert "taro@example.com" in (record.exc_text or "")


def test_formatter_keeps_forged_lines_inside_traceback_indented():
    """例外文に改行と偽の行（"INFO [app...] ..."）が入っていても、行頭は必ず継続の印になる。"""
    forged = "INFO [app.api.v1.endpoints.admin] admin: 口座情報を復号しました - admin_id=other"
    try:
        raise ValueError("x\n" + forged + chr(0x2028) + forged)
    except ValueError:
        record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "失敗", (), sys.exc_info())
    lines = app_logging.AppLogFormatter().format(record).splitlines()
    assert lines[0] == "ERROR [app.x] 失敗"
    assert all(line.startswith("  | ") for line in lines[1:])
    assert f"  | {forged}" + chr(92) + "u2028" + forged in lines


# ──────────────── uvicorn と同じ設定の上での実挙動（別プロセス） ────────────────

_CHILD_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import logging
    import os
    import sys

    sys.path.insert(0, os.getcwd())

    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles


    @compiles(JSONB, "sqlite")
    def _jsonb_as_json(type_, compiler, **kw):
        return "JSON"


    # uvicorn の CLI と同じ既定のログ設定（Config の生成時に configure_logging が走る）。
    from uvicorn.config import Config

    Config(app="app.main:app")

    import app.main  # APP_LOG_LEVEL があれば app.* の出力を設定してから create_app() する

    import app.db.models  # noqa: F401  -- 全モデルを Base.metadata に登録する
    from app.db.base import Base
    from app.db.session import engine


    async def _main():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await app.main._run_seed()
        await engine.dispose()


    asyncio.run(_main())
    logging.getLogger("app.probe").warning("probe-warning")
    logging.getLogger("uvicorn.error").info("probe-uvicorn")
    # httpx は INFO に送信先 URL をクエリごと出す（LINE の検証は access_token をクエリで渡す）。
    logging.getLogger("httpx").info(
        "HTTP Request: GET https://api.line.me/oauth2/v2.1/verify?access_token=SECRET-ACCESS-TOKEN"
    )
    # 未処理例外は uvicorn.error が "Exception in ASGI application" として出す。
    try:
        raise ValueError("Key (email)=(taro@example.com) already exists.")
    except ValueError as exc:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application\\n", exc_info=exc)
    sys.stderr.write("ROOT_HANDLERS=%d\\n" % len(logging.getLogger().handlers))
    """
)


def _run_child(tmp_path: pathlib.Path, app_log_level: str | None) -> list[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"APP_LOG_LEVEL", "DATABASE_URL", "APP_ENV", "JWT_SECRET", "STORAGE_BACKEND"}
    }
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'child.db').as_posix()}",
            "APP_ENV": "development",
            "JWT_SECRET": "x" * 64,
            "STORAGE_BACKEND": "local",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if app_log_level is not None:
        env["APP_LOG_LEVEL"] = app_log_level
    result = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stderr.splitlines()


def test_uvicorn_default_logging_plus_app_logging_emits_startup_info_once(tmp_path: pathlib.Path):
    """本番と同じ条件（uvicorn の既定設定＋APP_LOG_LEVEL=INFO）で起動時の INFO が1回ずつ出る。"""
    lines = _run_child(tmp_path, "INFO")

    assert lines.count("INFO [app.core.app_logging] logging: app.* のログを INFO 以上で stderr へ出力します") == 1
    # create_app() が import 時に出す起動ログも拾える（設定がアプリ生成より前）。
    assert sum(line.startswith("INFO [app.main] [startup] storage backend=local") for line in lines) == 1
    # Render で確認する目印（seed の完了ログ）が二重にならず1回だけ出る。
    assert lines.count("INFO [app.main] seed: チャネルシード完了") == 1
    # WARNING は書式付きで1回だけ（lastResort の本文だけの行が重ならない）。
    assert lines.count("WARNING [app.probe] probe-warning") == 1
    assert "probe-warning" not in lines
    # uvicorn 自身の書式は変えない。
    assert lines.count("INFO:     probe-uvicorn") == 1
    # root にはハンドラを付けず、httpx の INFO（クエリの access_token）も流さない。
    assert "ROOT_HANDLERS=0" in lines
    assert not any("SECRET-ACCESS-TOKEN" in line for line in lines)
    # 未処理例外のトレースバックも継続の印付き・マスク済み（見出しは uvicorn の書式のまま）。
    assert lines.count("ERROR:    Exception in ASGI application") == 1
    assert "  | Traceback (most recent call last):" in lines
    assert "  | ValueError: Key (email)=(t***@example.com) already exists." in lines
    assert not any("taro@example.com" in line for line in lines)


def test_without_app_log_level_app_info_is_dropped_as_before(tmp_path: pathlib.Path):
    """APP_LOG_LEVEL が無い場合は従来どおり（本番で起きていた症状の再現）。

    上のテストの検査が「何を見れば修正の有無を区別できるか」を正しく捉えていることの確認も兼ねる。
    """
    lines = _run_child(tmp_path, None)

    assert not any("seed: チャネルシード完了" in line for line in lines)
    assert not any("[startup] storage backend" in line for line in lines)
    # lastResort はレベルもロガー名も付けず本文だけを出す。
    assert "probe-warning" in lines
    assert lines.count("INFO:     probe-uvicorn") == 1
    # 未処理例外のトレースバックは素通し（安全網は APP_LOG_LEVEL があるときだけ効く）。
    assert "ROOT_HANDLERS=0" in lines
    assert "ValueError: Key (email)=(taro@example.com) already exists." in lines


# ──────────────── 起動経路（start.sh） ────────────────


def test_start_sh_exports_app_log_level_before_launching_uvicorn():
    """本番の起動経路が uvicorn の前に APP_LOG_LEVEL の既定値を渡している（外すと INFO が消える）。"""
    lines = [line.strip() for line in (_BACKEND_DIR / "start.sh").read_text(encoding="utf-8").splitlines()]
    export_line = 'export APP_LOG_LEVEL="${APP_LOG_LEVEL:-INFO}"'
    assert export_line in lines
    exec_index = next(i for i, line in enumerate(lines) if line.startswith("exec uvicorn app.main:app"))
    assert lines.index(export_line) < exec_index
