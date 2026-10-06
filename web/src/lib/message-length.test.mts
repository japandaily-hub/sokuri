/**
 * message-length.ts（本文の文字数上限・IME 判定）の回帰テスト。
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/message-length.test.mts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { MESSAGE_MAX_CHARS, countChars } from "./char-count.ts";
import { isImeComposingKey, messageLengthState } from "./message-length.ts";

describe("messageLengthState", () => {
  it("上限は backend と同じ 2000", () => {
    assert.equal(MESSAGE_MAX_CHARS, 2000);
  });
  it("ちょうど 2000 字は送れる・2001 字は超過", () => {
    assert.equal(messageLengthState("あ".repeat(2000)).over, false);
    const over = messageLengthState("あ".repeat(2001));
    assert.equal(over.over, true);
    assert.equal(over.excess, 1);
    assert.ok(over.overMessage?.includes("2,000字を超えている"));
    assert.ok(over.overMessage?.includes("1字減らして"));
  });
  it("前後の空白は数えない", () => {
    assert.equal(messageLengthState("  abc  ").count, 3);
    assert.equal(messageLengthState("   ").count, 0);
  });
  it("絵文字（サロゲートペア）は 1 字と数える", () => {
    const emoji = String.fromCodePoint(0x1f600);
    assert.equal(countChars(emoji + emoji), 2);
    assert.equal(messageLengthState(emoji.repeat(2000)).over, false);
  });
  it("カウンタ表示", () => {
    assert.equal(messageLengthState("あ".repeat(1234)).counterLabel, "1,234 / 2,000");
    assert.equal(messageLengthState("").overMessage, null);
  });
});

describe("isImeComposingKey", () => {
  it("isComposing / keyCode 229 は変換中", () => {
    assert.equal(isImeComposingKey({ isComposing: true }), true);
    assert.equal(isImeComposingKey({ nativeEvent: { isComposing: true } }), true);
    assert.equal(isImeComposingKey({ isComposing: false, keyCode: 229 }), true);
    assert.equal(isImeComposingKey({ nativeEvent: { keyCode: 229 } }), true);
  });
  it("通常の Enter（keyCode 13）は変換中ではない", () => {
    assert.equal(isImeComposingKey({ isComposing: false, keyCode: 13 }), false);
    assert.equal(isImeComposingKey({}), false);
  });
});
