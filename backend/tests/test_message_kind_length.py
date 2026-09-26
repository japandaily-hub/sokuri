"""app 配下の ``Message(kind=...)`` リテラルが列長（messages.kind の型）を超えないことを
保証する静的検査（回帰防止ガード）。

0046 で messages.kind を String(16) → String(32) に拡幅した経緯（alembic_version
VARCHAR(32) 全断障害と同種の「列長不足に実行時まで気づかない」事故）を踏まえ、実行時では
なくテストの静的検査で早期に検知する。``Message(...)`` のキーワード引数 ``kind=`` に
渡す文字列リテラルを AST で列挙し、``app.db.models.message.Message.kind`` の列長
（sqlalchemy ``String(32)``）を超えていないことを確認する。列長はハードコードせず
モデルから読むため、将来列長を変えてもこのテストは追従する。
"""

from __future__ import annotations

import ast
import pathlib

from app.db.models.message import Message

_APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


def _message_kind_literals() -> list[tuple[str, int, str]]:
    """app 配下の ``Message(...)`` 呼び出しに現れる ``kind=`` の文字列リテラルを列挙する。

    (相対パス, 行番号, kind値) のリストを返す。f-string・変数参照等の非リテラルは
    対象外（実行時に長さが変わりうる値は静的検査できないため。現状の実装は全て
    固定文字列のリテラルであり、非リテラル化された場合はレビューで見つける）。
    """
    results: list[tuple[str, int, str]] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "Message":
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "kind"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    results.append(
                        (str(path.relative_to(_APP_DIR.parent)), node.lineno, kw.value.value)
                    )
    return results


def test_message_kind_literals_fit_within_column_length() -> None:
    """``Message(kind="...")`` の全リテラルが列長（messages.kind の String 長）以下であること。"""
    column_length = Message.__table__.c.kind.type.length
    literals = _message_kind_literals()
    assert literals, "Message(kind=...) の呼び出しが1件も見つからない（検査対象なし・実装漏れの疑い）"
    offenders = [
        f"{path}:{lineno} kind={value!r} ({len(value)}文字)"
        for path, lineno, value in literals
        if len(value) > column_length
    ]
    assert offenders == [], (
        f"messages.kind の列長（{column_length}文字）を超えるリテラルがある: " + ", ".join(offenders)
    )
