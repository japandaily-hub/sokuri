# r3 バックエンド修正差分（security/QA レビュー指摘対応）

実施日: 2026-09-04 / 対象: backend のみ（config.py / main.py / alert_middleware.py /
services/alerts.py / tests/test_alerts.py / web/ は別セッション編集中のため未接触）。

## 1. C-1（admin 奪取）+ L-1（email 正規化）

- `backend/app/api/v1/endpoints/auth.py:56-90`（`_is_listed_admin_email` 新設・
  `_promote_to_admin_if_listed`）: 比較を `user.email.strip().lower() in admin_emails`
  に統一（L-1）。
- `auth.py:150-166`（`user_signup`）: role 判定を `_is_listed_admin_email` 経由にし、
  commit 後 `logger.warning("admin role granted: email=%s via=signup user_id=%s", ...)`。
- `_promote_to_admin_if_listed` 内でも昇格時に同形式の WARNING（`via=login_promotion`）。
- signup 時の admin 付与自体はリーダー指示どおり「残す」（初回運営アカウント作成のため）。
  `notify.py` フッターの問い合わせ先は変更していない（公開情報のため対象外）。
- テスト: `tests/test_katadzuke_api.py`
  `test_login_promotes_existing_user_to_admin_when_email_listed`（caplog拡張）、
  `test_signup_grants_admin_and_logs_warning`（新規）、
  `test_promote_to_admin_if_listed_normalizes_email_case_and_whitespace`（新規・L-1単体）。
- **運用タスク（未実施・要ユーザー承認）**: 本番 ADMIN_EMAILS の実値と、各アドレスに
  対応する user 行の存在・role=admin を `GET /admin/users?q=` で1回実測すること
  （r3-review-security.md R-3。本修正では検証不能）。

## 2. H-1（/contact 乱用）

- `backend/app/api/v1/endpoints/contact.py` 全面改修:
  - レート制限スコープを `public_read` → **`case_create`** に変更
    （IP軸 max=10 / アカウント軸 max=10 / window=3600秒、両軸とも全リクエストカウント。
    config.py 既存値。新規キー追加なし）。
  - `request.state.rate_limit.hit_account(f"contact:{email.lower()}")` でメール軸を追加
    （cases.py:121-128 と同じパターン）。
  - プロセス内簡易キャップ（`_MAX_NOTIFICATIONS_PER_HOUR=30` / 1時間 sliding window、
    `deque` + `time.monotonic()`）。上限到達後は送信スキップ + WARNING ログのみ、
    依頼者には202を返し続ける。
- **採用スコープの理由**: `config.py` の `rl_*` 既定値のうち「1桁〜10件/時間」に該当し、
  かつ `hit_account` が実際に機能する（`account_rule` を持つ）のは `case_create` のみ
  （`signup` は IP軸専用で `account_rule=None` のため `hit_account` が no-op になり、
  リーダー指示の「メール軸で2軸目」を満たせない）。
- **既知の制約（R-4・解消せず）**: `case_create` の IP軸バケットキーは実際の
  `POST /cases` と文字列上の scope 名が同一のため、同一IPからの `/contact` 連投は
  実際の案件作成クォータと衝突しうる（巻き添え）。専用スコープが無いため解消不可。
  429文言も「案件の作成が集中しています」になり `/contact` の文脈とは一致しない
  （config.py 変更不可の制約下でのトレードオフ。r3-fix-backend.md に明記）。
- テスト: `tests/test_rate_limit_api.py::TestContactRateLimit`
  （IP軸10件超で429／アカウント軸10件超で429、共に隔離limiter使用）、
  `tests/test_contact.py::test_contact_process_wide_cap_skips_after_limit`（新規）。

## 3. M-1（category 検証・制御文字）

- `backend/app/schemas_katadzuke.py`: `ContactCategory = Literal["service","pricing",
  "area","privacy","trouble","partner","press","other"]`
  （`web/src/app/contact/page.tsx` の `<option value=...>` と1対1一致。フロントは
  `HTMLSelectElement.value`＝英字スラッグを送信するため、日本語ラベルは元々送られていない
  ことを確認済み）。`ContactCreateRequest.category` をこの Literal に変更。
- `name` / `message` に `field_validator` を追加し、改行(`\n`)以外の Unicode カテゴリ C*
  （C0/C1制御文字・U+202A-202E/U+2066-2069 双方向制御・ゼロ幅文字含む）を拒否。
- テスト: `tests/test_contact.py::test_contact_validation_errors_422` に
  旧日本語ラベル・未知カテゴリ・RLO混入・ゼロ幅混入の4ケースを追加、
  `test_contact_message_allows_newlines`（改行は許容されることの回帰防止）を新規追加。

## 4. M-3 + QA-H2（admin ilike エスケープ・ID検索）

- `backend/app/api/v1/endpoints/admin.py`: `_escape_ilike_value`（%/_/\\ をエスケープ）・
  `_try_parse_uuid` を新設し、以下3関数に適用。
  - `admin_list_cases`（:363-376）: `Case.id` のID条件を `cast(...).ilike前方一致` から
    `uuid.UUID` パース成功時のみ `Case.id == uuid` に変更。email ilike は escape 付き。
  - `admin_list_transactions`（:451-472）: 同様に `Transaction.id` / `Transaction.case_id`
    を厳密一致に変更。email / company_name ilike は escape 付き。
  - `admin_list_users`（:533-547）: QA H-2対応でID完全一致条件を新規追加
    （従来 email/name のみで ID 検索が存在せず、web の CopyableId 経由の検索が0件だった）。
    email/name ilike は escape 付き。
  - 未使用になった `cast, String` の import を削除（`text` は元々未使用・本修正外のため未変更）。
- 挙動変更点（明記）: ID検索は「前方一致」から「UUID厳密一致」に変更（全表スキャン回避・
  リーダー指示どおり）。前方一致の利便性は失われるが、貼り付け検索（CopyableIdは
  常に完全なUUIDをコピーする）には影響しない。
- テスト: `tests/test_admin_user_controls.py`
  `test_list_users_search_by_id_exact_match`（H-2）、
  `test_list_users_search_escapes_ilike_wildcards`（M-3、`_` リテラル化の対照実験）。

## 5. M-4（analyze 503 固定文言）

- `backend/app/api/v1/endpoints/analyze.py`: `GenAIAPIError` 捕捉時に
  `logger.exception(...)` を追加し、`detail` を固定文言
  「AI サービスが一時的に利用できません。時間をおいて再度お試しください。」に変更
  （`_AI_SERVICE_UNAVAILABLE_DETAIL` 定数）。
- テスト: `tests/test_vision_retry.py::test_retry_exhaustion_maps_to_503_via_analyze_endpoint`
  のアサーションを固定文言の完全一致に更新。

## 6. M-5（analyze 外部URL拒否）

- `backend/app/schemas.py`: `AnalyzeRequest.base_image` に `field_validator` を追加し、
  `http://` / `https://` で始まる値を422で拒否（大文字小文字を問わない）。
  `vision.py` は無変更（案件フローが利用するため対象外・リーダー指示どおり）。
  `AnalyzeRequest` は `/analyze` エンドポイント専用（他箇所での利用なし・grep確認済み）
  のため schemas.py 側の Pydantic バリデータとして実装（endpoint 側の手動チェックより
  契約として一元化できるため）。
- テスト: `tests/test_api.py::test_analyze_rejects_external_url_422`
  （https/http/大文字小文字混在の3パターン、`analyze_image` 未呼び出しも確認）。

## 7. L-2（停止403の dict 化）

- `backend/app/api/deps.py`: `SUSPENDED_ACCOUNT_DETAIL = {"code": "account_suspended",
  "message": "..."}` を新設し `assert_user_not_suspended` の `detail` に使用。
- `backend/app/api/v1/endpoints/auth.py`: `user_login` / `line_exchange` の重複していた
  手動 raise（旧: 文字列 detail を3箇所に個別記述）を `assert_user_not_suspended(user)`
  呼び出しに統一（DRY。既存 import 済みの関数を再利用）。
- テスト: `tests/test_admin_user_controls.py::test_suspend_and_unsuspend_user` の
  アサーションを `r.json()["detail"]["code"] == "account_suspended"` /
  `"利用停止中" in r.json()["detail"]["message"]` に更新。

## 8. QA未解決2（停止時の open_case_count）

- `backend/app/schemas_katadzuke.py`: `UserSuspendResponse.open_case_count: int` 追加。
- `backend/app/api/v1/endpoints/admin.py::suspend_user`: 停止/解除いずれの操作でも
  対象ユーザーの `Case.status in ("open","bidding")` 件数を集計して返す
  （案件・成約側の状態には一切干渉しない＝リーダー指示どおり副作用は変更しない）。
- テスト: `tests/test_admin_user_controls.py::test_suspend_response_includes_open_case_count`
  （open/bidding は数え、closed は数えないこと）、
  既存 `test_suspend_and_unsuspend_user` にも `open_case_count == 0` の確認を追加。

---

結論3行・pytest結果・変更ファイル一覧・最終サマリは戻り値（会話応答）側に記載。
