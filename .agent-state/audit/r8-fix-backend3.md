# r8 High是正（backend3）

結論: H-1（退会×落札の競合直列化）・H-4（退会の再認証＋レート制限実効化）・未解決5（admin一覧の退会除外・verify/suspend 409）を実装。未解決4は既にGET /vendorsがdeleted_at IS NULLで全除外済みと確認、コード変更なし。
結論: H-1は「pending入札reject化→flush→進行中取引数再判定→非0ならrollback+409」の順序化＋select_bid側にoperator.deleted_at 409ガードを追加する多層防御。SQLiteはFOR UPDATE no-opのため実競合はテスト不可（r8-review既知の限界）。
結論: DELETE /operator/meはweb側が既に403/409/429契約で実装済み（katadzuke-api.ts:427-429, operator/profile/page.tsx:174-181）だったため、既存コードベースの400慣例より当該フロント契約を優先し403を採用（この非対称はレビューで要確認）。

pytest結果: 814 passed, 843 warnings（183.94s）。既存811 + 新規3件（withdraw誤パスワード403・select_bid deleted_at 409・admin include_deleted）全て緑。

変更ファイル:
- backend/app/schemas_katadzuke.py（OperatorAccountDeleteRequest追加）
- backend/app/api/v1/endpoints/operator_profile.py（DELETE /operator/me: パスワード必須化・レート制限実効化・reject→再判定の順序化）
- backend/app/api/v1/endpoints/bids.py（select_bidにdeleted_at 409ガード、_bid_outでoperator_suspended旗を退会済みにも流用）
- backend/app/api/v1/endpoints/admin.py（GET /admin/operatorsにinclude_deleted、verify/suspendでdeleted_at非null時409）
- backend/tests/test_r8_abnormal_guards.py・tests/test_admin_operator_controls.py（回帰テスト追加・既存DELETE呼び出しをbody付きに修正）

DELETE /operator/me 最終契約: body必須 {"password": str}。204成功／403パスワード不一致／409進行中取引あり／429連打（RateLimitGuard("account_delete")のaccount軸をctx.check_account/record_failure/reset_accountで実効化）。LINE専用（password_hash=None）は照合スキップ（users.py同型）。

未対応: 未解決6（cancel_count自動停止・運用しきい値）は経営判断待ちのため未着手。M-1〜M-6・L-1〜L-5（web側/文言/監査主体等）は本ミッション対象外（H是正のみ指示）。

サマリ: ✅ H-1・H-4・未解決5是正、未解決4確認のみ・pytest 814 passed 全緑
