# 取引あたりの日程提示・チャット件数の上限とレート制限 — 決定・レビュー記録（2026-09-27・Claude）

コード中の「L-4」は、2026-09-26 日程 API 入力検証のセキュリティレビュー（ブランチ claude/pensive-mestorf-cba971 の `.agent-state/schedule-validation/REVIEW.md` の SEC-L4）を指す。本ファイルの SEC-xx / QA-xx は今回のレビューの番号。対応コミットはブランチ claude/zealous-colden-554ea6 の「fix(backend): 取引あたりの日程提示・チャット件数に上限とレート制限を設ける（L-4）」（2026-09-27 時点で origin/main=11b97c1 の上・未 push・push はユーザー承認事項。載せ直すとハッシュが変わるため、push 後の記録で確定値を書く）。

## 背景（重大度 Low）

- `POST /transactions/{id}/schedule/propose`（業者のみ・1 回 10 候補まで）に、取引あたりの回数上限もレート制限もなかった。
- 09-26 の日程検証（未 push）で、`confirm_schedule` は行ロック（Case/Transaction の FOR UPDATE）を持ったまま、その取引の全 schedule_proposal の meta.slots を読むようになる。審査済みの業者がスクリプトで数万回提示すると、その取引の確定・完了・キャンセル・運営の強制終了が待たされる。
- `POST /transactions/{id}/messages`（create_message）にも件数上限・レート制限がなく、`GET /transactions/{id}/messages`（list_messages）はページングなしで全件を返す。

## 着手前の調査で分かったこと

- 09-26 の照合も、提示 API の行ロックと提示件数の集計（成約後フローのボタン化・claude/amazing-lamarr-866796）も main（9f2ffda）には入っておらず、どちらも未 push のブランチにある。
- 本番の messages.kind は VARCHAR(16) のため `schedule_proposal`（17 字）が入らず、日程提示は本番で現在失敗している（INC-2026-09-26-1。0046 で解消予定）。0046 が入るまで、本件の提示連打は本番では起こせない。
- 相手への LINE 新着通知は `notify_dispatch.dispatch_message_received` で「同じ取引・同じ相手へ 5 分に 1 通」に間引き済み。連投で LINE の送信枠が尽きる経路はなく、残る影響は DB の行数と一覧の応答の大きさ。
- web の 3 画面（ChatPanel・業者チャット・/schedule）は「初回に全件、以降は `after=<最後の created_at>` で差分」。`after` は created_at の厳密な `>` 比較で、同じ DB トランザクション内で作られた行は created_at が同じになり得る。件数で区切るページングを入れると同時刻の途中で切れて取りこぼすため、(created_at, id) の複合カーソルと 3 画面の改修が要る（3 画面とも未 push の 2 ブランチが改修中）。
- E2E のシードはチャットを作らず、E2E が送るメッセージ・提示の回数はレート制限より十分少ない。

## ユーザー決定（2026-09-27・選択式・3 問とも推奨案）

1. 日程提示: 1 取引 20 回まで（`MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION`）。超過は 409「日程候補の提示は1取引につき20回までです。調整はメッセージでご相談ください。」。依頼者は既存の候補か日程調整ページ（固定の時間帯）から確定できるので、取引は止まらない。
2. チャット（kind="text"）: 1 取引・当事者（sender_type）ごとに 300 件まで（`MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION`）。超過は 409「この取引で送れるメッセージの上限に達しました。運営へお問い合わせください。」。当事者ごとなので、片方が相手の枠を使い切って会話を止めることはできない。一覧は最大でも約 650 件（300×2＋提示 20＋少数のシステムメッセージ）に収まるため、list_messages にページングは入れず、web も変更しない。
3. レート制限（アカウント単位・全取引の合計）: チャット送信 60 秒で 30 件、日程提示 600 秒で 10 回。超過は 429（Retry-After つき）。

採らなかった案:
- 照合を PostgreSQL の JSONB 包含（`cast(meta, JSONB)['slots'].contains([slot])`＋LIMIT 1）にする案: 提示の上限で照合は最大 20 行・200 候補に収まる。PostgreSQL だけの分岐は、SQLite で動くテストでは確かめられない経路を増やすだけになる。
- list_messages のページング: 上記の取りこぼしと、web 3 画面の改修・未 push の 2 ブランチとの衝突のため。

## 実装の要点（backend のみ・マイグレーションなし）

- `core/limits.py`: 上記 2 定数。`MAX_REDUCTION_REQUESTS_PER_TRANSACTION` の直後に置いた（ファイル末尾は lamarr が追記しており、末尾に置くと衝突するため）。
- `config.py`: `rl_message_send_account_max=30`・`rl_message_send_window_sec=60`・`rl_schedule_propose_account_max=10`・`rl_schedule_propose_window_sec=600`（環境変数は RL_MESSAGE_SEND_ACCOUNT_MAX などフィールド名の大文字。いずれも 1 以上を検証）。既定値で効くので render.yaml・start.sh への追記は不要。本番で変えたいときは Render の環境変数に設定する（render.yaml の envVars は既存サービスに同期されない）。
- `core/rate_limit.py`: `RateLimitConfig` に `message_send_account`・`schedule_propose_account`（既存の呼び出しを壊さないようデフォルトつき）。
- `api/rate_limit_deps.py`: スコープ `message_send`・`schedule_propose`（アカウント軸のみ・IP 軸なし＝同じ回線の他の利用者を巻き込まない）と 429 の文言。
- `api/v1/endpoints/transactions.py`:
  - `_rate_limit_account_key(actor)` = `"{typ}:{id}"`（user と operator の UUID が同じバケットを共有しないよう名前空間を付ける）。
  - `_count_messages(session, txn_id, kind=..., sender_type=...)`: 当該取引だけを数える 1 クエリ。
  - create_message・propose_schedule: 本体の最初で `hit_account`（重い `_get_txn` より前）→ 当事者性 → 終了済みなら従来の transaction_closed の 409 → 件数上限の 409。件数上限は行ロックを取らない soft cap。同時送信での超過は「同時に COUNT〜COMMIT の間にいられる件数」＝DB 接続プール（既定 5+5=10）で頭打ちになり、1 インスタンスあたり最大 +9（text は 1 当事者 309 件、提示は 29 回＝約 290 候補）。レート制限の窓内バーストの方が大きいので、効いているのはプール（SEC-I1）。
  - 上限到達の WARNING は transaction_id・party・件数・上限（チャットは by_admin も）だけを出し、本文は出さない。
  - list_messages: 挙動は変えず、応答件数の天井とページングを入れる場合の注意をコメントで残した。
- 緊急停止（`RATE_LIMIT_ENABLED=false`）ではレート制限だけが外れ、件数上限は残る（超過幅もプールで頭打ちのまま）。
- 管理者（role=admin）は `_assert_party` で依頼者側として通る既存仕様のまま。件数は sender_type 単位なので管理者の発言は依頼者側の 300 件に入り、レート制限は管理者自身のバケットで数える（テストで固定）。上限に達した取引を運営が解除する手段はない（案内先の運営はメール等で仲介する）。

## レビュー指摘と対応（2026-09-27）

### SEC（security-reviewer）— Critical/High/Medium なし

| ID | 重大度 | 内容 | 対応 |
| :-- | :-- | :-- | :-- |
| SEC-L1 | Low | list_messages と mark_messages_read の呼び出し頻度が無制限。1 回あたりの量は上限で頭打ちになったが、自分の枠 300 件を 2000 字で埋めてから全件取得を並列で連打すると、1 回あたり数 MB の JSON 化が単一プロセスのイベントループと DB プールを占有しうる | 見送り（新しい上限値＝製品判断のため、ユーザーに確認する。推奨: list_messages にアカウント軸 60 秒 120 回〔web は 1 タブ 5 秒間隔＝12 回/分〕、mark_messages_read は既読ポインタが相手の最新発言以上なら UPDATE を省く） |
| SEC-I1 | Info | 超過幅を抑えているのはレート制限ではなく DB プール。同時実行時は text 309 件・提示 29 回（約 290 候補）まで | 対応（コメントを訂正）。提示 API に今すぐ行ロックを入れる案は採らない（lamarr の合流で行ロック下の厳密な判定になる） |
| SEC-I2 | Info | 管理者は依頼者側として通るため依頼者の 300 件枠を共有する。上限到達時に「運営へお問い合わせください」と案内するが、運営が解除する手段はない。WARNING に送信者の種別が残らない | 一部対応（WARNING に by_admin、回帰テスト 2 本〔非当事者の 403 が被害者のバケット・件数に影響しない／管理者の送信は管理者のバケットを消費し件数は依頼者側〕）。方針は現状維持（管理者は信頼済み）。上限の上書き手段は将来課題 |
| SEC-I3 | Info | 本番の messages.kind は VARCHAR(16) のままで提示が 500 になる。失敗した試行も schedule_propose のバケットを消費し、10 回の再試行で 429 が先に出て本当の原因が見えにくくなる | 反映順で対応（0046 を先に。下記「反映順」）。PG 同時実行チェックへのシナリオ追加（上限−1 から 10 並列で上限＋9 以下）は見送り（TODO） |
| SEC-I4 | Info | 429 の WARNING が 1 リクエストごとに 1 行出る（既存の仕組みに新スコープが乗っただけ） | 見送り（既存。アラート転送はなく、影響はログのノイズのみ） |
| SEC-I5 | Info | 利用者が書ける kind を将来増やすと件数の天井が崩れる／新着通知は 1 取引で最大約 300 通送れ、LINE の月間送信枠を 1 人で使い切りうる | 一部対応（kind を増やすときの注意をコメントに）。通知の宛先ごとの 1 日上限は別タスク |

確認済み・問題なしとされた観点: 判定順（件数の 409 は当事者判定の後で他人の取引の件数は漏れない・429 は呼び出し者自身のバケットなので取引の存在確認に使えない）、第三者による他人のバケット消費（キーは検証済み JWT から作るので不可）、回避経路（Message を作るのは transactions.py の 3 か所だけ・kind と sender_type はサーバーが決める）、情報漏えい、インメモリストアのキー数、インジェクション・CSRF。

### QA（qa-reviewer）— Critical/High なし

| ID | 重大度 | 内容 | 対応 |
| :-- | :-- | :-- | :-- |
| QA-M1 | Medium | チャットの 409 のテストが DB の件数不変を確かめていない | 対応 |
| QA-M2 | Medium | get_rate_limiter が設定の新項目を正しい引数へ渡しているかのテストがない | 対応（`__wrapped__` を直接呼び、lru_cache のシングルトンには触れない） |
| QA-L1 | Low | 既定値のテストが実行環境の RL_* 環境変数に影響される（実証済み） | 対応（delenv） |
| QA-L2 | Low | 提示側に「終了済みが件数上限より先」のテストがない | 対応 |
| QA-L3 | Low | テスト用ヘルパーの docstring が不正確 | 対応 |
| QA-Info | Info | 未 push の 2 ブランチとの合流時の注意（件数判定の一本化・行ロック後の厳密化・判定順） | 下記「別ブランチとの合流メモ」に反映 |

上限到達時の WARNING の書式は、引数の数が合わないと logging が例外を出さずに崩れるため、caplog で回帰を見る。

## 反映順（推奨）

本件はマイグレーションなし・backend のみ。

1. lamarr の 0046（messages.kind の拡幅）をマイグレーション先行で反映 → 本番 /readyz で head=0046 を確認 → lamarr の残り。先に入れないと、本番の提示は 500 のままで、本件のレート制限が再試行 10 回で 429 を返して原因を見えにくくする（SEC-I3）。
2. cool-burnell（claude/cool-burnell-bccf9c＝lamarr の上に 09-26 の日程検証〔pensive〕を載せ替え＋L-1/I-8。元の pensive ブランチはこれで置き換え。別セッションが作業中）。
3. 本件（L-4）を cool-burnell の結果の上へ載せ直してから push する。確定時の照合（2 に含まれる）が上限なしで動く期間をなくすため、2 と間を空けない。

## 検証

- pytest（CI 同等 `TZ=Asia/Tokyo PYTHONUTF8=1`）: 変更前 1456 passed → 初版 1471 passed → レビュー反映後 1475 passed・失敗 0（17 分。新規 19 件は `tests/test_transaction_message_limits.py`）。
- CI の pg-concurrency（実 PostgreSQL の同時実行シナリオ）はメッセージ・提示の API を通らないため影響なし。
- web は変更なし。409/429 の文字列 detail は既存のトースト（`toDisplayMessage` は 4xx の detail をそのまま表示）に出る。
- E2E は未実施（web の変更なし・E2E のシードはチャットを作らず、E2E の送信・提示の回数はレート制限より十分少ない）。
- PostgreSQL 実機での確認は未実施（件数は単純な COUNT。soft cap の超過幅はプール設定からの机上の見積もり）。
- 別ブランチとの合流は `git merge-tree` で試算した（作業ツリー・ブランチは動かしていない）。

## 別ブランチとの合流メモ（git merge-tree で試算済み）

- **lamarr（claude/amazing-lamarr-866796）**: transactions.py だけが衝突する（limits.py は自動で統合される）。衝突は import・propose_schedule の引数（`background` と `request` の両方を残す）・本体冒頭の 3 か所。**注意: 件数判定のブロックは衝突せずに lamarr の `_schedule_proposal_stats` の後ろへ自動で並ぶため、そのままだと件数を 2 回数え、「行ロックを取らない」というコメントが事実と合わなくなる。** 合流後の順序は「hit_account → `_assert_party_before_lock` →（任意）ロック前の件数判定で上限到達ならロックを取らずに 409 → `_lock_txn_rows` → `_get_txn`/`_assert_party` → `_assert_txn_open` → pending 判定 → `_schedule_proposal_stats` の件数で上限を再判定（ロック下なので厳密）→ 通知の判定」にし、コメントを直す。
- **pensive（claude/pensive-mestorf-cba971）**: 単独なら propose_schedule の 1 か所だけが衝突する。件数上限（409）と提示時の日付検証（422）の両方を残す。confirm_schedule の `_assert_offered_time_slot` は、提示が上限でおおむね 20 行になるので変更不要。照合のクエリを transaction_id・kind='schedule_proposal' に加えて sender_type='operator' でも絞ると多層防御になる（SEC-I1 の付記）。
- **cool-burnell（claude/cool-burnell-bccf9c・11:46 の b847ea4 で試算）**: pensive は cool-burnell に置き換わる予定。衝突は transactions.py の 3 か所（import・引数・本体冒頭。lamarr と同じ）と PROJECT_STATE.md・docs/TODO.md（同じ位置への追記）。**lamarr と同じく件数判定のブロックは衝突せずに「visiting の 409 → 日付検証（422）→ `_schedule_proposal_stats` → 本件の件数判定」の順に自動で並ぶ**ので、`_schedule_proposal_stats` の件数で上限を判定する形（ロック下で厳密）に書き換え、`_count_messages` による 2 回目の COUNT と「行ロックを取らない」コメントを消す。
- どの順で main に入っても、本件の変更は propose_schedule の周辺で衝突する。解消は Claude が行う。

## 範囲外・見送り（別タスク候補）

- list_messages・mark_messages_read の呼び出し頻度の制限（SEC-L1。上限値の判断はユーザー）。
- 上限に達した取引を運営が解除する手段（SEC-I2）。
- PG 同時実行チェックへのシナリオ追加: 上限−1 から 10 並列で送信・提示して上限＋9 以下になること（SEC-I3）。
- 429 の WARNING の間引き（SEC-I4・既存の仕組み全体の話）。
- 新着通知の宛先ごとの 1 日上限（LINE の月間送信枠の保護。SEC-I5）。
- チャット本文の制御文字・孤立サロゲート対策（前回の日程検証レビューの SEC-L6 として起票済み。入ると最大応答サイズも下がる）。
