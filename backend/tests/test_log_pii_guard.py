"""ログに生の個人情報を書かないためのガード。

2026-09-27: 本番で app.* の INFO を出すようにするにあたり、app 配下の logging 呼び出しを全件
点検し、生のメールアドレスを書いていた箇所（admin 権限の付与・剥奪、アカウント削除、口座情報・
本人確認書類の閲覧監査の admin_email 等）を ``mask_email`` へ直した。Render のログは第三者の
基盤に約7日残り、ダッシュボードの閲覧権限だけで読めるため、同じ書き方が戻ってきたら CI で落とす。

あわせて、自由文中のメールアドレスをまとめてマスクする ``mask_emails_in_text`` の振る舞いを確かめる。
"""
from __future__ import annotations

import ast
import pathlib
import re
import time

import pytest

from app.core.masking import mask_emails_in_text

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
_APP_DIR = _BACKEND_DIR / "app"

_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
)
#: この関数の引数の内側はマスク済みとみなして検査しない。
_MASKING_FUNCS = frozenset({"mask_email", "mask_emails_in_text"})
#: メールアドレス（またはその一覧）を表す名前: email / emails / xxx_email / xxx_emails。
_EMAIL_NAME_RE = re.compile(r"(?:^|_)emails?$")


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_logging_call(node: ast.Call) -> bool:
    """``logger.info(...)`` / ``logging.warning(...)`` 等の呼び出しか。

    受け手の名前に "log" を含むものだけを見る（app 配下は全モジュールが
    ``logger = logging.getLogger(__name__)`` の規約。``l = logging.getLogger(...)`` のような
    別名は検出できないので使わないこと）。
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
        return False
    return "log" in _callee_name(func.value).lower()


def _names_an_email(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return bool(_EMAIL_NAME_RE.search(node.attr))
    if isinstance(node, ast.Name):
        return bool(_EMAIL_NAME_RE.search(node.id))
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return isinstance(node.slice.value, str) and bool(_EMAIL_NAME_RE.search(node.slice.value))
    return False


def _is_email_lookup_call(node: ast.Call) -> bool:
    """``obj.get("email")`` や ``getattr(obj, "contact_email")`` のような取り出しか。"""
    key: ast.expr | None = None
    if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        key = node.args[0]
    elif isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
        key = node.args[1]
    return (
        isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and bool(_EMAIL_NAME_RE.search(key.value))
    )


def _raw_email_expressions(node: ast.AST):
    """マスク関数を通っていない「メールアドレスらしい式」を列挙する。"""
    if isinstance(node, ast.Call):
        if _callee_name(node.func) in _MASKING_FUNCS:
            return
        if _is_email_lookup_call(node):
            yield node
            return
        # 呼び出される関数名そのもの（例: is_placeholder_email(...)）は値ではないので見ない。
        # ただし user.email.lower() の user.email のような受け手側は値として検査する。
        if isinstance(node.func, ast.Attribute):
            yield from _raw_email_expressions(node.func.value)
        for child in [*node.args, *(kw.value for kw in node.keywords)]:
            yield from _raw_email_expressions(child)
        return
    if _names_an_email(node):
        yield node
        return
    for child in ast.iter_child_nodes(node):
        yield from _raw_email_expressions(child)


def _find_raw_email_logging(source: str, filename: str = "<test>") -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call) or not _is_logging_call(node):
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            for hit in _raw_email_expressions(arg):
                found.append(f"{filename}:{hit.lineno} {ast.unparse(hit)}")
    return found


def test_app_logging_calls_do_not_pass_raw_email_addresses():
    violations: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        relative = path.relative_to(_BACKEND_DIR).as_posix()
        violations += _find_raw_email_logging(path.read_text(encoding="utf-8"), relative)
    assert violations == [], (
        "ログへ生のメールアドレスを渡している箇所があります（app.core.masking.mask_email を通すこと）:\n"
        + "\n".join(violations)
    )


@pytest.mark.parametrize(
    "source",
    [
        'logger.warning("x email=%s", user.email)',
        'logger.info("x %s", target_email)',
        'logger.info(f"x {user.email}")',
        'logger.error("x %s", user.email.lower())',
        'logger.info("x %s", body["contact_email"])',
        'logger.info("x %s", body.get("email"))',
        'logger.warning("x %s", getattr(user, "contact_email"))',
        'logging.warning("x %s", settings.admin_emails)',
    ],
)
def test_guard_detects_raw_email_patterns(source: str):
    """ガード自体が典型的な書き方を検出できること（検査が空振りしていないことの確認）。"""
    assert _find_raw_email_logging(source) != []


@pytest.mark.parametrize(
    "source",
    [
        'logger.warning("x email=%s", mask_email(user.email))',
        'logger.info("x %s", user.email_notify_opt_in)',
        'logger.info("x %s", notify.is_placeholder_email(value))',
        'logger.info("x %s", len(recipients))',
        'logger.info("x %s", options.get("timeout"))',
        'logger.info("x %s", mask_email(body.get("email")))',
        'send_alert("x", f"email={user.email}")',
    ],
)
def test_guard_allows_masked_or_unrelated_values(source: str):
    assert _find_raw_email_logging(source) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("email=user@example.com\nuser_id=1", "email=u***@example.com\nuser_id=1"),
        ("key=admin-grant:first.last+tag@sub.example.co.jp", "key=admin-grant:f***@sub.example.co.jp"),
        ("a@example.com と b@example.org", "a***@example.com と b***@example.org"),
        ("Key (email)=(taro@example.com) already exists.", "Key (email)=(t***@example.com) already exists."),
        ("@router と user@localhost はメールとして扱わない", "@router と user@localhost はメールとして扱わない"),
        # 区切りなしで日本語に続くと、その日本語もローカル部として扱う（Unicode のアドレスも
        # 隠すため）。残るのは先頭の1字だけで、アドレス本体は隠れる。
        ("連絡先はtaro@example.comです", "連***@example.comです"),
        ("", ""),
    ],
)
def test_mask_emails_in_text(text: str, expected: str):
    assert mask_emails_in_text(text) == expected


def test_mask_emails_in_text_stays_linear_on_long_word_runs():
    """全ログ行に掛かるため、「長い英数字の連続＋@」でも二乗時間にならない（旧式は2万字で数秒）。"""
    started = time.perf_counter()
    for text in ("a" * 50_000 + "@", "a" * 50_000 + "@example.com", ("x" * 70 + "@") * 700):
        mask_emails_in_text(text)
    assert time.perf_counter() - started < 1.0
