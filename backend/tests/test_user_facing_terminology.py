"""backend が利用者に出す文言の用語検査（最終レビュー QA M-1）。

カタヅケのコピー用語ルール（2026-09-18 全ページ校閲）では、利用者向けの文言で
「落札」→「成約」、「商品」→「品物」、「査定」→「入札」と言い換える。web は校閲済みだが、
backend の通知文（メール・LINE）とエラー文言に旧語が残っていた。

検査対象（AST で文字列リテラルを集める。コメント・docstring は利用者に出ないので対象外）:
- app/services/notify.py・line_notify.py・notify_dispatch.py の全文字列リテラル
  （f-string の固定部分を含む）。
- app/api 配下と app/main.py の ``detail=``・``message=`` キーワードに渡す値の中の文字列
  （HTTPException の理由・構造化エラーの日本語文）。

意図して残す語は _ALLOWED_PHRASES に理由つきで載せる。該当箇所の語を取り除いてから
検査するので、許可した言い回しの外に同じ語が出れば検出する。
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_APP = _BACKEND_ROOT / "app"

_FORBIDDEN_TERMS = ("落札", "商品", "査定")

_NOTIFY_MODULES = (
    _APP / "services" / "notify.py",
    _APP / "services" / "line_notify.py",
    _APP / "services" / "notify_dispatch.py",
)

# 意図して残す言い回し（理由つき）。
_ALLOWED_PHRASES: dict[str, str] = {
    # 業界の一般名詞として他社サービス（一括査定サイト）を指す場合は言い換えない。
    "一括査定": "他社の一括査定サービスを指す一般名詞",
    # 「現地で品物を見て金額を決め直す」行為は業界語の現物査定で説明する（入札とは別の行為）。
    "現物査定は成約後": "成約後に業者が現地で行う確認の説明（入札とは別の行為）",
}


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body:
                first = node.body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    ids.add(id(first.value))
    return ids


def _string_constants(node: ast.AST, skip: set[int]) -> list[ast.Constant]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and id(child) not in skip
    ]


def _violations(text: str) -> list[str]:
    stripped = text
    for phrase in _ALLOWED_PHRASES:
        stripped = stripped.replace(phrase, "")
    return [term for term in _FORBIDDEN_TERMS if term in stripped]


def _collect_notify_literals() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _NOTIFY_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for const in _string_constants(tree, _docstring_node_ids(tree)):
            found.append((path.name, const.lineno, const.value))
    return found


def _collect_endpoint_messages() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    paths = sorted((_APP / "api").rglob("*.py")) + [_APP / "main.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in ("detail", "message"):
                for const in _string_constants(node.value, set()):
                    found.append((str(path.relative_to(_BACKEND_ROOT)), const.lineno, const.value))
    return found


def test_scanners_find_literals():
    """陽性対照: 収集器が実際に文言を拾えている（空振りで常に合格しない）。"""
    notify_literals = _collect_notify_literals()
    endpoint_messages = _collect_endpoint_messages()
    assert any("【カタヅケ】" in text for _, _, text in notify_literals)
    assert any("成約情報が見つかりません" in text for _, _, text in endpoint_messages)
    assert _violations("入札が落札されました") == ["落札"]
    assert _violations("他社の一括査定サイト") == []
    assert _violations("一括査定と査定") == ["査定"]


def test_notify_messages_use_current_terms():
    offenders = [
        (name, line, text[:60], _violations(text))
        for name, line, text in _collect_notify_literals()
        if _violations(text)
    ]
    assert offenders == [], offenders


def test_endpoint_error_messages_use_current_terms():
    offenders = [
        (name, line, text[:60], _violations(text))
        for name, line, text in _collect_endpoint_messages()
        if _violations(text)
    ]
    assert offenders == [], offenders
