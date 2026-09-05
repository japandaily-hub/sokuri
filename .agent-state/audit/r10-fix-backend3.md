# r10-review M1/M6 修正（backend3）

- 対象: r10-review.md の M1（contact_messages 削除API・退会時匿名化）／M6（pending_with_license の is_suspended 除外）
- M1: `DELETE /admin/contacts/{id}`（get_current_admin・204・監査ログ相当のlogger.info）を新規追加。`DELETE /users/me` に、同一メール（大小無視）の contact_messages を name/email/message 匿名化する処理を追加。
- M6: admin.py の counts.pending_with_license 集計 CASE 式に `Operator.is_suspended.is_(False)` を追加し、停止中 pending を除外。
- テスト: test_r10_backend_fixes.py に4件追加（admin削除成功/404、admin以外403・未認証401、退会時匿名化、M6の停止除外）。

pytest: 855 passed（追加前851→追加4件で855）。0 failed。

## 変更ファイル
- backend/app/api/v1/endpoints/admin.py
- backend/app/api/v1/endpoints/users.py
- backend/tests/test_r10_backend_fixes.py
