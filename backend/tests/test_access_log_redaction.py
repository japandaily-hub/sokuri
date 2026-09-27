"""アクセスログ（uvicorn.access）の伏せ字（app/core/app_logging.py・app/core/masking.py）のテスト。

背景（2026-09-27 のログ点検）: uvicorn は1リクエスト1行のアクセスログに、パスとクエリ文字列を
そのまま出す。写真の ``GET /api/v1/files/{storage_key}`` は無認証の capability URL なので、Render の
ログ（約7日・ダッシュボードの権限で読める）を読める人が写真を取れた。``/readyz?token=`` 等の
DIAG_TOKEN や検索語 ``?q=``（氏名・メールアドレスが入りうる）も残っていた。

ここでは次を確かめる:
- 伏せ字の関数（パスの鍵を先頭8字＋``...``・クエリは値を伏せる・それ以外は変えない）
- フィルタが uvicorn の書式を変えず、失敗しても例外を出さず、何度付けても1つであること
- 実際に uvicorn（h11・httptools）を起動してリクエストしたときの1行（別プロセス）。APP_LOG_LEVEL の
  有無に依らず効くこと。フィルタを外すと同じリクエストで鍵と値がそのまま出ること（陽性対照）も
  確かめ、この検査が漏れを捉えられることを示す
"""
from __future__ import annotations

import logging
import os
import pathlib
import re
import subprocess
import sys
import textwrap

import pytest
from uvicorn.logging import AccessFormatter

from app.core import app_logging
from app.core.masking import mask_query_string, mask_request_target_for_log

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]

#: 形式どおりの storage_key（32桁 hex＋拡張子）。先頭8字は "0123abcd"。
_STORAGE_KEY = "0123abcd" + "4567" * 6 + ".jpg"
_MASKED_KEY = "0123abcd..."

#: uvicorn（protocols/http）がアクセスログに渡す書式と、既定の AccessFormatter の書式。
_UVICORN_ACCESS_MESSAGE = '%s - "%s %s HTTP/%s" %d'
_UVICORN_ACCESS_FORMAT = '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'


@pytest.fixture
def uvicorn_loggers():
    """テスト中に付け外しした uvicorn.access・uvicorn.error のフィルタを元に戻す（import 時の分は残す）。"""
    targets = [logging.getLogger("uvicorn.access"), logging.getLogger("uvicorn.error")]
    saved = {target.name: list(target.filters) for target in targets}
    yield targets
    for target in targets:
        for added in [f for f in target.filters if f not in saved[target.name]]:
            target.removeFilter(added)
        for removed in [f for f in saved[target.name] if f not in target.filters]:
            target.addFilter(removed)


def _filters_of(logger_name: str, filter_type: type) -> list[logging.Filter]:
    return [f for f in logging.getLogger(logger_name).filters if isinstance(f, filter_type)]


def _access_record(full_path: str, *, method: str = "GET", status: int = 200) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "uvicorn/protocols/http/httptools_impl.py",
        484,
        _UVICORN_ACCESS_MESSAGE,
        ("203.0.113.5:4567", method, full_path, "1.1", status),
        None,
    )


def _format_like_uvicorn(record: logging.LogRecord) -> str:
    return AccessFormatter(_UVICORN_ACCESS_FORMAT, use_colors=False).format(record)


# ──────────────── 伏せ字の関数 ────────────────


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        # 写真の capability URL（GET 配信・PUT アップロード）は先頭8字＋"..."
        (f"/api/v1/files/{_STORAGE_KEY}", f"/api/v1/files/{_MASKED_KEY}"),
        (f"/api/v1/upload/{_STORAGE_KEY}", f"/api/v1/upload/{_MASKED_KEY}"),
        # 形式に合わない値（前後に文字が付いた鍵）も丸める。汎用の照合は英数字が隣接すると外れる
        (f"/api/v1/files/x{_STORAGE_KEY}", "/api/v1/files/x0123abc..."),
        (f"/api/v1/files/{_STORAGE_KEY}x", f"/api/v1/files/{_MASKED_KEY}"),
        # ルートの位置以外に入った鍵も丸める（mask_sensitive_in_text の安全網）
        (f"/api/v1/other/{_STORAGE_KEY}/x", f"/api/v1/other/{_MASKED_KEY}/x"),
        # クエリは値を伏せ、名前は残す
        (f"/api/v1/files/{_STORAGE_KEY}?token=SECRET&v=2", f"/api/v1/files/{_MASKED_KEY}?token=***&v=***"),
        ("/readyz?token=SECRET-DIAG-TOKEN", "/readyz?token=***"),
        ("/api/v1/_diag/client-ip?token=SECRET-DIAG-TOKEN", "/api/v1/_diag/client-ip?token=***"),
        ("/api/v1/admin/users?q=taro%40example.com&limit=20", "/api/v1/admin/users?q=***&limit=***"),
        # 何も伏せるものが無いパスは変えない
        ("/api/v1/upload/presign", "/api/v1/upload/presign"),
        ("/api/v1/cases/123/bids", "/api/v1/cases/123/bids"),
        ("/health", "/health"),
        ("/", "/"),
        ("/readyz?", "/readyz?"),
    ],
)
def test_mask_request_target_for_log(target: str, expected: str):
    assert mask_request_target_for_log(target) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("a=1&b=2", "a=***&b=***"),
        # "=" の無い組・識別子でない名前は組ごと伏せる（名前に値や鍵を入れられても残さない）
        ("SECRET-BARE-TOKEN", "***"),
        (f"{_STORAGE_KEY}=1", "***"),
        ("a%40b=1", "***"),
        ("=value", "***"),
        ("q[]=1", "***"),
        ("n" * 33 + "=1", "***"),
        # 空の組は捨てる
        ("a=1&&b=2&", "a=***&b=***"),
        ("", ""),
        # 値の中の "=" や ";" も値として伏せる
        ("token=a=b;c=d", "token=***"),
    ],
)
def test_mask_query_string(query: str, expected: str):
    assert mask_query_string(query) == expected


# ──────────────── フィルタ ────────────────


def _access_filter() -> logging.Filter:
    return app_logging._RequestTargetRedactionFilter(mask_bare_message=True)


def test_filter_masks_only_the_path_and_keeps_uvicorn_format():
    record = _access_record(f"/api/v1/files/{_STORAGE_KEY}?token=SECRET-QUERY-TOKEN")
    assert _access_filter().filter(record) is True
    line = _format_like_uvicorn(record)
    assert line == (
        f'INFO:     203.0.113.5:4567 - "GET /api/v1/files/{_MASKED_KEY}?token=*** HTTP/1.1" 200 OK'
    )
    assert _STORAGE_KEY not in line and "SECRET-QUERY-TOKEN" not in line


def test_filter_keeps_ipv6_client_address_and_other_arguments():
    record = _access_record(f"/api/v1/upload/{_STORAGE_KEY}", method="PUT", status=204)
    record.args = ("[2001:db8::1]:4567", *record.args[1:])
    _access_filter().filter(record)
    assert record.args == ("[2001:db8::1]:4567", "PUT", f"/api/v1/upload/{_MASKED_KEY}", "1.1", 204)


def test_filter_never_raises_and_hides_the_argument_on_failure(monkeypatch: pytest.MonkeyPatch):
    """ロガーのフィルタの例外は uvicorn の応答処理まで伝わる。失敗した引数は出さない側に倒す。"""

    def _broken_for_paths(value: str) -> str:
        if value.startswith("/"):
            raise RuntimeError("mask failed")
        return value

    monkeypatch.setattr(app_logging, "mask_request_target_for_log", _broken_for_paths)
    record = _access_record(f"/api/v1/files/{_STORAGE_KEY}")
    assert _access_filter().filter(record) is True
    line = _format_like_uvicorn(record)
    assert line == 'INFO:     203.0.113.5:4567 - "GET <hidden> HTTP/1.1" 200 OK'


def test_filter_hides_the_whole_record_when_arguments_cannot_be_read():
    """独自の Mapping 等で引数を読めないときも例外を出さず、本文ごと伏せる。"""

    class _BrokenMapping(dict):
        def items(self):  # noqa: ANN201
            raise RuntimeError("cannot iterate")

    record = _access_record(f"/api/v1/files/{_STORAGE_KEY}")
    record.args = _BrokenMapping(path=f"/api/v1/files/{_STORAGE_KEY}")
    assert _access_filter().filter(record) is True
    assert record.getMessage() == "<hidden>"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        # uvicorn が引数の並び・数を変えても（例: 応答時間を足す）パスは伏せる
        (
            ("203.0.113.5:4567", "1.1", "GET", f"/api/v1/files/{_STORAGE_KEY}?token=S", 200, 0.012),
            ("203.0.113.5:4567", "1.1", "GET", f"/api/v1/files/{_MASKED_KEY}?token=***", 200, 0.012),
        ),
        (("value",), ("value",)),
    ],
)
def test_filter_masks_paths_regardless_of_argument_layout(args: tuple, expected: tuple):
    record = logging.LogRecord("uvicorn.access", logging.INFO, "x.py", 1, "%s " * len(args), args, None)
    assert _access_filter().filter(record) is True
    assert record.args == expected


def test_filter_masks_mapping_arguments_and_bare_access_messages():
    mapped = logging.LogRecord(
        "uvicorn.access", logging.INFO, "x.py", 1, "%(path)s", ({"path": f"/files/{_STORAGE_KEY}"},), None
    )
    _access_filter().filter(mapped)
    assert mapped.args == {"path": f"/files/{_MASKED_KEY}"}

    # 引数の無い記録（uvicorn が本文を組み立てて渡すようになった場合）は本文ごと伏せる。
    bare_line = f'1.2.3.4:5 - "GET /api/v1/files/{_STORAGE_KEY}?token=S HTTP/1.1" 200'
    bare = logging.LogRecord("uvicorn.access", logging.INFO, "x.py", 1, bare_line, (), None)
    _access_filter().filter(bare)
    assert _STORAGE_KEY not in bare.getMessage() and "token=S" not in bare.getMessage()

    # uvicorn.error 用（mask_bare_message=False）は通常の文言を崩さない。
    plain_line = "Waiting for application startup?"
    plain = logging.LogRecord("uvicorn.error", logging.INFO, "x.py", 1, plain_line, (), None)
    app_logging._RequestTargetRedactionFilter(mask_bare_message=False).filter(plain)
    assert plain.getMessage() == plain_line


def test_uvicorn_error_websocket_line_is_masked(uvicorn_loggers: list[logging.Logger]):
    """WebSocket の接続拒否の行（uvicorn.error）にもパスとクエリが出る。同じく伏せる。"""
    app_logging.install_log_redaction()
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "uvicorn/protocols/websockets/websockets_impl.py",
        279,
        '%s - "WebSocket %s" 403',
        ("203.0.113.5:4567", f"/api/v1/files/{_STORAGE_KEY}?token=SECRET-WS-TOKEN"),
        None,
    )
    for installed in logging.getLogger("uvicorn.error").filters:
        installed.filter(record)
    assert record.getMessage() == f'203.0.113.5:4567 - "WebSocket /api/v1/files/{_MASKED_KEY}?token=***" 403'


def test_install_is_idempotent(uvicorn_loggers: list[logging.Logger]):
    assert app_logging.install_log_redaction() is True
    assert app_logging.install_log_redaction() is True
    assert len(_filters_of("uvicorn.access", app_logging._RequestTargetRedactionFilter)) == 1
    assert len(_filters_of("uvicorn.error", app_logging._RequestTargetRedactionFilter)) == 1
    assert len(_filters_of("uvicorn.error", app_logging._UvicornTracebackFilter)) == 1


def test_app_main_installs_filters_on_import():
    """app.main の import で付く（APP_LOG_LEVEL の有無に依らないことは下の別プロセスの検査で見る）。"""
    import app.main  # noqa: F401 -- import 時に付く

    assert len(_filters_of("uvicorn.access", app_logging._RequestTargetRedactionFilter)) == 1
    assert len(_filters_of("uvicorn.error", app_logging._RequestTargetRedactionFilter)) == 1
    assert len(_filters_of("uvicorn.error", app_logging._UvicornTracebackFilter)) == 1


# ──────────────── 実際の uvicorn での1行（別プロセス） ────────────────

_CHILD_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import logging
    import os
    import sys

    sys.path.insert(0, os.getcwd())

    import httpx
    import uvicorn
    from uvicorn.config import Config

    KEY = os.environ["PROBE_STORAGE_KEY"]


    async def _serve_and_request(http_impl, marker):
        # uvicorn の CLI と同じく、Config の生成時に既定のログ設定（dictConfig）が走り、serve() の中で
        # app.main が読み込まれる（本番の起動順と同じ）。lifespan は DB を使うので切る。
        # port=0 で OS に空きポートを選ばせ、起動後に実際のポートを読む（空きを探して閉じてから
        # 使うと、その間に他のプロセスに取られうる）。
        config = Config(app="app.main:app", host="127.0.0.1", port=0, http=http_impl, lifespan="off")
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve())
        for _ in range(400):
            if server.started:
                break
            if serve_task.done():
                serve_task.result()
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("uvicorn が起動しませんでした")
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url="http://127.0.0.1:%d" % port) as client:
            await client.get("/api/v1/files/" + KEY, params={"token": "SECRET-QUERY-" + marker, "v": marker})
            await client.put("/api/v1/upload/" + KEY, params={"marker": marker}, content=b"x")
            await client.get("/readyz", params={"token": "SECRET-DIAG-" + marker})
        server.should_exit = True
        await serve_task


    async def _main():
        await _serve_and_request("h11", "h11")
        await _serve_and_request("httptools", "httptools")
        # 陽性対照: フィルタを外すと、同じリクエストで鍵とクエリの値がそのまま出る。
        access = logging.getLogger("uvicorn.access")
        for existing in list(access.filters):
            access.removeFilter(existing)
        await _serve_and_request("h11", "control")


    asyncio.run(_main())
    """
)

_ACCESS_LINE_RE = re.compile(
    r'^INFO: {5}127\.0\.0\.1:\d+ - "(?P<method>GET|PUT) (?P<target>\S+) HTTP/1\.1" \d{3} '
)


#: 子プロセスで上書きする（親の値を持ち込まない）環境変数。
_CHILD_OVERRIDDEN_ENV = frozenset(
    {"APP_LOG_LEVEL", "DATABASE_URL", "APP_ENV", "JWT_SECRET", "STORAGE_BACKEND", "STORAGE_DIR"}
)


def _run_uvicorn_child(tmp_path: pathlib.Path, app_log_level: str | None) -> list[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _CHILD_OVERRIDDEN_ENV
    }
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'child.db').as_posix()}",
            "APP_ENV": "development",
            "JWT_SECRET": "x" * 64,
            "STORAGE_BACKEND": "local",
            "STORAGE_DIR": str(tmp_path / "storage"),
            "PROBE_STORAGE_KEY": _STORAGE_KEY,
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
    # uvicorn の既定設定ではアクセスログは stdout、それ以外（uvicorn.error・app.*）は stderr に出る。
    return [line for line in result.stdout.splitlines() if _ACCESS_LINE_RE.match(line)]


@pytest.mark.parametrize("app_log_level", [None, "INFO"])
def test_real_uvicorn_access_log_hides_storage_key_and_query_values(
    tmp_path: pathlib.Path, app_log_level: str | None
):
    lines = _run_uvicorn_child(tmp_path, app_log_level)
    matches = [_ACCESS_LINE_RE.match(line) for line in lines]
    targets = [f"{match.group('method')} {match.group('target')}" for match in matches if match]

    # h11・httptools の2回は伏せ字（書式は uvicorn のまま＝上の正規表現に一致している）。
    masked = [
        f"GET /api/v1/files/{_MASKED_KEY}?token=***&v=***",
        f"PUT /api/v1/upload/{_MASKED_KEY}?marker=***",
        "GET /readyz?token=***",
    ]
    assert targets[:6] == masked * 2
    for marker in ("h11", "httptools"):
        leaked = (f"SECRET-QUERY-{marker}", f"SECRET-DIAG-{marker}")
        assert not any(secret in line for secret in leaked for line in lines)
    assert not any(_STORAGE_KEY in line for line in lines[:6])

    # 陽性対照: フィルタを外した3回目は鍵と値がそのまま出る（この検査が漏れを捉えられる）。
    assert targets[6:] == [
        f"GET /api/v1/files/{_STORAGE_KEY}?token=SECRET-QUERY-control&v=control",
        f"PUT /api/v1/upload/{_STORAGE_KEY}?marker=control",
        "GET /readyz?token=SECRET-DIAG-control",
    ]
