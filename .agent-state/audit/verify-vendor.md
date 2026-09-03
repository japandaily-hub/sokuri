# vendor-journey.md High指摘 反証結果（2026-09-03）

対象: `.agent-state/audit/vendor-journey.md` H-1〜H-7。全件コード直読で裏取り。判定に迷う点なし（全件、棄却できる根拠を発見できなかった）。

---

## H-1. 申込完了CTAが「業者ログインへ」でアカウント未作成
判定: **CONFIRMED**
根拠:
- `web/src/app/business/page.tsx:725-728` CTAは`/operator/login`固定。
- `backend/app/api/v1/endpoints/operator_applications.py:112-131` `OperatorApplication`にpassword_hash等の認証情報カラムは無く保存もしない。
- 承認後の正規導線は実在し機能する: `backend/app/api/v1/endpoints/admin.py:299-340`（承認時に`Invite`発行＋`notify.send_operator_application_approved`をcode付きで正しく呼ぶ）。指摘文の「正しい導線」記述も裏取り済み＝正確。
修正案の安全性: `web/src/app/business/page.tsx`のみ変更で完結。除外3ファイルに非依存。安全。

## H-2. 「審査待ち」バナーが到達不能デッドコード
判定: **CONFIRMED**
根拠:
- `backend/app/api/v1/endpoints/cases.py:281-293` 業者向け`list_cases`はvendor_status非依存で常に200（コード内コメントでも明言）。
- `backend/app/api/deps.py:132-144` vendor_status=="active"必須の403は`get_verified_operator`のみが持ち、`list_cases`が使う`get_current_actor`はis_suspendedのみ判定（vendor_status非参照）。403分岐は文字通り到達不能。
- `web/src/app/operator/page.tsx:266-273`,`web/src/app/operator/cases/page.tsx:123-129` とも`e.status===403`分岐は生きているが発火しない。
修正案の安全性: 提案は`cases/[id]/page.tsx`と同パターン（`getOperatorProfile().vendor_status`取得）への統一。`getOperatorProfile`は既存export（katadzuke-api.ts:320付近で型定義済み・呼び出し実績あり`cases/[id]/page.tsx:72`）のため**katadzuke-api.tsへの変更は不要**、除外ファイルに触れず実装可。ただし`operator/cases/page.tsx`はgit status上M（既に他作業者が編集中）で、明示除外リストには無いが実質競合リスクあり。**先に`operator/page.tsx`（非除外・未編集）だけ着手し、`cases/page.tsx`は編集者と調整してから、が安全な順序。**

## H-3. プロフィール審査バッジがverified_at依存で永久「審査中」
判定: **CONFIRMED**
根拠:
- `backend/app/api/v1/endpoints/auth.py:212-222` 招待コードありは`vendor_status="active"`即付与だが`verified_at=None`固定（コメント「admin approveで更新」）。
- `backend/app/api/v1/endpoints/admin.py:165-179` `verified_at`更新はこのadmin手動endpointのみ。
- `web/src/app/operator/profile/page.tsx:227` `verified = profile?.verified_at != null` → line 337-343・526-533で審査中/確認済みを出し分け。文言も指摘と一致確認。
修正案の安全性: `profile/page.tsx`の1行差し替えのみ。`katadzuke-api.ts`の型に`vendor_status`は既存（`web/src/lib/katadzuke-api.ts:320`）のためAPI層変更不要、除外ファイル非依存で安全。

## H-4. 「入札額を更新する」ボタンが常に失敗
判定: **CONFIRMED**
根拠:
- `web/src/app/operator/page.tsx:127-129` `lot.myBid`時にラベルのみ変わるが呼ぶのは同一`createBid`（page.tsx:338）。
- `web/src/lib/katadzuke-api.ts:827-837` PATCH/PUT等の更新系は不在（grep でも`bids.py`にput/patchルート無し確認）。
- `backend/app/api/v1/endpoints/bids.py:125-137` 既存入札があれば理由問わず409。
- 対比 `cases/[id]/page.tsx:240` の「1回のみ」表示と矛盾も実在確認。
修正案の安全性: `operator/page.tsx`（非除外）のみの変更で完結。安全。

## H-5. チャット画面ヘッダーにナビ・ログアウト無し
判定: **CONFIRMED**
根拠:
- `web/src/app/operator/chat/[id]/page.tsx:270-291` 独自`ch-header`。戻る矢印は`/operator/cases`固定(273)、ベルは`/operator`固定(283)、ログアウト無し。
- `web/src/components/kdz/OperatorHeader.tsx:52-64,94-100` ナビ+`signOut`ボタンを保持。
- `ch-header`のCSSは`operator-shared.css`ではなく別ファイル`web/src/app/operator/chat/[id]/chat.css`に定義（grep確認済み）。
修正案の安全性: 変更対象は`chat/[id]/page.tsx`と`chat.css`のみで、除外3ファイル（cases/[id]/page.tsx, operator-shared.css, katadzuke-api.ts）に一切非依存。安全。OperatorHeader流用案・自前ログアウト追加案どちらも成立。

## H-6. 入札上限（1億円）未表示・超過時エラーが意味不明
判定: **CONFIRMED**
根拠:
- `backend/app/schemas_katadzuke.py:444` `amount: int = Field(gt=0, le=100_000_000)`。
- `web/src/app/operator/page.tsx:201`, `web/src/app/operator/cases/[id]/page.tsx:252-253` ともmin/stepのみでmax無し（実読で確認）。
- `web/src/lib/katadzuke-api.ts:500-508` `typeof body.detail === "string"`のみ採用、pydantic配列detailは握り潰し`message="HTTP 422"`のまま。
- `web/src/lib/katadzuke-api.ts:1054-1064` `/^HTTP \d+$/`一致でfallback文言に置換。ロジック連鎖を実コードで確認。
修正案の安全性・**要警告**: 提案修正は`operator/page.tsx`と`operator/cases/[id]/page.tsx`の両方への`max`属性追加を含むが、**後者は編集禁止対象ファイル**。代替: 今回は`operator/page.tsx`のみ着手し、`cases/[id]/page.tsx`側は編集者へパッチ内容を申し送り、マージ後に反映する。なお本欠陥の根本原因（detail配列の握り潰し）は`katadzuke-api.ts`（同じく除外）にあり、そこを直さない限り恒久修正にはならない点も申し送り事項。

## H-7. 「対応エリアの案件のみ表示」の案内が事実誤認
判定: **CONFIRMED**
根拠:
- `web/src/app/operator/profile/page.tsx:462-464` 文言を実読で確認（指摘文と完全一致）。
- `backend/app/api/v1/endpoints/cases.py:285-293` `Case.status.in_(["open","bidding"])`のみでarea/service_areaフィルタ皆無。
修正案の安全性: 「文言削除・訂正」案を採用するなら`profile/page.tsx`のみで完結し安全。「エリアフィルタ実装」案は`cases.py`（現在git status上M＝他作業者編集中の可能性）とOperatorモデル拡張を要し衝突リスクが高い。**文言訂正のみを推奨**（実装コストとの非対称性からも軽微な方を優先すべき）。

---

## 見落とされたHigh相当の欠陥（追加発見）

### A. ダッシュボード`LotCard`の入札フォームがvendor_status非依存で常時アクティブ
根拠: `web/src/app/operator/page.tsx`全体をgrepしても`vendorStatus`/`vendor_status`/`getOperatorProfile`が一切出現しない（0件）。`LotCard`（page.tsx:109-230）はpropsに`vendorStatus`を受け取らず、`awaitingApproval`のような分岐も無い。H-2の「バナーが出ない」よりさらに深刻で、pending業者はダッシュボードの**全カードで「入札する」ボタンと金額入力欄がそのまま操作可能**に見える（cases/[id]では`awaitingApproval`でフォーム自体を隠す設計と明確に矛盾）。H-2の修正（バナー追加のみ）だけでは本欠陥は解消しない点に注意。

### B. 422バリデーションエラーのdetail配列握り潰しはbid amountに限らず全フォーム共通の欠陥
根拠: `web/src/lib/katadzuke-api.ts:500-508`の`request()`はアプリ全体の共通HTTPクライアントであり、FastAPIの自動バリデーション422は常に`detail`が配列（`[{loc,msg,type},...]`）で返る。この関数は文字列以外のdetailを一律破棄するため、bid amount超過（H-6）に限らず、`operator/signup`のパスワード要件違反、`profile`保存時のフィールド長超過など**アプリ内の全pydanticバリデーションエラーがユーザーに理由不明の汎用文言でしか表示されない**構造的欠陥。H-6は症状の一例に過ぎず、根本原因は共通層にある。

---

## サマリー
判定集計: CONFIRMED 7 / PARTIAL 0 / REFUTED 0（H-1〜H-7全件、棄却できる反証は発見できなかった）
棄却・PARTIAL: 該当なし
追加発見: A（ダッシュボードのvendor_status非ゲート、operator/page.tsx全域で確認済み）／B（422 detail配列握り潰しは全フォーム共通の構造的欠陥、katadzuke-api.ts:500-508）
保存パス: C:/Users/ko13h/Claude/Projects/ソクウリ/.agent-state/audit/verify-vendor.md
