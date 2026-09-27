"""ログに生の個人情報を書かないためのガード。

2026-09-27: 本番で app.* の INFO を出すようにするにあたり、app 配下の logging 呼び出しを全件
点検し、生のメールアドレスを書いていた箇所（admin 権限の付与・剥奪、アカウント削除、口座情報・
本人確認書類の閲覧監査の admin_email 等）を ``mask_email`` へ直した。Render のログは第三者の
基盤に約7日残り、ダッシュボードの閲覧権限だけで読めるため、同じ書き方が戻ってきたら CI で落とす。
メールのほか、LINE の userId（Push の宛先）・写真の storage_key（無認証の capability URL）・
電話番号・住所も、それぞれのマスク関数を通さずに渡したら落とす。

あわせて、自由文中の値をまとめてマスクする ``mask_emails_in_text`` / ``mask_sensitive_in_text`` の
振る舞いを確かめる。
"""
from __future__ import annotations

import ast
import pathlib
import re
import time

import pytest

from app.core.masking import mask_emails_in_text, mask_sensitive_in_text

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
_APP_DIR = _BACKEND_DIR / "app"

_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
)
#: この関数の引数の内側はマスク済みとみなして検査しない。
_MASKING_FUNCS = frozenset(
    {
        "mask_email",
        "mask_emails_in_text",
        "mask_sensitive_in_text",
        "mask_key_for_log",
        "_mask_line_user_id",
        "truncate_ip_for_log",
        "mask_account_number",
    }
)
#: 値そのものを明かさない組み込み関数（型名・長さ・真偽だけを出す）。引数の内側は検査しない。
_NON_REVEALING_BUILTINS = frozenset({"type", "len", "bool"})
#: 生で渡してはいけない値の名前（末尾一致）: email(s)・line_user_id(s)・storage_key(s)・
#: phone(s)・phone_number(s)・address(es)（ip_address も含む）。生 IP の client_ip は、唯一の
#: 該当箇所（operator_applications.py の件数超過ログ）を並走ブランチ 4cb6b9a が削除するため、
#: その取り込み後に対象へ加える。
_EMAIL_NAME_RE = re.compile(
    r"(?:^|_)(?:emails?|line_user_ids?|storage_keys?|phones?|phone_numbers?|address(?:es)?)$"
    # 人の名前の項目（汎用の name は種別名・ルール名等にも使うので対象外）と口座名義。
    r"|(?:^|_)(?:family|given|full|contact|representative|company)_names?$"
    r"|(?:^|_)account_holders?(?:_names?)?$"
    # 秘密値（トークン・パスワード・API キー・Webhook の URL）。
    r"|(?:^|_)(?:tokens?|passwords?|api_keys?|secrets?|webhook_urls?)$",
    re.IGNORECASE,
)


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
    receiver = func.value
    if isinstance(receiver, ast.Call):  # logging.getLogger(__name__).info(...) の形
        return _callee_name(receiver.func) == "getLogger"
    return "log" in _callee_name(receiver).lower()


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
    """マスク関数を通っていない「個人情報らしい式」を列挙する。"""
    if isinstance(node, ast.Compare):
        return  # 比較（x is None・a == b 等）の結果は真偽だけで、値そのものは出ない
    if isinstance(node, ast.Call):
        if _callee_name(node.func) in _MASKING_FUNCS:
            return
        if isinstance(node.func, ast.Name) and node.func.id in _NON_REVEALING_BUILTINS:
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


def test_app_logging_calls_do_not_pass_raw_personal_identifiers():
    violations: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        relative = path.relative_to(_BACKEND_DIR).as_posix()
        violations += _find_raw_email_logging(path.read_text(encoding="utf-8"), relative)
    assert violations == [], (
        "ログへ生の個人情報（メール・LINE userId・storage_key・電話・住所）を渡している箇所があります"
        "（mask_email / _mask_line_user_id / mask_key_for_log 等を通すこと）:\n" + "\n".join(violations)
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
        'logger.error("x userId=%s", line_user_id)',
        'logger.warning("x key=%s", storage_key)',
        'logger.info("x %s", user.phone)',
        'logger.info("x %s", profile.address)',
        'logger.info("x %s", application.company_name)',
        'logger.info("x %s", bank["account_holder"])',
        'logger.warning("x %s", settings.alert_webhook_url)',
        'logger.error("x %s", body.password)',
        'logger.info("x %s", settings.JWT_SECRET)',
        'logging.getLogger(__name__).info("x %s", user.email)',
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
        'logger.info("x %s", _mask_line_user_id(line_user_id))',
        'logger.warning("x key=%s", storage.mask_key_for_log(storage_key))',
        'logger.warning("x ip_net=%s", truncate_ip_for_log(ip_address))',
        'logger.error("x type=%s length=%s", type(line_user_id).__name__, len(str(line_user_id)))',
        'logger.info("x has_email=%s", bool(user.email))',
        'logger.info("x missing=%s", line_user_id is None)',
        'logger.info("RoutingRule name=%s を追加", rule_seed["name"])',
        'logger.info("x %s", _ops_token_mismatch_count)',
        'logger.info("x configured=%s", bool(settings.alert_webhook_url))',
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
        # RFC が許す記号入りのローカル部も丸ごと隠す（記号より前を平文で残さない）。
        ("email=taro.yamada=shop@example.com", "email=t***@example.com"),
        ("first/last@example.com", "f***@example.com"),
        # 既知のラベル（email= / admin_email=）は残し、未知の xxx= はローカル部ごと隠す（隠す側に倒す）。
        ("admin_email=admin.user@katadzuke.jp", "admin_email=a***@katadzuke.jp"),
        ("to=taro@example.com", "t***@example.com"),
        # RFC の上限（64字）を超えるローカル部も隠す（長さで取りこぼさない）。
        ("x" * 70 + "@example.com", "x***@example.com"),
        # 記号だけでつながった2件目以降も隠す（1段目は先のメールのドメインから続く部分を開始位置に
        # できないため、区切り記号の直後から拾う2段目で補う）。
        ("to=a@x.jp&cc=b@y.jp", "t***@x.jp&cc=b***@y.jp"),
        ("a@x.jp|b@y.jp", "a***@x.jp|b***@y.jp"),
        ("a@x.jp/b@y.jp", "a***@x.jp/b***@y.jp"),
        # マスク済みの値は何度掛けても変わらない。
        ("email=t***@example.com", "email=t***@example.com"),
        ("t***@x.jp&cc=b***@y.jp", "t***@x.jp&cc=b***@y.jp"),
        ("", ""),
    ],
)
def test_mask_emails_in_text(text: str, expected: str):
    assert mask_emails_in_text(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GET /api/v1/files/0123456789abcdef0123456789abcdef.jpg 200", "GET /api/v1/files/01234567... 200"),
        (
            "endpoint URL: https://b.acct.r2.cloudflarestorage.com/case-photos/fedcba9876543210fedcba9876543210.webp",
            "endpoint URL: https://b.acct.r2.cloudflarestorage.com/case-photos/fedcba98...",
        ),
        ("to=U0123456789abcdef0123456789abcdef push", "to=U012… push"),
        # 拡張子の無い 32 桁 hex（案件等の ID）はそのまま残す。
        ("case=0123456789abcdef0123456789abcdef", "case=0123456789abcdef0123456789abcdef"),
        ("email=taro@example.com key=0123456789abcdef0123456789abcdef.png", "email=t***@example.com key=01234567..."),
    ],
)
def test_mask_sensitive_in_text(text: str, expected: str):
    assert mask_sensitive_in_text(text) == expected


def test_mask_functions_stay_linear_on_pathological_input():
    """全ログ行に掛かるため、「長い英数字の連続＋@」等でも二乗時間にならない（旧式は2万字で数秒）。"""
    started = time.perf_counter()
    for text in (
        "a" * 50_000 + "@",
        "a" * 50_000 + "@example.com",
        ("x" * 70 + "@") * 700,
        "." * 20_000 + "@x",
        "@" * 20_000,
        "0" * 50_000 + ".jpg",
        "U" + "0" * 50_000,
        "&" * 50_000 + "a@x.jp",
        "&a" * 25_000 + "@",
    ):
        mask_sensitive_in_text(text)
    assert time.perf_counter() - started < 1.0
