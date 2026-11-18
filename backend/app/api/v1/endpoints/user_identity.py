"""依頼者の本人確認書類（身分証画像）の受付 — 廃止済み。

運転免許証・マイナンバーカード等の画像を預かること自体が個人情報の漏えい時の
被害を大きくするため、本人確認書類の受付を全面的にやめた（2026-11）。保存済みの
画像は alembic 0049 で消去している。お引き取りの際の本人確認は、古物営業法
第15条に基づき訪問する古物商（業者）が行う。

旧エンドポイントは、古い画面やブックマークからの呼び出しに「受付終了」を明示する
ため 410 Gone だけを返す。リクエスト本文は一切読まない（multipart を解析しない＝
画像がサーバーのメモリにも載らない）。認証も行わない: どの利用者にも同じ固定の
応答を返すだけで、在不在や状態を漏らす情報が無いため。

業者の古物商許可証画像（operator_license.py）は本件の対象外。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

IDENTITY_DOCUMENTS_RETIRED_DETAIL = (
    "本人確認書類の受付は終了しました。古物営業法で定める場合には、"
    "買取業者が訪問時に本人確認を行います。"
)

# 廃止した旧エンドポイント（メソッド, パス）。テストでもこの表を唯一の情報源にする。
RETIRED_IDENTITY_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/users/me/identity"),
    ("POST", "/users/me/identity-documents"),
    ("GET", "/users/me/identity-documents/{document_id}/file"),
    ("GET", "/admin/identity-documents"),
    ("GET", "/admin/identity-documents/{document_id}/file"),
    ("PATCH", "/admin/identity-documents/{document_id}/approve"),
    ("PATCH", "/admin/identity-documents/{document_id}/reject"),
)


async def _identity_documents_retired() -> JSONResponse:
    """本文・パスパラメータを読まずに 410 を返す（全旧エンドポイント共通）。"""
    # 認証なしで叩けるため INFO にはしない（大量に叩かれて保持7日のログを押し流させない）。
    logger.debug("user_identity: 廃止済みの本人確認書類エンドポイントへのアクセスに 410 を返しました")
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={"detail": IDENTITY_DOCUMENTS_RETIRED_DETAIL},
        headers={"Cache-Control": "no-store"},
    )


for _method, _path in RETIRED_IDENTITY_ROUTES:
    router.add_api_route(
        _path,
        _identity_documents_retired,
        methods=[_method],
        status_code=status.HTTP_410_GONE,
        summary="（廃止）本人確認書類 — 常に 410 Gone",
        include_in_schema=False,
    )
