"""長さ超過の日本語 detail の呼び名がエンドポイントごとに正しいこと（最終レビュー QA L-2）。

以前は ``message`` 欄すべてを「入札メッセージ」と呼んでいた（お問い合わせ 4,000字・
事前申込の備考にも出ていた）。エラーは実際のスキーマ検証から作り、上限値も
スキーマ定義（ctx.max_length）から出ることを確かめる。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.main import _too_long_message
from app.schemas_katadzuke import (
    BidCreateRequest,
    ContactCreateRequest,
    MessageCreateRequest,
    OperatorApplicationCreateRequest,
    ReductionCreateRequest,
    TransactionCancelRequest,
)


def _too_long_error(model: type[BaseModel], field: str, length: int) -> dict:
    """``model`` の ``field`` に ``length`` 文字を入れたときの string_too_long エラー。"""
    payload = {field: "あ" * length}
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            if error["type"] == "string_too_long" and error["loc"][-1] == field:
                return error
    raise AssertionError(f"{model.__name__}.{field} で string_too_long が出ない")


@pytest.mark.parametrize(
    ("model", "field", "length", "path", "expected"),
    [
        (BidCreateRequest, "message", 2001, "/api/v1/cases/abc/bids", "入札メッセージは2,000文字以内で入力してください。"),
        (BidCreateRequest, "message", 2001, "/api/v1/cases/abc/bids/me", "入札メッセージは2,000文字以内で入力してください。"),
        (ContactCreateRequest, "message", 4001, "/api/v1/contact", "お問い合わせ内容は4,000文字以内で入力してください。"),
        (
            OperatorApplicationCreateRequest,
            "message",
            2001,
            "/api/v1/operator-applications",
            "ご質問・備考は2,000文字以内で入力してください。",
        ),
        (MessageCreateRequest, "body", 2001, "/api/v1/transactions/t1/messages", "メッセージは2,000文字以内で入力してください。"),
        (TransactionCancelRequest, "reason", 2001, "/api/v1/transactions/t1/cancel", "キャンセルの理由は2,000文字以内で入力してください。"),
        (TransactionCancelRequest, "reason", 2001, "/api/v1/cases/c1/cancel/", "キャンセルの理由は2,000文字以内で入力してください。"),
        (ReductionCreateRequest, "reason", 2001, "/api/v1/transactions/t1/reduction", "減額の理由は2,000文字以内で入力してください。"),
    ],
)
def test_label_follows_endpoint(model, field, length, path, expected):
    assert _too_long_message(_too_long_error(model, field, length), path) == expected


def test_contact_message_is_never_called_bid_message():
    message = _too_long_message(_too_long_error(ContactCreateRequest, "message", 4001), "/api/v1/contact")
    assert message is not None and "入札" not in message


def test_unknown_path_message_field_falls_back_to_array_shape():
    """対応の無いパスの ``message`` 欄は呼び名を推測しない（None → 従来の配列形式）。"""
    error = _too_long_error(BidCreateRequest, "message", 2001)
    assert _too_long_message(error, "/api/v1/unknown") is None
    # body / reason は汎用の呼び名で返す。
    body_error = _too_long_error(MessageCreateRequest, "body", 2001)
    assert _too_long_message(body_error, "/api/v1/other") == "メッセージは2,000文字以内で入力してください。"
