/**
 * case-detail-view の回帰テスト。実行（cwd は web）: node --experimental-strip-types --test src/lib/case-detail-view.test.mts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { buildHousingAttributes, isCaseIdFormat, isCompletionBeforeVisit, meaningfulCaseSummary } from "./case-detail-view.ts";

test("案件IDはUUID形式のみ受け付ける", () => {
  assert.equal(isCaseIdFormat("c1358ff2-7d6a-4c1e-9d3a-0123456789ab"), true);
  assert.equal(isCaseIdFormat("abc"), false);
  assert.equal(isCaseIdFormat(""), false);
  assert.equal(isCaseIdFormat(undefined), false);
  assert.equal(isCaseIdFormat("c1358ff2-7d6a-4c1e-9d3a-0123456789abZ"), false);
});

test("住居情報: 未入力は出さず、EV未入力を「なし」と断定しない", () => {
  assert.deepEqual(
    buildHousingAttributes({ housing_type: "マンション", floor_plan: "2LDK", floor_number: null, has_elevator: null }),
    ["マンション", "2LDK"],
  );
  assert.deepEqual(
    buildHousingAttributes({ housing_type: null, floor_plan: null, floor_number: null, has_elevator: null }),
    [],
  );
  assert.deepEqual(
    buildHousingAttributes({ housing_type: "アパート", floor_plan: "1K", floor_number: 3, has_elevator: false }),
    ["アパート", "1K", "3階", "エレベーターなし"],
  );
  assert.deepEqual(
    buildHousingAttributes({ housing_type: null, floor_plan: null, floor_number: 0, has_elevator: true }),
    ["0階", "エレベーターあり"],
  );
});

test("作業完了: 訪問日前・日程未定・不正形式は警告、当日以降は警告なし", () => {
  assert.equal(isCompletionBeforeVisit("2026-10-11", "2026-10-06"), true);
  assert.equal(isCompletionBeforeVisit(null, "2026-10-06"), true);
  assert.equal(isCompletionBeforeVisit("2026/10/11", "2026-10-06"), true);
  assert.equal(isCompletionBeforeVisit("2026-10-06", "2026-10-06"), false);
  assert.equal(isCompletionBeforeVisit("2026-10-01", "2026-10-06"), false);
});

test("案件の説明: 定型（詳細は写真を確認してください）・空は出さず、実際の説明は出す", () => {
  assert.equal(meaningfulCaseSummary("利用目的: 引っ越し。住居: マンション（2LDK）。写真 3 枚。詳細は写真を確認してください。"), null);
  assert.equal(meaningfulCaseSummary("利用目的: 遺品整理。写真 1 枚。詳細は写真を確認してください。"), null);
  assert.equal(meaningfulCaseSummary(null), null);
  assert.equal(meaningfulCaseSummary(undefined), null);
  assert.equal(meaningfulCaseSummary("   "), null);
  assert.equal(meaningfulCaseSummary("  木製の本棚。目立つ傷はありません。 "), "木製の本棚。目立つ傷はありません。");
  // 定型に似ていても実際の説明が混ざるものは出す。
  assert.equal(
    meaningfulCaseSummary("利用目的: 引っ越し。写真 2 枚。詳細は写真を確認してください。背面に傷があります。"),
    "利用目的: 引っ越し。写真 2 枚。詳細は写真を確認してください。背面に傷があります。",
  );
});
