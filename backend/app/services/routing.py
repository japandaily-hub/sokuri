"""ルーティングエンジン — RoutingRule テーブルを評価し AssessmentRecommendation を生成する。

設計方針（ハンドオフ §6-2 ハイブリッドルーティング）:
- ``RoutingRule`` を ``priority`` 昇順・``is_active=True`` でフィルタして全件評価。
- マッチ条件カラムが NULL のルールはワイルドカード（常に一致）として扱う。
- コンディション順序比較には :data:`~app.db.models.enums.CONDITION_RANK` を使用。
- 1 件以上マッチした場合は ``RoutingMethod.RULE``、0 件は ``RoutingMethod.LLM`` フォールバック。
- LLM フォールバックは現フェーズでは stub（TODO コメント）。
- ``channel.affiliate_meta`` を eager-load して ``is_sponsored`` を判定する。

Phase 4 変更点:
- ``evaluate_routing_rules`` に ``item: Item`` パラメータを追加。
- ``generate_outbound_url`` を呼び出して ``AssessmentRecommendation.outbound_url`` を設定。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.assessment import Assessment, AssessmentRecommendation
from app.db.models.channel import Channel
from app.db.models.enums import (
    CONDITION_RANK,
    CategoryTier,
    ItemCondition,
    RoutingMethod,
)
from app.db.models.item import Item
from app.db.models.routing import RoutingRule
from app.services.affiliate import generate_outbound_url


# ---------------------------------------------------------------------------
# ルーティング結果 DTO
# ---------------------------------------------------------------------------

@dataclass
class RoutingResult:
    """:func:`evaluate_routing_rules` の戻り値。"""

    method: RoutingMethod
    """ルーティングの出自（RULE / LLM / HYBRID）。"""

    recommendations: list[AssessmentRecommendation] = field(default_factory=list)
    """セッションに追加済みの AssessmentRecommendation 一覧（rank 昇順）。"""


# ---------------------------------------------------------------------------
# 条件マッチ評価
# ---------------------------------------------------------------------------

def _matches_rule(
    rule: RoutingRule,
    category_tier: CategoryTier,
    condition: ItemCondition,
    base_market_price: int,
) -> bool:
    """1 つの RoutingRule が品目情報にマッチするか評価する。

    各条件カラムは NULL をワイルドカード（無条件一致）として扱う（ハンドオフ §1-2）。

    Args:
        rule: 評価対象のルーティングルール。
        category_tier: 品目の粗カテゴリ。
        condition: ユーザーが確定したコンディション。
        base_market_price: AI 推定の基準相場（JPY）。

    Returns:
        全条件を満たす場合 True。
    """
    # --- カテゴリ条件 ---
    if rule.match_category_tier is not None:
        if rule.match_category_tier != category_tier:
            return False

    # --- コンディション条件（CONDITION_RANK で順序比較） ---
    condition_rank = CONDITION_RANK.get(condition, -1)
    if condition_rank == -1:
        # UNKNOWN は順序を持たないためコンディション絞り込みルールには一致しない
        if rule.match_min_condition is not None or rule.match_max_condition is not None:
            return False

    if rule.match_min_condition is not None:
        min_rank = CONDITION_RANK.get(rule.match_min_condition, -1)
        if condition_rank < min_rank:
            return False

    if rule.match_max_condition is not None:
        max_rank = CONDITION_RANK.get(rule.match_max_condition, -1)
        if condition_rank > max_rank:
            return False

    # --- 価格条件 ---
    if rule.match_price_min is not None and base_market_price < rule.match_price_min:
        return False
    if rule.match_price_max is not None and base_market_price > rule.match_price_max:
        return False

    # match_attributes は Phase 5 以降で評価（現フェーズはスキップ）
    # TODO(Phase 5): JSONB 述語による attributes 条件評価を実装する

    return True


# ---------------------------------------------------------------------------
# LLM フォールバック（stub）
# ---------------------------------------------------------------------------

async def _llm_fallback(
    session: AsyncSession,
    assessment: Assessment,
    category_tier: CategoryTier,
    condition: ItemCondition,
    base_market_price: int,
) -> list[AssessmentRecommendation]:
    """LLM フォールバックルーティング（現フェーズは stub）。

    TODO(Phase 5): Gemini に category_tier / condition / base_market_price を渡して
    最適チャネルを推論させ、AssessmentRecommendation を生成する。
    現時点では空リストを返し、EstimateResponse の recommendations は [] になる。
    """
    return []


# ---------------------------------------------------------------------------
# メインエントリーポイント
# ---------------------------------------------------------------------------

async def evaluate_routing_rules(
    session: AsyncSession,
    assessment: Assessment,
    item: Item,
    category_tier: CategoryTier,
    condition: ItemCondition,
    base_market_price: int,
) -> RoutingResult:
    """RoutingRule を評価し、マッチしたルールから AssessmentRecommendation を生成する。

    マッチしたルールの ``recommendation_rank`` を AssessmentRecommendation.rank として使用する。
    ``channel.affiliate_meta`` を eager-load し、``requires_pr_label=True`` なら
    ``is_sponsored=True`` とする（ステマ規制 §3）。

    Phase 4: :func:`~app.services.affiliate.generate_outbound_url` を呼び出して
    ``outbound_url`` を設定する（Phase 3 では None 固定だった）。

    1 件もマッチしない場合は LLM フォールバックを呼び出す（現フェーズは stub）。

    Args:
        session: 呼び出し元と共有する AsyncSession。
        assessment: 既にセッションに追加・flush 済みの Assessment（ID が確定している）。
        item: 品目 ORM インスタンス（送客 URL 生成に使用）。
        category_tier: 品目の粗カテゴリ。
        condition: ユーザーが確定したコンディション。
        base_market_price: AI 推定の基準相場（JPY）。

    Returns:
        :class:`RoutingResult`（recommendations はセッションに追加済み）。
    """
    # RoutingRule を priority 昇順で全件取得。channel + affiliate_meta を eager-load。
    stmt = (
        select(RoutingRule)
        .where(RoutingRule.is_active.is_(True))
        .order_by(RoutingRule.priority.asc())
        .options(
            selectinload(RoutingRule.channel).selectinload(Channel.affiliate_meta)
        )
    )
    result = await session.execute(stmt)
    rules: list[RoutingRule] = list(result.scalars().all())

    matched_recommendations: list[AssessmentRecommendation] = []

    for rule in rules:
        if not _matches_rule(rule, category_tier, condition, base_market_price):
            continue

        # アフィリエイト送客かつ PR 表記が必要な場合は is_sponsored=True（ステマ規制 §3）
        is_sponsored = (
            rule.channel.affiliate_meta is not None
            and rule.channel.affiliate_meta.is_active
            and rule.channel.affiliate_meta.requires_pr_label
        )

        # Phase 4: 送客 URL を生成（チャネルに AffiliateMeta がなければ base_url を返す）
        outbound_url = generate_outbound_url(
            item=item,
            assessment=assessment,
            channel=rule.channel,
            confirmed_condition=condition,
        )

        rec = AssessmentRecommendation(
            id=uuid.uuid4(),
            assessment_id=assessment.id,
            channel_id=rule.channel_id,
            source_routing_rule_id=rule.id,
            rank=rule.recommendation_rank,
            reason=rule.reason_template,
            is_sponsored=is_sponsored,
            outbound_url=outbound_url,
        )
        session.add(rec)
        matched_recommendations.append(rec)

    if not matched_recommendations:
        # LLM フォールバック（現フェーズは stub で空リストを返す）
        llm_recs = await _llm_fallback(
            session, assessment, category_tier, condition, base_market_price
        )
        return RoutingResult(method=RoutingMethod.LLM, recommendations=llm_recs)

    return RoutingResult(method=RoutingMethod.RULE, recommendations=matched_recommendations)
