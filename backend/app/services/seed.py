"""初期チャネルデータ投入スクリプト（冪等 upsert）。

[推測] 初期スコープ（ハンドオフ §6-1 未確定のため推測値）:
  - BUYER_ASP        : 高単価標準品 (idos_standard)
  - BULK_BUYER       : 低単価生活品 (net_off_bulk)
  - FLEA_MARKET      : 低単価生活品 (mercari)
  - CAR_APPRAISAL    : 車 (mota_car)

[推測] 不動産 (REAL_ESTATE_APPRAISAL) は法務確認待ちのため is_active=False でシード。
  RoutingRule も is_active=False で定義する（ハンドオフ §6-3 未確定）。

[推測] 車チャネルは ASP 正式提携前のため、RENTRACKS 経由の暫定 URL テンプレートで対応。
  提携確定後に program_id と tracking_url_template を更新すること。

TODO(§6-1 確定後): ステークホルダーとスコープを合意し、不要チャネルを整理する。
TODO(§6-3 確定後): 不動産チャネルの法務確認完了後に is_active=True に変更する。

冪等性保証:
  - Channel: code（UNIQUE 制約あり）で重複チェック。
  - AffiliateMeta: channel_id（UNIQUE 制約あり）で重複チェック。
  - RoutingRule: name で重複チェック（既存は上書きしない）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel import AffiliateMeta, Channel
from app.db.models.enums import (
    AffiliateNetwork,
    CategoryTier,
    ChannelType,
    RewardType,
)
from app.db.models.routing import RoutingRule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# チャネルシードデータ
# ---------------------------------------------------------------------------

_CHANNEL_SEEDS: list[dict] = [
    {
        "code": "idos_standard",
        "display_name": "アイドス（高単価買取）",
        "channel_type": ChannelType.BUYER_ASP,
        "primary_category_tier": CategoryTier.HIGH_VALUE_STANDARD,
        "base_url": "https://www.idos.jp/",
        "is_active": True,
        "priority": 10,
    },
    {
        "code": "net_off_bulk",
        "display_name": "ネットオフまとめ買取",
        "channel_type": ChannelType.BULK_BUYER,
        "primary_category_tier": CategoryTier.LOW_VALUE_DAILY,
        "base_url": "https://www.netoff.co.jp/buy/",
        "is_active": True,
        "priority": 20,
    },
    {
        "code": "mercari",
        "display_name": "メルカリ",
        "channel_type": ChannelType.FLEA_MARKET,
        "primary_category_tier": CategoryTier.LOW_VALUE_DAILY,
        "base_url": "https://www.mercari.com/jp/",
        "is_active": True,
        "priority": 30,
    },
    {
        # [推測] CAR_APPRAISAL は ASP 正式提携前。暫定 URL 送客で対応（§6-3）。
        # TODO(§6-3 確定後): 正式提携 URL に差し替える。
        "code": "mota_car",
        "display_name": "MOTA車買取",
        "channel_type": ChannelType.CAR_APPRAISAL,
        "primary_category_tier": CategoryTier.VEHICLE,
        "base_url": "https://mota.jp/buy/",
        "is_active": True,
        "priority": 10,
    },
    {
        # ヤフオク: フリマ（§2 収益化不可）。高単価商品のオークション選択肢として提示。
        "code": "yahoo_auction",
        "display_name": "ヤフオク",
        "channel_type": ChannelType.FLEA_MARKET,
        "primary_category_tier": CategoryTier.HIGH_VALUE_STANDARD,
        "base_url": "https://auctions.yahoo.co.jp/",
        "is_active": True,
        "priority": 20,
    },
    {
        # ブックオフオンライン: まとめ買取（本・CD・DVD・ゲームなど低単価品向け）
        "code": "bookoff_online",
        "display_name": "ブックオフオンライン",
        "channel_type": ChannelType.BULK_BUYER,
        "primary_category_tier": CategoryTier.LOW_VALUE_DAILY,
        "base_url": "https://www.bookoffonline.co.jp/buy/",
        "is_active": True,
        "priority": 25,
    },
    {
        # コメ兵: ブランド品・貴金属・時計の高単価買取専門店
        # [推測] AffiliateMeta program_id は ASP 申込後に差し替え（§6-1）
        # TODO(§6-1 確定後): 実際の program_id と tracking_url_template に更新。
        "code": "komehyo",
        "display_name": "コメ兵（ブランド買取）",
        "channel_type": ChannelType.BUYER_ASP,
        "primary_category_tier": CategoryTier.HIGH_VALUE_STANDARD,
        "base_url": "https://www.komehyo.co.jp/kaitori/",
        "is_active": True,
        "priority": 15,
    },
    {
        # [推測] 不動産: 法務確認待ちのため is_active=False（ハンドオフ §6-3）
        # TODO(§6-3 確定後): 法務確認完了後に is_active=True に変更し AffiliateMeta を追加。
        "code": "lifull_realestate",
        "display_name": "LIFULL HOME'S不動産査定",
        "channel_type": ChannelType.REAL_ESTATE_APPRAISAL,
        "primary_category_tier": CategoryTier.REAL_ESTATE,
        "base_url": "https://www.homes.co.jp/sell/",
        "is_active": False,
        "priority": 10,
    },
]


# ---------------------------------------------------------------------------
# AffiliateMeta シードデータ（チャネルコード → メタ）
# mercari は収益化不可（§2）のため AffiliateMeta なし。
# ---------------------------------------------------------------------------

_AFFILIATE_META_SEEDS: dict[str, dict] = {
    "idos_standard": {
        # [推測] A8.net program_id はプレースホルダ（ASP 申込後に差し替え）
        # TODO(§6-1 確定後): 実際の A8.net program_id と tracking_url_template に更新。
        "asp_network": AffiliateNetwork.A8_NET,
        "program_id": "TODO_IDOS_A8_PROGRAM_ID",
        "tracking_url_template": (
            "https://px.a8.net/svt/ejp"
            "?a8mat=TODO_IDOS_A8_PROGRAM_ID"
            "&a8ejpredirect=https%3A%2F%2Fwww.idos.jp%2F"
            "%3Fq%3D{item_name}"
            "%26category%3D{category}"
            "%26condition%3D{condition}"
            "%26pmin%3D{price_min}"
            "%26pmax%3D{price_max}"
        ),
        "reward_type": RewardType.CPA,
        "reward_amount_min": 800,
        "reward_amount_max": 6600,
        "requires_pr_label": True,
    },
    "net_off_bulk": {
        # [推測] ACCESSTRADE program_id はプレースホルダ（ASP 申込後に差し替え）
        # TODO(§6-1 確定後): 実際の ACCESSTRADE program_id と tracking_url_template に更新。
        "asp_network": AffiliateNetwork.ACCESSTRADE,
        "program_id": "TODO_NETOFF_ACCESSTRADE_PROGRAM_ID",
        "tracking_url_template": (
            "https://h.accesstrade.net/sp/cc"
            "?rk=TODO_NETOFF_ACCESSTRADE_PROGRAM_ID"
            "&url=https%3A%2F%2Fwww.netoff.co.jp%2Fbuy%2F"
            "%3Fq%3D{item_name}"
            "%26category%3D{category}"
            "%26pmin%3D{price_min}"
            "%26pmax%3D{price_max}"
        ),
        "reward_type": RewardType.CPA,
        "reward_amount_min": 300,
        "reward_amount_max": 1500,
        "requires_pr_label": True,
    },
    # mercari / yahoo_auction: AffiliateMeta なし（§2 収益化不可のためキー自体を定義しない）
    "bookoff_online": {
        # [推測] ACCESSTRADE program_id はプレースホルダ（ASP 申込後に差し替え）
        # TODO(§6-1 確定後): 実際の program_id と tracking_url_template に更新。
        "asp_network": AffiliateNetwork.ACCESSTRADE,
        "program_id": "TODO_BOOKOFF_ACCESSTRADE_PROGRAM_ID",
        "tracking_url_template": (
            "https://h.accesstrade.net/sp/cc"
            "?rk=TODO_BOOKOFF_ACCESSTRADE_PROGRAM_ID"
            "&url=https%3A%2F%2Fwww.bookoffonline.co.jp%2Fbuy%2F"
            "%3Fq%3D{item_name}"
        ),
        "reward_type": RewardType.CPA,
        "reward_amount_min": 100,
        "reward_amount_max": 500,
        "requires_pr_label": True,
    },
    "komehyo": {
        # [推測] A8.net program_id はプレースホルダ（ASP 申込後に差し替え）
        # TODO(§6-1 確定後): 実際の A8.net program_id と tracking_url_template に更新。
        "asp_network": AffiliateNetwork.A8_NET,
        "program_id": "TODO_KOMEHYO_A8_PROGRAM_ID",
        "tracking_url_template": (
            "https://px.a8.net/svt/ejp"
            "?a8mat=TODO_KOMEHYO_A8_PROGRAM_ID"
            "&a8ejpredirect=https%3A%2F%2Fwww.komehyo.co.jp%2Fkaitori%2F"
            "%3Fq%3D{item_name}"
            "%26category%3D{category}"
            "%26condition%3D{condition}"
        ),
        "reward_type": RewardType.CPA,
        "reward_amount_min": 500,
        "reward_amount_max": 5000,
        "requires_pr_label": True,
    },
    "mota_car": {
        # [推測] RENTRACKS program_id はプレースホルダ（提携前暫定）
        # [推測] 車チャネルは提携確定前のため MOTA 直リンクへの暫定 URL テンプレート（§6-3）
        # TODO(§6-3 確定後): 正式提携後に program_id と tracking_url_template を更新。
        "asp_network": AffiliateNetwork.RENTRACKS,
        "program_id": "TODO_MOTA_RENTRACKS_PROGRAM_ID",
        "tracking_url_template": (
            "https://t.rentracks.jp/t/r.php"
            "?sid=TODO_MOTA_RENTRACKS_PROGRAM_ID"
            "&url=https%3A%2F%2Fmota.jp%2Fbuy%2F"
            "%3Fcar%3D{item_name}"
            "%26condition%3D{condition}"
            "%26pmin%3D{price_min}"
            "%26pmax%3D{price_max}"
        ),
        "reward_type": RewardType.CPL,
        "reward_amount_min": 1000,
        "reward_amount_max": 5000,
        "requires_pr_label": True,
    },
}


# ---------------------------------------------------------------------------
# RoutingRule シードデータ
# ---------------------------------------------------------------------------

_ROUTING_RULE_SEEDS: list[dict] = [
    {
        "name": "高単価標準品→アイドス",
        "match_category_tier": CategoryTier.HIGH_VALUE_STANDARD,
        "match_price_min": 5000,
        "channel_code": "idos_standard",
        "recommendation_rank": 1,
        "is_active": True,
        "priority": 10,
        "reason_template": (
            "査定額5,000円以上の高単価商品はアイドスへの買取申込みがおすすめです。"
        ),
    },
    {
        "name": "低単価生活品→ネットオフまとめ",
        "match_category_tier": CategoryTier.LOW_VALUE_DAILY,
        "match_price_min": None,
        "channel_code": "net_off_bulk",
        "recommendation_rank": 1,
        "is_active": True,
        "priority": 20,
        "reason_template": (
            "生活雑貨はネットオフのまとめ買取で一括送付が便利です。"
        ),
    },
    {
        "name": "低単価生活品→メルカリ",
        "match_category_tier": CategoryTier.LOW_VALUE_DAILY,
        "match_price_min": None,
        "channel_code": "mercari",
        "recommendation_rank": 2,
        "is_active": True,
        "priority": 30,
        "reason_template": (
            "メルカリへの出品で相場の最大値を狙えます。"
        ),
    },
    {
        "name": "車→MOTA",
        "match_category_tier": CategoryTier.VEHICLE,
        "match_price_min": None,
        "channel_code": "mota_car",
        "recommendation_rank": 1,
        "is_active": True,
        "priority": 10,
        "reason_template": (
            "車の売却はMOTA車買取で複数社の査定を一括比較できます。"
        ),
    },
    {
        "name": "高単価標準品→ヤフオク",
        "match_category_tier": CategoryTier.HIGH_VALUE_STANDARD,
        "match_price_min": None,
        "channel_code": "yahoo_auction",
        "recommendation_rank": 2,
        "is_active": True,
        "priority": 20,
        "reason_template": (
            "ヤフオクへの出品で相場より高値が期待できます（出品手数料が発生する場合があります）。"
        ),
    },
    {
        "name": "高単価標準品→コメ兵",
        "match_category_tier": CategoryTier.HIGH_VALUE_STANDARD,
        "match_price_min": 10000,
        "channel_code": "komehyo",
        "recommendation_rank": 3,
        "is_active": True,
        "priority": 15,
        "reason_template": (
            "ブランド品・貴金属・時計はコメ兵の専門査定で高値が期待できます。"
        ),
    },
    {
        "name": "低単価生活品→ブックオフオンライン",
        "match_category_tier": CategoryTier.LOW_VALUE_DAILY,
        "match_price_min": None,
        "channel_code": "bookoff_online",
        "recommendation_rank": 3,
        "is_active": True,
        "priority": 25,
        "reason_template": (
            "本・CD・DVD・ゲームはブックオフオンラインへ宅配便で一括送付できます。"
        ),
    },
    {
        # [推測] 不動産ルール: is_active=False で定義（法務確認待ち §6-3）
        # TODO(§6-3 確定後): 法務確認完了後に is_active=True に変更する。
        "name": "不動産→LIFULL（非アクティブ）",
        "match_category_tier": CategoryTier.REAL_ESTATE,
        "match_price_min": None,
        "channel_code": "lifull_realestate",
        "recommendation_rank": 1,
        "is_active": False,
        "priority": 10,
        "reason_template": (
            "不動産の査定はLIFULL HOME'Sで複数社への一括依頼が可能です。"
        ),
    },
]


# ---------------------------------------------------------------------------
# シード実行エントリーポイント
# ---------------------------------------------------------------------------

async def seed_channels_and_rules(session: AsyncSession) -> None:
    """チャネル・AffiliateMeta・RoutingRule を冪等に投入する。

    既存レコードは上書きしない（INSERT ONLY IF NOT EXISTS）。
    重複キー: Channel.code / AffiliateMeta.channel_id / RoutingRule.name。

    影響範囲:
      - channels / affiliate_meta / routing_rules テーブルへの INSERT（初回のみ）。
      - 本関数内で commit を行う。呼び出し元はトランザクション管理不要。

    Args:
        session: 呼び出し元から受け取る AsyncSession。
    """
    # --- 1. Channels ---
    code_to_channel: dict[str, Channel] = {}

    for seed in _CHANNEL_SEEDS:
        existing: Channel | None = await session.scalar(
            select(Channel).where(Channel.code == seed["code"])
        )
        if existing is not None:
            logger.debug("Channel code=%s は既に存在するためスキップ", seed["code"])
            code_to_channel[seed["code"]] = existing
            continue

        channel = Channel(
            id=uuid.uuid4(),
            code=seed["code"],
            display_name=seed["display_name"],
            channel_type=seed["channel_type"],
            primary_category_tier=seed["primary_category_tier"],
            base_url=seed["base_url"],
            is_active=seed["is_active"],
            priority=seed["priority"],
        )
        session.add(channel)
        await session.flush()  # channel.id を確定（AffiliateMeta の FK に必要）
        code_to_channel[seed["code"]] = channel
        logger.info("Channel code=%s を追加", seed["code"])

    # --- 2. AffiliateMeta ---
    for channel_code, meta_seed in _AFFILIATE_META_SEEDS.items():
        channel = code_to_channel[channel_code]

        existing_meta: AffiliateMeta | None = await session.scalar(
            select(AffiliateMeta).where(AffiliateMeta.channel_id == channel.id)
        )
        if existing_meta is not None:
            logger.debug(
                "AffiliateMeta channel_code=%s は既に存在するためスキップ", channel_code
            )
            continue

        meta = AffiliateMeta(
            id=uuid.uuid4(),
            channel_id=channel.id,
            asp_network=meta_seed["asp_network"],
            program_id=meta_seed["program_id"],
            tracking_url_template=meta_seed["tracking_url_template"],
            reward_type=meta_seed["reward_type"],
            reward_amount_min=meta_seed["reward_amount_min"],
            reward_amount_max=meta_seed["reward_amount_max"],
            requires_pr_label=meta_seed["requires_pr_label"],
        )
        session.add(meta)
        logger.info("AffiliateMeta channel_code=%s を追加", channel_code)

    # --- 3. RoutingRules ---
    for rule_seed in _ROUTING_RULE_SEEDS:
        existing_rule: RoutingRule | None = await session.scalar(
            select(RoutingRule).where(RoutingRule.name == rule_seed["name"])
        )
        if existing_rule is not None:
            logger.debug(
                "RoutingRule name=%s は既に存在するためスキップ", rule_seed["name"]
            )
            continue

        channel = code_to_channel[rule_seed["channel_code"]]
        rule = RoutingRule(
            id=uuid.uuid4(),
            name=rule_seed["name"],
            match_category_tier=rule_seed["match_category_tier"],
            match_price_min=rule_seed.get("match_price_min"),
            channel_id=channel.id,
            recommendation_rank=rule_seed["recommendation_rank"],
            is_active=rule_seed["is_active"],
            priority=rule_seed["priority"],
            reason_template=rule_seed.get("reason_template"),
        )
        session.add(rule)
        logger.info("RoutingRule name=%s を追加", rule_seed["name"])

    await session.commit()
    logger.info("seed_channels_and_rules: 完了")
