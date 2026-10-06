import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { LINE_CONSENT_REQUIRED_HINT, canStartLineAuth, lineConsentHint } from "./line-consent.ts";

describe("canStartLineAuth（N-2・N-9: LINE ボタンは明示の同意後だけ押せる）", () => {
  it("同意済み・遷移中でない → 押せる", () => {
    assert.equal(canStartLineAuth({ agreed: true, busy: false }), true);
  });
  it("未同意 → 押せない", () => {
    assert.equal(canStartLineAuth({ agreed: false, busy: false }), false);
  });
  it("同意済みでも遷移中 → 押せない（二重押し防止）", () => {
    assert.equal(canStartLineAuth({ agreed: true, busy: true }), false);
  });
  it("未同意かつ遷移中 → 押せない", () => {
    assert.equal(canStartLineAuth({ agreed: false, busy: true }), false);
  });
  it("boolean の true 以外は同意とみなさない（取り違え防止）", () => {
    for (const v of ["true", 1, null, undefined, {}] as unknown[]) {
      assert.equal(canStartLineAuth({ agreed: v as boolean, busy: false }), false, String(v));
    }
  });
});

describe("lineConsentHint", () => {
  it("未同意のときだけ理由を出す", () => {
    assert.equal(lineConsentHint({ agreed: false, busy: false }), LINE_CONSENT_REQUIRED_HINT);
    assert.equal(lineConsentHint({ agreed: true, busy: false }), null);
  });
  it("遷移中は出さない", () => {
    assert.equal(lineConsentHint({ agreed: false, busy: true }), null);
    assert.equal(lineConsentHint({ agreed: true, busy: true }), null);
  });
  it("理由の文言は規約とポリシーの両方に触れる", () => {
    assert.match(LINE_CONSENT_REQUIRED_HINT, /利用規約/);
    assert.match(LINE_CONSENT_REQUIRED_HINT, /プライバシーポリシー/);
  });
});

describe("配線: /login・/signup の LINE ボタンは同意つきの部品を使い、みなし同意を残さない", () => {
  const APP = join(process.cwd(), "src", "app");
  for (const file of ["login/page.tsx", "signup/page.tsx"]) {
    const src = readFileSync(join(APP, file), "utf8");
    it(`${file}: LineConsentAuth を使う`, () => {
      assert.match(src, /<LineConsentAuth\b/);
    });
    it(`${file}: 同意なしの LineAuthButton を直接置かない`, () => {
      assert.doesNotMatch(src, /<LineAuthButton\b/);
    });
    it(`${file}: みなし同意の文言がない`, () => {
      assert.doesNotMatch(src, /同意したものとみなします/);
    });
  }
});
