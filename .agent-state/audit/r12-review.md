# r12 統合レビュー（2026-09-06・opus・レビュアーは Write 不可のためリーダー転記）

総合判定: 条件付き不合格（Critical 0 / High 3 / Medium 8 / Low 5）。決定1・2・4 は成立、不合格理由は決定3（リマインド）のみ。
実測: pytest 864 / tsc 0 / eslint 0 / playwright --list 30 / alembic 単一ヘッド 0033（静的）。

## High
- H-1 0033 が既存行のマーカーを NULL のまま追加し、抽出に窓も LIMIT も無く、起動直後に1周走る → デプロイ直後に過去の該当全件へ一斉通知。修正: 0033 で既存行を既送信扱いに埋める＋窓（14日）と limit(200)。
- H-2 二重送信防止が同時実行に対して不成立（SELECT→dispatch→末尾 commit・行ロック無し）。修正: UPDATE … RETURNING で先に claim → commit → 通知（または FOR UPDATE SKIP LOCKED）。
- H-3 依頼者向けリマインドのリンクが `/transactions/{id}`（web に存在しない）→ 404。修正: `/chat/{id}`。
## Medium
- M-1 `limited` の閲覧可否が backend（可）と web（不可扱い）で矛盾。M-2 rejected に「審査中」表示。M-3 403 の吸収が profile 取得成功に依存。M-4 operator/chat の手数料予定額ラベルが税別未統一。M-5 通知を commit 前に送る／外部 HTTP をトランザクション内で待つ。M-6 REMINDER_INTERVAL_SECONDS に下限なし。M-7 運用文書に新 API・env・キルスイッチ未記載。M-8 TODO.md の法務前提（最高入札額の開示）が陳腐化。
## Low
- L-1 未承認業者トークンでの /files が 403/200 でオラクル化。L-2 alerts.fire_and_forget の Task 参照（既知）。L-3 pending+visit_date 経路と JST 境界のテスト無し。L-4 E2E に決定1・2 の回帰ゼロ。L-5 コールドスタート毎に1周（H-1 未修正だと被害最大化）。
## 未解決リスク
/files は無認証 capability URL のまま（署名付き短命 URL 化は別タスク）／active→pending 差し戻し時に取引詳細は見え写真だけ 403／spin-down 中は背景ループが走らない（外部 cron 未設計）／スケールアウトで H-2 顕在化／limited 実データ未確認／リマインド再送手段なし。
