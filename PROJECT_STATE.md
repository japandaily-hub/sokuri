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
- **完了（イテレーション3・Workflow並列）**: コンテンツ/法務6ページ（terms/privacy/legal/company/contact/404）を Workflow `wr9anbg0v`（6エージェント並列）で実装、統合build緑(25ルート)・commit `50bfa69`。各ページは SiteChrome配下でmainのみ描画、固有CSSは各ルートに co-located。
- 🔴 **リリースブロッカー（spawn task task_b62c0b43）**: `/company`・`/legal` にデザインモック由来の**架空事業者情報**（古物商許可 第303291234号・代表者 山村大輔・資本金8000万・実績数値 等）。公開前に実値/明示プレースホルダへ差替必須。**未デプロイのブランチなので本番影響なし**。
- **次アクション（loop P1）**: ①content残り（faq/photo-guide/examples）+ 単純auth（verify-email/password-reset/create-complete）を Workflow 並列 → ②複雑な既存配線ページ（signup 3step/create 多step/result）を個別に丁寧に再スキン（既存wiring維持）→ ③ユーザーアプリ/業者クラスタ。
- **既知の要対応**: 実画像アセット未投入＝`PhImg` プレースホルダ（ユーザー決定: 進行）。LINE認証=未実装（準備中トースト）。contactフォーム送信=未配線（デモ文言）。
- **完了（イテレーション4・Workflow w97tixiok）**: クラスタ2=faq/photo-guide/examples/verify-email/password-reset/create-complete、build緑(31ルート)・commit `2755886`。
- **進行中（イテレーション5・Workflow wzqnc87jc）**: クラスタ3=business + mypage/applications/notifications/mypage-profile/mypage-withdraw（bareクロム・AppHeader統一・commit `44cb307`で基盤先行）。
- 補足: ログイン後アプリ画面は `AppHeader`（ロゴ+通知ベル）に統一。`SiteChrome` BARE_PREFIXES に /mypage・/applications・/notifications・/business 追加。
- **次アクション（loop P1）**: クラスタ3完了→build検証→コミット。次クラスタ4=動的/対話系（vendors/[id]・chat/[id]・schedule・review・operator-chat・operator-profile）。**最後に複雑な既存配線ページ（signup 3step・create 多step・result・operator dashboard）を既存wiring維持で個別再スキン**。
- **完了（イテレーション5・Workflow wzqnc87jc）**: クラスタ3=business/mypage/applications/notifications/profile/withdraw、build緑(37ルート)・commit `beb69d7`。business.css のコメント内 `.faq-*` +スラッシュが `*/` を形成→cssnano崩れを修正。
- **進行中（イテレーション6・Workflow wec8yvvzf）**: クラスタ4=vendors/[id]・chat/[id]・schedule・review（bareクロム拡張・commit先行）。※初回は自作スクリプトのテンプレート文字列に `*/` 混入で失敗→array.join方式で再投入。
- **次アクション（loop P1）**: クラスタ4完了→build→コミット。**残=複雑な既存配線ページのみ: signup(3step)/create(多step)/result(3状態)/operator dashboard + operator-chat/operator-profile**。これらは既存の signIn/katadzuke-api/middleware 配線を読み込み**維持したまま**個別丁寧に再スキン（Workflow agentに既存ファイルを渡すか、リーダー直実装）。
- **完了（イテレーション6-8）**: クラスタ4(vendors/chat/schedule/review・commit `379c7e5`)＋クラスタ5(operator dashboard/chat/profile・commit `ae7336f`)＋**signup 3ステップ再スキン**(既存signupUser→signIn配線維持・commit `709e628`)。共有フローCSS(flow-header/footer/form-card/pw-strength)を katazuke-pages.css に集約。
- **次アクション（loop P1）**: **残2のみ＝/create と /result**（最も複雑な既存配線）。/create は useToken/uploadCasePhoto/createCase→/cases/{id} 配線を読み込み**維持**しつつ新デザインのflow-header/footer/form-cardで再スキン。/result は既存セッション/状態配線を維持。リーダー直実装で慎重に（並列しない）。
- **✅ 完了（イテレーション9-10）**: create(commit 67c9f8b)・result(業者入札選択・旧AssetWise置換・commit e474612)再スキン → **全33ページ新デザイン実装完了**。security-reviewer + qa-reviewer 並列レビュー実施、指摘是正(commit 4817cd9): オープンリダイレクト/虚偽成功断定/BlobURLリーク/business.cssスコープ/メール検証/aria。
- **gate_status**: build=GREEN(41ルート) / typecheck=GREEN / **security=レビュー済(Critical/High=0, Medium 1件是正)** / **QA=レビュー済(blocker是正)** / 全33ページ=**33完了** / visualQA=ローカル(localhost:3100)でユーザー確認可
- **🏁 デザイン実装タスク完了（/loop 停止）**。リリース前のユーザー対応項目は KATAZUKE_REDESIGN_PLAN.md 末尾「✅全33ページ完了」節を参照（架空事業者情報の差替=task_b62c0b43 / 実画像 / 新ページのバックエンド配線 / LINE認証 / デプロイ）。

## 🔐 2026-07-02〜03 ウォークスルー是正＋本番セキュリティ堅牢化（/loop 自走・strategy-agents）
- **commit `c24549e`**: ウォークスルーP0/P1是正＋LINE統合の一式（65ファイル）を保全コミット。P0-1(Failed to fetch日本語化)/P0-2(認証ガード8パス)/P1-1(license必須+vendor_status 3値)/P1-2(LINEログイン+落札落選日程通知)/P1-3(チャット・日程・プロフィール実配線)/P1-4(規約同意サーバー検証)。詳細= `docs/reviews/walkthrough_review_2026-07-02.md` とメモリ katazuke-ux-walkthrough-p0-issues。
- **commit `06abd12`**: 既存の別課題2件をクローズ。①CORS `allow_origins=["*"]` 廃止→ALLOWED_ORIGINS設定制（危険トークン"*"/null除外・末尾スラッシュ正規化・productionフォールバックはFRONTEND_BASE_URLのみ）②本番起動ガード（APP_ENV=production×弱鍵JWT_SECRET or ワイルドカード混入→起動失敗、logger.critical付き）③create_app() DI化＋test_main.py/test_config.py新設。security/qa独立レビュー3巡でHigh2・Medium4全解消。
- **task_bd221d4e（middleware業者検証）は by-design と裁定**: 権限ゲートはバックエンド deps.get_verified_operator（vendor_status=="active"）＋transactions._assert_party（当事者スコープ）。pending業者の/operator閲覧許可は意図した非対称（閲覧可・入札不可）。middleware.ts ヘッダコメントに明文化済み＝再指摘は誤検知。
- **gate_status**: backend pytest=**138 passed** / web=前回green（今回webは middleware コメントのみ変更） / security=2巡通過(Critical/High 0) / QA=2巡通過(High 2→解消)
- **残存リスク（文書化済み・低）**: APP_ENV未設定の非正規デプロイ経路ではガード不発（render.yamlは明示済み）／main.pyとconfig.pyの危険トークン判定が二重化（次回リファクタで共有ヘルパー化推奨）／ADMIN_EMAILSがrender.yamlに平文（ユーザー判断でsync:false化を推奨）。
- **リリース前のユーザー対応項目（コード側は完了）**: ①/company・/legalの架空事業者情報→実値(task_b62c0b43) ②実画像アセット投入 ③LINEクレデンシャル設定（フロント: LINE_CLIENT_ID/SECRET・コールバックURL登録、バックエンド: LINE_CLIENT_ID/LINE_CHANNEL_ACCESS_TOKEN）④Render環境変数の確認（APP_ENV/ALLOWED_ORIGINSはrender.yaml反映済み・デプロイ時に実ログで起動確認）⑤mainマージ→デプロイ（承認操作）。

## 🧪 2026-07-03 フルスタック実機E2E（初のバックエンド接続ウォークスルー・/loop 自走）
- **環境**: backend=SQLite起動スクリプト `backend/run_local_e2e.py`（Docker/PostgreSQL不要・使い捨てDB e2e_local.db・conftestと同じJSONB→JSON方式）＋ web=本番ビルドを :3100（.claude/launch.json katazuke-web）。
- **APIレベルE2E全通**: user/admin/業者signup→admin承認(pending→active)→案件→入札→落札選択→取引→チャット往復→日程提案→確定(status=visiting)→業者プロフィール。シードは scratchpad の seed_e2e*.ps1（admin=e2e-admin@example.com/業者承認はPATCH verify {verified:true}）。
- **ブラウザ実機で配線確認済み✅**: /login /cases /cases/[id] /chat/[id]（**UI送信→業者側到達まで実証**）/schedule、/operator/login /operator/cases /operator/transactions(+詳細=住所連絡先開示+減額フォーム) /operator/chat /operator/profile。ミドルウェア分離（業者セッションでuser専用ページ→/loginへ）も実機実証。**全巡回でconsoleエラー0**。
- 🔴 **未配線＝ログインユーザーに架空データを表示する6ページ（次ラウンドの主対象）**: /mypage(山田花子) /applications(架空入札) /notifications(架空通知・**通知APIは未実装**) /result(「デモ表示」ラベル) /vendors/[id](**GET /vendors/{id}は実装済みなのに未配線**) /review(架空取引)。
- ⚠️ /operator ダッシュボード: 「交渉中」ハードコード0（operator/page.tsx の「チャットAPI未実装のため」コメントが陳腐化）・「今月の成約」はcompletedのみでvisiting非計上。
- **次アクションP1**: architect設計→上記6ページ＋ダッシュボード集計の実配線（frontend実装→security/qaレビュー→本E2E環境で再検証）。

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
