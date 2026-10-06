import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BID_MESSAGE_MAX_CHARS,
  classifyBidPosition,
  countCodePoints,
  formatBidAmountWithUnit,
  isBidMessageWithinLimit,
} from "./bid-input.ts";

test("コードポイントで数える（絵文字は1）", () => {
  assert.equal(countCodePoints("あいう"), 3);
  assert.equal(countCodePoints("😀"), 1);
  assert.equal(isBidMessageWithinLimit("あ".repeat(BID_MESSAGE_MAX_CHARS)), true);
  assert.equal(isBidMessageWithinLimit("あ".repeat(BID_MESSAGE_MAX_CHARS + 1)), false);
});

test("金額は千円区切り＋万・億の読みを併記する", () => {
  assert.equal(formatBidAmountWithUnit(5000), "¥5,000");
  assert.equal(formatBidAmountWithUnit(50_000), "¥50,000（5万円）");
  assert.equal(formatBidAmountWithUnit(500_000), "¥500,000（50万円）");
  assert.equal(formatBidAmountWithUnit(123_000), "¥123,000（12万3,000円）");
  assert.equal(formatBidAmountWithUnit(100_000_000), "¥100,000,000（1億円）");
});

test("同額は tied、上回られは behind、単独首位は top", () => {
  assert.equal(classifyBidPosition(40000, 40000, [40000]), "tied");
  assert.equal(classifyBidPosition(40000, 45000, [45000]), "behind");
  assert.equal(classifyBidPosition(50000, 50000, [40000]), "top");
  assert.equal(classifyBidPosition(50000, null, []), null);
});
