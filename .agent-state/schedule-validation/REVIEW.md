# 日程調整 API の入力検証強化 — 決定・レビュー記録（2026-09-26・Claude）

コード中の「日程検証レビュー SEC-xx / QA-xx」はこのファイルの番号を指す。対応コミットは 98ec5f6。2026-09-27 にボタン化ブランチ（claude/amazing-lamarr-866796）の上へ載せ替えて 4c7274a（ブランチ claude/cool-burnell-bccf9c・未 push・push はユーザー承認事項。下記「載せ替え」参照）。

## 背景（2026-09-25 セキュリティレビュー・重大度 Low）

- `ScheduleProposeRequest.slots`（各 1〜64 字・最大 10 件）と `ScheduleConfirmRequest.visit_time_slot`（1〜32 字）は文字数しか検証していなかった。
- `confirm_schedule` は visit_time_slot が提示候補に含まれるか、ラベル内の「◯月◯日」と visit_date が一致するかを見ていなかった。
- 依頼者が API を直接呼ぶと、双方向制御文字で業者の画面の時間帯を逆順に見せる、visit_date=10/1 のまま visit_time_slot="9月28日 10:00" として業者の画面（日付入りラベルはそのまま表示）と通知・リマインド（visit_date 基準）を食い違わせる、ができた。XSS ではない（React のテキスト描画）。

## ユーザー決定（2026-09-26・選択式）

1. 候補・確定時間帯は制御文字（Unicode Cc/Cf/Co/Cs・改行含む）を 422。
2. 確定時の照合は**許可リスト方式**: 固定時間帯 5 種（`/schedule` の TIME_SLOTS）か、この取引で業者が提示した**全**候補（チャットは過去の提示カードからも確定できるため）に完全一致しなければ 422。
3. ラベル内の日付と visit_date の不一致は**拒否＋表示も visit_date 正**。
4. 追加: 候補の上限を 32 字に統一（DB 列 String(32)）／note も制御文字を拒否（改行のみ許可）／**note を運営名義のシステムメッセージから分離**（依頼者本人の text メッセージにする）。

着手前の調査で、当初案の「直近の提案候補に含まれるか」の照合は `/schedule`（任意の日付＋固定時間帯を送る・E2E 04 の経路）と既存 pytest 4 本を壊すことが分かったため、2 は許可リスト方式になった。

## 実装の要点

backend
- `schemas_katadzuke.py`: `VISIT_TIME_SLOT_MAX_LENGTH = 32`、`SCHEDULE_FIXED_TIME_SLOTS`（web の TIME_SLOTS と 1 文字違わず一致。backend のテストが web のファイルを読んで照合）、`_reject_control_chars`（改行を許さない項目では Zl/Zp も拒否）、`_reject_rtl_chars`（双方向クラス R/AL/AN。候補・確定時間帯だけ）、note は改行のみ許可。
- `transactions.py`: `_slot_month_days`（NFKC 後に `([0-9]+)\s*月\s*([0-9]+)\s*日`）、`_assert_offered_time_slot`（許可リスト照合）、`_assert_slot_date_matches`（日付の集合が visit_date の月日と一致しなければ 422）、提示時に「1 候補に別々の日付が 2 つ以上」「存在しない日付」を 422。理由を画面に出すため、これらはエンドポイント内で文字列 detail の 422 を返す（Pydantic の 422 は配列 detail で web には汎用文言しか出ない）。数値 422 を使う（`HTTP_422_UNPROCESSABLE_ENTITY` は Starlette 1.x で非推奨、改名後の定数は旧版に無い）。
- note は確定メッセージから外し、`sender_type="user"`・`kind="text"` の別メッセージにする。created_at は DB の `now()`（PostgreSQL ではトランザクション開始時刻）で同時刻になるため、確定メッセージを flush→refresh して得た時刻 +1µs を明示して「確定→ひとこと」の順に固定。新着通知は重ねない（日程確定の通知が既に飛ぶ）。

web
- `lib/categories.ts`: `stripControlChars`（Cc/Cf/Co/Cs＋Zl/Zp・1 行用）、`stripControlCharsKeepNewlines`（複数行用）、`slotMonthDays`（backend と同じ正規表現）。`formatVisitSchedule` はラベルの日付がすべて visit_date と一致するときだけラベル単独、それ以外は visit_date を先頭に出す。
- チャット（ChatPanel）の確定は生のラベルを送る（サーバーの完全一致照合のため）。表示だけ整形。日付の読み取りは slotMonthDays を使い、全角数字・合字・空白入りの候補もチャットから確定できる。
- 業者の候補入力は maxLength=32・送信前に制御文字を除去。`/schedule` のひとことは送信前に改行以外の制御文字を除去（ZWJ 絵文字やタブで理由の出ない 422 にならないように）。
- 運営名義（system）の吹き出しだけ、表示時に改行以外の制御文字を除去（本対応前に保存済みのメッセージへの二重の防御）。

## 日程検証レビュー（2026-09-26）の指摘と対応

### SEC（security-reviewer）— Critical/High/Medium なし

| ID | 重大度 | 内容 | 対応 |
| :-- | :-- | :-- | :-- |
| SEC-L1 | Low | 業者の候補ラベル（32 字）が運営名義の確定メッセージ本文に入る | 見送り（文言・デザインの判断が要る。別タスク「運営名義の確定メッセージと業者ラベルを分ける」） |
| SEC-L2 | Low | 双方向クラス R/AL/AN の文字（例 U+05F3）で見た目の日付と照合上の日付をずらせる | 対応（`_reject_rtl_chars`） |
| SEC-L3 | Low | U+2028/U+2029（Zl/Zp）が 1 行項目で拒否されない | 対応（backend 拒否・web 表示除去） |
| SEC-L4 | Low | 提示回数の上限がなく、確定時に行ロックを持ったまま全提示を読む | 見送り（上限値は製品判断。別タスク「取引あたりの提示・メッセージ件数に上限を設ける」） |
| SEC-L5 | Low | 本対応前に保存された運営名義メッセージの本文に表示時の除去がかからない | 対応（system 吹き出しだけ改行以外を除去） |
| SEC-L6 | Low | 通常チャット本文は制御文字を検証していない・孤立サロゲートで 500 の恐れ（既存） | 範囲外（別タスク「チャット本文の制御文字検証と孤立サロゲート対策」） |
| SEC-I1 | Info | 日付検出が「M月D日」の隣接形だけ（「10/1」「十月一日」等は素通し） | 一部対応（空白入りを許容）。他の表記は既知の残り（許可リストで候補は業者自身の文言に限られ、表示は visit_date が先頭・確定メッセージに ISO 日付が入る） |
| SEC-I2 | Info | 年を照合しない（今日と同じ月日だけは翌年の同日でも通る） | 見送り（TODO） |
| SEC-I3 | Info | ハングルのフィラー等だけの「見えない候補」が空白判定を通る | 見送り（TODO） |
| SEC-I4 | Info | backend の `\d` は Unicode 数字、web は ASCII のみで判定が食い違う | 対応（`[0-9]` に統一） |
| SEC-I5 | Info | 提示時に「2月30日」「13月1日」等を見ていない | 対応（提示時 422） |
| SEC-I6 | Info | ChatPanel が候補を文字列に絞っておらず、壊れた meta で描画が落ち得る | 対応（typeof string で絞る。/schedule も） |
| SEC-I7 | Info | 運営（admin）が確定すると note が依頼者の発言として保存される | 見送り（既存の create_message と同じ形。TODO） |
| SEC-I8 | Info | note が確定メッセージの続きに見える（違いはアバターの 1 文字） | 見送り（SEC-L1 と同じ別タスク） |
| SEC-I9 | Info | ZWJ 絵文字・タグ文字・タブで正当な note が 422（理由不明） | 対応（/schedule で送信前整形） |

### QA（qa-reviewer）— Critical/High なし

| ID | 重大度 | 内容 | 対応 |
| :-- | :-- | :-- | :-- |
| QA-M1 | Medium | PostgreSQL で created_at が同時刻になり得る | 変更なし（timestamptz はマイクロ秒の整数で +1µs は必ず後。id は UUID4 でタイブレークに意味がない）。PostgreSQL 実機での確認は未実施（Docker 停止中） |
| QA-M2 | Medium | 「note は日程確定通知と併せて伝わる」というコメントが事実と違う | 対応（通知は訪問日と URL のみ） |
| QA-M3 | Medium | 本対応前の提示（33〜64 字・制御文字入り）はチャットから確定できない | 許容（33〜64 字は以前から確定不能。/schedule からは確定可・業者の再提示で解消） |
| QA-M4 | Medium | 全角数字の候補がチャットから確定できない（backend は対応済み） | 対応（slotMonthDays に統一） |
| QA-L5 | Low | 漢数字の日付は検出されない | 既知の残り（SEC-I1 と同じ） |
| QA-L6 | Low | note の `\r\n` は 422 | 許容（お問い合わせと同じ基準。/schedule は送信前整形で `\r` を除去） |
| QA-L7 | Low | 合字（㋈㏠）のテストが無い | 対応 |
| QA-L8 | Low | 年またぎのテストが無い | 対応（純関数テスト） |
| QA-Info9/10 | Info | 命名の対称性 | 変更なし |
| QA-Info11 | Info | katadzuke-api.ts のコメント例が実際の形式と違う | 対応 |
| QA-Info12 | Info | parseSlotDate の重複 | 対応（slotMonthDays に統一） |

### 再レビュー（修正分・2026-09-26）— security・QA とも Critical/High なし

前回の SEC-L2・L3・L5・I1・I4・I5・I6・I9、QA-M2・M4・L7・L8・Info11・Info12 はすべて解消と判定。新規:

| ID | 重大度 | 内容 | 対応 |
| :-- | :-- | :-- | :-- |
| SEC-N1 | Low | 結合文字 U+034F・異体字セレクタ・Cn の既定無視可能文字・極細の空白で「1▯2月3日」と書くと、画面は 12月3日・照合は 2月3日になる（業者起点。SEC-L2 と同じ影響を別の文字で） | 見送り。文字種で塞ぐとノーブレークスペース・絵文字の VS16・分解形のかな等の正当な入力と衝突し、「l2月3日」「丨2月3日」のような目に見える紛らわしい文字は文字種では原理的に塞げない。根本策（提示を日付＋時間帯の構造化入力にしてラベルをサーバーで生成）を別タスク「日程候補の提示を日付と時間帯の選択式にする」へ |
| SEC-N2 | Info | 未割り当て（Cn）の文字は R/AL/AN 検査をすり抜ける（ブラウザは RTL ブロックの未割り当て文字を R/AL 扱い） | 見送り（SEC-N1 と同じ根本策で解消） |
| SEC-N3 / QA-R-M1 | Info / Medium | 前回の修正による後退: ChatPanel の parseSlotDate が「2月29日」を今年の暦で判定してから年を決めていた（平年に翌年の 2/29 が解析不能・うるう年の 3 月以降は存在しない翌年の 2/29 を送る） | 対応（`slotVisitDate(slot, today)` に切り出し、年を先に決めてからその年で実在を確認。単体テストで境目を固定） |
| QA-R-L1 | Low | 提示時に「2月29日」が通る陽性テストが無い | 対応 |
| QA-R-I1 | Info | `date()` の OverflowError 分岐のテストが無い | 対応（巨大な数字の候補で 422） |
| QA-R-I2 | Info | formatVisitSchedule に不正な visitDate のテストが無い | 対応 |

## 検証

- pytest（CI 同等 `TZ=Asia/Tokyo PYTHONUTF8=1`）: 変更前 1435 passed → 最終 1495 passed・失敗 0（新規 60 件は `tests/test_schedule_input_validation.py`）。
- web: `npx tsc --noEmit`・`npx eslint src e2e` エラー 0、`node --test` 106 passed（新規 49 件は `src/lib/categories.test.mts`）。
- ローカル E2E（worktree 専用: API 127.0.0.1:8003・web localhost:3000・使い捨て SQLite。当時は他セッションが 3100/3101/8000/8002 を使用中）: 全 spec 36 passed（8 skipped は `E2E_AUDIT_DIR` 未指定の視覚監査で設計どおり）を 3 回（最後は最終コードで DB を作り直して実施）。
- 一時 spec（コミットしない）で実画面を確認: チャットの候補カードからの確定（半角・全角数字。最終コードでも再確認）、業者の取引詳細で日付を重ねない表示、`/schedule` のひとこと（ZWJ 入り）が送信前整形で確定まで通り業者のチャットで「運」の確定メッセージの直後に「客」の発言として並ぶ、業者 UI で「2月30日」を提示すると「存在しない日付が含まれています…」が出る、実サーバーが候補外・日付違いを 422＋日本語 detail で返す。
- 2026-09-27 に origin/main（cab4f51。運営ログイン後の画面遷移の修正・業者チャットの空状態の修正を含む）へ rebase。コミットの変更行は rebase 前と同一（業者チャットは自動統合）。backend は先方の変更なし（日程の 2 ファイルで 170 passed）、web は tsc・eslint エラー 0・`node --test` 141 passed、E2E は DB を作り直して 36 passed（8 skipped）。
- PostgreSQL 実機での確認は未実施（Docker 停止中）。CI の backend ジョブは SQLite、pg-concurrency ジョブは日程 API を通らない。

## 既存データへの影響

- 保存済みの値は変更しない。確定済みの取引には影響なし。
- 未確定の取引に残る本対応前の提示のうち、制御文字・右から左の文字入り・33 字以上・複数日付・存在しない日付の候補は、チャットのカードから確定できない（`/schedule` からは確定可・業者の再提示で解消）。本番 DB は直接見ていないため件数は未確認（β 期間で実取引はごく少数 [推測]）。
- 本対応前の運営名義メッセージ（note 連結を含む）は本文を変えず、表示時に改行以外の制御文字を除去する。

## 載せ替え（2026-09-27・ボタン化ブランチとの統合）

ユーザー決定（選択式）「lamarr＋pensive を統合」: ボタン化（a6b81dd〜d660ac7。本番で日程の提示・確定が失敗する潜在不具合を直す 0046 を含み、先に反映される見込み）の上へ 98ec5f6 を cherry-pick し 4c7274a にした。元のブランチ claude/pensive-mestorf-cba971 は置き換え。

- 衝突（5 ファイル）: 業者チャットの候補入力・/schedule・ChatPanel はボタン化の側を採用。ボタン化が候補入力を日付＋時間帯の選択式（ラベルは `formatSlotLabel` が生成）に置き換えたため、自由入力欄向けの maxLength・送信前の制御文字除去は不要になった。propose_schedule の入力検証は、ボタン化で入った通知判定の DB 集計より前に置いた。PROJECT_STATE は両方の項目を残した。
- テキストに出ない食い違い:
  - 固定時間帯の定義はボタン化で `web/src/lib/visit-slots.ts` の `VISIT_TIME_SLOTS` に移ったため、一致ガード（`test_schedule_fixed_time_slots_matches_frontend_time_slots`）はそちらを読む。
  - 日付の読み取りが 2 実装（本対応の `slotVisitDate`＝年を無視して今年→翌年、ボタン化の `parseSlotDate`＝明記年を尊重）に分かれていたのを `parseSlotDate` に一本化した（明記年はそのまま使い、年なしは今年→翌年で実在し今日以降の年、NFKC・空白入り可）。`slotVisitDate` とそのテストは `visit-slots.test.mts` へ移設。年を無視したままだと、年入りラベルが過去日のとき翌年の visit_date を送ってしまう。
  - backend の日付照合（本対応 ③）を年入りラベルへ拡張: 明記された年も visit_date と照合し（422）、提示時に年が 2 種類ある候補・その年に実在しない日付（2027年2月29日 等）を 422。月日だけだと「2026年10月1日」の候補を visit_date=2027-10-01 で確定でき、③と同じずれが年の単位で起きる（確定 API の上限 365 日の範囲では、ラベル側の年を変える細工で起きる）。SEC-I2（年なしラベル）は変わらない。
  - 重複定数 `SCHEDULE_SLOT_MAX_LENGTH` は使われなくなったため削除（`VISIT_TIME_SLOT_MAX_LENGTH` が残る）。
  - ボタン化のテスト 2 か所が確定時間帯に表示名 "午前" を送っており許可リスト照合で 422 になったため、固定時間帯の値へ置換（本対応で既存テストに行った置換と同じ）。
- 検証: pytest 全件（載せ替え直後は上記の 9 件が失敗 → 是正）、年入りラベルのテスト 10 件を追加、web 単体 184・tsc（src・e2e）・eslint エラー 0。
