/**
 * 全 spec 共通の test / expect（@playwright/test の拡張）。
 *
 * spec は "@playwright/test" ではなく本ファイルから test / expect を import すること。
 * 別のブラウザコンテキストが要る場合も browser.newContext() / browser.newPage() ではなく
 * newE2EContext() を使う（どちらも下記の開発用オーバーレイ対策を全ページに効かせるため）。
 *
 * 接続先の検査: ローカルスタック以外への誤実行を防ぐ検査を4段（設定読み込み時 → worker
 * 自動 fixture → context 生成 → API クライアント生成）で重ねている。本ファイルは worker
 * 自動 fixture（localTargetGuard）と context fixture / newE2EContext の2段を担う。検査の
 * 本体・許可リスト・重ねている理由は e2e/helpers/local-target.ts を参照。
 */
import {
  test as base,
  expect,
  type Browser,
  type BrowserContext,
  type BrowserContextOptions,
} from "@playwright/test";
import { API_URL, BASE_URL } from "./env";
import { assertLocalTargets, describeTargetOrigins, isRemoteTargetAllowed, type E2ETarget } from "./local-target";

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
  if (options?.baseURL !== undefined) {
    assertLocalTargets([{ label: "newE2EContext の baseURL", url: options.baseURL }]);
  }
  const context = await browser.newContext(options);
  await hideNextDevOverlay(context);
  return context;
}

/**
 * worker fixture の追加分の型。auto な worker fixture（localTargetGuard）は、そのワーカーで
 * 他の fixture・beforeAll・テスト本体より先に準備される（Playwright 1.63 の fixture 解決処理で
 * 確認済み）。接続先の検査だけが目的で値そのものは使わないため型は void。
 * 主防御は playwright.config.ts の読み込み時の検査（ワーカーを1つも起動しない）。この worker
 * fixture は、別の設定ファイルで実行された場合や project ごとの baseURL を確認するための二段目。
 */
interface LocalTargetGuardFixtures {
  localTargetGuard: void;
}

export const test = base.extend<Record<never, never>, LocalTargetGuardFixtures>({
  // 第2引数は Playwright の慣例では `use` だが、react-hooks/rules-of-hooks が React 19 の use() と
  // 誤認して lint エラーになるため別名にしている（Playwright は引数名に依存しない）。
  context: async ({ context, baseURL }, provide) => {
    if (baseURL !== undefined) {
      // コンテキストを作るテストで、実効する baseURL を検査する（worker fixture の localTargetGuard は
      // project の既定値までしか見えない）。spec での test.use({ baseURL }) は eslint で禁止している
      // ため、ここは helpers や別の設定ファイルから上書きされた場合の保険。
      assertLocalTargets([{ label: "このテストの baseURL", url: baseURL }]);
    }
    await hideNextDevOverlay(context);
    await provide(context);
  },
  // Playwright は第1引数の分割代入から依存 fixture を読み取るため、依存が無くても `{}` と書く
  // （`_` などにすると "First argument must use the object destructuring pattern" で失敗する）。
  localTargetGuard: [
    async ({}, provide, workerInfo) => {
      const projectBaseURL = workerInfo.project.use.baseURL;
      const targets: E2ETarget[] = [
        { label: "E2E_BASE_URL", url: BASE_URL },
        { label: "E2E_API_URL", url: API_URL },
      ];
      if (projectBaseURL !== undefined) {
        targets.push({
          label: `playwright.config.ts の baseURL（project: ${workerInfo.project.name}）`,
          url: projectBaseURL,
        });
      }
      if (isRemoteTargetAllowed()) {
        console.warn(
          `[e2e] E2E_ALLOW_REMOTE=1 のため、次の接続先をローカルか検査せずに使います: ${describeTargetOrigins(targets)}`,
        );
      } else {
        assertLocalTargets(targets);
      }
      await provide();
    },
    { scope: "worker", auto: true },
  ],
});

export { expect };
