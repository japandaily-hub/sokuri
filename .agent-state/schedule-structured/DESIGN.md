# 日程候補の提示を「日付＋時間帯」の構造化入力にする — 設計書（草案 v2）

- 状態: **草案 v2・ユーザー確認前**（2026-09-27 Claude。設計＝architect〔opus〕、反証＝独立の検証役〔fable〕、事実確認と採否＝リーダー）。確定した論点は末尾「ユーザー決定」に追記する。
- 関連: 入力検証強化の記録 `.agent-state/schedule-validation/REVIEW.md`（ブランチ claude/pensive-mestorf-cba971 にのみ存在・未 push）、ボタン化（ブランチ claude/amazing-lamarr-866796・先端 d660ac7・検証済みで push 承認待ち）。
- パスの略記: `L:` = `.claude/worktrees/amazing-lamarr-866796/`、`P:` = `.claude/worktrees/pensive-mestorf-cba971/`、`M:` = main（9f2ffda＝本番）

影響範囲（1行）: backend の日程 API 3本（propose を変更、accept を新設、confirm を /schedule 専用に厳格化）と新しい純関数モジュール1つ、web の日程入力・表示6ファイル、E2E 03/04、backend テスト6ファイル。DB の変更は lamarr にある 0046 だけ。

## 0. リーダーによる事実確認（2026-09-27）

- 本番の messages.kind は alembic 0009 以来 VARCHAR(16)（`L:backend/alembic/versions/0009_messages_schedule_and_operator_profiles.py:35`）。kind を触るマイグレーションは 0009 と 0046 だけ。17字の schedule_proposal・18字の schedule_confirmed は PostgreSQL で INSERT に失敗するため、**0046 を反映するまで**本番には旧形式の提示データも API で確定した訪問日程もできない（推定。本番 DB は直接見ていない）。0046 を先に出すと、構造化の反映までの間に旧形式（v1）の提示が本番にできうる（→ §7・§8）。
- アプリにメッセージを削除する経路は無い（`delete(Message` 等の grep 0 件）。ただし将来の削除機能で壊れないよう、「最新の提示」は件数でなく seq の最大値で判定する（§4）。
- `max(meta["seq"].as_integer())` は SQLAlchemy 2.0.50 の SQLite で動き（v1・meta が NULL の行は無視）、PostgreSQL では `max(CAST(messages.meta ->> 'seq' AS INTEGER))` になる（使い捨てスクリプトで確認）。
- 本番の web（main）は dict 形式の detail の `message` を画面に出す（`M:web/src/lib/katadzuke-api.ts:786-815` と toDisplayMessage）。旧タブにも「再読み込みしてください」が届く。
- `_assert_party` は管理者を "user" として通す（`L:backend/app/api/v1/endpoints/transactions.py:277-282`）。完了確定は `completed_by="admin"` を記録している（同 :522）。
- 確認モーダルの実体は `web/src/components/kdz/ConfirmModal.tsx`（role=dialog・フォーカス閉じ込め・Esc 対応。admin 配下は再エクスポート）。
- d4945c8 は PROJECT_STATE.md のみの記録コミット（次に main へ push する人が含める指示あり）。

## 1. 結論

1. 提示 API は `{candidates:[{date:"YYYY-MM-DD", start:"HH:MM"|null, end:"HH:MM"|null}]}`（1〜10件）。当面、時間帯は「固定4枠＋時間指定なし」だけを受け付ける（任意の時刻に広げても API の形は変えない）。
2. 表示ラベル「2026年10月1日（木）9:00〜12:00」はサーバーだけが作り、meta v2 `{v:2, seq, candidates:[{date,start,end,label}]}` に保存する。v2 に `slots` は保存しない。
3. 確定用に `POST …/schedule/proposals/{proposal_id}/accept {candidate_index}` を新設する。visit_date、visit_time_slot（時刻だけ）、確定メッセージの本文は、どれもサーバーが構造化データから作る。チャットからの確定ではひとことを受け付けない（必要ならチャットで送る）。
4. 既存の `…/schedule/confirm` は /schedule 専用（任意の日付＋固定5種）として残し、固定5種の許可リストと日本時間の「今日」を追加する。
5. 確定できる提示: 最新の提示だけ（推奨・要確認。2026-09-26 の決定「全提示の候補」からの変更）。「最新」は seq の最大値で判定する。
6. 開いたままの旧タブからの送信は何も書き込まず、再読み込みを促す 422（code=schedule_client_outdated）。v1 データは表示だけにして /schedule へ案内する。
7. 作業の基点は lamarr の先端。pensive は push せず、ひとことの分離、固定5種の一致テスト、表示時の除去だけを移す。
8. 解消: SEC-N1/N2/L1/L2/I1/I2/I3/I5/I7/I8、QA-L5、F6（UTC の date.today）。残る: SEC-L4 の件数上限値、SEC-L6。

## 2. API 契約

### 2.1 propose（変更）`POST /api/v1/transactions/{transaction_id}/schedule/propose` → 201 `MessageOut`

リクエスト例: `{"candidates":[{"date":"2026-10-01","start":"09:00","end":"12:00"},{"date":"2026-10-03","start":null,"end":null}]}`

| 項目 | 規則 | 違反時 |
|---|---|---|
| candidates | 1〜10件。キーが無い（旧タブの `{slots}`）場合はハンドラで判定 | 422 `{"code":"schedule_client_outdated","message":"画面が古いため送信できませんでした。ページを再読み込みしてから、もう一度候補日を送ってください。"}` |
| date | "YYYY-MM-DD" の文字列に限る。日本時間の今日 ≤ date ≤ 今日+365日 | 422 "候補日は本日（日本時間）から1年以内の日付を選んでください。" |
| start/end | "HH:MM"。組は (09:00,12:00)・(12:00,15:00)・(15:00,18:00)・(18:00,21:00) か両方 null | 422（Pydantic の配列形式。正規の UI からは到達しない） |
| 当日の候補 | date が今日で、end が今の時刻（日本時間）以前 | 422 "終わった時間帯は候補にできません。" |
| 重複 | 同じ (date,start,end) は不可 | 422 "同じ日付・時間帯の候補が重複しています。" |
| 余分なキー | 候補要素は extra="forbid" | 422（配列形式） |

判定順: 認可（403/404）→ ロック → 状態（409 transaction_closed / schedule_already_confirmed）→ 意味の検証（422）→ 保存。業者のひとことは提示に持たせない（通常のメッセージで送れる）。正規の利用者が踏みうる検証（旧タブ・日付範囲・当日の終わった枠・重複）はハンドラで文字列または dict の detail を返す（Pydantic の配列 detail は画面で汎用文言になるため）。

### 2.2 accept（新設）`POST /api/v1/transactions/{transaction_id}/schedule/proposals/{proposal_id}/accept` → 200 `TransactionOut`

リクエスト: `{"candidate_index":0}`（extra="forbid"。StrictInt 0〜9）

| 状況 | status | detail |
|---|---|---|
| 当事者でない・依頼者側でない（管理者は依頼者側として通る） | 403 | "この成約への権限がありません。" / "日程確定はユーザー側のみ行えます。" |
| proposal_id がこの取引の schedule_proposal でない（他取引の id を含む） | 404 | "候補日の提示が見つかりません。ページを再読み込みしてください。" |
| status が pending でない | 409 | "日程確定できる状態ではありません。" |
| より新しい提示がある（論点2で「最新のみ」を選んだ場合） | 409 | `{"code":"schedule_proposal_superseded","message":"業者から新しい候補日が届いています。最新の候補からお選びください。"}` |
| 候補が過ぎている（日付が今日より前、または今日で end を過ぎた） | 409 | `{"code":"schedule_candidate_expired","message":"この候補日は過ぎています。業者に新しい候補を依頼するか、日程調整ページからお選びください。"}` |
| v1・未知の版の提示 | 422 | `{"code":"schedule_proposal_legacy","message":"この候補は古い形式のため、ここでは確定できません。日程調整ページからお選びください。"}` |
| 添字が範囲外 | 422 | "候補が見つかりません。ページを再読み込みしてください。" |

### 2.3 confirm（既存・/schedule 専用）`{visit_date, visit_time_slot, note?}`（形は変えない）

- visit_time_slot が固定5種以外なら 422 `{"code":"schedule_client_outdated","message":"この画面からは確定できません。ページを再読み込みしてから、もう一度お選びください。"}`（旧依頼者タブのラベル確定もここで止まる）。
- 日付の範囲検査は Pydantic の `date.today()` からハンドラへ移して日本時間で判定し、文字列 detail で返す。今日の枠で end を過ぎたものは 422。
- note の検証は pensive と同じ（改行以外の制御文字を拒否）。**管理者が代理で確定する場合、note は受け付けない**（422 "運営による代理の確定では、ひとことは送れません。"。note が依頼者本人の発言として保存される SEC-I7 を閉じる）。

別 URL にする理由: 同じ URL で2つの形を受けると、混在リクエストの扱いがあいまいになり、Pydantic のエラーが2系統の配列になる。状態遷移は共通関数 `_apply_schedule_confirmation` にまとめる。

## 3. データ

- schedule_proposal の meta v2: `{"v":2,"seq":3,"candidates":[{"date":"2026-10-01","start":"09:00","end":"12:00","label":"2026年10月1日（木）9:00〜12:00"},{"date":"2026-10-03","start":null,"end":null,"label":"2026年10月3日（土）時間指定なし"}]}`。date は isoformat 文字列で入れる（JSON 列）。
- ラベルに年を常に入れる（lamarr の formatSlotLabel・E2E 03 の期待値と同じ形式）。時間指定なしのラベルは値「時間指定なし」を使う（依頼者の日程調整ページの小見出し「業者に一任」は出さない。業者画面のボタンの小見出しは lamarr どおり「時間は相談」）。
- v2 に `slots` を持たせない（保存した重複データは消せず、将来ラベルを再解析する入口になる）。旧タブでは候補カードが空になるだけで、送信すれば 422 で再読み込みを案内する。
- schedule_confirmed の meta v2: `{"v":2,"source":"proposal"|"calendar","proposal_id"?,"candidate_index"?,"visit_date","visit_time_slot","label","confirmed_by":"user"|"admin"}`（confirmed_by の決め方は完了確定の completed_by と同じ）。
- transactions: visit_date=候補の date、visit_time_slot=時刻だけのラベル（固定値と1文字違わず一致）、status="visiting"。
- マイグレーション: 0046 以外は不要。Message の docstring を v2 の説明に更新する。

## 4. サーバー処理（新モジュール `backend/app/services/visit_schedule.py`・DB に依存しない純関数）

中身: `VISIT_TIME_WINDOWS`、`FIXED_VISIT_TIME_SLOTS`、`time_label(start,end)`、`format_visit_label(date,time_label)`、`parse_proposal_meta(meta)`（v2 / v1 / unknown）、`now_jst()`／`today_jst()`（`L:backend/app/api/v1/endpoints/transactions.py:465` の `_today_jst` を移す）、`is_candidate_expired(candidate, now)`。

- propose: 認可 → ロック → 取得 → operator 以外 403 → 409（終了済み・確定済み）→ candidates 無しは warning ログ `schedule.legacy_client`（ラベル本文は出さない）＋422 outdated → 日本時間で日付範囲・当日の終わった枠・重複 → `seq = COALESCE(MAX(meta.seq), 0) + 1`（ロック下の1クエリ）→ Message 追加（通知の判定・送信は lamarr のまま）。
- accept: 認可 → ロック → 取得 → user 以外 403 → pending 以外 409 → `id と transaction_id と kind` で提示を1行取得（無ければ 404）→ v2 以外 422 legacy →（最新のみの場合）`seq != MAX(meta.seq)` で 409 superseded → 添字範囲外 422 → 過ぎていれば 409 expired → `_apply_schedule_confirmation(source="proposal")`。全提示を読み込まない（SEC-L4 の「ロックを持ったまま全提示を読む」は解消）。
- confirm: 認可 → ロック → 取得 → party → status → 許可リスト外は warning ログ＋422 outdated → 日本時間で範囲・当日の終わった枠 → 管理者の代理で note ありは 422 → `_apply_schedule_confirmation(source="calendar")`。
- `_apply_schedule_confirmation`: visit_date・visit_time_slot・status を設定 → 本文 `訪問日程が {format_visit_label(...)} に確定しました。`（業者の文字も note も連結しない）→ flush＋created_at を refresh → note があれば依頼者本人の text メッセージを created_at+1µs で追加（pensive の実装を移す）→ commit → `dispatch_schedule_confirmed`（変更なし）。
- ロックは既存の `lock_transaction_rows` 1本。propose と accept は同じ行ロックで直列になり、結果は必ずどちらか一方に決まる。created_at は PG ではトランザクション開始時刻でロック待ちにより逆転しうるため、最新の判定には seq を使う。

## 5. web の変更

- `lib/visit-slots.ts`: VISIT_TIME_SLOTS に start/end を追加し `VisitTimeSlotValue` 型を公開。`parseScheduleProposalMeta`（実行時の型ガードつき v2 / v1 / unknown）、`latestProposalId`（seq の最大値。サーバーと同じ定義）、`parseScheduleConfirmedMeta` を追加。formatSlotLabel は業者画面のプレビュー専用に (date,start,end) を受ける形にし、サーバーと同じ golden fixture で検証。parseSlotDate・SLOT_DATE_PATTERN・VISIT_TIME_SLOT_MAX_LENGTH は削除（ラベル解析を全廃）。
- `lib/katadzuke-api.ts`: `proposeSchedule(id, candidates, token)`、`acceptScheduleCandidate(id, proposalId, index, token)` を新設、`confirmSchedule` の visit_time_slot を `VisitTimeSlotValue` 型に。
- `operator/chat/[id]/page.tsx`: ラベル生成をやめ {date,start,end} を送る（重複除去は `date|start|end`）。送信済み一覧は v2 なら label、v1 なら除去処理をかけた slots。最新の提示に「（最新）」、それ以前は灰色。（最新のみの場合）送信ボタンの下に「新しく送ると、前に送った候補は選べなくなります」を出し、入力欄には最新の提示のうち過ぎていない候補を最初から入れておく。outdated なら「再読み込み」ボタン。
- `components/kdz/ChatPanel.tsx`: 確定は `handleAccept(msg, index)`（ConfirmModal を経て accept）。superseded / expired を受けたら再取得。候補カードは版で描き分け（確定できる v2＝候補ごとのボタン、置き換わった v2＝文字だけ、v1・unknown＝文字だけ＋「日程調整ページで選ぶ」リンク、過ぎた候補は無効化、key は添字）。schedule_confirmed は meta.label から作る「確定しました」の帯で表示（旧データは body を制御文字除去）。
- `app/schedule/page.tsx`: ハイライトは最新 v2 の candidates[].date から作る（解析しない）。確定リクエストは変えない。
- `lib/categories.ts` の formatVisitSchedule: 日付は常に visitDate から作り、slot は固定値か厳密な時刻範囲のときだけ後ろに付ける。影響する画面: cases/[id]、mypage、review、operator/transactions、operator/transactions/[id]。
- `e2e/helpers/api.ts`: proposeSchedule を candidates に、acceptSchedule を追加。

## 6. UI 案

業者の提示カード（推奨 A）:

```
A（推奨: lamarr の現行UI）           B（2週間の帯＋複数選択）          C（よく使う候補＋自由な日付）
┌引き取り候補日を提案する──────┐ ┌◀10月▶ [1木][2金][3土][4日]…┐ ┌よく使う: [明日 午前][明日 午後]┐
│候補日1 [2026/10/01 ▼]   [×]│ │10月3日（土）の時間帯（複数可）│ │         [明後日 午前][週末 午前]│
│[9:00〜12:00 午前][12:00〜 昼]│ │[午前✓][昼][午後✓][夜][相談]  │ │ほかの日: [日付▼][時間帯×5]     │
│[15:00〜 午後][18:00〜 夜]    │ │選択中3件  ・10/1 9:00〜12:00×│ │選択中2件 …                     │
│[時間指定なし 時間は相談]     │ │          ・10/3 9:00〜12:00×│ │[2件を送信する]                  │
│→ 2026年10月1日（木）9:00〜12:00│ │[3件を送信する]               │ └────────────────┘
│[＋候補日を追加] (最大10)     │ └──────────────────┘
│新しく送ると前の候補は選べません│
│[候補日を送信する]            │
└──────────────────────┘
```

依頼者の確定カード（推奨 B）:

```
A（現行: ラジオ＋1ボタン）          B（推奨: 候補ごとのボタン＋確認）       C（押すと展開）
┌引き取り候補日──────────┐ ┌引き取り候補日（押すと確定へ）──┐ ┌引き取り候補日──────────┐
│◉ 10月1日（木）9:00〜12:00   │ │[10月1日（木）9:00〜12:00 で確定] │ │▸ 10月1日（木）9:00〜12:00   │
│○ 10月3日（土）15:00〜18:00  │ │[10月3日（土）15:00〜18:00 で確定]│ │▾ 10月3日（土）15:00〜18:00  │
│[10月1日… を選ぶ]            │ │どれも合わない→日程調整ページで選ぶ│ │  [この日で確定する]         │
└──────────────────┘ └────────────────────┘ └──────────────────┘
 B の確認: 「2026年10月1日（木）9:00〜12:00 で確定しますか？確定すると業者に通知され、変更はメッセージでの相談になります」[やめる][確定する]
 確定後（業者・依頼者とも）: ──[済] 訪問日程が確定しました  2026年10月1日（木）9:00〜12:00──
```

## 7. 後方互換と移行

| 経路 | 挙動 |
|---|---|
| 旧業者タブ（main の自由記述 `{slots}`） | 403/404/409 の後で 422 outdated。書き込みゼロ。warning ログで件数を数えられる |
| 旧依頼者タブ（main の ChatPanel・ラベルで確定） | confirm の許可リストで 422 outdated。v2 の提示は空のカードとして表示（再読み込みで直る） |
| 旧 /schedule タブ（固定5種） | そのまま通る（「今日」の判定だけ日本時間） |
| v1 データ（meta.slots だけ）。0046 反映〜構造化反映の間に本番でできうる | 表示だけ（除去処理をかけた文字列）＋ /schedule への案内。accept は 422 legacy。業者が出し直せば新形式になる |
| 日付入りラベルが visit_time_slot に入った旧行 | formatVisitSchedule は日付だけを出す |
| デプロイのずれ（Vercel と Render の数分） | 新 web＋旧 API は汎用エラー、旧 web＋新 API は outdated。どちらも不正なデータは書かれない |

サーバーで新旧両方を受け付ける移行期間は設けない。終了条件: Render のログで `schedule.legacy_client` が7日連続 0 件（ログの保持は7日）になったら、旧形式の判定コードを片付ける。

## 8. 未 push の3ブランチとの順序（ユーザー確認事項）

- **(A) 推奨**: lamarr はそのセッションの計画どおり先に反映（検証用 PR の CI → 0046 を先行 → /readyz 確認 → 残り）。構造化は lamarr の先端の上で作り、仕上がったら main に載せ直して続けて反映（数日以内）。その間に本番でできた提示は、構造化の反映後は表示だけ（§7）。pensive は push しない（構造化で置き換え、必要な部分だけ移す）。
- (B): 構造化を仕上げてから、0046 → lamarr の残り＋構造化を同じ日に続けて反映。旧形式の提示が本番にできず、pensive の防御が無い期間も生じない。かわりに日程機能の復旧（INC-2026-09-26-1）は構造化の完成まで待つ。
- (C) 非推奨: lamarr→pensive→構造化の順にすべて反映（pensive のラベル照合は直後に消すコード。5ファイルの衝突解消と反映が無駄になる）。
- angry-lamport（8b3a82c）は独立に反映できる（lamarr と衝突なし）。

## 9. 解消するレビュー指摘と残るもの

| ID | 本設計後 |
|---|---|
| SEC-N1 / N2 / L2 | 解消。業者の文字列はラベル・visit_time_slot・確定文・照合のどこにも入らない |
| SEC-I1 / QA-L5 | 解消。ラベルを解析しない |
| SEC-I2 | 解消。ISO 日付で持ち、ラベルに年が入る |
| SEC-I3 / I5 | 解消。自由記述が無く、日付は date 型 |
| SEC-L1 | 新データでは構造上解消。旧データは表示時の除去 |
| SEC-I7 | 解消。管理者の代理確定では note を受け付けない。confirmed_by を記録 |
| SEC-I8 | 確定を「確定しました」の帯で出せば解消（UI 案 B） |
| SEC-L4 | 全提示を読む問題は解消（accept は1行取得＋最大値の集計1回）。件数の上限値は別タスク |
| SEC-L6 | 残る（範囲外） |

別タスク「運営名義の確定メッセージと業者ラベルを分ける」は、中心の SEC-L1・SEC-I8 と付随の SEC-I7 を本件で閉じるため、完了扱いにする。

## 10. テスト計画

- backend 新規: `tests/test_schedule_structured.py`（propose の形・範囲・日本時間の境界・当日の終わった枠・重複・枠外・余分なキー・`{slots}` の 422／accept の正常系・IDOR 404・superseded（最大 seq で判定・v1 が混ざっても）・legacy・範囲外・expired（日付と当日の end）・業者 403・状態 409・管理者の confirmed_by／confirm の固定5種・管理者の note 422）、`tests/test_visit_schedule_unit.py`（曜日・うるう日・年末年始・UTC 14:59/15:00 境界・v1/v2 読み分け）、固定時間帯と `web/src/lib/visit-slots.ts` の一致テスト（波ダッシュ U+301C と U+FF5E のずれも検出）、ラベルの golden fixture。
- backend 更新: test_katadzuke_api.py・test_account_api.py・test_r10_backend_fixes.py・test_txn_state_integrity.py・test_r8_abnormal_guards.py の slots／"10:00-12:00" を新形式・固定値へ。
- PostgreSQL: CI の pg-concurrency（`backend/scripts/pg_concurrency_check.py`）に S11（propose と accept の競合で結果が一方に決まる・accept の二重押しで 200 と 409・可能なら運営の強制終了と accept の競合）。`meta ->> 'seq'` の集計も実 PG で通る。
- web（node --test）: visit-slots.test.mts 更新、categories.test.mts。
- E2E: 03＝業者の操作は同じ・依頼者は候補ボタン→確認モーダル→両者に確定の帯。04＝/schedule 経路のまま（当日の終わった枠を選ばないよう時間帯を確認）。E2E と build は実装者が流し、レビュー担当には走らせない。

## 11. 反証（独立の検証役）の採否

| 指摘 | 採否 | 理由・対応 |
|---|---|---|
| C1 旧データ無しの前提は 0046 先行と両立しない（High） | 採用 | §0・§7・§8 を訂正。窓の間の v1 は表示だけ。窓を無くす (B) を選択肢に追加 |
| C2 「最新のみ」の安全上の理由は accept の1行取得で消える（High） | 論点化 | 事実として採用（§4）。残るのは製品判断なので論点2としてユーザーへ |
| C3 件数＝seq は削除機能で壊れる（Medium） | 採用 | 最新＝seq の最大値に統一（SQLite・PG の SQL を確認済み） |
| C4 時間指定なし＝「業者に一任」が業者提示で破綻（Medium） | 不採用 | ラベルは値「時間指定なし」を使い、「業者に一任」は出ない（§3） |
| C5 旧 web が dict の detail を表示できるか未確認（Medium） | 不採用 | 確認済み。main の katadzuke-api.ts:786-815 が message を表示する |
| C6 pensive を出さないと窓の間 Low 指摘が残る（Medium） | 論点化 | 反映順 (A)/(B) の比較に含めた |
| C7 ConfirmModal の参照先が再エクスポート（Low） | 採用 | 実体の components/kdz/ConfirmModal.tsx に修正 |
| C8 当日の候補は end を過ぎたら期限切れに（Low） | 採用 | propose・accept・confirm に追加 |
| 見落とし: 管理者の代理確定の note（SEC-I7） | 採用 | 管理者の代理では note を 422 |
| 見落とし: 通知に時間帯を入れる | 次回候補 | 範囲外（通知の文面変更） |

## 12. ユーザーに確認する論点

1. 時間帯: 固定4枠＋時間指定なし（推奨）か、4枠＋「時刻を指定」（30分刻み）か。
2. 確定できる提示: 最新の提示だけ（推奨）か、過去の提示もすべて（2026-09-26 の決定どおり）か。
3. UI: 業者＝A（現行）、依頼者＝B（候補ごとのボタン＋確認・確定の帯）でよいか。
4. 反映の順番（§8）: (A) lamarr 先行（推奨）か (B) 構造化を待って同じ日に続けて反映か。

## ユーザー決定（2026-09-27・選択式）

1. 時間帯: **4枠＋「時刻を指定」**（固定4枠のボタン・時間指定なし・開始と終了を30分刻みで選ぶ）。→ §13 の時刻規則。§1-1・§2.1 の「固定4枠だけ」はこれで置き換わる。
2. 確定できる候補: **最新の提示だけ**（推奨どおり。2026-09-26 の「全提示」から変更）。
3. 依頼者の確定画面: **候補ごとのボタン＋確認**（推奨 B。確定は「訪問日程が確定しました」の帯で表示）。業者の入力画面は lamarr の画面に「時刻を指定」を足す。
4. 反映の順番: **lamarr を先に反映**（推奨 (A)）。構造化は lamarr の先端 d660ac7 の上で作る。pensive は push せず必要な部分だけ移す。

## 13. 実装仕様（確定版・backend と web の共通の正本）

### 13.1 時刻・ラベル・期限の規則（backend `app/services/visit_schedule.py` と web `lib/visit-slots.ts` で一致させる）

- start/end は「両方 null（時間指定なし）」か「両方 "HH:MM"（ゼロ詰め・分は 00 か 30）」。
- 06:00 ≤ start < end ≤ 22:00、end − start ≥ 60 分。固定4枠（09:00–12:00・12:00–15:00・15:00–18:00・18:00–21:00）もこの規則を満たすので、サーバーは固定と任意を区別しない。
- time_label: null/null → `時間指定なし`、それ以外 → `{時(ゼロ詰めなし)}:{分}〜{時}:{分}`（波ダッシュは U+301C）。固定4枠の time_label は固定値と1文字違わず一致する（例 `9:00〜12:00`）。
- label: `{年}年{月}月{日}日（{曜}）{time_label}`（括弧は全角 U+FF08/U+FF09、日付と時刻の間に空白なし）。正解データは `web/src/lib/visit-slots.golden.json`（backend・web の両方のテストで照合する）。
- 期限切れ（日本時間）: date < 今日 → 期限切れ。date = 今日 かつ end が null でなく 現在時刻 ≥ end → 期限切れ。end が null（時間指定なし）の当日は期限切れにしない。
- propose の日付範囲: 今日 ≤ date ≤ 今日+365日（日本時間）。
- 固定5種（/schedule で使う値）: `9:00〜12:00`・`12:00〜15:00`・`15:00〜18:00`・`18:00〜21:00`・`時間指定なし`。

### 13.2 web の VISIT_TIME_SLOTS の書式（backend の一致テストが正規表現で読む・この形を崩さない）

```ts
export const VISIT_TIME_SLOTS: VisitTimeSlot[] = [
  { value: "9:00〜12:00", label: "午前", start: "09:00", end: "12:00" },
  { value: "12:00〜15:00", label: "昼", start: "12:00", end: "15:00" },
  { value: "15:00〜18:00", label: "午後", start: "15:00", end: "18:00" },
  { value: "18:00〜21:00", label: "夜", start: "18:00", end: "21:00" },
  { value: "時間指定なし", label: "業者に一任", start: null, end: null },
];
```

### 13.3 API（§2 を次のとおり確定）

- propose: `{candidates:[{date,start,end}]}`（1〜10件・候補要素は extra="forbid"・最上位の未知のキーは無視）。ハンドラの判定順: 認可 → ロック → 取得 → operator 以外 403 → 409（終了済み・確定済み）→ candidates が無い／null は warning ログ `schedule.legacy_client path=propose` と 422 dict outdated → 日付範囲 422（文字列 "候補日は本日（日本時間）から1年以内の日付を選んでください。"）→ 当日の終わった枠 422（"終わった時間帯は候補にできません。"）→ 重複 422（"同じ日付・時間帯の候補が重複しています。"）→ seq → 保存 → 通知（lamarr のまま）。書式・時刻の規則違反・片方だけ null・余分なキー・件数 0/11 は Pydantic の 422（配列）でよい。
- accept: `POST /transactions/{transaction_id}/schedule/proposals/{proposal_id}/accept`、`{candidate_index: StrictInt 0〜9}`（extra="forbid"）→ 200 TransactionOut。判定順と文言は §2.2（superseded は `proposal.seq != MAX(seq)`）。
- confirm（/schedule 専用）: 形は `{visit_date, visit_time_slot, note?}` のまま。Pydantic の `date.today()` 検査を外し、ハンドラで: 認可 → ロック → 取得 → user 以外 403 → pending 以外 409 → 固定5種以外は warning ログ `schedule.legacy_client path=confirm` と 422 dict outdated → 今日より前 422（"訪問日は本日以降を指定してください。"）→ 365日超 422（"訪問日は1年以内で指定してください。"）→ 当日の終わった枠 422（"終わった時間帯は選べません。別の時間帯か日付をお選びください。"）→ 管理者の代理で note あり 422（"運営による代理の確定では、ひとことは送れません。"）→ 確定。
- 確定の共通処理・meta v2・confirmed_by・note の分離は §3・§4 のとおり。confirmed_by は完了確定の completed_by と同じ判定（管理者かつ案件の所有者でなければ "admin"）。
- seq: `COALESCE(MAX(CAST(meta ->> 'seq' AS INTEGER)), 0) + 1`（SQLAlchemy では `func.max(Message.meta["seq"].as_integer())`）をロック下で求める。

### 13.4 web（§5 を次のとおり確定）

- 業者の提示カード: 各行に日付入力＋ボタン6つ（固定4枠・時間指定なし・「時刻を指定」）。「時刻を指定」を選ぶと開始・終了の選択（30分刻み。開始 6:00〜21:00・終了 7:00〜22:00・既定 10:00〜12:00・1時間未満は送信不可）が出る。当日の終わった枠は選べない。プレビューは formatSlotLabel。送信は `{date,start,end}`（重複は `date|start|end` で除去）。最新の提示があるときは、カードを開いたときにその提示のうち過ぎていない候補を最初から入れ、送信ボタンの下に「新しく送ると、前に送った候補は選べなくなります。」を出す。送信済みの一覧は最新に「（最新）」、それ以前は灰色。
- 依頼者の確定カード: 最新の v2 だけ候補ごとの「{label} で確定」ボタン（過ぎた候補は無効＋「過ぎた候補です」）。押すと ConfirmModal（`web/src/components/kdz/ConfirmModal.tsx`）で「{label} で確定しますか？確定すると業者に通知され、変更はメッセージでの相談になります。」→ accept。409 superseded / expired は理由を出してメッセージと取引を取り直す。置き換わった v2 は文字だけ（灰色・「新しい候補が届いています」）、v1・unknown は文字だけ＋「日程調整ページで選ぶ」リンク。最新カードの下にも「どれも合わない場合は日程調整ページで選ぶ」リンク。
- schedule_confirmed は両者のチャットで「✓ 訪問日程が確定しました ＋ label」の帯（v2 は meta.label、旧データは本文の制御文字を除去して表示）。
- /schedule: 業者提示のハイライトは最新 v2 の candidates の日付から作る。当日の終わった枠は選べない。ひとことは送信前に改行以外の制御文字を除去。
- formatVisitSchedule: 日付は常に visitDate から作り、slot は固定値か `^\d{1,2}:\d{2}〜\d{1,2}:\d{2}$` に一致するときだけ後ろに付ける。
- E2E: 03 は業者が日付＋9:00〜12:00 で提示 → 依頼者に有効な「{label} で確定」が1つ → 押して確認 → 両者に確定の帯。04 は /schedule で今日の「時間指定なし」を選ぶ（当日の終わった枠の拒否に掛からないように）。
