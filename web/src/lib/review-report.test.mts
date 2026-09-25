/**
 * review-report.ts の純関数の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/review-report.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts / review-verdict.test.mts と同じ。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildReviewReportMessagePrefix,
  buildReviewReportSubject,
  extractReviewIdFromMessage,
  parseReviewReportSubject,
  withReviewReportPrefix,
} from "./review-report.ts";

const SAMPLE_ID = "8a3f7e10-1234-4abc-9def-0123456789ab";

describe("buildReviewReportSubject / parseReviewReportSubject", () => {
  it("往復で元の ID に戻る", () => {
    const subject = buildReviewReportSubject(SAMPLE_ID);
    assert.equal(subject, `口コミの報告（${SAMPLE_ID}）`);
    assert.equal(parseReviewReportSubject(subject), SAMPLE_ID);
  });

  it("null・undefined・空文字は null", () => {
    assert.equal(parseReviewReportSubject(null), null);
    assert.equal(parseReviewReportSubject(undefined), null);
    assert.equal(parseReviewReportSubject(""), null);
  });

  it("前後に余計な文字が付くと不一致（厳密一致のみ許可）", () => {
    const subject = buildReviewReportSubject(SAMPLE_ID);
    assert.equal(parseReviewReportSubject(`${subject} `), null);
    assert.equal(parseReviewReportSubject(`re: ${subject}`), null);
    assert.equal(parseReviewReportSubject(subject.slice(0, -1)), null);
  });

  it("UUID の形式が崩れていると不一致", () => {
    assert.equal(parseReviewReportSubject("口コミの報告（not-a-uuid）"), null);
  });

  it("無関係な subject は null（/contact の他導線に誤反応しない）", () => {
    assert.equal(parseReviewReportSubject("事業者情報の開示請求"), null);
  });
});

describe("buildReviewReportMessagePrefix / withReviewReportPrefix / extractReviewIdFromMessage", () => {
  it("本文ありなら件名行 + 改行 + 本文になる", () => {
    const withPrefix = withReviewReportPrefix(SAMPLE_ID, "この口コミは事実と異なります。");
    assert.equal(withPrefix, `報告する口コミ: ${SAMPLE_ID}\nこの口コミは事実と異なります。`);
  });

  it("本文が空なら件名行だけになる", () => {
    assert.equal(withReviewReportPrefix(SAMPLE_ID, ""), buildReviewReportMessagePrefix(SAMPLE_ID));
  });

  it("往復で元の ID を取り出せる（本文あり・なし双方）", () => {
    assert.equal(extractReviewIdFromMessage(withReviewReportPrefix(SAMPLE_ID, "内容の説明です。")), SAMPLE_ID);
    assert.equal(extractReviewIdFromMessage(withReviewReportPrefix(SAMPLE_ID, "")), SAMPLE_ID);
  });

  it("先頭行以外に同じ文言があっても無視する", () => {
    const message = `お問い合わせです。\n報告する口コミ: ${SAMPLE_ID}`;
    assert.equal(extractReviewIdFromMessage(message), null);
  });

  it("件名行が無い・形式が崩れている場合は null", () => {
    assert.equal(extractReviewIdFromMessage("いつもお世話になっております。"), null);
    assert.equal(extractReviewIdFromMessage("報告する口コミ: not-a-uuid\n本文"), null);
  });
});
