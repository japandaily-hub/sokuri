# R3 セキュリティ再レビュー指摘 修正（backend3）

実施日: 2026-09-04

## 対応した項目

1. **[Critical] admin昇格の一本化**: `_admin_role_available(session)`（DBに有効な
   role=admin・deleted_at IS NULL のユーザーが0人か判定）を新設し、signup側の
   初回ブートストラップ判定と `_promote_to_admin_if_listed(session, user)`（login/
   LINE exchange昇格）の両方がこの1関数を参照するよう統合。既存adminが居る間は
   login昇格をブロックし、代わりに warning アラート（「ADMIN_EMAILS記載アドレス
   がadmin不在条件を満たさずログイン」）を発火。昇格成功時のcritical通知は
   commit成功後に移動（commit失敗時の偽通知を防止）。
2. **2人目以降のadmin追加/削除**: `POST /admin/users/{id}/promote` /
   `POST /admin/users/{id}/demote` を新設（admin.py）。
3. **業者ログイン停止403**: `operator_login` の文字列detailを
   `assert_operator_not_suspended(operator)` 呼び出しに置換（deps.pyのdict
   detailに一本化）。
4. **/contactキャップ**: ブロッキング上限を300req/hourに引き上げ、旧30は
   ブロックしないアラート閾値（初回超過のみwarning）に降格。503にRetry-Afterヘッダ
   （秒）付与。予約（_reserve_notification_slot）はIP軸(Depends)・アカウント軸
   (hit_account)通過後に実行するよう順序変更。
5. **summary.py https フォールバック**: `photo_url_for_ai` のhttps分岐を、
   到達時にlogger.warningを出しNoneを返す（AI解析スキップ・案件作成は継続）形に変更。

## pytest 結果

`.venv\Scripts\python.exe -m pytest -q` → **714 passed**, 0 failed, 657 warnings（178.41s）。
（706→714、新規/改修テスト8件追加、全て緑）

## 変更ファイル

- app/api/v1/endpoints/auth.py（admin判定一本化・operator/login 403置換）
- app/api/v1/endpoints/admin.py（promote/demote新設・alerts/schema import追加）
- app/api/v1/endpoints/contact.py（キャップ300/アラート閾値30/Retry-After/順序変更）
- app/schemas_katadzuke.py（AdminUserRoleResponse追加）
- app/services/summary.py（photo_url_for_ai https分岐修正）
- tests/test_katadzuke_api.py, tests/test_admin_user_controls.py,
  tests/test_contact.py, tests/test_summary.py

## promote / demote の契約

- `POST /admin/users/{user_id}/promote`（`get_current_admin`必須）
  - 前提: 対象が存在・`deleted_at IS NULL`・`is_suspended=False`・`role=="user"`
  - 自己指定 409／404（存在しない）／409（停止中）／409（既にuser以外）
  - 成功: `{"id": <uuid>, "role": "admin"}`、alerts critical + logger.warning
- `POST /admin/users/{user_id}/demote`（`get_current_admin`必須）
  - 前提: 対象が存在・`deleted_at IS NULL`・`role=="admin"`・自分以外にも
    有効なadminが1人以上残ること
  - 自己指定409／404／409（role!=admin）／409（最後の1人）
  - 成功: `{"id": <uuid>, "role": "user"}`、alerts critical + logger.warning

## 未対応

- なし（指示の1〜5、テスト観点6項目すべて対応・回帰テスト追加）

## 末尾サマリ

✅ Critical1・Medium3すべて修正・回帰テスト追加・pytest 714 passed（0 failed）。
config.py/main.py/alert_middleware.py/services/alerts.py/tests/test_alerts.py/web/ は無編集。
