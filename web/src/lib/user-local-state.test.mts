import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { clearUserLocalState, shortSha256, userScopedStorageKey } from "./user-local-state.ts";

function fakeStorage(entries: Record<string, string>) {
  const map = new Map(Object.entries(entries));
  return {
    map,
    get length() {
      return map.size;
    },
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => void map.delete(key),
  };
}

describe("shortSha256", () => {
  it("SHA-256 の先頭16文字（既知ベクトル: 'abc'）", async () => {
    assert.equal(await shortSha256("abc"), "ba7816bf8f01cfea");
  });
});

describe("userScopedStorageKey", () => {
  it("利用者ごとに別のキー・同じ利用者は同じキー（大文字小文字と前後空白は無視）", async () => {
    const a = await userScopedStorageKey("kdz:create-draft:v2", "A@example.com");
    const a2 = await userScopedStorageKey("kdz:create-draft:v2", " a@example.com ");
    const b = await userScopedStorageKey("kdz:create-draft:v2", "b@example.com");
    assert.equal(a, a2);
    assert.notEqual(a, b);
    assert.match(a ?? "", /^kdz:create-draft:v2:[0-9a-f]{16}$/);
  });
  it("識別子が無ければ null（保存・復元しない）・識別子そのものはキーに含めない", async () => {
    assert.equal(await userScopedStorageKey("k", undefined), null);
    assert.equal(await userScopedStorageKey("k", "  "), null);
    assert.doesNotMatch((await userScopedStorageKey("k", "a@example.com")) ?? "", /example/);
  });
});

describe("clearUserLocalState", () => {
  it("接頭辞に一致するキーだけを、旧版・全利用者分まとめて消す", () => {
    const storage = fakeStorage({
      "kdz:create-draft:v1": "{}",
      "kdz:create-draft:v2:aaaaaaaaaaaaaaaa": "{}",
      "kdz.notifications.read.v2:bbbbbbbbbbbbbbbb": "[]",
      "other-key": "keep",
    });
    assert.equal(clearUserLocalState(storage), 3);
    assert.deepEqual(Array.from(storage.map.keys()), ["other-key"]);
  });
  it("storage が無い・例外を投げても落ちない", () => {
    assert.equal(clearUserLocalState(null), 0);
    const broken = {
      length: 1,
      key: () => {
        throw new Error("denied");
      },
      removeItem: () => undefined,
    };
    assert.equal(clearUserLocalState(broken), 0);
  });
});
