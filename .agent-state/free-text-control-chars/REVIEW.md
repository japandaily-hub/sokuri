# 自由記述欄の制御文字検証と NUL・孤立サロゲートの一括拒否（2026-09-27）

依頼: 通常チャット `POST /api/v1/transactions/{id}/messages` の本文（MessageCreateRequest.body）に制御文字の検証が無い
（2026-09-26 の日程 API 入力検証のセキュリティレビューで範囲外として見つかった Low）。他の自由記述欄も同様か確認して直す。

## 1. 修正前の実測

### SQLite（pytest と同じ構成・実アプリ create_app＝本番と同じ 422 ハンドラ）
- RLO（U+202E）・NUL・タブは、チャット本文・日程のひとこと・候補日・減額理由・取引キャンセル理由・運営の強制終了理由・
  案件の番地/市区町村・出品取り下げ理由・入札メッセージ（新規/引き上げ）・業者の自己紹介/対応時間・依頼者の氏名で 201/200 のまま保存。
- 孤立サロゲート（JSON の `\ud800` エスケープ）: 上限（max_length/min_length）付きの str は Pydantic が UTF-8 化するため
  `string_unicode`（英語文言）で 422。**制約なしの `CaseCreateRequest.address_detail` だけ素通りし DB 書き込みで 500
  ＋ ServerErrorAlertMiddleware の Critical アラート**。
- 既に守られていた欄: お問い合わせ（`_reject_non_newline_control_chars` で Cc/Cf/Co/Cs を 422）、品名・商品説明・口コミ・
  口コミの削除理由・業者の対応エリア（NFKC＋C* 全除去。ZWJ も消えるので家族絵文字は分解される＝既存挙動）。
- web: チャット入力は依頼者・業者とも `<input type="text">`。422 の Pydantic 配列 detail は画面に理由が出ない（「送信に失敗しました」等の汎用文言）。
  吹き出しは `white-space: pre-wrap`・React のテキスト描画（XSS ではない）。LINE の新着通知に本文は載らない。

### 実 PostgreSQL 16.2（Docker Desktop が停止中のため pgserver 0.1.4 の wheel から PostgreSQL 本体だけを作業フォルダに展開・
initdb〔UTF8〕・127.0.0.1:55433。実マイグレーション head=0045。修正前のコードの API を :8011 で起動）
- **NUL で 500**: チャット本文・減額理由・取引キャンセル理由・入札メッセージ・業者の自己紹介・案件の番地・**会員登録の氏名（認証不要）**。
  API ログ: `asyncpg.exceptions.CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8": 0x00`、
  そのたびに Critical「未処理の例外が発生しました」。お問い合わせだけ 422。
- **孤立サロゲートで 500**: 案件の番地（asyncpg `DataError: invalid input for query argument $7 ... surrogates not allowed`）。他は 422（string_unicode）。
- RLO・タブ・ZWJ 絵文字は 201/200 で保存（RLO 入りの保存済みメッセージ 1 件を DB で確認）。
- （範囲外の再確認）日程の提示・確定は内容に関係なく 500: `StringDataRightTruncationError: value too long for type character varying(16)`
  ＝ messages.kind の VARCHAR(16) 超過。別ブランチ（成約後フロー・0046・未 push）で修正予定の既知不具合。

## 2. ユーザーの決定（2026-09-27・選択式）
1. 拒否基準: 双方向制御文字（Bidi_Control 12字＝U+061C・U+200E/200F・U+202A–202E・U+2066–2069）＋改行以外の C0/C1 制御文字
   （タブ・CR・NUL を含む）＋孤立サロゲートを 422。ZWJ・旗のタグ文字・ゼロ幅スペース等の他の書式文字と私用領域は許可。
2. 適用範囲: 相手・公開画面に出る自由記述欄（チャット本文・入札メッセージ・減額理由・取引キャンセル理由・出品取り下げ理由・
   業者の自己紹介/対応時間・案件の番地/市区町村/住居タイプ/間取り）に 1 の基準＋すべての JSON 入力で NUL・孤立サロゲートを一括 422。
3. 実 PG 検証: pgserver で一時 PG（使い捨て・プロジェクトの venv やシステムには入れない）。

## 3. 設計（architect → リーダー確定。仕様書は作業フォルダの SPEC_free_text_guard.md）
- (a) `app/services/text_sanitize.py` に整数コードポイント範囲から組み立てた文字クラスの正規表現（C 実装・O(n)）と
  `reject_disallowed_display_chars`。12 欄に field_validator（mode="after"）。文言「{項目名}に制御文字を含めることはできません。」。
- (b) `app/api/request_char_guard.py` の依存を `api_router` のコンストラクタで全ルートの先頭依存にする。FastAPI が JSON と解釈済みのボディ
  （Starlette のキャッシュを再利用＝再パースなし）とクエリを再帰なしで走査し、NUL・孤立サロゲートを `disallowed_character` の 422
  （input・ctx なし・loc は U+FFFD で無害化＝既定ハンドラでも本番ハンドラでも 500 にならない）。body_field の無いルート（写真・許可証・本人確認書類の
  アップロード）と Form のルートはボディを読まない。
- web: `web/src/lib/text-guard.ts` の純関数で、サーバーが拒否する文字を送信前に整形（CRLF/CR→LF・タブ→空白・他は除去）。
  katadzuke-api.ts の送信 8 関数に適用。整形の結果が空・最小文字数未満なら理由付きの KdzApiError(422)。
- S9（`scripts/pg_concurrency_check.py`）: 実 PG で陽性対照（PG 自体が NUL・孤立サロゲートを拒否すること、許可文字が完全一致で保存されること）
  ＋拒否 16 経路が 422 で 500 にならず何も保存されないこと。
- **リーダー修正（architect 案から）**
  - web の判定に正規表現の Unicode プロパティエスケープ（`\p{...}`・u フラグ）を使わず、UTF-16 コード単位の 1 回走査にした。
    main の web は `\p{` を使っておらず、Next 15 の既定の対象ブラウザ（browserslist 未設定＝Firefox 67 等）は未対応で、
    katadzuke-api.ts が import するため API クライアントごと読み込めなくなる恐れがあるため。
  - 送信 8 関数の `export function ...(` 宣言行は変えない（async 化しない）。別ブランチ（成約後フロー）が `cancelTransaction` の直前に
    関数を挿入しており、宣言行を変えると隣接変更でマージ衝突するため。`withTextGuard` で包んで同期 throw を reject にする。
  - クエリ文字列の NUL も一括拒否に含めた（ユーザー方針「JSON 入力」からの拡張）。運営の検索欄 q の NUL は ILIKE のバインド値として PG に届き
    500＋Critical になるため、同じ根本原因を同じ場所で塞ぐ。外す場合はガードのクエリ部分を削るだけ。
- 衝突回避: 未マージの 98ec5f6（日程 API 検証）が触る日程調整節・お問い合わせ節・categories.ts・吹き出し描画と、
  成約後フロー（0046）の挿入箇所には触れない。

## 4. 実装・検証
- コミット: fa691c5（実装）→ 次のコミット（レビュー対応）。実装は backend／frontend の担当エージェントが並行（同じファイルを触らない分担）。
- 変更: backend `app/api/request_char_guard.py`（新規）・`app/api/v1/router.py`・`app/services/text_sanitize.py`・`app/schemas_katadzuke.py`、
  テスト `tests/test_request_char_guard.py`（新規 72 件）・`tests/test_display_text_guard.py`（新規 176 件）・`tests/test_case_items.py`（品名の NUL は
  全体の防御で 422 になるため除去の確認を BEL に変更・以前から生で入っていた RLO を chr() に置換）、`scripts/pg_concurrency_check.py`（S9）、
  `docs/ops/e2e.md`（S9）、web `src/lib/text-guard.ts`（新規）・`src/lib/text-guard.test.mts`（新規 57 件）・`src/lib/katadzuke-api.ts`（送信 8 関数）。
- pytest 全件: fa691c5 時点 1685 passed／レビュー対応後（最終）**1709 passed**（9分4秒）。新規テストは約 253 件（ガード 77・表示欄 176 ほか）。
- web: 単体 159 件全 pass（新規 57）・`tsc --noEmit`・eslint エラー 0。next build・E2E は未実施（web の変更は API クライアント内の送信前整形だけで、画面ファイルは不変）。
- 実 PostgreSQL 16.2（上記の使い捨て PG・実マイグレーション head=0045）: **S1〜S9 全 PASS**（fa691c5 とレビュー対応後の 2 回）。
  S9 の陽性対照で PG 自体が NUL（CharacterNotInRepertoireError）と孤立サロゲート（DataError）を拒否することを確認。
  2 回とも API ログに 500・未処理例外 0 件。
- 修正前後の比較（実 PG・同じ再現スクリプト。前＝修正前 → 後）:

  | 欄 | NUL | 孤立サロゲート | RLO・タブ | ZWJ 絵文字 |
  | --- | --- | --- | --- | --- |
  | チャット本文・減額理由・入札メッセージ・自己紹介・取引キャンセル理由 | 500 → 422（全体） | 422（英語）→ 422（全体） | 201/200 → 422（欄の検証） | 201/200 のまま |
  | 案件の番地 | 500 → 422（全体） | **500** → 422（全体） | 201 → 422（欄の検証） | 201 のまま |
  | 会員登録の氏名（認証不要・表示用の検証の対象外） | 500 → 422（全体） | 422（英語）→ 422（全体） | 201 のまま（範囲外） | 201 のまま |
  | お問い合わせ（既存の検証あり） | 422 → 422（全体） | 422 → 422（全体） | 422 のまま | 422 のまま（既存の Cf 拒否） |
  | 日程の提示・確定（範囲外の既知不具合で常に 500） | 500 → 422（全体） | 422 → 422（全体） | 500 のまま | 500 のまま |

- レビュー対応の確認（実 PG）: Content-Type 無し＋NUL → 422・未作成／余分なキーに 10,001 要素＋NUL → 413・未作成／
  上限未満（9,994 要素）の正常な登録 → 201／パスの `%00` → 422（loc `["path","case_id"]`）／クエリのキーの NUL → 422／通常の日本語クエリ → 200。
- 変更ファイルの不可視文字（Cf・Co・Cs・改行とタブ以外の Cc・U+00A0）: 全ファイル 0 件。
- 別セッションとの調整: 「業者申込のメール送信に全体上限を設ける」セッションが schemas の業者事前申込節に
  `_reject_single_line_control_chars` を追加する（98ec5f6 の `_reject_control_chars(allow_newline=False)` と同じ判定。両方が main に入った時点で寄せて消せる形）。
  こちらの全体の防御が先に効くため、あちらの HTTP テストは NUL の msg・type を検査しない形にしてもらった。

## 5. レビュー
- security／QA（実装後・並列）: **Critical/High 0**。コード中の「security review B1」等はこの表の番号。
  - F1（QA・Medium）: web の最小文字数判定がタブ・改行だけの入力を見逃す → 整形後を trim したコードポイント数で常に判定
    （trim 後 ≦ trim 前なので、web が通した入力は backend の min_length も必ず満たす）。
  - B6（QA・Low／Info）: クエリのキーの NUL のテスト追加、テスト名と説明の食い違いを修正。
  - B1（security 指摘1・Low）: Content-Type 無しのボディを FastAPI が JSON として読む設定・版ではガードを迂回できた
    → Content-Type 無しも JSON として検査（読めない本文は素通しにして既存の 422 に任せる）。
  - B2（security 指摘2・Low）: 認証前の巨大 JSON の走査で処理時間が延びる → 走査ノード数の上限 10,000
    （正規の最大は案件作成の 1,661）、超過は 413。打ち切って素通しにすると迂回になるため必ず拒否（fail-closed）。
  - B3（security 指摘4・Info）: パスパラメータも検査（Starlette は型ヒントに関係なく path_params を str で持つため、実質すべてのパスパラメータが対象）。
  - B4（security 指摘5・Info）: ログに生の URL パスを出さない、拒否件数のプロセス内累計を添える。
  - B5: 根拠コメントの言い過ぎ（見た目の偽装は Bidi_Control に限られる）と docstring の不正確さを訂正。
  - security 指摘3（AI の解析結果を保存する前の無害化）・指摘6（既存コードに生のまま残る不可視文字）→ 別タスク（6 節）。
  - security 指摘7（公開リポジトリ）→ 本台帳には未修正の経路の再現手順を書かない。
- レビュー対応後の再確認（security・対応差分のみ）: **Critical/High 0**（Low 1・Info 5）。うち次を追加で対応: Form ルートのフォーム値も検査（将来 Form を追加しても素通りしない。
  Starlette が解析済みのフォームを保持するため読み直しなし）／Content-Type 無しでの MemoryError を 413（fail-closed）／
  テスト説明と上限根拠の訂正（受理される正規の最大は 581 ノード・単純な積の上界は 1,661）。残り（本文サイズの上限・依存版の固定・表示側の隔離）は 6 節。
- 最終確認（実 PG・最終コード）: S1〜S9 全 PASS・API ログの 500 と未処理例外 0 件、レビュー対応の確認 6/6、web 159 件・tsc・eslint 緑、不可視文字 0 件。

## 6. 残課題（別タスク）
- 表示側での双方向の隔離（利用者の文章を `<bdi>`／`unicode-bidi: isolate`＋`dir="auto"` で包む）。右から左に書く文字そのものによる
  数字の並び替えと、保存済みの RLO 入りデータ（本対応前に保存されたもの）の両方に効く。
- タグ文字を国旗の並びの中だけで許可する／1 行の欄（市区町村・住居タイプ・間取り・対応時間）で改行・行区切りも拒否する。
- 今回の 12 欄以外で相手や公開画面に出る欄（業者登録の会社名など）の表示用検証。
- AI の解析結果を保存する前の無害化（案件側は除去済み。旧来の解析 API の経路）。
- お問い合わせ・日程のひとこと（98ec5f6）の Cf 全拒否をチャット本文の基準に揃えるか（ZWJ 絵文字が理由の出ない 422 になる）。
- 既存のコード・テストに生のまま残る不可視文字（web の categories.ts・test_contact.py・test_message_guard.py）を数値表記へ。
- 案件の番地の長さ上限・アプリ層のリクエストボディ上限・pyproject の FastAPI 下限（ロックファイル無し）の見直し。
- 減額理由の backend の min_length は空白も数える（空白だけの 10 文字は backend では通る。画面側で弾いている）。
