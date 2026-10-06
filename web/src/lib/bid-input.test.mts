import assert from "node:assert/strict";
import { test } from "node:test";

import { MESSAGE_MAX_CHARS, countChars } from "./char-count.ts";
import {
  classifyBidPosition,
  formatBidAmountWithUnit,
  isBidMessageWithinLimit,
} from "./bid-input.ts";

test("コードポイントで数える（絵文字は1）", () => {
  assert.equal(countChars("あいう"), 3);
  assert.equal(countChars("😀"), 1);
  assert.equal(isBidMessageWithinLimit("あ".repeat(MESSAGE_MAX_CHARS)), true);
  assert.equal(isBidMessageWithinLimit("あ".repeat(MESSAGE_MAX_CHARS + 1)), false);
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

test("一覧の首位文言: 2社以上の首位は同額の可能性を添える", async () => {
  const { topBidderLabel } = await import("./bid-input.ts");
  assert.equal(topBidderLabel(true, 1), "自社が最高額");
  assert.equal(topBidderLabel(true, 2), "自社が最高額（同額の可能性あり）");
  assert.equal(topBidderLabel(false, 3), "他社が上回り中");
  assert.equal(topBidderLabel(undefined, 3), null);
  // backend が同額フラグを返すときは断定する（R2-04）。
  assert.equal(topBidderLabel(true, 3, false), "自社が単独の最高額");
  assert.equal(topBidderLabel(true, 3, true), "自社が最高額（他社と同額で並んでいます）");
  assert.equal(topBidderLabel(true, 3, null), "自社が最高額（同額の可能性あり）");
  assert.equal(topBidderLabel(false, 3, true), "他社が上回り中");
});

test("初回入札の確認モーダルの桁表示: 境界と不正値", () => {
  assert.equal(formatBidAmountWithUnit(9_999), "¥9,999");
  assert.equal(formatBidAmountWithUnit(10_000), "¥10,000（1万円）");
  assert.equal(formatBidAmountWithUnit(0), "¥0");
  assert.equal(formatBidAmountWithUnit(100_010_000), "¥100,010,000（1億1万円）");
  assert.equal(formatBidAmountWithUnit(1_234_567), "¥1,234,567（123万4,567円）");
  // 桁の打ち間違い（5 万と 50 万）が読みで区別できる
  assert.notEqual(formatBidAmountWithUnit(50_000), formatBidAmountWithUnit(500_000));
});
