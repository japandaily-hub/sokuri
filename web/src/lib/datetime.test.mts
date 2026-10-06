/**
 * datetime.ts（API 日時の日本時間表示）の回帰テスト。
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/datetime.test.mts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  formatJstDate,
  formatJstDateSeparator,
  formatJstDateTime,
  formatJstMonthDayTime,
  formatJstTime,
  parseApiDateTime,
} from "./datetime.ts";

describe("parseApiDateTime", () => {
  it("時差情報のない日時は UTC として解釈する（V-02）", () => {
    assert.equal(parseApiDateTime("2026-10-06T02:34:20")?.toISOString(), "2026-10-06T02:34:20.000Z");
    assert.equal(parseApiDateTime("2026-10-06 02:34:20")?.toISOString(), "2026-10-06T02:34:20.000Z");
    assert.equal(parseApiDateTime("2026-10-06T02:34:20.123456")?.toISOString(), "2026-10-06T02:34:20.123Z");
  });
  it("Z ありはそのまま UTC", () => {
    assert.equal(parseApiDateTime("2026-10-06T02:34:20Z")?.toISOString(), "2026-10-06T02:34:20.000Z");
    assert.equal(parseApiDateTime("2026-10-06T02:34:20.5z")?.toISOString(), "2026-10-06T02:34:20.500Z");
  });
  it("オフセットありはそのオフセットで解釈する", () => {
    assert.equal(parseApiDateTime("2026-10-06T11:34:20+09:00")?.toISOString(), "2026-10-06T02:34:20.000Z");
    assert.equal(parseApiDateTime("2026-10-06T11:34:20+0900")?.toISOString(), "2026-10-06T02:34:20.000Z");
    assert.equal(parseApiDateTime("2026-10-06T11:34:20+09")?.toISOString(), "2026-10-06T02:34:20.000Z");
    assert.equal(parseApiDateTime("2026-10-05T21:34:20-05:00")?.toISOString(), "2026-10-06T02:34:20.000Z");
  });
  it("不正・空・非文字列は null", () => {
    for (const bad of ["", "   ", "abc", "2026-13-45T99:99:99", null, undefined]) {
      assert.equal(parseApiDateTime(bad as string | null | undefined), null);
    }
  });
});

describe("日本時間の整形", () => {
  it("UTC の素の値を JST で出す（02:44 は 11:44）", () => {
    assert.equal(formatJstTime("2026-10-06T02:44:00"), "11:44");
    assert.equal(formatJstTime("2026-10-06T02:44:00Z"), "11:44");
    assert.equal(formatJstTime("2026-10-06T11:44:00+09:00"), "11:44");
  });
  it("日付をまたぐ（UTC 15:30 は JST 翌日 00:30）", () => {
    assert.equal(formatJstTime("2026-10-06T15:30:00"), "00:30");
    assert.equal(formatJstDate("2026-10-06T15:30:00"), "2026/10/7");
    assert.equal(formatJstMonthDayTime("2026-10-06T15:30:00"), "10/7 00:30");
  });
  it("日付＋時刻・日付区切り", () => {
    assert.equal(formatJstDateTime("2026-10-06T02:34:18"), "2026/10/6 11:34");
    assert.match(formatJstDateSeparator("2026-10-06T02:34:18"), /^10月6日/);
  });
  it("不正値は空文字", () => {
    assert.equal(formatJstTime("xxx"), "");
    assert.equal(formatJstDateTime(""), "");
    assert.equal(formatJstDate(undefined), "");
  });
});

import { formatJstDateTimeSeconds, jstYearMonthKey } from "./datetime.ts";

describe("formatJstDateTimeSeconds / jstYearMonthKey", () => {
  it("秒つきで日本時間にする", () => {
    assert.equal(formatJstDateTimeSeconds("2026-10-06T02:34:18"), "2026/10/6 11:34:18");
    assert.equal(formatJstDateTimeSeconds("garbage"), "");
  });
  it("JST の月境界で年月キーを返す（UTC 月末 15:00 以降は翌月）", () => {
    assert.equal(jstYearMonthKey("2026-09-30T14:59:59Z"), "2026-09");
    assert.equal(jstYearMonthKey("2026-09-30T15:00:00Z"), "2026-10");
    assert.equal(jstYearMonthKey("2026-12-31T15:00:00"), "2027-01");
    assert.equal(jstYearMonthKey(null), null);
    assert.equal(jstYearMonthKey("garbage"), null);
  });
});
