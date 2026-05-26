"""Unit tests for affiliate.generate_outbound_url using SimpleNamespace duck-typing."""
from __future__ import annotations
from types import SimpleNamespace
import pytest
from app.db.models.enums import CategoryTier, ItemCondition
from app.services.affiliate import generate_outbound_url

def make_channel(template=None, with_meta=True):
    meta = None
    if with_meta:
        tmpl = template if template is not None else (
            "https://track.example.com/?q={item_name}&cat={category}"
            "&pmin={price_min}&pmax={price_max}&cond={condition}"
        )
        meta = SimpleNamespace(tracking_url_template=tmpl)
    return SimpleNamespace(affiliate_meta=meta, base_url="https://example.com/sell")

def make_item(name="iPhone 15 Pro 256GB", tier=CategoryTier.HIGH_VALUE_STANDARD):
    return SimpleNamespace(detected_name=name, category_tier=tier)

def make_assessment(price_min=64000, price_max=72000):
    return SimpleNamespace(estimated_price_min=price_min, estimated_price_max=price_max)

# --- Placeholder expansion ---
def test_all_placeholders_expanded():
    channel = make_channel(template=(
        "https://asp.example.com/?name={item_name}&cat={category}"
        "&min={price_min}&max={price_max}&cond={condition}"
    ))
    url = generate_outbound_url(make_item("iPhone 15 Pro"), make_assessment(64000, 72000), channel, ItemCondition.GOOD)
    assert "{item_name}" not in url
    assert "{category}" not in url
    assert "{price_min}" not in url
    assert "{price_max}" not in url
    assert "{condition}" not in url

def test_item_name_space_encoded_as_percent20():
    channel = make_channel(template="https://asp.example.com/?q={item_name}")
    url = generate_outbound_url(make_item("iPhone 15 Pro Max"), make_assessment(), channel, ItemCondition.GOOD)
    assert " " not in url
    assert "%20" in url

def test_category_value_in_url():
    channel = make_channel(template="https://asp.example.com/?cat={category}")
    url = generate_outbound_url(make_item(tier=CategoryTier.HIGH_VALUE_STANDARD), make_assessment(), channel, ItemCondition.GOOD)
    assert "high_value_standard" in url

def test_price_values_in_url():
    channel = make_channel(template="https://asp.example.com/?min={price_min}&max={price_max}")
    url = generate_outbound_url(make_item(), make_assessment(5000, 10000), channel, ItemCondition.GOOD)
    assert "5000" in url
    assert "10000" in url

def test_condition_value_in_url():
    channel = make_channel(template="https://asp.example.com/?cond={condition}")
    url = generate_outbound_url(make_item(), make_assessment(), channel, ItemCondition.LIKE_NEW)
    assert "like_new" in url

# --- URL encoding ---
def test_ampersand_in_name_encoded():
    channel = make_channel(template="https://asp.example.com/?q={item_name}")
    url = generate_outbound_url(make_item("Sony A7 IV & Accessories"), make_assessment(), channel, ItemCondition.GOOD)
    assert "%26" in url

def test_slash_in_name_encoded():
    channel = make_channel(template="https://asp.example.com/?q={item_name}")
    url = generate_outbound_url(make_item("MacBook Pro 14/16inch"), make_assessment(), channel, ItemCondition.GOOD)
    assert "%2F" in url

def test_hash_in_name_encoded():
    channel = make_channel(template="https://asp.example.com/?q={item_name}")
    url = generate_outbound_url(make_item("Sony WH-1000XM5 #Black"), make_assessment(), channel, ItemCondition.GOOD)
    assert "%23" in url

# --- No AffiliateMeta ---
def test_no_meta_returns_base_url():
    channel = make_channel(with_meta=False)
    url = generate_outbound_url(make_item(), make_assessment(), channel, ItemCondition.GOOD)
    assert url == "https://example.com/sell"

def test_empty_template_returns_base_url():
    channel = make_channel(template="")
    url = generate_outbound_url(make_item(), make_assessment(), channel, ItemCondition.GOOD)
    assert url == channel.base_url

def test_none_price_min_substituted_as_zero():
    channel = make_channel(template="https://asp.example.com/?min={price_min}")
    url = generate_outbound_url(make_item(), make_assessment(price_min=None, price_max=10000), channel, ItemCondition.GOOD)
    assert "min=0" in url
