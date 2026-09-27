"""メタガード: 送信元 IP は正本（app.core.client_ip）だけが読むこと。

2026-09-27: 公開の POST /operator-applications が正本を使わず、独自の
``app/core/request_ip.get_client_ip`` で X-Forwarded-For の先頭（利用者が自由に書ける値）を
読んでいたため、ヘッダを付け替えるだけで IP 単位の回数制限を回避でき、記録される IP も
偽の値になっていた。client_ip.py の docstring が「ヘッダ取得を個別に実装すると判定が乖離し
無言のバイパスに戻る」と警告していたとおりの事態で、注意書きだけでは防げなかった。

app/ 配下で、送信元 IP を運ぶヘッダ名の文字列や ``request.client.host`` が許可したファイル
以外に現れたら落とす。送信元 IP が必要なら ``resolve_client_ip_with_reason`` か
``RateLimitGuard`` を使うこと（docs/ops/incidents.md 原則3「教訓はテストにする」）。

文字列は構文木の定数として完全一致で調べるため、コメントや docstring・ログ文中の
言及（"X-Forwarded-For ヘッダが…" 等）は対象にならない。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# ヘッダ名（小文字）→ そのヘッダ名を書いてよいファイル（app/ からの相対パス）。
_IP_HEADER_ALLOWED_FILES: dict[str, frozenset[str]] = {
    # 正本の取得口（get_xff_raw。重複ヘッダを getlist で結合する）。
    "x-forwarded-for": frozenset({"core/client_ip.py"}),
    # /api/v1/_diag/client-ip の参考表示だけ（CF ゾーンが自ゾーンではないため判定には使えない）。
    "cf-connecting-ip": frozenset({"main.py"}),
    "x-real-ip": frozenset(),
    "forwarded": frozenset(),
    "true-client-ip": frozenset(),
    # 署名付き中継IP（I8）。署名検証（verify_request_client_ip_relay）を経ずに
    # このヘッダを読む実装を禁止する。
    "x-katazuke-client-ip-relay": frozenset({"core/client_ip_relay.py"}),
}

# request.client.host（プロキシ配下では常にプロキシ自身の IP）を書いてよいファイル。
# 正本のフォールバックと、診断エンドポイントの peer 表示だけ。
_CLIENT_HOST_ALLOWED_FILES = frozenset({"core/client_ip.py", "main.py"})

# 署名付き中継IP（I8）の検証関連シンボル → それを import・参照してよいファイル
# （2回目 security review L-C）。署名検証（verify_client_ip_relay /
# verify_request_client_ip_relay）を経ずに RELAY_HEADER_NAME で直接ヘッダの値を
# 読み、検証済みのふりをして利用者IPとして使う実装が紛れ込むことを防ぐ
# （上記の X-Forwarded-For 版の再発防止と同じ動機）。core/client_ip_relay.py は
# 検証ロジックの定義元、api/rate_limit_deps.py はその唯一の呼び出し元。
_RELAY_SYMBOL_ALLOWED_FILES = frozenset({"core/client_ip_relay.py", "api/rate_limit_deps.py"})
_RELAY_RESTRICTED_SYMBOLS = frozenset(
    {"RELAY_HEADER_NAME", "verify_client_ip_relay", "verify_request_client_ip_relay"}
)


def _app_sources() -> list[tuple[str, ast.AST]]:
    sources = []
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(APP_DIR).as_posix()
        sources.append((relative, ast.parse(path.read_text(encoding="utf-8"), filename=relative)))
    return sources


def test_app_sources_found():
    relatives = {relative for relative, _ in _app_sources()}
    assert "core/client_ip.py" in relatives
    assert "main.py" in relatives


def test_ip_headers_are_read_only_by_the_canonical_module():
    violations = []
    for relative, tree in _app_sources():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            header = node.value.strip().lower()
            allowed = _IP_HEADER_ALLOWED_FILES.get(header)
            if allowed is not None and relative not in allowed:
                violations.append(f"{relative}:{node.lineno} {node.value!r}")
    assert not violations, (
        "送信元 IP のヘッダを正本（app/core/client_ip.py）以外で読んでいます。"
        "resolve_client_ip_with_reason か RateLimitGuard を使ってください: " + ", ".join(violations)
    )


def test_request_client_host_is_used_only_by_the_canonical_module():
    violations = []
    for relative, tree in _app_sources():
        if relative in _CLIENT_HOST_ALLOWED_FILES:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "host"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "client"
            ):
                violations.append(f"{relative}:{node.lineno}")
    assert not violations, (
        "request.client.host を直接使っています（プロキシ配下では全員が同じ IP になる）。"
        "resolve_client_ip_with_reason を使ってください: " + ", ".join(violations)
    )


def test_relay_verification_symbols_used_only_by_allowed_files():
    """署名付き中継IP（I8）の検証関連シンボルを許可ファイル以外で
    import・参照することを禁止する（2回目 security review L-C）。

    ``ast.alias``（``import``/``from ... import`` の名前）・``ast.Name``
    （変数参照・関数呼び出し）・``ast.Attribute``（``module.attr`` 形式の
    参照）の3種を横断して調べる。docstring・コメント・文字列リテラル中の
    言及は対象にならない（識別子としての参照のみを検出するため、上記
    ``_IP_HEADER_ALLOWED_FILES`` のような文字列定数の完全一致検査とは
    別の検査軸になる）。
    """
    violations = []
    for relative, tree in _app_sources():
        if relative in _RELAY_SYMBOL_ALLOWED_FILES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.alias):
                name = node.name
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            else:
                continue
            if name in _RELAY_RESTRICTED_SYMBOLS:
                violations.append(f"{relative}:{node.lineno} {name}")
    assert not violations, (
        "署名付き中継IPの検証関連シンボル（RELAY_HEADER_NAME・"
        "verify_client_ip_relay・verify_request_client_ip_relay）を、"
        "core/client_ip_relay.py・api/rate_limit_deps.py 以外で参照しています"
        "（署名検証を経ずにヘッダの値を使う実装の混入を防ぐため禁止）: "
        + ", ".join(violations)
    )
