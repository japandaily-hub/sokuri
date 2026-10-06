/** chat-cursor の境界テスト（同秒・重なり窓・自分の送信・空応答）。 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { advanceCursor, appendNewMessages, cursorToAfterParam, latestCreatedAt } from "./chat-cursor.ts";

const m = (id: string, created_at: string) => ({ id, created_at });

describe("latestCreatedAt / advanceCursor", () => {
  it("空応答ではカーソルを動かさない", () => {
    assert.equal(latestCreatedAt([]), undefined);
    assert.equal(advanceCursor("2026-10-06T02:00:00Z", []), "2026-10-06T02:00:00Z");
    assert.equal(advanceCursor(undefined, []), undefined);
  });
  it("末尾ではなく最大の created_at で進める（並びが前後しても）", () => {
    const batch = [m("a", "2026-10-06T02:00:10Z"), m("b", "2026-10-06T02:00:05Z")];
    assert.equal(latestCreatedAt(batch), "2026-10-06T02:00:10Z");
  });
  it("現在より古い取得では戻さない", () => {
    assert.equal(advanceCursor("2026-10-06T02:00:10Z", [m("a", "2026-10-06T02:00:05Z")]), "2026-10-06T02:00:10Z");
  });
  it("時差なしの値は UTC として比較する", () => {
    assert.equal(advanceCursor("2026-10-06T02:00:10", [m("a", "2026-10-06T02:00:10Z")]), "2026-10-06T02:00:10");
    assert.equal(advanceCursor("2026-10-06T02:00:10", [m("a", "2026-10-06T11:00:11+09:00")]), "2026-10-06T11:00:11+09:00");
  });
  it("解釈できない値は無視する", () => {
    assert.equal(latestCreatedAt([m("a", "garbage")]), undefined);
    assert.equal(advanceCursor("2026-10-06T02:00:10Z", [m("a", "garbage")]), "2026-10-06T02:00:10Z");
  });
  it("自分の送信（楽観追加）はカーソルを進めない: 呼ばなければ変わらない", () => {
    const cursor = "2026-10-06T02:00:00Z";
    // 相手の発言(02:00:03)が自分の送信(02:00:05)より前にサーバーへ入っていた場合も、
    // カーソルは 02:00:00 のままなので次の差分で拾える。
    const after = cursorToAfterParam(cursor);
    assert.equal(after, "2026-10-06T01:59:55.000Z");
    assert.ok(new Date("2026-10-06T02:00:03Z").getTime() > new Date(after as string).getTime());
  });
});

describe("cursorToAfterParam", () => {
  it("カーソルなし・不正は undefined（全件）", () => {
    assert.equal(cursorToAfterParam(undefined), undefined);
    assert.equal(cursorToAfterParam("garbage"), undefined);
  });
  it("5 秒手前の UTC ISO にする", () => {
    assert.equal(cursorToAfterParam("2026-10-06T02:34:20"), "2026-10-06T02:34:15.000Z");
    assert.equal(cursorToAfterParam("2026-10-06T11:34:20+09:00"), "2026-10-06T02:34:15.000Z");
  });
  it("重なり窓を指定できる（同秒の取りこぼしを窓内に収める）", () => {
    assert.equal(cursorToAfterParam("2026-10-06T02:34:20Z", 0), "2026-10-06T02:34:20.000Z");
  });
});

describe("appendNewMessages", () => {
  it("重なり窓で再び返った既知の id は足さない", () => {
    const prev = [m("a", "2026-10-06T02:00:00Z"), m("b", "2026-10-06T02:00:01Z")];
    const next = appendNewMessages(prev, [m("b", "2026-10-06T02:00:01Z"), m("c", "2026-10-06T02:00:01Z")]);
    assert.deepEqual(next.map((x) => x.id), ["a", "b", "c"]);
  });
  it("同秒の別 id は両方残る", () => {
    const next = appendNewMessages([m("a", "2026-10-06T02:00:00Z")], [m("b", "2026-10-06T02:00:00Z")]);
    assert.equal(next.length, 2);
  });
  it("新規が無ければ同じ参照を返す・応答内の重複も 1 件にする", () => {
    const prev = [m("a", "x")];
    assert.equal(appendNewMessages(prev, []), prev);
    assert.equal(appendNewMessages(prev, [m("a", "x")]), prev);
    assert.equal(appendNewMessages([], [m("z", "x"), m("z", "x")]).length, 1);
  });
});
