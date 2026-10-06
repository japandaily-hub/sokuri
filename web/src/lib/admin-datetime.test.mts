/**
 * admin-datetime.ts の回帰テスト（H-1: 時差情報のない日時は UTC として日本時間で表示する）。
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/admin-datetime.test.mts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { formatAdminDate, formatAdminDateTime, parseApiDateTime } from "./admin-datetime.ts";

describe("parseApiDateTime", () => {
  it("時差情報のない値は UTC として解釈する", () => {
    assert.equal(parseApiDateTime("2026-10-06T02:34:18")?.toISOString(), "2026-10-06T02:34:18.000Z");
    assert.equal(parseApiDateTime("2026-10-06 02:34:18")?.toISOString(), "2026-10-06T02:34:18.000Z");
  });
  it("Z・オフセット付きはそのまま解釈する", () => {
    assert.equal(parseApiDateTime("2026-10-06T02:34:18Z")?.toISOString(), "2026-10-06T02:34:18.000Z");
    assert.equal(parseApiDateTime("2026-10-06T11:34:18+09:00")?.toISOString(), "2026-10-06T02:34:18.000Z");
    assert.equal(parseApiDateTime("2026-10-06T02:34:18.123456+00:00")?.toISOString(), "2026-10-06T02:34:18.123Z");
  });
  it("空・不正値は null", () => {
    assert.equal(parseApiDateTime(null), null);
    assert.equal(parseApiDateTime(""), null);
    assert.equal(parseApiDateTime("not-a-date"), null);
  });
});

describe("formatAdminDateTime / formatAdminDate", () => {
  it("UTC の 02:34 は日本時間の 11:34", () => {
    assert.equal(formatAdminDateTime("2026-10-06T02:34:18"), "2026/10/6 11:34:18");
    assert.equal(formatAdminDateTime("2026-10-06T02:34:18Z"), "2026/10/6 11:34:18");
  });
  it("日付は日本時間で繰り上がる（UTC 16:00 は翌日）", () => {
    assert.equal(formatAdminDate("2026-10-06T16:00:00"), "2026/10/7");
  });
  it("不正値は —", () => {
    assert.equal(formatAdminDateTime(undefined), "—");
    assert.equal(formatAdminDate("zzz"), "—");
  });
});
