"""送客 URL 生成サービス — AffiliateMeta.tracking_url_template を展開する。

設計判断:
- AffiliateMeta が存在しないチャネル（フリマ等の収益化不可）は
  channel.base_url をそのまま返す（テンプレートなし）。
- XSS 対策: 全文字列パラメータを urllib.parse.quote で URLエンコードする。
  数値パラメータ（price_min / price_max）は str() 変換のみ（注入リスクなし）。

プレースホルダ仕様:
    {item_name}  → Item.detected_name (URLエンコード)
    {category}   → Item.category_tier.value (URLエンコード)
    {price_min}  → Assessment.estimated_price_min (整数文字列)
    {price_max}  → Assessment.estimated_price_max (整数文字列)
    {condition}  → ユーザー確定 ItemCondition.value (URLエンコード)

TODO(§6-1 確定後): ASP 固有のパラメータ追加（例: a8mat / rk など）が必要になった
    場合は本モジュールにチャネル種別ごとの展開ロジックを追加する。
"""

from __future__ import annotations

from urllib.parse import quote

from app.db.models.assessment import Assessment
from app.db.models.channel import Channel
from app.db.models.enums import ItemCondition
from app.db.models.item import Item


def generate_outbound_url(
    item: Item,
    assessment: Assessment,
    channel: Channel,
    confirmed_condition: ItemCondition,
) -> str:
    """チャネル向け送客 URL を生成して返す。

    AffiliateMeta.tracking_url_template が存在する場合はプレースホルダを展開する。
    存在しない場合（フリマ等）は channel.base_url をそのまま返す。

    影響範囲: 読み取りのみ。DB への副作用なし。

    Args:
        item: 品目 ORM インスタンス（detected_name / category_tier を使用）。
        assessment: 査定 ORM インスタンス（estimated_price_min / max を使用）。
        channel: チャネル ORM インスタンス（affiliate_meta が eager-load 済みであること）。
        confirmed_condition: ユーザーが確定したコンディション（item.condition とは別）。

    Returns:
        展開済みの送客 URL 文字列。
    """
    meta = channel.affiliate_meta

    # AffiliateMeta なし or テンプレート未設定 → base_url をそのまま返す
    if meta is None or not meta.tracking_url_template:
        return channel.base_url

    template: str = meta.tracking_url_template

    # 文字列パラメータは quote() でエンコード（safe="" で / も含めてエンコード）
    # 数値パラメータは整数文字列に変換するのみ（数値なので注入リスクなし）
    url = (
        template
        .replace("{item_name}", quote(item.detected_name, safe=""))
        .replace("{category}", quote(item.category_tier.value, safe=""))
        .replace("{price_min}", str(assessment.estimated_price_min or 0))
        .replace("{price_max}", str(assessment.estimated_price_max or 0))
        .replace("{condition}", quote(confirmed_condition.value, safe=""))
    )

    return url
