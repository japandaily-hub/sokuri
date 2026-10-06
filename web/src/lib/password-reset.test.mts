import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  parseResetLink,
  RESET_DEFAULT_ERROR_MESSAGE,
  parseResetToken,
  resolveResetErrorMessage,
  toResetAccountType,
} from "./password-reset.ts";

const VALID = "A".repeat(43);

describe("parseResetToken（あり・なし・不正形式の 3 態）", () => {
  it("あり: 形式に合う token と種別を取り出す", () => {
    assert.deepEqual(parseResetToken(`?token=${VALID}&type=operator`), {
      status: "ready",
      token: VALID,
      accountType: "operator",
    });
    assert.deepEqual(parseResetToken(`?token=${VALID}`), { status: "ready", token: VALID, accountType: "user" });
  });
  it("なし: token が無い・空・search が空", () => {
    assert.equal(parseResetToken("").status, "missing");
    assert.equal(parseResetToken(null).status, "missing");
    assert.equal(parseResetToken("?type=operator").status, "missing");
    assert.equal(parseResetToken("?token=").status, "missing");
  });
  it("不正形式: 短い・長い・使えない文字は missing（token を結果に含めない）", () => {
    for (const bad of ["short", "A".repeat(31), "A".repeat(129), `${"A".repeat(40)}<script>`, `${"A".repeat(40)} ab`]) {
      const result = parseResetToken(`?token=${encodeURIComponent(bad)}`);
      assert.equal(result.status, "missing");
      assert.equal("token" in result, false);
    }
  });
  it("2 回目に URL から token が消えていても、1 回目の結果を保持していれば ready のまま（再読込は missing になる）", () => {
    const first = parseResetToken(`?token=${VALID}`);
    const second = parseResetToken("");
    assert.equal(first.status, "ready");
    assert.equal(second.status, "missing");
  });
  it("type の不明値は user", () => {
    assert.equal(toResetAccountType("admin"), "user");
    assert.equal(toResetAccountType(undefined), "user");
  });
});

describe("resolveResetErrorMessage", () => {
  it("日本語の 4xx はそのまま使う", () => {
    assert.equal(resolveResetErrorMessage(400, "リンクが無効か期限切れです。"), "リンクが無効か期限切れです。");
    assert.equal(resolveResetErrorMessage(429, " 回数が上限に達しました "), "回数が上限に達しました");
  });
  it("404・5xx は日本語でも既定の文言", () => {
    assert.equal(resolveResetErrorMessage(404, "見つかりません"), RESET_DEFAULT_ERROR_MESSAGE);
    assert.equal(resolveResetErrorMessage(500, "内部エラー"), RESET_DEFAULT_ERROR_MESSAGE);
    assert.equal(resolveResetErrorMessage(503, "Service Unavailable"), RESET_DEFAULT_ERROR_MESSAGE);
  });
  it("日本語を含まない detail（Not Found 等）・空・null は既定の文言", () => {
    assert.equal(resolveResetErrorMessage(400, "Not Found"), RESET_DEFAULT_ERROR_MESSAGE);
    assert.equal(resolveResetErrorMessage(422, "Unprocessable Entity"), RESET_DEFAULT_ERROR_MESSAGE);
    assert.equal(resolveResetErrorMessage(400, ""), RESET_DEFAULT_ERROR_MESSAGE);
    assert.equal(resolveResetErrorMessage(400, null), RESET_DEFAULT_ERROR_MESSAGE);
  });
});

// ── フラグメント形式のリンク（security review M-3: token をサーバー・外部ログに送らない） ──

const GOOD_TOKEN = "A".repeat(43);

it("parseResetLink: フラグメントの token と種別を読む", () => {
  assert.deepEqual(parseResetLink("", `#token=${GOOD_TOKEN}&type=operator`), {
    status: "ready",
    token: GOOD_TOKEN,
    accountType: "operator",
  });
});

it("parseResetLink: 先頭の # が無くても読める", () => {
  assert.equal(parseResetLink("", `token=${GOOD_TOKEN}`).status, "ready");
});

it("parseResetLink: 旧形式のクエリも受ける（フラグメントが無いとき）", () => {
  assert.deepEqual(parseResetLink(`?token=${GOOD_TOKEN}&type=user`, ""), {
    status: "ready",
    token: GOOD_TOKEN,
    accountType: "user",
  });
});

it("parseResetLink: 両方にあればフラグメントを優先", () => {
  const other = "B".repeat(43);
  const r = parseResetLink(`?token=${other}`, `#token=${GOOD_TOKEN}`);
  assert.equal(r.status === "ready" && r.token, GOOD_TOKEN);
});

it("parseResetLink: どちらにも無い・不正形式は missing", () => {
  assert.equal(parseResetLink("", "").status, "missing");
  assert.equal(parseResetLink("", "#token=short").status, "missing");
  assert.equal(parseResetLink("?token=" + "!".repeat(40), "").status, "missing");
});

