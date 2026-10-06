import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { MESSAGE_MAX_CHARS, countChars } from "./char-count.ts";

describe("countChars", () => {
  it("上限は backend と同じ 2000", () => {
    assert.equal(MESSAGE_MAX_CHARS, 2000);
  });
  it("サロゲートペアは1文字として数える（Pythonのlen()と一致させるため）", () => {
    assert.equal(countChars(String.fromCodePoint(0x1f600)), 1);
    assert.equal(countChars(String.fromCodePoint(0x1f600).repeat(3)), 3);
  });
  it("孤立サロゲートもそれ自体を1文字として数える", () => {
    assert.equal(countChars(String.fromCharCode(0xd800)), 1);
    assert.equal(countChars(String.fromCharCode(0xdc00)), 1);
  });
  it("日本語は1文字ずつ・空文字は0", () => {
    assert.equal(countChars("こんにちは"), 5);
    assert.equal(countChars(""), 0);
  });
  it("trim オプション: チャットは trim 後、入札は生の値（既定）で数える", () => {
    assert.equal(countChars("  あ  "), 5);
    assert.equal(countChars("  あ  ", { trim: false }), 5);
    assert.equal(countChars("  あ  ", { trim: true }), 1);
    assert.equal(countChars("   ", { trim: true }), 0);
  });
});
