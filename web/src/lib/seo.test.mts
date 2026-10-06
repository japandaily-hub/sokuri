/**
 * seo（公開ページのメタデータ組み立て）の回帰テスト。
 *
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/seo.test.mts
 * 拡張子を .mts にしている理由は safe-path.test.mts のコメントを参照。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { DEFAULT_OG_IMAGE, SITE_NAME, assertSitePath, publicPageMetadata, socialTitle } from "./seo.ts";

describe("publicPageMetadata", () => {
  const meta = publicPageMetadata({ path: "/faq", title: "よくある質問", description: "説明文" });

  it("og:url と canonical がそのページのパスになる（トップのままにならない）", () => {
    assert.equal((meta.openGraph as { url?: string }).url, "/faq");
    assert.deepEqual(meta.alternates, { canonical: "/faq" });
  });

  it("og:title・twitter:title はページ名＋サイト名で、トップの文言にならない", () => {
    const og = meta.openGraph as { title?: string };
    const tw = meta.twitter as { title?: string };
    assert.equal(og.title, `よくある質問 | ${SITE_NAME}`);
    assert.equal(tw.title, og.title);
  });

  it("上書きで siteName・locale・画像が落ちない", () => {
    const og = meta.openGraph as { siteName?: string; locale?: string; images?: unknown[] };
    assert.equal(og.siteName, SITE_NAME);
    assert.equal(og.locale, "ja_JP");
    assert.deepEqual(og.images, [{ ...DEFAULT_OG_IMAGE }]);
  });

  it("robots は指定しない（root layout の index を継承する）", () => {
    assert.equal(meta.robots, undefined);
  });

  it("呼び出しごとに別のオブジェクトを返す（共有の画像定義を書き換えさせない）", () => {
    const other = publicPageMetadata({ path: "/terms", title: "利用規約", description: "x" });
    const a = (meta.openGraph as { images: object[] }).images[0];
    const b = (other.openGraph as { images: object[] }).images[0];
    assert.notEqual(a, b);
    assert.notEqual(a, DEFAULT_OG_IMAGE);
  });
});

describe("assertSitePath", () => {
  for (const ok of ["/", "/faq", "/terms", "/photo-guide"]) {
    it(`受け付ける: ${ok}`, () => assert.doesNotThrow(() => assertSitePath(ok)));
  }
  for (const bad of ["faq", "https://example.com/", "//evil.example", "/faq?x=1", "/faq#a", "/a b", ""]) {
    it(`拒否する: ${JSON.stringify(bad)}`, () => assert.throws(() => assertSitePath(bad), /公開ページのパスが不正です/));
  }
});

describe("socialTitle", () => {
  it("title.template と同じ区切り", () => assert.equal(socialTitle("運営者情報"), "運営者情報 | カタヅケ"));
});
