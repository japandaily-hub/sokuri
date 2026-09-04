# r4 修正の QA/セキュリティ統合レビュー（2026-09-04・opus・レビュアーは Write 失敗のためリーダーが転記）

総合判定: 条件付き合格（Critical 0 / High 2 / Medium 5 / Low 4）。pytest 717 passed・tsc 0・eslint 0 error（警告3は既存）。
合格確認: /admin/operator-applications の契約は schemas_katadzuke.py:933-957 の全21項目が TS と一致、パス/メソッド一致（admin.py:825/843/855/899/946）。口座は _to_application_out がマスクのみ、全桁は明示押下＋監査ログ。ConfirmModal 4フローの確定ハンドラは元処理を呼ぶ。停止案内はループなし。文言（3営業日9箇所・改定日2箇所・LINE通知）整合。新ルートは middleware で保護。

## High
- H1 notify.py:68-80 + alerts.py:70-72 — BREVO 未設定検知のアラートは email 経路が同じ理由で出ない。LINE/webhook 未設定なら logger.warning のみ。test_notify.py:35 は send_alert をモックし「呼んだこと」しか検証していない。→ LINE/webhook のトランスポートをスタブして配送を検証、本番は LINE アラート設定に依存することを明記。
- H2 test_katadzuke_api.py:1158 — 事前申込の GET /{id}・reveal-bank-account（口座全桁）・approve・reject に認可の負テスト 0 件。→ 4ルート×3主体の parametrized テスト。
## Medium
- M1 admin/page.tsx:130-148 — 事前申込取得を Promise.all に同梱、1本の5xxで画面全体不能 → allSettled。
- M2 operator-applications/page.tsx:146-170 / admin/page.tsx:227-251 — 失敗時に Target をクリアせずモーダルが残り Notice が隠れる。却下理由が空だと無反応 → ConfirmModal に error 表示、空理由のバリデーション。
- M3 operator/login/page.tsx:34-39 — reachable ガード無しで callbackUrl を無条件 replace（/mypage → /forbidden）。業者→別業者の切替導線なし。
- M4 admin/page.tsx:134,139-142 / operator-applications:180-189 — バッジ・フィルタが最新100件内のみ。admin.py:835 は created_at desc 固定・status 絞込/total 無し → received 優先ソート＋status/total を backend に追加。
- M5 AdminPagination.tsx:24-26 — 件数が limit の倍数のとき「次へ」活性のまま、2ページ目で「0〜100件」誤表示 → to = itemCount===0 ? 0 : offset+itemCount。
## Low
- L1 account_type の TS Literal vs backend str → pydantic Literal 化。L2 docs/TODO.md:22・business_plan md の「許可番号任意／承認1営業日」が旧記述。L3 notify.py の reset 関数の配置。L4 alerts.py create_task の強参照なし（対象外ファイル）。
## 未解決リスク
1. next build 未実行（本番ビルド固有の CSS 事故の既往あり）。2. web の自動テスト 0 件。3. 本番 BREVO_API_KEY／ALERT_* 実値未確認。4. 規約改定の告知・再同意運用が不在（民法548条の4 要法務確認）。5. 口座全桁開示の監査ログが標準出力のみ。
