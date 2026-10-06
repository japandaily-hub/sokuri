/**
 * notifications-view.ts の回帰テスト（N-3 部分失敗の判定／S-5 既読）。
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/notifications-view.test.mts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  READ_MAX_ENTRIES,
  addReadSignatures,
  decideListView,
  deriveRows,
  parseReadSignatures,
  partialFailureMessage,
} from "./notifications-view.ts";

describe("decideListView", () => {
  it("行も失敗も無ければ空状態", () => {
    assert.deepEqual(decideListView(0, []), { kind: "empty" });
  });
  it("行が無く取得に失敗していれば空状態にせず error", () => {
    const v = decideListView(0, ["cases"]);
    assert.equal(v.kind, "error");
  });
  it("行があり失敗が無ければ通常表示", () => {
    assert.deepEqual(decideListView(2, []), { kind: "rows", partialFailure: false, missingLabels: [] });
  });
  it("案件の取得だけ失敗して取引の行がある場合は部分失敗として欠けた分を示す", () => {
    const v = decideListView(1, ["cases"]);
    assert.deepEqual(v, { kind: "rows", partialFailure: true, missingLabels: ["案件（入札）"] });
  });
  it("両方失敗なら両方のラベルを示す", () => {
    const v = decideListView(0, ["cases", "transactions"]);
    assert.deepEqual(v.kind === "error" && v.missingLabels, ["案件（入札）", "取引"]);
  });
  it("部分失敗の説明に欠けた取得元が入る", () => {
    assert.match(partialFailureMessage(["案件（入札）"]), /案件（入札）.*表示されていない通知があります/);
  });
});

describe("deriveRows", () => {
  it("入札・進行中・評価待ちを導く（closed/cancelled は入札に数えない）", () => {
    const rows = deriveRows(
      [
        { id: "a", bid_count: 2, status: "open" },
        { id: "b", bid_count: 1, status: "closed" },
        { id: "c", bid_count: 0, status: "open" },
      ],
      [
        { id: "t1", case_id: "a", status: "visiting" },
        { id: "t2", case_id: "x", status: "completed", has_review: false },
        { id: "t3", case_id: "y", status: "completed", has_review: true },
      ],
    );
    assert.deepEqual(rows.map((r) => r.key), ["bidding", "negotiating", "review"]);
    assert.equal(rows[1].singleCaseId, "a");
    assert.equal(rows[2].singleTransactionId, "t2");
  });
  it("入札数が増えると署名が変わる（既読が新着に戻る）", () => {
    const a = deriveRows([{ id: "a", bid_count: 1, status: "open" }], null)[0].signature;
    const b = deriveRows([{ id: "a", bid_count: 2, status: "open" }], null)[0].signature;
    assert.notEqual(a, b);
  });
  it("取得に失敗した側（null）は行を作らない", () => {
    assert.deepEqual(deriveRows(null, null), []);
  });
});

describe("既読の保存", () => {
  it("壊れた値や配列以外は空配列", () => {
    assert.deepEqual(parseReadSignatures(null), []);
    assert.deepEqual(parseReadSignatures("{"), []);
    assert.deepEqual(parseReadSignatures('{"a":1}'), []);
    assert.deepEqual(parseReadSignatures('["x",1,null,""]'), ["x"]);
  });
  it("追加は重複せず、上限を超えたら古いものから捨てる", () => {
    assert.deepEqual(addReadSignatures(["a", "b"], ["b", "c"]), ["a", "b", "c"]);
    const many = Array.from({ length: READ_MAX_ENTRIES }, (_, i) => `s${i}`);
    const out = addReadSignatures(many, ["new"]);
    assert.equal(out.length, READ_MAX_ENTRIES);
    assert.equal(out[out.length - 1], "new");
    assert.equal(out.includes("s0"), false);
  });
});
