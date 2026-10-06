import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { resolveListViewState } from "./list-state.ts";

describe("resolveListViewState（取得失敗と 0 件の区別）", () => {
  it("失敗は 0 件より優先する（出品が消えたと誤解させない）", () => {
    assert.equal(resolveListViewState({ failed: true, items: [] }), "failed");
    assert.equal(resolveListViewState({ failed: true, items: null }), "failed");
  });
  it("未取得・読み込み中は loading", () => {
    assert.equal(resolveListViewState({ failed: false, items: null }), "loading");
    assert.equal(resolveListViewState({ failed: false, items: undefined }), "loading");
    assert.equal(resolveListViewState({ pending: true, failed: false, items: [{}] }), "loading");
  });
  it("取得済みの 0 件は empty・1 件以上は list", () => {
    assert.equal(resolveListViewState({ failed: false, items: [] }), "empty");
    assert.equal(resolveListViewState({ failed: false, items: [{}] }), "list");
  });
});
