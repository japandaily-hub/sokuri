/**
 * 全 spec 共通の test / expect（@playwright/test の拡張）。
 *
 * spec は "@playwright/test" ではなく本ファイルから test / expect を import すること。
 * 別のブラウザコンテキストが要る場合も browser.newContext() / browser.newPage() ではなく
 * newE2EContext() を使う（どちらも下記の開発用オーバーレイ対策を全ページに効かせるため）。
 */
import {
  test as base,
  expect,
  type Browser,
  type BrowserContext,
  type BrowserContextOptions,
} from "@playwright/test";

/**
 * next dev だけが描画する開発用オーバーレイ（`<nextjs-portal>`。左下の「N」インジケーターと
 * エラー表示を収める shadow DOM のホスト）を、このコンテキストで開く全ページで非表示にする。
 *
 * - 本番（next build）には存在しない要素。375px 幅では左下 36px 四方を占め、画面下端に固定された
 *   入力欄の左端のボタン（業者チャットの「日程を提案」）に重なってクリックを横取りする。
 *   チャット画面は 100vh 固定なので、スクロールでは避けられない。
 * - next.config の devIndicators は next dev の起動時にバンドルへ埋め込まれる設定で、E2E だけに
 *   限定するには起動時の環境変数が要る（webServer を使わない本 E2E からは強制できない）。
 *   DevTools の「Hide Dev Tools」は dev サーバー側に保存され、開発者のブラウザにも効く。
 *   どちらも使わず、テストのブラウザ内だけで消す。
 * - `<style>` 要素ではなく adoptedStyleSheets を使うのは、HTML のパース前（init script の実行
 *   時点）から効かせ、DOM に要素を足さない（React のハイドレーションに関わらない）ため。
 * - Next のランタイムエラーは console にも出るので、オーバーレイを消しても検知は失われない。
 */
async function hideNextDevOverlay(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync("nextjs-portal { display: none !important; }");
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    } catch (error) {
      // 隠せなくてもテストは続ける（重なった場合はクリックのタイムアウトとして表に出る）。
      // console.error にしないのは、console error を検査するテスト（01）を巻き込まないため。
      console.warn("[e2e] nextjs-portal を非表示にできませんでした", error);
    }
  });
}

/**
 * browser.newContext() の代わりに使う。テスト実行中に作るコンテキストは project の use 設定
 * （viewport・baseURL 等）を引き継ぐ（Playwright 公式ドキュメント「Explicit Context Creation and
 * Option Inheritance」。明示した options が優先）。そのうえで開発用オーバーレイも消す。
 */
export async function newE2EContext(browser: Browser, options?: BrowserContextOptions): Promise<BrowserContext> {
  const context = await browser.newContext(options);
  await hideNextDevOverlay(context);
  return context;
}

export const test = base.extend({
  // 第2引数は Playwright の慣例では `use` だが、react-hooks/rules-of-hooks が React 19 の use() と
  // 誤認して lint エラーになるため別名にしている（Playwright は引数名に依存しない）。
  context: async ({ context }, provide) => {
    await hideNextDevOverlay(context);
    await provide(context);
  },
});

export { expect };
