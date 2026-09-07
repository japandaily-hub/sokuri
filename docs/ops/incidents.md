# 障害台帳と再発防止の仕組み（学習する運用）

更新: 2026-09-07。**障害対応は「直った」では終わらない。この台帳に1行足し、教訓をガード（自動検査）に変えて初めて完了。**
Claude / Codex はセッション開始時に本ファイルの「原則」と「未収束の教訓」を読む（`AGENTS.md` 参照）。

## 原則（すべての障害対応の完了条件）

1. **失敗を通知した経路には必ず復旧も届く。** 運営は「復旧の連絡が来ない＝未解決」と扱う。復旧通知は障害の通知と同じ経路（LINE＋メール）へ、`[RECOVERED]` を付けて1回。手動対応で直した場合も `scripts/uptime_check.py` の `notify()` で解消を送る（`.env.alerts` を source して実行）。
2. **宣言と実態は機械で突き合わせる。** 人がダッシュボードで変えた値（プラン・名前・環境変数）は設定ファイルとズレる。ズレは定期検査で検出し、通知する（人の記憶に頼らない）。
3. **教訓はテストかワークフローにする。** 「注意する」「覚えておく」は再発防止ではない。同じ失敗をしたら CI が赤くなる形にする（例: `backend/tests/test_alert_pairing.py`・`test_render_drift.py`）。
4. **台帳は1障害1行以上。** 症状・根本原因・対処・再発防止ガード・状態を書く。「原因不明のまま復旧」も状態 `open` として残す。

## 対応手順（チェックリスト）

- [ ] 症状と通知元（Gmail / LINE / GitHub / Render）を特定し、実ログ・API で裏取りする（メール本文だけで判断しない）
- [ ] 根本原因を1文で言えるまで掘る（「再デプロイしたら直った」は原因ではない）
- [ ] 修正を適用し、本番で効いたことをログ／API で確認（`/health` の commit、Blueprint の status など）
- [ ] **復旧通知を送る**（自動の仕組みが無い経路なら手動で `notify()`）
- [ ] 本台帳に追記（下表）
- [ ] 再発防止ガードを追加（テスト／ワークフロー／drift 検査）。既存ガードで拾えるはずだった場合は、なぜ拾えなかったかを台帳に書く
- [ ] 関連ドキュメント（`docs/ops/admin-operations.md`・`render.yaml` のコメント等）を実態に合わせる

## 再発防止ガード一覧（機械が守っているもの）

| ガード | 何を守るか | 実体 | 動くタイミング |
|---|---|---|---|
| Render drift 検査 | render.yaml と Render 実態（DB plan/名前/region・サービス設定・env キー）のズレ | `scripts/render_drift_check.py` + `render-sync.yml` | render.yaml の push 後・毎週月曜・手動 |
| Render 同期の失敗/復旧 | Blueprint 同期 error → [FAILED]、success に戻る → [RECOVERED] | `scripts/render_sync_check.py` + `render-sync.yml` | render.yaml の push 後 |
| CI の失敗/復旧 | main の CI 失敗 → [FAILED]、直前失敗→今回成功 → [RECOVERED] | `scripts/run_transition_notify.py` + `ci.yml` の `notify` | push (main) ごと |
| Ops cron の失敗/復旧 | 日次/毎時ジョブの失敗 → 通知、正常に戻る → [RECOVERED]（到達前失敗も状態保存） | `scripts/ops_jobs.py` `_track_recovery` + `ops-cron.yml` `notify-failure` | 毎時 / 日次 |
| 外形監視の down/up | /health /readyz /frontend の障害と復旧、degraded_config | `scripts/uptime_check.py` + `uptime-alert.yml` | 5分毎 |
| 通知の対ガード（メタ） | 失敗を通知する経路・スクリプトに復旧側が無ければ CI が落ちる | `backend/tests/test_alert_pairing.py` | pytest（CI） |
| 判定ロジックのテスト | 失敗/復旧/正常/cancelled の判定と drift 比較 | `backend/tests/test_alert_transitions.py`・`test_render_drift.py` | pytest（CI） |
| Ops cron 欠測検知 | 毎時ジョブが24時間で下限回数回っていない | `ops_jobs.py` daily ⑤ | 日次 |

## 台帳

| ID | 日付 | 通知元 / 症状 | 根本原因 | 対処 | 再発防止ガード | 状態 |
|---|---|---|---|---|---|---|
| INC-2026-09-07-1 | 2026-09-01〜09-07 | Render メール「Blueprint Sync Failed for sokuri」（9/1・9/6） | 本番 DB を 9/1 に dashboard で有料 basic_256mb・実名 `sokuri_jwd3` で作り直したのに、render.yaml が `plan: free` / `databaseName: sokuri` のまま。Render は有料→free の変更と DB 名の変更を受け付けず同期が error。デプロイは autoDeploy で通るため6日間気づかず | render.yaml を実態に追従（642e6d3）→ 同期 success・in_sync | Render drift 検査（週次＋push 後）／同期の失敗・復旧通知 | closed |
| INC-2026-09-07-2 | 2026-09-04〜09-07 | Gmail に失敗通知（Render 同期・CI・Ops cron）は届くが、解消しても復旧の連絡が来ない | 失敗の通知元（Render・GitHub）が復旧を送らない設計で、こちら側にも対になる復旧通知が無かった。Ops cron の復旧通知は 9/6 の失敗より後に実装 | 3件の解消を手動で notify()（9/7 15:40 JST）。CI notify ジョブ・render-sync.yml・Ops cron 到達前失敗の状態保存を実装（9053474） | 通知の対ガード（`test_alert_pairing.py`）／判定テスト | closed |
| INC-2026-09-06-1 | 2026-09-06 | GitHub「Run failed: Ops cron」（5cb0dd5・d698de6・手動実行） | 初期設定（ops_bootstrap）の途中で手動実行したため、OPS_JOB_TOKEN 未反映の 403 → 続いて ADMIN_EMAILS の未登録エイリアスを棚卸しが検出（設計どおりの検出） | エイリアスを ADMIN_EMAILS から除外（c5df8ba）。以後の定期実行は success | 棚卸しは正常動作。初期設定中の手動実行は「Render 反映→GitHub Secret→実証」の順を `ops_bootstrap.py` が担う（手順書 `admin-operations.md`） | closed |
| INC-2026-09-05-1 | 2026-09-04〜09-05 | GitHub「Run failed: CI」（0b930b4・552500f・c69c927・a09cb5e・3444881） | Syntax guard（null-byte スキャン）と backend テストの失敗。後続 push で是正 | 後続コミットで是正。9/5 22:26 JST 以降 success | CI の失敗/復旧通知（今後は復旧が届く） | closed |
| INC-2026-07-A | 2026-07 | 本番全断（alembic） | `alembic_version` VARCHAR(32) に 46 字のリビジョン ID が入らず毎回ロールバック | env.py で拡幅（f6dd33f） | `/readyz` の alembic_version＝expected_head 照合（外形監視） | closed |

## 未収束の教訓（ガード化できていないもの）

- Render の Blueprint `envVars` は既存サービスへ同期されない（2026-07-18 実測）。本番で効かせたい既定値は `backend/start.sh` の export か dashboard。drift 検査はキーの有無を見るが、値の一致は見ない（秘密を扱わないため）。値のズレは `/readyz` の `config` / `degraded_config` で間接的に検知する。
- Render 同期エラーの本文は API に出ない。通知には dashboard の Blueprint ページを添える。
