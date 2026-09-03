# セキュリティレビュー（人の森整合テーマ差分・2026-09-03）

独立レビュアー（読み取り専用・立案文脈なし）の所見。件数: Critical 0 / High 2 / Medium 2 / Low 3。
**対応状況は末尾の表を参照（同日中にリーダーが全件対応）。**

## 所見（重大度順）

| 重大度 | ファイル:行 | 事象 | 根拠 | 修正案 |
|---|---|---|---|---|
| High | `web/src/app/globals.css:5` + `web/next.config.ts` + `web/vercel.json` | 第三者オリジン（fonts.googleapis.com）からの CSS 読み込みがあるのに CSP が存在しない。`@import` は SRI を付与できない | `next.config.ts` の `headers()` に HSTS/nosniff 等はあるが `Content-Security-Policy` が無い。Google 側または経路が侵害されると全ページ（/login /mypage /chat 含む）に任意 CSS が注入できる | `next/font/google` へ移行して自己ホスト化し、`@import` と preconnect を削除する（外部オリジン自体が消える）。移行しない場合は最低限 `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; frame-ancestors 'none'; base-uri 'none'; object-src 'none'` を設定 |
| High | `web/src/app/globals.css:5` ↔ `web/src/app/privacy/page.tsx:76,98` | Google Fonts の実行時ロードで全訪問者の IP・UA・Referer が Google（米国）へ送られるが、プライバシーポリシーに第三者提供・外国にある第三者への提供の記載が無い | privacy ページに Google／フォント／外国の記載ゼロ。ログイン後画面でも同じ CSS が読まれる | 自己ホスト化で送信自体を消す（ポリシー改訂不要になる） |
| Medium | `web/src/app/layout.tsx:103-108` | スキップリンク `href="#main"` の着地点が無いルートが多数（WCAG 2.4.1） | `id="main"` が無い: /password-reset /verify-email /admin /cases /cases/[id] /chat/[id] /operator /schedule /result /operator/chat/[id]。`<main>` はあるが id 欠落: review/page.tsx:149,183・operator/profile/page.tsx:358・vendors/[id]/page.tsx:63,85・create/complete/page.tsx:87・error.tsx:28 | 各 `<main>` に `id="main"` を付与。将来は SiteChrome 側で一元化 |
| Medium | login/page.tsx:69, operator/login/page.tsx:59, operator/signup/page.tsx:100, signup/page.tsx:248, create/page.tsx:347 | 認証失敗バナー `.auth-error` に `role="alert"` が無く、SR 利用者にログイン失敗が伝わらない | 同コードベースの他画面（business/notifications/mypage）は `role="alert"` を持つ。視覚的な欠落は無し（`katazuke-pages.css:75-79` 生存） | `role="alert"` を付与 |
| Low | `web/src/app/layout.tsx:119-130` | JSON-LD を `JSON.stringify` で注入。現状は静的で安全だが、動的値を混ぜた瞬間に `</script>` ブレイクアウトが成立する構造 | `JSON.stringify` は `<` をエスケープしない | `.replace(/</g, "\\u003c")` を挟む |
| Low | `web/src/components/kdz/auth.tsx:91-92` | パスワード表示切替の `aria-label` が固定文言で `aria-pressed` も無い | 表示状態が SR に伝わらない | `aria-pressed={show}` と動的ラベル |
| Low | layout.tsx:105 ↔ katazuke-pages.css:114 | スキップリンクと `.kdz-overlay` の z-index が同値 100 | モーダル表示中にスキップリンクのフォーカスリングが遮蔽層の裏に隠れる | スキップリンクを z-index 300 へ |

## クリーン判定の根拠
- `Logo.tsx` の `style={{ "--wm": ... }}` は数値プロップのみを補間し、外部入力の流入経路なし。
- `opengraph-image.tsx` / `apple-icon.tsx` / `manifest.ts` は静的リテラルのみ、`fetch` なし。
- `.vt` は `aria-hidden="true"` で直後の h2 と同文言＝二重読み上げなし。`:focus-visible` リングは 4.70:1。
- 白地反転による白文字残存は TSX/CSS 全検索で該当ゼロ（`.btn-white` は緑地白文字へ反転済み）。

## 対応状況（2026-09-03）

| 所見 | 対応 |
|---|---|
| High ×2（外部フォント） | **対応済み**: `layout.tsx` で `next/font/google`（Noto Serif JP 400/600・Noto Sans JP 400/500・Montserrat 600・Libre Baskerville 400）をビルド時自己ホスト。`globals.css` の `@import url(...)` と preconnect を削除。`katazuke.css` の `--serif/--ui/--en/--en-display` は `var(--font-*)` を先頭参照 |
| Medium（id="main"） | **対応済み**: `<main>` を持つ全ファイルに `id="main"` を付与（Codex 並行作業中の operator/cases 2 ファイルは既に保持） |
| Medium（role="alert"） | **対応済み**: 5 箇所に付与 |
| Low ×3 | **対応済み**: JSON-LD の `<` エスケープ、`aria-pressed` + 動的ラベル、スキップリンク z-index 300 |
| 残存 | CSP ヘッダー自体は未導入（外部オリジンは消えたため優先度は下がる。導入時は JSON-LD インライン Script の nonce 設計が必要） |
