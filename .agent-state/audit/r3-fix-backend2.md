# R3 セキュリティ再レビュー指摘 修正（backend2）

実施日: 2026-09-04

## 対応した項目

1. **N-1（Critical・admin奪取）**: `auth.py` の `user_signup` で admin 付与を
   「DBに role=admin が1人も存在しない場合のみ」に限定（初回ブートストラップ専用）。
   signup 付与・ログイン昇格（`_promote_to_admin_if_listed`）の両方で
   `alerts.send_alert(severity="critical")` を発火（WARNING ログに追加）。
2. **N-2（High）**: `rate_limit_deps.py` に scope="contact" を新設（数値ルールは
   case_create流用・count_all=True）し、`contact.py` を `RateLimitGuard("contact")`
   に変更。IP軸バケットが POST /cases と分離された。`_SCOPE_MESSAGES["contact"]` 追加。
3. **N-4（High）**: `contact.py` のプロセス内キャップを「送信通数」→「リクエスト数」
   （30件/時）に変更。超過時は202ではなく503（`katazuke.info@gmail.com`への直接連絡を案内）。
   最初の超過検知時に alerts.send_alert(severity="warning") を1回発火。
   `tests/test_contact.py` / `tests/test_rate_limit_api.py` に autouse resetフィクスチャ追加。
4. **N-6**: `deps.py` の `assert_operator_not_suspended` を dict detail（依頼者側と
   `SUSPENDED_ACCOUNT_DETAIL` を共用）に統一。`get_verified_operator` 内の重複インライン
   実装も同関数呼び出しに統合。
5. **N-7（SSRFシンク）**: 呼び出し元を全数grepし、案件フロー（summary.py経由）は常に
   base64/data:URLのみ渡す設計（Photo.urlは常に相対パス）と確認。`vision.py`の
   `analyze_image` からhttps URL受理を全面撤廃（ValueErrorで拒否）。将来R2/S3移行時は
   allowlistを明示追加してから再有効化する旨コメントで明記。
6. **N-9**: `schemas_katadzuke.py` の制御文字validatorを `{Cc,Cf,Co,Cs}` に限定、
   Cn（未割り当て）を偽陽性源として許容。
7. **QA M2/M3/M5**: admin一覧3本（cases/transactions/users）にid tie-breaker追加。
   `GET /admin/users` に `include_deleted`（既定false）を追加し退会済みを除外。
   `notify.py` の問い合わせメールをContactCategory→日本語ラベル変換（件名のhtml.escape誤用も是正）。

## pytest 結果

`.venv\Scripts\python.exe -m pytest -q` → **706 passed**, 0 failed, 649 warnings（219.78s）。
（修正前ベースライン696 passed → 新規テスト10件追加、全て緑）

## 変更ファイル

- app/api/v1/endpoints/auth.py
- app/api/rate_limit_deps.py
- app/api/v1/endpoints/contact.py
- app/api/deps.py
- app/services/vision.py
- app/schemas_katadzuke.py
- app/api/v1/endpoints/admin.py
- app/services/notify.py
- tests/test_contact.py, tests/test_rate_limit_api.py, tests/test_katadzuke_api.py,
  tests/test_line_integration.py, tests/test_admin_user_controls.py, tests/test_vision_retry.py

## alerts.py で呼んだ関数（既存公開APIをそのまま利用・alerts.py自体は未編集）

`alerts.fire_and_forget(alerts.send_alert(title, body, severity=..., key=...))`
（auth.pyのadmin付与2箇所、contact.pyのキャップ超過1箇所）

## 未対応（対象外・TODO化）

- SEC M-2（停止操作の監査ログテーブル）: リーダー指示により今回対象外。
- R-M1/R-M5/URISK系（web側修正が必要な項目）: web/ は編集対象外のため未着手。

## 末尾サマリ

✅ 指摘7項目すべて実装・各項目に回帰テストを追加・pytest 706 passed（0 failed）。
config.py/main.py/alert_middleware.py/services/alerts.py/tests/test_alerts.py/web/ は無編集。
