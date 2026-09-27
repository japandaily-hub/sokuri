/**
 * chat-system-notice.ts（運営名義メッセージのお知らせ枠の判定と、日程確定の「業者が提示した候補」
 * の取り出し）の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/chat-system-notice.test.mts
 * 拡張子を .mts にしている理由・import に拡張子を付ける理由は visit-slots.test.mts と同じ。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  OPERATOR_SLOT_LABEL_HEADING,
  SYSTEM_NOTICE_LABEL,
  isSystemNotice,
  operatorSlotLabelOf,
} from "./chat-system-notice.ts";

describe("文言（2026-09-27 ユーザー決定）", () => {
  it("お知らせ枠のラベルと別枠の見出し", () => {
    assert.equal(SYSTEM_NOTICE_LABEL, "カタヅケからのお知らせ");
    assert.equal(OPERATOR_SLOT_LABEL_HEADING, "業者が提示した候補");
  });
});

describe("isSystemNotice", () => {
  it("sender_type が system のときだけ true（依頼者・業者の発言は吹き出しのまま）", () => {
    assert.equal(isSystemNotice({ sender_type: "system" }), true);
    assert.equal(isSystemNotice({ sender_type: "user" }), false);
    assert.equal(isSystemNotice({ sender_type: "operator" }), false);
  });
});

describe("operatorSlotLabelOf", () => {
  const confirmed = (meta: Record<string, unknown> | null) => ({
    sender_type: "system",
    kind: "schedule_confirmed",
    meta,
  });

  it("運営名義の日程確定で operator_slot_label が文字列ならその値", () => {
    assert.equal(
      operatorSlotLabelOf(confirmed({ visit_date: "2026-10-01", visit_time_slot: "10月1日 午前", operator_slot_label: "10月1日 午前" })),
      "10月1日 午前",
    );
  });
  it("固定時間帯で確定した日程確定（operator_slot_label なし）は null", () => {
    assert.equal(operatorSlotLabelOf(confirmed({ visit_date: "2026-10-01", visit_time_slot: "時間指定なし" })), null);
  });
  it("2026-09-27 より前の日程確定（meta に visit_time_slot だけ）は null（本文をそのまま出す）", () => {
    assert.equal(operatorSlotLabelOf(confirmed({ visit_date: "2026-10-01", visit_time_slot: "10月1日 午前" })), null);
  });
  it("壊れた meta（null・文字列以外・空白だけ）は null", () => {
    assert.equal(operatorSlotLabelOf(confirmed(null)), null);
    assert.equal(operatorSlotLabelOf(confirmed({ operator_slot_label: 123 })), null);
    assert.equal(operatorSlotLabelOf(confirmed({ operator_slot_label: ["10月1日"] })), null);
    assert.equal(operatorSlotLabelOf(confirmed({ operator_slot_label: "  　" })), null);
  });
  it("日程確定以外の運営名義メッセージ（完了確定の記録など）は null", () => {
    assert.equal(
      operatorSlotLabelOf({ sender_type: "system", kind: "completed", meta: { operator_slot_label: "x" } }),
      null,
    );
  });
  it("運営名義でないメッセージは、meta に同名の項目があっても null（業者・依頼者は別枠を作れない）", () => {
    assert.equal(
      operatorSlotLabelOf({ sender_type: "operator", kind: "schedule_confirmed", meta: { operator_slot_label: "x" } }),
      null,
    );
    assert.equal(
      operatorSlotLabelOf({ sender_type: "user", kind: "text", meta: { operator_slot_label: "x" } }),
      null,
    );
  });
});
