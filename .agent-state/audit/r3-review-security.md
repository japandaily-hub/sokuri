# r3 セキュリティレビュー（2026-09-04・opus 独立レビュー。レビュアーは Write 不可だったためリーダーが転記）

## 総合判定: 条件付き不合格 — Critical 1 / High 2 / Medium 7 / Low 4

### Critical
- C-1 ADMIN_EMAILS 未登録アドレスの land-grab による admin 奪取。auth.py:125（signup 時に無条件 admin 付与・メール到達性検証なし）／新設 auth.py:59-71,176,646（昇格を毎ログインへ拡大）／notify.py:82-83（フッターが全通知メールに katazuke.info@gmail.com を印字）。攻撃: 通知メールのフッターから運営アドレスを得て POST /auth/signup に同アドレス→未登録なら即 role=admin。修正: 本番 ADMIN_EMAILS 全件について user 行の存在と role=admin を実測（要確認）／signup 時付与の廃止または既存アカウント昇格のみへ一本化／フッター問い合わせ先を admin ログインアドレスと別にする。

### High
- H-1 POST /contact（無認証）が admin メール爆撃・Brevo 枯渇の直通経路。contact.py:34 が RateLimitGuard("public_read")（120 req/60s）のみ、XFF 欠如時は IP 軸スキップ。修正: signup_ip 等の厳しい既存スコープへ変更＋email 軸 hit_account＋プロセス内キャップ。
- H-2 401 共通処理が signOut 失敗時に無限リダイレクトループ。katadzuke-api.ts:519-531（.finally で reject でも遷移）、:510-511（モジュール変数ガードはフルページ遷移でリセット）、middleware.ts:64-77、login/page.tsx:23-25。修正: await signOut 成功時のみ遷移、sessionStorage でループ検知、login の自動 replace に role ガード、middleware の /admin 非admin は /login でなく別経路へ。open redirect は safe-path.ts で非成立。line-link.ts reauth 非回帰。

### Medium
- M-1 notify.py:278 Subject に未検証 category（CR/LF・U+202E 許容）。→ Literal 列挙化 or 制御文字拒否。
- M-2 admin.py:615-617 停止操作が logger.info のみ、解除時に suspended_reason を None 上書き。→ 監査テーブル／unsuspended_at。
- M-3 ilike の %/_ 未エスケープ（admin.py:365,368,450,452,456,457,532,533）、cast(id,String).ilike は全表スキャン。→ escape 付き ilike、ID は UUID パース時のみ == 比較。
- M-4 analyze.py:81-84 Gemini の生例外を 503 detail で返す。→ 固定文言＋logger.exception。
- M-5 vision.py:273-276 任意 https URL を file_uri へ素通し。→ 本番は data: のみ許可。
- M-6 admin/users/page.tsx:117 placeholder「ユーザーID（前方一致）」だが backend に ID 検索が無い。
- M-7 contact.py:36-43 ADMIN_EMAILS 空でも 202。render.yaml envVars 非同期の実績あり。→ 起動時 CRITICAL／readyz degraded（main.py 解禁後）／リリース時に実送信確認。

### Low
- L-1 auth.py:68 user.email を正規化せず比較。L-2 停止は 403 で web は 401 のみ処理＝停止依頼者に「壊れている」表示。L-3 katadzuke-api.ts:1559 パス補間に encodeURIComponent なし。L-4 contact の email は形式検証のみ（返信先詐称）。

### 指摘なし（確認済み）
get_current_admin 全付与／limit 上限／admin 自己停止防止／依頼者停止ゲートの網羅（deps.py:130,209、auth.py:171-175,524,641-645）／メール本文の html.escape／通知宛先の取り違えなし／SQLi・open redirect 非成立／auth.ts maxAge=updateAge=7日は config.py:59 と一致／0025 は up/down 対称。

### 未解決リスク
- R-1 0025 の CREATE INDEX（非 CONCURRENTLY）ロック、boolean インデックスの選択性（部分インデックス推奨）。
- R-2 通知送信失敗が本番ログのみ（notify.py:71-73→notify_dispatch.py:59-65 で二重に握りつぶし）。
- R-3 本番 ADMIN_EMAILS 実値と user 行の有無は未検証（GET /admin/users?q= で1回実測）。
- R-4 /contact が public_read を流用し、公開一覧閲覧と同一 IP バケット＝巻き添え 429。
