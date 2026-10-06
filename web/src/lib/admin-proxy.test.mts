/**
 * admin-proxy.ts の回帰テスト（H-3: 運営の代理閲覧帯、H-2 画面側: チャット入力の無効化）。
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/admin-proxy.test.mts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { shouldDisableChatInput, shouldShowProxyBanner } from "./admin-proxy.ts";

describe("shouldShowProxyBanner", () => {
  it("運営が依頼者・業者向けの画面を開いたときだけ出す", () => {
    assert.equal(shouldShowProxyBanner("/cases/abc", "admin"), true);
    assert.equal(shouldShowProxyBanner("/chat/123", "admin"), true);
    assert.equal(shouldShowProxyBanner("/mypage", "admin"), false);
    assert.equal(shouldShowProxyBanner("/notifications", "admin"), false);
    assert.equal(shouldShowProxyBanner("/operator", "admin"), true);
    assert.equal(shouldShowProxyBanner("/operator/cases/1", "admin"), true);
    assert.equal(shouldShowProxyBanner("/create", "admin"), true);
  });
  it("運営以外・/admin・公開ページでは出さない", () => {
    assert.equal(shouldShowProxyBanner("/cases/abc", "user"), false);
    assert.equal(shouldShowProxyBanner("/chat/123", "operator"), false);
    assert.equal(shouldShowProxyBanner("/admin/users", "admin"), false);
    assert.equal(shouldShowProxyBanner("/", "admin"), false);
    assert.equal(shouldShowProxyBanner("/casesfoo", "admin"), false);
    assert.equal(shouldShowProxyBanner("/operator/login", "admin"), false);
    assert.equal(shouldShowProxyBanner("/operatorfoo", "admin"), false);
    assert.equal(shouldShowProxyBanner("/operator", "operator"), false);
    assert.equal(shouldShowProxyBanner(null, "admin"), false);
    assert.equal(shouldShowProxyBanner("/cases", undefined), false);
  });
});

describe("shouldDisableChatInput", () => {
  it("運営がチャット系画面にいるときだけ入力を無効にする", () => {
    assert.equal(shouldDisableChatInput("/chat/1", "admin"), true);
    assert.equal(shouldDisableChatInput("/cases/1", "admin"), true);
    assert.equal(shouldDisableChatInput("/operator/chat/1", "admin"), true);
    assert.equal(shouldDisableChatInput("/operator/cases/1", "admin"), false);
    assert.equal(shouldDisableChatInput("/mypage", "admin"), false);
    assert.equal(shouldDisableChatInput("/chat/1", "user"), false);
  });
});
