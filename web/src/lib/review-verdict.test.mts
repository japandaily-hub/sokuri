/**
 * review-verdict.ts の純関数の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/review-verdict.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts と同じ（tsconfig の include に一致させず、型検査・ビルドの対象から
 * 外したまま実行できるようにするため）。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  REVIEW_COMMENT_MAX,
  REVIEW_PHRASES,
  appendPhrase,
  canAppend,
  formatVerdictCounts,
  hasPhrase,
  removePhrase,
  type ReviewDirection,
} from "./review-verdict.ts";

const DIRECTIONS: readonly ReviewDirection[] = ["to_operator", "to_user"];

describe("REVIEW_PHRASES の不変条件", () => {
  for (const direction of DIRECTIONS) {
    it(`${direction}: 評価を切り替えても候補文どうしが互いに部分文字列にならない（good/improve 混在）`, () => {
      // 評価（good/improve）を切り替えてもコメント本文は消えない仕様のため、
      // good 側の候補文が improve 側の部分文字列になっている（またはその逆）と、
      // hasPhrase による選択状態の判定を誤らせる。同一 direction 内は
      // good/improve を区別せず全ペアで確認する（QA再レビュー Low 対応）。
      const phrases = [...REVIEW_PHRASES[direction].good, ...REVIEW_PHRASES[direction].improve];
      assert.ok(phrases.length > 0, "候補文が1件も無い");
      for (const a of phrases) {
        for (const b of phrases) {
          if (a === b) continue;
          assert.equal(a.includes(b), false, `"${a}" が "${b}" を部分文字列として含んでいる`);
        }
      }
    });
  }
});

describe("hasPhrase", () => {
  it("候補文が本文に含まれていれば true", () => {
    assert.equal(hasPhrase("安心して取引できました！ありがとう", "安心して取引できました！"), true);
  });
  it("候補文が本文に含まれていなければ false", () => {
    assert.equal(hasPhrase("スムーズでした！", "安心して取引できました！"), false);
  });
});

describe("appendPhrase", () => {
  it("空文字への追記はフレーズをそのまま返す", () => {
    assert.equal(appendPhrase("", "スムーズでした！"), "スムーズでした！");
  });
  it("直前が文末記号（。）なら区切りを入れない", () => {
    assert.equal(
      appendPhrase("ありがとうございました。", "スムーズでした！"),
      "ありがとうございました。スムーズでした！",
    );
  });
  it("直前が文末記号（半角!）でも区切りを入れない", () => {
    assert.equal(appendPhrase("助かりました!", "スムーズでした！"), "助かりました!スムーズでした！");
  });
  it("直前が文末記号（全角？）でも区切りを入れない", () => {
    assert.equal(appendPhrase("大丈夫ですか？", "スムーズでした！"), "大丈夫ですか？スムーズでした！");
  });
  it("直前が文末記号（半角?）でも区切りを入れない", () => {
    assert.equal(appendPhrase("大丈夫ですか?", "スムーズでした！"), "大丈夫ですか?スムーズでした！");
  });
  it("直前が文末記号以外なら半角スペース1つを挟む", () => {
    assert.equal(appendPhrase("はじめまして", "スムーズでした！"), "はじめまして スムーズでした！");
  });
  it("末尾の空白（半角）は除いてから追記する（二重スペースにしない）", () => {
    assert.equal(appendPhrase("はじめまして   ", "スムーズでした！"), "はじめまして スムーズでした！");
  });
  it("末尾の空白が全角スペースでも除いてから追記する", () => {
    assert.equal(
      appendPhrase("はじめまして　　", "スムーズでした！"),
      "はじめまして スムーズでした！",
    );
  });
});

describe("removePhrase", () => {
  it("appendPhrase の逆操作になる（往復で元の文字列に戻る）", () => {
    const bases = ["", "ありがとうございました。", "はじめまして", "助かりました!"];
    const phrase = "スムーズでした！";
    for (const base of bases) {
      const appended = appendPhrase(base, phrase);
      assert.equal(removePhrase(appended, phrase), base, `base=${JSON.stringify(base)}`);
    }
  });
  it("候補文が含まれていなければ変化しない", () => {
    assert.equal(removePhrase("こんにちは", "スムーズでした！"), "こんにちは");
  });
  it("候補文の前後にあるユーザー自身の文章には触れない", () => {
    const text = "はじめまして スムーズでした！よろしくお願いします";
    assert.equal(removePhrase(text, "スムーズでした！"), "はじめましてよろしくお願いします");
  });
  it("利用者自身が打った、候補文と無関係な位置の半角スペースには触れない", () => {
    const phrase = "スムーズでした！";
    const userText = "こんにちは 今日は良い天気です";
    const appended = appendPhrase(userText, phrase);
    assert.equal(appended, `${userText} ${phrase}`);
    assert.equal(removePhrase(appended, phrase), userText);
  });
  it("候補文の直前に利用者自身が半角スペースを手動入力していた場合、appendPhrase が" +
    "挟んだものと区別できずそのスペースごと取り除く（現状の仕様として固定）", () => {
    const phrase = "スムーズでした！";
    const text = `メモ ${phrase}`; // チップ操作を経ずに手入力で全く同じ文言を作ったケース
    assert.equal(removePhrase(text, phrase), "メモ");
  });
  it("同じ候補文が2回含まれる場合、1回の呼び出しでは最初の1件だけが消える", () => {
    const phrase = "スムーズでした！"; // 文末が！のため2回連続追記しても区切りは入らない
    const twice = appendPhrase(appendPhrase("", phrase), phrase);
    assert.equal(twice, phrase + phrase);
    const once = removePhrase(twice, phrase);
    assert.equal(once, phrase, "1件目だけが消え、2件目はそのまま残るはず");
    assert.equal(hasPhrase(once, phrase), true);
    assert.equal(removePhrase(once, phrase), "");
  });
});

describe("候補文の一部だけ手動編集された場合の挙動（現状の仕様として固定）", () => {
  it("末尾の「！」だけを消した直後に同じチップを押すと、完全一致しないため" +
    "選択中とは判定されず、全文を重複して追記する", () => {
    const phrase = "安心して取引できました！";
    const edited = phrase.slice(0, -1); // 利用者が末尾の「！」だけを手動で消した状態
    assert.equal(hasPhrase(edited, phrase), false);
    assert.equal(canAppend(edited, phrase), true);
    assert.equal(appendPhrase(edited, phrase), `${edited} ${phrase}`);
  });
});

describe("canAppend", () => {
  it("追記後がちょうど上限文字数なら true", () => {
    const phrase = "あ".repeat(5);
    // "い"×n + 区切り半角スペース1 + phrase(5) === REVIEW_COMMENT_MAX
    const base = "い".repeat(REVIEW_COMMENT_MAX - phrase.length - 1);
    assert.equal(base.length + 1 + phrase.length, REVIEW_COMMENT_MAX);
    assert.equal(canAppend(base, phrase), true);
  });
  it("追記後に上限を1字超えるなら false", () => {
    const phrase = "あ".repeat(5);
    const base = "い".repeat(REVIEW_COMMENT_MAX - phrase.length);
    assert.equal(canAppend(base, phrase), false);
  });
  it("空文字への追記でちょうど300字（REVIEW_COMMENT_MAX）なら true", () => {
    const phrase = "あ".repeat(REVIEW_COMMENT_MAX);
    assert.equal(canAppend("", phrase), true);
  });
  it("空文字への追記で301字（REVIEW_COMMENT_MAX+1）なら false", () => {
    const phrase = "あ".repeat(REVIEW_COMMENT_MAX + 1);
    assert.equal(canAppend("", phrase), false);
  });
});

describe("formatVerdictCounts", () => {
  it("よかった・伸びしろの件数を整形する", () => {
    assert.equal(formatVerdictCounts(3, 1), "よかった 3・伸びしろ 1");
  });
  it("0件でも表示できる", () => {
    assert.equal(formatVerdictCounts(0, 0), "よかった 0・伸びしろ 0");
  });
});
