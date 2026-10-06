/**
 * create-draft の回帰テスト。実行（cwd は web）: node --experimental-strip-types --test src/lib/create-draft.test.mts
 */
import test from "node:test";
import assert from "node:assert/strict";
import {
  isDefaultDraft,
  parseCreateDraft,
  serializeCreateDraft,
  type CreateDraft,
  type CreateDraftChoices,
} from "./create-draft.ts";

const choices: CreateDraftChoices = {
  purposes: ["引っ越し", "遺品整理"],
  prefectures: ["東京都", "神奈川県"],
  housingTypes: ["一戸建て", "マンション"],
  floorPlans: ["2LDK", "3LDK"],
};
const defaults: CreateDraft = {
  purpose: "引っ越し",
  prefecture: "東京都",
  city: "",
  housingType: "マンション",
  floorPlan: "2LDK",
  floorNumber: "",
  hasElevator: false,
};

test("保存して読み戻すと同じ内容になる", () => {
  const draft: CreateDraft = { ...defaults, purpose: "遺品整理", city: "世田谷区", floorNumber: "3", hasElevator: true };
  assert.deepEqual(parseCreateDraft(serializeCreateDraft(draft), choices), draft);
});

test("保存対象に番地・連絡先・同意の項目が含まれない", () => {
  const keys = Object.keys(JSON.parse(serializeCreateDraft(defaults))).sort();
  assert.deepEqual(keys, ["city", "floorNumber", "floorPlan", "hasElevator", "housingType", "prefecture", "purpose", "v"]);
});

test("壊れた JSON・別の版・型違い・許可リスト外は null", () => {
  assert.equal(parseCreateDraft(null, choices), null);
  assert.equal(parseCreateDraft("", choices), null);
  assert.equal(parseCreateDraft("{", choices), null);
  assert.equal(parseCreateDraft("[]", choices), null);
  assert.equal(parseCreateDraft("null", choices), null);
  const base = JSON.parse(serializeCreateDraft(defaults));
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, v: 2 }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, purpose: "<script>" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, prefecture: "大阪府" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, hasElevator: "true" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, floorNumber: 3 }), choices), null);
});

test("市区町村: 長さ超過・制御文字は null、階数は 0〜100 の整数のみ", () => {
  const base = JSON.parse(serializeCreateDraft(defaults));
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, city: "あ".repeat(65) }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, city: "a" + String.fromCharCode(0) + "b" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, city: "a" + String.fromCharCode(0x202e) }), choices), null);
  assert.notEqual(parseCreateDraft(JSON.stringify({ ...base, floorNumber: "100" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, floorNumber: "101" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, floorNumber: "-1" }), choices), null);
  assert.equal(parseCreateDraft(JSON.stringify({ ...base, floorNumber: "1e2" }), choices), null);
});

test("既定値のままなら保存不要（isDefaultDraft）", () => {
  assert.equal(isDefaultDraft(defaults, defaults), true);
  assert.equal(isDefaultDraft({ ...defaults, city: "  " }, defaults), true);
  assert.equal(isDefaultDraft({ ...defaults, city: "港区" }, defaults), false);
  assert.equal(isDefaultDraft({ ...defaults, hasElevator: true }, defaults), false);
  assert.equal(isDefaultDraft({ ...defaults, floorPlan: "3LDK" }, defaults), false);
});
