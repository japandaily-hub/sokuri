/**
 * E2E の接続先（フロント / バックエンド API）がローカルスタックかどうかを検査する純関数群。
 *
 * 呼び出し元は次の4段で重ねている（番号が小さいほど早く・広く止める）。
 *   ① playwright.config.ts の読み込み時。設定ファイルの評価中に throw し、ワーカーを
 *      1つも起動しない（beforeAll・afterAll も一切走らない）＝主防御。
 *   ② e2e/helpers/test.ts の worker 自動 fixture（localTargetGuard）。①と同じ値を、
 *      各ワーカーの最初のテストより前にもう一度検査する。project ごとの baseURL も見る。
 *   ③ e2e/helpers/test.ts の context fixture と newE2EContext。ブラウザのコンテキストを作るとき
 *      に、実効する baseURL（newE2EContext に明示した値を含む）を検査する。
 *   ④ e2e/helpers/api.ts の Api.create()。API クライアントを作るたびに検査する。
 * ②（worker fixture）だけに頼らないのは、worker fixture が失敗しても Playwright 1.63 は同じ
 * ファイルの afterAll（失敗した fixture を引数で要求しない hook）を実行するため（実測済み）。
 * 将来 afterAll や2本目の beforeAll に API を叩く後始末を足すと、②では止まらない。①は
 * ワーカーを起動する前に止めるので hook は一切走らず、④は API クライアントを作るその場で
 * 検査するので fixture のキャッシュや hook の実行順に依存しない。
 * ③は page / context を使うテストでしか走らない（request fixture だけのテストでは作られない）。
 * そのため spec で baseURL を書くこと（test.use・test.extend・newE2EContext の options など、
 * オブジェクトの baseURL キー全般）と @playwright/test からの request・default の import は
 * web/eslint.config.mjs で禁止し、baseURL の出どころを①②が検査する playwright.config.ts だけにしている
 * （組み込みの request fixture も baseURL はこの設定値になる）。
 *
 * 判定は拒否リストではなく許可リスト（{@link LOCAL_HOSTNAMES}）。本番・プレビュー等の
 * ホスト名は将来増えうるため拒否リストでは検査漏れが起きる。本番のホスト名はこのファイルにも
 * テストコードのどこにも書かない。{@link ALLOW_REMOTE_ENV} が "1" のときだけ、意図してローカル
 * 以外に向けるための脱出口として検査を外す。
 *
 * next dev 自身が使う接続先はここでは検査しない（E2E のプロセスの外で決まるため）。サーバー側
 * （NextAuth の authorize() 等）は web/src/lib/backend-api-base.ts が未設定時に本番へ落とさない
 * ことで塞ぎ、画面が使う NEXT_PUBLIC_API_URL は未設定なら web/src/lib/katadzuke-api.ts が例外に
 * する。設定された値そのものがローカルかどうかは web/.env.local を用意する人が確かめる
 * （docs/ops/e2e.md）。
 *
 * local-target.test.mts から node --test で直接 import されるため、このファイルは import を
 * 持たない（依存ゼロ）。Node の型除去（type stripping）で実行できるよう、enum・namespace・
 * コンストラクタ引数プロパティは使わない。
 */

/** process.env とテストから渡す素のオブジェクトの両方を受け付けるための型。 */
type EnvLike = Readonly<Record<string, string | undefined>>;

/**
 * ローカルスタックとみなすホスト名の許可リスト（WHATWG URL の hostname 表記。
 * IPv6 のループバックは角括弧付きの "[::1]" になる）。
 */
export const LOCAL_HOSTNAMES: ReadonlySet<string> = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** "1" のときだけ接続先のローカル検査を外す環境変数名。 */
export const ALLOW_REMOTE_ENV = "E2E_ALLOW_REMOTE";

/** 検査対象の接続先 1 件。 */
export interface E2ETarget {
  /** エラー・警告メッセージに出す識別名（例: "E2E_BASE_URL"）。 */
  readonly label: string;
  readonly url: string;
}

/**
 * {@link ALLOW_REMOTE_ENV} が "1" と完全一致のときだけ true を返す。
 * "true"・" 1"（前後空白）・"0"・"" は false 扱い（表記ゆれで誤って緩めないための厳密比較）。
 * @param env 既定は process.env。テストから process.env を汚さずに検証できるよう引数で渡せる。
 */
export function isRemoteTargetAllowed(env: EnvLike = process.env): boolean {
  return env[ALLOW_REMOTE_ENV] === "1";
}

/**
 * 接続先が http/https のローカルスタックかを検査し、該当しなければ throw する。
 * エラーメッセージには url の origin だけを出す（userinfo・パス・クエリを含めない。
 * リポジトリは公開で CI のログも公開のため）。
 * @throws {Error} URL として解釈できない／http・https 以外のスキーム／許可リスト外のホスト
 */
export function assertLocalTarget({ label, url }: E2ETarget): void {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`[e2e] ${label} を URL として解釈できません。`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    // スキームを省略した "localhost:8000/..." は URL としては "localhost:" スキームの
    // opaque path URL に解釈され、origin が文字列 "null" になって原因が分かりにくいため、
    // ホスト名の検査より先にスキームを検査してこの専用文言で止める。
    throw new Error(`[e2e] ${label} は http:// か https:// で始まる URL にしてください。`);
  }
  if (!LOCAL_HOSTNAMES.has(parsed.hostname)) {
    throw new Error(
      `[e2e] ${label} がローカルではありません（${parsed.origin}）。E2E はローカルスタック専用です` +
        `（docs/ops/e2e.md）。意図してローカル以外に向けるときだけ E2E_ALLOW_REMOTE=1 を付けてください。`,
    );
  }
}

/**
 * 複数の接続先をまとめて検査する。{@link isRemoteTargetAllowed} が true の間は何もせず return
 * する（検査を外したことの警告はここでは出さない。呼び出し側の worker fixture が一度だけ出す）。
 */
export function assertLocalTargets(targets: readonly E2ETarget[], env: EnvLike = process.env): void {
  if (isRemoteTargetAllowed(env)) return;
  for (const target of targets) {
    assertLocalTarget(target);
  }
}

/**
 * 警告メッセージ用に、接続先の origin だけを「label=origin」の形にして「、」区切りでつなぐ
 * （認証情報・パス・クエリは含めない）。URL として解釈できない値は「label=（解釈できない値）」
 * と表示する。
 */
export function describeTargetOrigins(targets: readonly E2ETarget[]): string {
  return targets
    .map(({ label, url }) => {
      try {
        return `${label}=${new URL(url).origin}`;
      } catch {
        return `${label}=（解釈できない値）`;
      }
    })
    .join("、");
}
