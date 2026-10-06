import test from "node:test";
import assert from "node:assert/strict";
import { maskEmail } from "./mask-email.ts";

test("メールの伏せ字: 先頭1文字とドメインだけ出す", () => {
  assert.equal(maskEmail("tanaka@example.co.jp"), "t***@example.co.jp");
  assert.equal(maskEmail("  a@b.com "), "a***@b.com");
  assert.equal(maskEmail("a.b+c@example.com"), "a***@example.com");
});

test("メールの伏せ字: 不正・空は null", () => {
  assert.equal(maskEmail(null), null);
  assert.equal(maskEmail(undefined), null);
  assert.equal(maskEmail(""), null);
  assert.equal(maskEmail("no-at-sign"), null);
  assert.equal(maskEmail("@example.com"), null);
  assert.equal(maskEmail("a@"), null);
  assert.equal(maskEmail("a@localhost"), null);
  assert.equal(maskEmail("a b@example.com"), null);
});
