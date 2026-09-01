"""Case → CaseMaskedOut の組み立て共通ロジック（DRY是正）。

以前は ``cases.py``（一覧・詳細）と ``transactions.py``（成約詳細内の case 埋め込み）に
ほぼ同一の組み立てコードが重複しており、CaseItem 追加のような項目追加時に
片方だけ更新して同期漏れが起きるリスクがあった。本モジュールへ抽出し、両方から
共通で呼び出す。

``bid_count`` / ``my_bid`` / ``top_bid_amount`` は入札関連情報（``case.bids``）を
参照する cases.py 側のみで追加設定する。transactions.py は成約が既に確定した
文脈のため従来通りこれらを設定しない（デフォルト値のまま）。
"""

from __future__ import annotations

from app.db.models.case import Case
from app.schemas_katadzuke import CaseItemOut, CaseMaskedOut, CasePhotoOut


def build_case_masked_out(case: Case) -> CaseMaskedOut:
    """業者向けマスク済み案件情報（住所詳細を含まないコア部分）を組み立てる。"""
    return CaseMaskedOut(
        id=case.id,
        status=case.status,
        purpose=case.purpose,
        prefecture=case.prefecture,
        city=case.city,
        housing_type=case.housing_type,
        floor_plan=case.floor_plan,
        floor_number=case.floor_number,
        has_elevator=case.has_elevator,
        ai_summary=case.ai_summary,
        created_at=case.created_at,
        photos=[CasePhotoOut.model_validate(p) for p in case.photos],
        items=[CaseItemOut.model_validate(item) for item in case.items],
        item_count=len(case.items),
        # case.photos は未分類写真・商品紐づけ写真の両方を含む案件全体の総数
        # （CasePhoto.case_id は常にセットされるため、item.photos はこの部分集合）。
        photo_count=len(case.photos),
    )
