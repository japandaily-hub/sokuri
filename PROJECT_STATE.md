# PROJECT_STATE — カタヅケ クローズドβ

## 🎨 2026-06-27〜 デザインハンドオフ実装（/loop 自走・strategy-agents Leader）
- **ブランチ**: `feat/design-handoff-katazuke`（main=本番には未マージ。デプロイはユーザー承認操作のため自動実行しない）
- **タスク**: 新デザインハンドオフ（`docs/design_handoff_katazuke/` 33画面・高忠実度）を `web/` にピクセル忠実実装。DoD正本=リポジトリ直下 `KATAZUKE_REDESIGN_PLAN.md`。
- **正本の確定**: 稼働ファイルは **C:\sokuri**。OneDrive側（…\Projects\ソクウリ）は**ソース脱水の空殻（.tsx 0件・package.json無）＝編集禁止**。
- **完了（イテレーション1・基盤）**:
  - `src/app/katazuke.css`（ハンドオフCSS移植）+ `globals.css`（layer順宣言→`@import ... layer(components)`）+ `tailwind.config.ts`（kdz-* トークン・container無効化）+ フォント（Zen Kaku/Noto Sans を @import url 実行時ロード）
  - 共通部品 `src/components/kdz/`（Icons / interactions / SiteHeader / chrome / SiteChrome / Logo）
  - `src/app/layout.tsx`（薄シェル化・共通クロム・SEO維持）+ `src/app/page.tsx`（**トップLP全16セクション再実装**）
  - **検証**: `npx tsc --noEmit` クリーン / `npm run build` 緑（23ルート・lint通過）。**視覚QAは未実施（次イテレーションで実施）**。
- **完了（イテレーション2）**: `/login` 再スキン（commit 8331765）。認証/フォーム共通基盤を新設: `katazuke-pages.css`（auth-bar/auth-card/field/btn-line-auth/モーダル/トースト）+ `components/kdz/auth.tsx`（AuthBar/Field/PasswordField/LineAuthButton/TrustRow）。既存 signIn 配線維持。
- **QA所見（重要）**: ①ローカル `next start`/`dev` で NextAuth が動くには `web/.env.local` に `AUTH_SECRET` 必須（追加済・gitignore）。②**preview_screenshot は本アプリで networkidle に達せず常時タイムアウト**（dev=HMR websocket / prod=フォントCDN待ち。ページ自体はSSR200・markup健全・console errorなし）。視覚QAはユーザーがブラウザで `localhost:3100`（`.claude/launch.json` の katazuke-web）を直接確認する方式に切替。プレビュー起動コマンドは `npm --prefix C:\sokuri\web run start -- -p 3100`。
- **次アクション（loop P1）**: 認証/フロー残り（signup[3step]/verify-email/password-reset/create[多step]/create-complete）→ 以降 §KATAZUKE_REDESIGN_PLAN のクラスタ順。**両パターン（LP/auth）確立済のため、静的・単純ページ群は Workflow で並列実装可**。
- **既知の要対応**: 実画像アセット未投入＝`PhImg` プレースホルダ。**ユーザー決定(2026-06-27): プレースホルダのまま進行**（再質問しない）。LINE認証=バックエンド未実装（準備中トースト）。
- **gate_status**: build=GREEN / typecheck=GREEN / visualQA=ユーザー確認方式へ移行 / security=未 / 全33ページ=2完了(基盤+top+login)/残31

---

最終更新: 2026-06-13 / **本番デプロイ&E2E全合格済み（β稼働中）。現フェーズ＝業者獲得（量・スケール）。プラン正本: 業者獲得スケールプラン_v1.md**

## 🔧 2026-06-16 デプロイ前是正（strategy-agents Leader）— push-vendor-engine.ps1 の本番事故を2件修正
**push前検証で、スクリプトのままだと本番デプロイが失敗することを検出・修正した:**
1. **migration採番ズレ（致命）**: 新規 `0005_invites_lot_name.py` の `down_revision` が `"0004_auth_tables"` を指していたが、正典C:\sokuriでは auth_tables の revision ID は `"0005_auth_tables"`。そのままだと Render の `alembic upgrade head` が `Can't locate revision '0004_auth_tables'` でクラッシュ。→ `down_revision="0005_auth_tables"` に修正。チェーン検証で単一HEAD `0006_vendor_status`・全7本線形連結を確認（C:\sokuri実HEAD=0005_auth_tables から新規2本=追加系のみ適用）。
2. **コピー漏れ3ファイル（機能欠落）**: pushスクリプトのコピー対象に `endpoints/auth.py`（オープン業者登録）・`cases.py`・`transactions.py`（vendor_status住所マスク）が無く、これらを入れないと業者登録が旧挙動(招待コード必須→403)のまま。→ copy/git-add 両方に3ファイルを追加。
- **実機ゲート**: C:\sokuri\backend\.venv に不足依存(pyjwt/aiosqlite/email-validator/dnspython)を導入し、`pytest` を実行 → **61 passed, 0 failed**（beta E2E 57 + vendor 4。当初4 failedだった vendor テストが3ファイル追加で全緑）。
- **未対応(非ブロッカー・後続)**: フッターの /legal・/unsubscribe リンクは `web/src/app/layout.tsx` 内にあり、同ファイルは rebrand(a471a5f) と衝突するため今回は触れず。/legal・/unsubscribe の**ページ本体は配信される**。フッター導線は layout.tsx へ手動マージが必要（P2の /legal 実値記入と同時推奨）。

## ⚠️ 重要訂正（このファイルの以下旧記述を上書き）
- 正典repoは **C:\sokuri**（github.com/japandaily-hub/sokuri）。OneDrive側は作業コピー
- 本番バックエンドは **Render**（sokuri-backend.onrender.com）。Railwayは廃止済み
- C:\sokuriはアルバム機能(0003_add_albums, 無効化中)を持つため、カタヅケmigrationは
  **0004_katadzuke_schema / 0005_auth_tables** に振替済み
- 統合検証: backend pytest **56 passed** / web build **成功(21ページ, next 15.5.18)**
- 本番ブランドは当面ソクウリのまま（HP/layout色は不変更、カタヅケ画面を追加。layoutはProviders挿入のみ）
- katadzuke-api.ts / auth.ts に FALLBACK_PROD_API_URL（Vercel Sensitive env対策）
- render.yaml: JWT_SECRET(generateValue)/ADMIN_EMAILS/STORAGE_DIR=/tmp/uploads(エフェメラル・β許容)/
  BREVO_API_KEY(sync:false)/MAIL_FROM/FRONTEND_BASE_URL 追記済み
- ✅【完了 2026-06-12夜】push(7ffa097, 7084d8d)・Render稼働・Vercel AUTH_SECRET+NEXT_PUBLIC_API_URL修正(/api/v1付与)+Redeploy — **本番デプロイ完了**
- ✅【スモークテスト全合格 2026-06-12深夜・本番E2E】招待発行→業者登録→未承認403→承認→案件作成(写真PUT)→業者一覧住所マスク→入札→落札→業者へ住所/連絡先開示→減額(理由必須422検証)→承認(final 25000)→完了→双方レビュー→rating 5.0反映。UI側もsignup→/create 4STEP、業者ログイン→落札管理表示を実機確認
- **リリース直前状態。残りはユーザー操作のみ**: ①ご本人 https://sokuri.vercel.app/signup 登録(=admin) ②/adminで実業者3社へ招待コード発行・送付 ③(任意)RenderにBREVO_API_KEY設定でメール有効化
- probe検証データ: users=probe-check/probe-ui/ko.13.hei+kdzadmin(admin)、operator=片付けプローブ(株)、case/txn各1件(完了済) — βでは無害。ADMIN_EMAILSに+kdzadminエイリアス追加済(Render env+render.yaml)
- 既知マイナーバグ(非ブロッカー): ai_summaryフォールバック文の「写真N枚」がAI解析可能枚数基準（case.photos数を渡すべき）/ UI写真アップロードがRender再起動と重なると「失敗しました」(リトライで成功)
- 修正済み追加: backend/Dockerfile（app/コピーをpip installの前へ）
- ✅【最終磨き込み 78f51b0 push済・本番反映確認済】①セッション対応ヘッダーナビ（ログイン/ログアウト/マイ案件/管理/業者メニュー）②写真アップロード自動リトライ ③ai_summary写真枚数バグ修正 ④フッターに業者ログイン導線 ⑤招待業者向け案内文面 docs/beta-operator-onboarding.md（送付用テンプレ）。render.yamlもコミット済
- C:\sokuri未コミットの残作業ファイル: kdz-commit.ps1 / push-katadzuke.ps1 / .kdz-*.log / test-room.jpg（一時物・削除可）
- sandboxマウント注意: ホストWrite/Edit直後のファイルはbashから截断して見える（C:\sokuriでも発生）。
  bash経由Writeは整合。検証は/tmpでheredoc再生成方式

## フェーズ進捗
- [x] Phase A: バックエンドAPI（pytest 80/80）
- [x] Phase B: 認証（NextAuth v5 Credentials → backend JWT）
- [x] Phase C: フロントエンド全画面（npm run build 成功・18ルート）
- [x] Phase D: メール3種実装済み + env/デプロイ手順整備
- [ ] 本番デプロイ実行（→ deploy-katadzuke.ps1 / ユーザー操作）

## 完成定義チェック（13項目）
- [x] 案件作成（写真+住居情報+AI要約）
- [x] 業者が案件一覧・詳細を閲覧（承認制・住所マスク）
- [x] 業者が入札（1案件1回・金額+メッセージ）
- [x] ユーザーが入札一覧確認・1社選択
- [x] 落札後に業者へ住所詳細開示（バックエンド制御・テスト済）
- [x] 減額申請フロー（理由必須10字+DB NOT NULL→ユーザー承認/却下）
- [x] 成約完了・キャンセル（業者キャンセルはcancel_count記録）
- [x] ユーザー認証（email+password / ADMIN_EMAILSでadmin）
- [x] 業者認証（招待コード1回限り+email+password）
- [x] 管理画面（招待コード発行KDZ-XXXXXXXX・業者承認/取消）
- [x] メール通知3種（案件化完了/入札/落札 — Brevo、キー未設定時スキップ）
- [x] npm run build エラーなし（sandbox検証済）
- [x] pytest エラーなし（80 passed）
- [ ] Vercel+Railway本番デプロイ → **次アクションP1**

## アーキテクチャ要点
- 認証: backend発行JWT（scrypt+PyJWT HS256）。NextAuth v5はCredentials Providerで
  /auth/login・/auth/operator/login を呼びtokenをセッション保持。middleware.tsで
  user(/create,/cases)・operator(/operator)・admin(/admin)を分岐
- 写真: POST /upload/presign → PUT /upload/{key} → GET /files/{key}（ローカルディスク、
  STORAGE_DIR。RailwayはVolume /data 必須。R2移行はstorage.pyのURL差し替えのみ）
- AI要約: services/summary.py が vision.analyze_image を写真ごとに呼び集約。失敗時フォールバック文
- 住所統制: cases系は常にマスク。GET /transactions/{id} のみ当事者に開示（cancelled後は非開示）
- migrationチェーン: 0001→0002→0003→0004（railway.json起動時にalembic upgrade head自動実行）

## 新規/変更ファイル一覧
backend: alembic/versions/0004_auth_tables.py / models{user,invite,operator+,__init__+} /
core/security.py / api/deps.py / schemas_katadzuke.py / services{storage,summary,notify} /
endpoints{auth,case_photos,cases,bids,transactions,reductions,reviews,admin} / router+ /
main+(CORS PUT/PATCH/DELETE) / config+ / pyproject+ / tests/{conftest+,test_katadzuke_api.py} /
.env.example+ / **seed.py修復**（同期コンフリクト破損→440行正版でWrite済）
web: auth.ts / middleware.ts / types/next-auth.d.ts / lib/katadzuke-api.ts /
components/{AuthCard,kdz/Ui}.tsx / app/{providers,login,signup,operator/{login,signup,cases,
cases/[id],transactions,transactions/[id]},create,cases,cases/[id],admin}/page.tsx /
api/auth/[...nextauth]/route.ts / layout.tsx(カタヅケ化+Providers) / package.json(next-auth beta.29) /
**tailwind.config.ts修復**（WEEK1書き換えで欠落したcontainer/cta/xs/accent/fade-*を復元。teal維持）/
.env.example新規
root: deploy-katadzuke.ps1

## 本番デプロイ手順（ユーザー実行）
1. Railway Variables: DATABASE_URL/GOOGLE_API_KEY/ALLOWED_ORIGINS(=Vercel URL)/
   JWT_SECRET(rand 64hex)/ADMIN_EMAILS/STORAGE_DIR=/data/uploads/BREVO_API_KEY/
   MAIL_FROM/FRONTEND_BASE_URL(=Vercel URL) + Volume /data
2. Vercel: Root=web, NEXT_PUBLIC_API_URL(=Railway URL/api/v1), AUTH_SECRET
3. `.\deploy-katadzuke.ps1 -RailwayUrl https://... -VercelUrl https://...`
4. スクリプト末尾のスモークテスト6手順を実施

## 既知の地雷（再発防止）
- **sandboxマウントはOneDriveの最近書いたファイルを截断して見せる**（旧版/null/途中切れ。
  syntaxは通るが実行で壊れるパターンあり）。テストは/tmpコピー後に
  compileall+import+sentinel末尾照合、壊れていたらheredocで再生成してから実行
- sandboxはbash呼び出し終了で子プロセスをkill（nohup無効）→ npm installは
  `--omit=optional`+package-lock事前生成で1回完結、大物バイナリはcurl -C - で取得
- 正典側の実破損2件は修復済み: seed.py（重複断片）/ tailwind.config.ts（トークン欠落）
- pyproject requires-python>=3.11 vs sandbox 3.10 → テスト時は依存個別pip

## 次アクション（2026-06-15更新 — 業者獲得エンジン実装完了）
| P | アクション | 担当 |
|---|---|---|
| **P1(即)** | **push-vendor-engine.ps1 を実行**（C:\sokuri へコピー → git push → Render自動 alembic upgrade head） | ユーザー |
| P2 | /legal の [運営者名][住所][電話番号] を実際の値に書き換えてからアウトリーチ開始 | ユーザー |
| P3 | 業者リスト_首都圏（遺品整理士認定協会/JRRC/ポータル掲載）上位100社へ §9 文面でアウトリーチ開始 | ユーザー |
| 済✅ | TASK-1 バルクコード一括発行（POST /admin/invites/bulk・最大500件・CSVダウンロード） | 完了 |
| 済✅ | TASK-2 オープン業者登録+vendor_status制（Migration 0005/0006・招待コード任意・limited/active） | 完了 |
| 済✅ | TASK-3 GET /admin/cell-density（需給比率ヒートマップ） | 完了 |
| 済✅ | TASK-4 /unsubscribe・/legal・フッターリンク（コンプラページ） | 完了 |
| 旧(済) | 本番デプロイ・E2E14ステップ全合格・最終磨き込み78f51b0 push済 | 完了 |

## 実装完了サマリ（2026-06-15 strategy-agents 自走）
- pytest 22/22 PASS（新規5テスト含む）
- Migration chain: 0001→0002→0003→0004→0005→0006（整合確認済み）
- 重要設計決定: vendor_status は3値(pending/limited/active)・invite_code部分ユニークINDEX・認可ゲートOR条件移行
- npm build: Windows Node.jsバイナリのためsandbox確認不可 → push後 Vercel 自動ビルドで確認
- ⚠️ /legal の運営者情報はプレースホルダー[要記入]のまま → アウトリーチ前に必ず埋めること

> 業者獲得の核心: 0円の冷たいGmap営業のみだと月7〜16社稼働が実力値。月40社級は「団体名簿/ポータル掲載業者/紹介」など反応率の高いチャネルを先に回して初めて到達。北極星KPI＝週次・新規“稼働”業者数（登録後14日以内に1入札）。
