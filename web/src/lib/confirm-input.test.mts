import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isReasonMissing, isTypedNameMatch } from "./confirm-input.ts";

describe("isTypedNameMatch（削除確認の社名入力）", () => {
  it("前後の空白を除いて完全一致なら true", () => {
    assert.equal(isTypedNameMatch("株式会社テスト", "株式会社テスト"), true);
    assert.equal(isTypedNameMatch("  株式会社テスト ", "株式会社テスト"), true);
  });
  it("一部・大小文字・全半角の違いは false", () => {
    assert.equal(isTypedNameMatch("株式会社", "株式会社テスト"), false);
    assert.equal(isTypedNameMatch("abc", "ABC"), false);
    assert.equal(isTypedNameMatch("ＡＢＣ", "ABC"), false);
  });
  it("未入力・null は false。期待値が空のときは常に false（空同士の一致で通さない）", () => {
    assert.equal(isTypedNameMatch("", "株式会社テスト"), false);
    assert.equal(isTypedNameMatch(null, "株式会社テスト"), false);
    assert.equal(isTypedNameMatch("", ""), false);
    assert.equal(isTypedNameMatch("x", "  "), false);
  });
});

describe("isReasonMissing（停止・却下理由の必須判定）", () => {
  it("理由必須で空・空白のみなら true", () => {
    assert.equal(isReasonMissing(true, true, ""), true);
    assert.equal(isReasonMissing(true, true, "   "), true);
  });
  it("入力があれば false", () => {
    assert.equal(isReasonMissing(true, true, "不正利用の疑い"), false);
  });
  it("任意の理由欄・理由欄なしでは空でも false", () => {
    assert.equal(isReasonMissing(true, false, ""), false);
    assert.equal(isReasonMissing(false, true, ""), false);
  });
});
