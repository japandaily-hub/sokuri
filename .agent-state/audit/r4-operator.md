# 運営導線 回帰監査 台帳（第4周・r4）

最終更新: 2026-09-04 / 監査方式: 静的読解（Read/Grep/Bash、読み取り専用）/ 対象: 運営（admin）視点のみ・commit 885f2ec（r3）の回帰検出
前提: `.agent-state/audit/{r3-operator,r3-verify-operator,r3-review-security,r3-review-qa2}.md` と `docs/TODO.md`（01・03）を先読み。TODO.md 03 記載の意図的未対応（監査ログテーブル化・/contact IPキャップ共有・admin不在時の自動昇格再有効化窓・alerts Task参照・停止依頼者の進行中案件・LINEループキー・fee_amount 0円・web自動テスト0件）、および r3-review-qa.md L3（admin が /chat 経由で依頼者名義投稿できる・Low判定済み）は再指摘しない。以下は上記に無い新規観点のみ。

---

## High

### H1. 業者「事前申込（/business経由）」の審査・承認・却下・口座開示が、管理画面のどこからも到達できない
- 該当:
  - `backend/app/api/v1/endpoints/admin.py:825-984` — `GET /admin/operator-applications`（一覧）・`GET /admin/operator-applications/{id}`（詳細）・`POST /admin/operator-applications/{id}/reveal-bank-account`（口座復号開示）・`PATCH /admin/operator-applications/{id}/approve`（招待コード発行＋承認メール）・`PATCH /admin/operator-applications/{id}/reject`（却下メール）の5エンドポイントが実装済み（`get_current_admin` 必須）。
  - `web/src/app/business/page.tsx:18,187` — `POST /operator-applications`（**認証不要の公開エンドポイント**）へ送信する業者向け集客ページが本番導線として存在（トップ・フッター等から到達可能な公開ページ）。
  - `web/src/lib/katadzuke-api.ts` 全文 grep — `adminListOperatorApplications` / `adminApproveOperatorApplication` / `adminRejectOperatorApplication` / `adminRevealOperatorApplicationBankAccount` に相当する関数は**1つも存在しない**（`submitOperatorApplication`（公開投稿側）のみ実装、`:1185-1201`）。
  - `web/src/app/admin/` 配下のディレクトリは `_components / cases / identity-documents / layout.tsx / page.tsx / transactions / users` の7つのみ（`operator-applications` ディレクトリ無し）。`web/src/app/admin/page.tsx:298-316` のトップナビ（案件一覧／取引一覧／依頼者一覧／本人確認書類の審査の4リンク）にも申込審査への導線は無い。
- 事象: `/business` は現在稼働中のリード獲得チャネルであり、そこから届く申込（会社名・許可番号・口座情報等を含む）は DB（`OperatorApplication` テーブル）には保存されるが、**運営はブラウザ操作で一切閲覧・承認・却下できない**。承認（招待コード発行＋自動メール送信）・却下（理由付き自動メール送信）・口座情報の開示のいずれも、認証済み admin トークンを使った手動 API 呼び出し（curl/Postman 等）でしか実行できない。既存の「業者招待コード発行（単発/バルク）」画面（`/admin`）や「本人確認書類審査」画面（`/admin/identity-documents`）と同水準の運営導線が、最も新規業者を集める入口（`/business`）にだけ欠落している。
- 再現手順: `/business` にアクセス→フォームに入力して送信→200/201で完了表示（`submitOperatorApplication` 成功）。その後 `/admin` トップおよびナビ内の全リンクを辿っても、この申込を確認・承認する画面が存在しないことを確認。バックエンドで `GET /admin/operator-applications` を直接叩けば一覧は取得できる（=機能自体は健全）ことも合わせて確認。
- リスク: β運用中に `/business` 経由の申込が溜まっても運営が気づく手段が画面上に無く、承認が滞留する（招待コードが発行されないため業者は登録に進めない）。既存の招待コード配布フロー（`/admin` の単発/バルク発行）と事前申込フローが並存しているにもかかわらず、後者だけ運用不能な状態でリリースすると新規業者獲得が実質止まる。
- 修正案: 最小構成として `web/src/lib/katadzuke-api.ts` に4関数（list/get/approve/reject/reveal-bank-account、`AdminListParams` 等の既存パターンを流用）を追加し、`web/src/app/admin/operator-applications/page.tsx` を新設（`AdminPagination`・`StatusFilterBar`・`ConfirmModal` など今回追加済みの共通部品をそのまま使えば実装コストは小さい）。`/admin/page.tsx` のトップナビに5番目のリンクとして追加する。

---

## Medium

### M1. 案件一覧・取引一覧のID検索プレースホルダが「前方一致」と表示するが、実装は完全一致（UUIDパース）のみで前方一致は成立しない
- 該当:
  - `web/src/app/admin/cases/page.tsx:120` — placeholder「案件ID（**前方一致**）・依頼者メール（部分一致）で検索」。
  - `web/src/app/admin/transactions/page.tsx:120` — placeholder「取引ID・案件ID（**前方一致**）／依頼者メール・業者名（部分一致）で検索」。
  - `backend/app/api/v1/endpoints/admin.py:396-398`（`admin_list_cases`）・`:493-499`（`admin_list_transactions`）— いずれも `_try_parse_uuid(q_norm)`（`:88-98`。`uuid.UUID(value)` が例外なく通る＝入力全体が有効なUUID文字列である場合のみ）で ID 条件を追加しており、ilike によるワイルドカード・前方一致は一切行っていない（`admin.py:78-85` の `_escape_ilike_value` はメール／会社名側にのみ適用）。
  - 対比: 同じバッチで直っている `web/src/app/admin/users/page.tsx:168` の placeholder は「メール／表示名（部分一致）またはユーザーIDで検索」で「前方一致」の語を含まない（r3-review-qa2.md QA-H2 で「前方一致の語を落としたのは正しい」と検証済み）。同一の不整合クラスが、同じ日に新設された案件一覧・取引一覧の2画面だけ未修正のまま残っている。
- 事象: 運営が `CopyableId` でコピーした先頭8桁（例: `a1b2c3d4`）や、他画面からメモした一部だけのIDを検索欄に入力すると、`uuid.UUID("a1b2c3d4")` は `ValueError` になり ID 条件は一切追加されず、メール／会社名側の条件だけで絞り込まれる（＝多くの場合 0 件）。表示文言は「前方一致」なので、運営はこれを「該当データが存在しない」と誤読しうる。完全な UUID を貼り付けた場合のみ正しく機能する。
- 再現手順: `/admin/cases` の検索欄に既存案件IDの先頭8文字だけを入力→検索→0件（該当する案件はありません）と表示されることを確認。同じ案件の完全なUUIDを貼り付けると1件ヒットすることと対比。
- 修正案: placeholder の文言を users ページと同じく「案件ID（完全一致）・依頼者メール（部分一致）で検索」に是正する（表示文言のみの修正で完結し、バックエンド変更は不要）。

### M2. 停止／承認の確認ダイアログが、新設の依頼者一覧だけ `ConfirmModal`、既存の業者一覧・本人確認書類審査は `window.confirm` のままで、同一運営フロー内でUXが分裂している
- 該当:
  - `web/src/app/admin/users/page.tsx:4-7`（コメント）「window.confirm はブラウザ既定のスタイルで文言が読みにくく、テストもしづらいため使わない」に基づき `ConfirmModal` を採用（`:271-309`）。
  - 一方 `web/src/app/admin/page.tsx:216-221`（業者停止／解除の確認）・`:237`（業者承認の確認）は今回のコミットでも `window.confirm` のまま。`web/src/app/admin/identity-documents/page.tsx:127`（本人確認書類の承認確認）も同様に `window.confirm`。
  - いずれも同じ「破壊的操作の確認」という業務であり、`ConfirmModal` の設計コメント自体が「既存の許可証画像モーダル・本人確認書類モーダルと同じ role="dialog" 構成を踏襲する」（`web/src/app/admin/_components/ConfirmModal.tsx:6-7`）と書いているにもかかわらず、確認ダイアログ自体は踏襲されていない。
- 事象: 運営担当者は同じ管理画面内で、依頼者停止時はブランドに沿った読みやすいモーダル（理由欄付き）を使う一方、業者停止・業者承認・本人確認書類承認では OS 標準の素っ気ないダイアログ（文言が長いと折り返しが崩れやすく、自動テストからも操作できない）に戻る。業者停止は依頼者停止と同じく「即時ログイン不可・全操作403」という重い操作であるにもかかわらず、確認体験の重みが不揃いになっている。
- 再現手順: `/admin` で業者の「停止する」ボタンを押す→OS標準の `confirm()` ダイアログが出ることを確認。`/admin/users` で依頼者の「停止する」を押す→自前のブランドモーダル（理由欄付き）が出ることを確認。同一運営者が同じセッション内で両方の操作を行うと体験が不連続であることを確認。
- 修正案: `web/src/app/admin/page.tsx` の業者停止・承認確認と `web/src/app/admin/identity-documents/page.tsx` の承認・却下確認を、今回新設済みの `ConfirmModal`（`web/src/app/admin/_components/ConfirmModal.tsx`）に置き換える。共通部品は既に存在するため、置き換えコスト自体は小さい。

---

## 確認したが問題なし（今回新規に検証した観点）

- **認可の網羅性**: `backend/app/api/v1/endpoints/admin.py` の `@router` 23件・`Depends(get_current_admin)` 23件で1対1対応（grep突合）。promote/demote 新設分（`:715,770`）も含め漏れなし。`GET /files/{storage_key}`（`case_photos.py:111`）は写真専用の意図的な無認証設計のまま変更なし。
- **admin自身のロックアウト防止**: `suspend_user`（自己停止409・admin対象409）、`demote_admin_to_user`（自己降格409・最後の1人409）、`promote_user_to_admin`（自己指定409）はいずれも実装済みで抜けなし。
- **一覧の tie-breaker・退会済み除外**: `admin_list_cases`/`admin_list_transactions`/`admin_list_users` とも `created_at desc, id desc` の決定的な順序と `_escape_ilike_value` によるワイルドカードエスケープが3画面で統一されている。`admin_list_users` の `include_deleted`（既定false）も機能している。
- **ページング境界**: `AdminPagination`（`web/src/app/admin/_components/AdminPagination.tsx:31,39`）の「前へ」`offset===0`・「次へ」`offset+limit>=total` の disabled 判定は total=0／ちょうど割り切れる件数のいずれでも正しく機能する（コード上の境界値確認）。
- **操作後の一覧更新**: cases/transactions/users いずれの画面も操作（検索・停止・昇格・降格）後に `reload()` を呼び直しており、フロント側で楽観更新のみで済ませて実データとズレる箇所は無い。
- **失敗時の表示**: 3画面とも `toDisplayMessage(e, "...")` を経由した `Notice tone="error"` 表示で統一されている。
- **alerts 呼び出しの整合**: `admin.py` の promote/demote が呼ぶ `alerts.send_alert(title, body, severity=..., key=...)` は `alerts.py:131-137` のシグネチャと一致（引数の型・キーワードとも齟齬なし）。

---

## 未解決・確認できなかった点

1. H1（業者事前申込レビューUI欠落）は本タスクの禁止事項（ファイル編集・新規作成）に該当するため未実装。次アクションとして別セッションでの着手を推奨する。
2. `/business` ページが実際にどの程度のリード流入を生んでいるか（本番トラフィック実績）は本監査の対象外のため未確認。H1の実害の大きさはそこに依存する。
3. 業者事前申込フローと、既存の招待コード起点フロー（`/admin` バルク発行）のどちらを主要導線として運用する方針かは、Block2記載の課題（TODO.md 02「上位3社から選ぶ」等と同種の仕様未確定事項）に近く、本監査では判定していない。

---

## サマリ
結論: 新規 High を1件（業者事前申込の承認・却下・口座開示の管理画面UI・APIクライアントが完全欠落。`/business` からのリードが運営から見えない）検出。Medium 2件（案件/取引一覧の検索プレースホルダ文言と実装のズレ＝users画面で既に直った不整合クラスの伝播漏れ、確認モーダルUXの新旧混在）はいずれも実コードで再現手順つきで確認済み。
High/Medium件数: High 1 / Medium 2（計3件、上限10件以内）。
保存パス: `C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r4-operator.md`
未解決: 上記「未解決・確認できなかった点」参照（H1の実装着手・本番リード流入量の実測・事前申込フローの運用方針確定）。
✅達成: 認可境界（23/23一致）・admin自己ロックアウト防止・一覧の決定的順序と退会済み除外・ページング境界値・操作後リロード・失敗時表示・alerts呼び出しシグネチャはいずれも健全と確認。
⚠️課題: High 1件（事前申込審査UI欠落）・Medium 2件（検索文言不整合・確認モーダルUX不統一）はいずれも実装が必要（本タスク範囲外）。
❌ブロッカー: なし（H1はリリース阻害というよりは新規業者獲得チャネルの運用不能状態であり、次アクション化すべき事項）。
