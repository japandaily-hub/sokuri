"""Unit tests for routing._matches_rule using SimpleNamespace duck-typing."""
from __future__ import annotations
from types import SimpleNamespace
import pytest
from app.db.models.enums import CategoryTier, ItemCondition
from app.services.routing import _matches_rule

def make_rule(**overrides):
    defaults = {
        "match_category_tier": None,
        "match_min_condition": None,
        "match_max_condition": None,
        "match_price_min": None,
        "match_price_max": None,
        "match_attributes": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)

# --- Category tier ---
def test_wildcard_matches_all_tiers():
    rule = make_rule()
    for tier in CategoryTier:
        assert _matches_rule(rule, tier, ItemCondition.GOOD, 5000)

def test_high_value_standard_matches_only_itself():
    rule = make_rule(match_category_tier=CategoryTier.HIGH_VALUE_STANDARD)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 5000)
    assert not _matches_rule(rule, CategoryTier.LOW_VALUE_DAILY, ItemCondition.GOOD, 5000)
    assert not _matches_rule(rule, CategoryTier.VEHICLE, ItemCondition.GOOD, 5000)

# --- Price boundary ---
def test_price_below_min_no_match():
    rule = make_rule(match_price_min=5000)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 4999)

def test_price_at_min_matches():
    rule = make_rule(match_price_min=5000)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 5000)

def test_price_above_max_no_match():
    rule = make_rule(match_price_max=10000)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 10001)

def test_price_at_max_matches():
    rule = make_rule(match_price_max=10000)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 10000)

# --- Condition range ---
def test_fair_below_good_no_match():
    rule = make_rule(match_min_condition=ItemCondition.GOOD, match_max_condition=ItemCondition.NEW)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.FAIR, 5000)

def test_good_at_min_matches():
    rule = make_rule(match_min_condition=ItemCondition.GOOD, match_max_condition=ItemCondition.NEW)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 5000)

def test_like_new_in_range_matches():
    rule = make_rule(match_min_condition=ItemCondition.GOOD, match_max_condition=ItemCondition.NEW)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.LIKE_NEW, 5000)

def test_new_at_max_matches():
    rule = make_rule(match_min_condition=ItemCondition.GOOD, match_max_condition=ItemCondition.NEW)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.NEW, 5000)

# --- UNKNOWN condition ---
def test_unknown_excluded_from_condition_range():
    rule = make_rule(match_min_condition=ItemCondition.GOOD, match_max_condition=ItemCondition.NEW)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.UNKNOWN, 5000)

def test_unknown_excluded_with_only_min():
    rule = make_rule(match_min_condition=ItemCondition.POOR)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.UNKNOWN, 5000)

def test_unknown_excluded_with_only_max():
    rule = make_rule(match_max_condition=ItemCondition.NEW)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.UNKNOWN, 5000)

def test_unknown_matches_full_wildcard_rule():
    rule = make_rule()
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.UNKNOWN, 5000)

# --- Combined ---
def test_all_conditions_must_match():
    rule = make_rule(
        match_category_tier=CategoryTier.HIGH_VALUE_STANDARD,
        match_min_condition=ItemCondition.GOOD,
        match_price_min=5000,
    )
    assert not _matches_rule(rule, CategoryTier.LOW_VALUE_DAILY, ItemCondition.GOOD, 5000)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.FAIR, 5000)
    assert not _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 4999)
    assert _matches_rule(rule, CategoryTier.HIGH_VALUE_STANDARD, ItemCondition.GOOD, 5000)
