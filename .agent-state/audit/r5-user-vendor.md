# 依頼者・業者導線 最終回帰監査台帳（第5周・r5-user-vendor・2026-09-04）

対象: コミット `885f2ec → 3da71de`（第4周コミット、`web/src/app/operator/login` `web/src/app/login`
`web/src/app/mypage` `web/src/app/notifications` `web/src/app/faq` `web/src/app/contact`
`web/src/app/privacy` `web/src/app/terms` `docs/beta-operator-onboarding.md` の差分）に対する
独立の最終回帰監査。前提: `r4-user.md`・`r4-vendor.md`・`r4-crosscut.md`・`r4-verify-crosscut.md`・
`r4-fix-frontend.md`・`r4-fix-frontend2.md`・`docs/TODO.md` 01/03 を読了済み。これらの自己申告は
額面で受けず、全件を実ファイルで再検証した。

## 検証結果サマリ（是正確認できた項目）
R4-H1（本人確認目的の不一致）／R4-H2（規約・PP最終改定日）／R4-H3（招待テンプレの許可番号「任意」）／
R4-M1 crosscut（業者審査SLA 1営業日/3営業日）／R4-M1 vendor（`/operator/login` 既存業者セッションの
行き止まり）／R4-M2（問い合わせ返信SLA 2営業日/3営業日）／R4-M3（`/contact` 完了文の「登録メールアドレス」）／
R4-M5（`/notifications` のLINE文言、`:148,:321,:471` 全3箇所）／ADD-H1（`CURRENT_OPERATOR_TERMS_VERSION`
不一致）は、いずれも実装・文言とも正しく是正されたことをコード直読で確認した（誤りなし）。
`/operator/login` の是正は r4-vendor.md の推奨案（自動遷移）ではなく банер+手動リンク方式を採用しており
設計が変わっているが、行き止まり自体は解消されているため問題視しない。

---

## High
（該当なし）

## Medium

### R5-M1. R4-M4（古物営業法＝当社の義務、という誤った docstring）が3箇所中2箇所しか是正されておらず、`backend/app/db/models/user_identity_document.py` に残存
- 画面: バックエンド内部コメントのみ（ユーザー非露出だが再伝播リスク）
- 事象: 3da71de は同一のコミット（コミットメッセージ自身が「文言残存の是正」と明記）で
  `web/src/lib/katadzuke-api.ts:730,833` の「古物営業法の本人確認・年齢確認に使用」を
  「なりすまし・不正出品の防止および運営からの本人確認のため（任意提出）に使用。古物営業法第15条の
  確認義務を負うのは訪問する古物商（業者）であり、当社ではない。」へ正しく是正した。しかし
  R4-M4 が同時に指摘していた3箇所目 `backend/app/db/models/user_identity_document.py:3`
  （「古物営業法上の本人確認義務に対応するため、依頼者が身分証…の画像を提出し」）は今回のコミット
  で一切触られておらず、旧い誤った前提のままである。同じ性質の3箇所のうち2箇所だけを直す
  「取りこぼし」であり、次に本人確認機能を触る担当者がこのモデル docstring を根拠に
  UI文言を書き戻すと R4-H1/A2 が再発する。
- 根拠 file:line:
  - `backend/app/db/models/user_identity_document.py:3`（現存、未修正）—
    「古物営業法上の本人確認義務に対応するため、依頼者が身分証（運転免許証・マイナンバー
    カード・パスポート・在留カード・健康保険証）の画像を提出し、admin が承認/却下する。」
  - 対比・是正済み: `web/src/lib/katadzuke-api.ts:730`「なりすまし・不正出品の防止および運営からの
    本人確認のため（任意提出）に使用。古物営業法第15条の確認義務を負うのは訪問する古物商（業者）
    であり、当社ではない。」／同 `:833` も同様に是正済み。
  - `git log --oneline 885f2ec..3da71de -- backend/app/db/models/user_identity_document.py` は
    0件（このファイルは3da71deで一切変更されていないことを確認済み）。
- 再現手順: `backend/app/db/models/user_identity_document.py` の冒頭 docstring を読む。
  同じ本人確認機能の別ファイル（`katadzuke-api.ts:730,833`、`web/src/app/mypage/identity/page.tsx:6`）
  と正面から矛盾する記述が残っていることが分かる。
- 修正案: `user_identity_document.py:3-4` を「なりすまし・不正出品の防止および運営からの本人確認の
  ため（任意提出）に、依頼者が身分証…の画像を提出し、admin が承認/却下する。古物営業法第15条の
  確認義務を負うのは訪問する古物商（業者）であり、当社ではない。」へ統一する。

### R5-M2. ADD-M1（プライバシーポリシー収集項目表への「お問い合わせ情報」追加）が自己申告の整合ルールを満たさず、収集項目の一部（お問い合わせ種別）が欠落
- 画面: `/privacy`
- 事象: 3da71de は `web/src/app/privacy/page.tsx` の `COLLECTED` 配列に「お問い合わせ情報」の行を
  新設し、ADD-M1（収集項目表からお問い合わせ情報が丸ごと欠落していた問題）自体は解消した。
  しかし追加された行の `detail` は「お名前、メールアドレス、お問い合わせ内容」の3項目のみで、
  バックエンドが実際に収集・保存する4項目目の `category`（お問い合わせ種別／`ContactCategory`）が
  抜けている。この配列の直前コメント自身が「バックエンドの実収集項目…と整合させて記載すること」と
  明記しており、追加された行はその自己申告ルールを満たしていない。
- 根拠 file:line:
  - `web/src/app/privacy/page.tsx:22`（新設行）—
    `{ type: "お問い合わせ情報", how: "お問い合わせフォーム送信時", detail: "お名前、メールアドレス、お問い合わせ内容（回答のためにのみ利用します）" }`
  - `web/src/app/privacy/page.tsx:11-13`（配列直前のコメント）—「第2条「収集する情報」の表データ。
    バックエンドの実収集項目…と整合させて記載すること。」
  - `backend/app/schemas_katadzuke.py:1171-1177`（`ContactCreateRequest`）— `name: str`・
    `email: EmailStr`・`category: ContactCategory`（必須）・`message: str` の4フィールドを実収集。
    `category` が `detail` に含まれていない。
- 再現手順: `/privacy` の「収集する情報」表を開き、「お問い合わせ情報」行の内容と、`/contact`
  フォーム（`web/src/app/contact/page.tsx`）に実在するカテゴリ選択欄を突き合わせると、
  カテゴリ選択で入力した情報がプライバシーポリシーの収集項目表に記載されていないことが分かる。
- 修正案: `:22` の `detail` を「お名前、メールアドレス、お問い合わせ種別、お問い合わせ内容
  （回答のためにのみ利用します）」へ（`r4-verify-crosscut.md` の ADD-M1 修正案がもともとこの4項目を
  提示していたが、実装時に「お問い合わせ種別」が脱落したとみられる）。

---

## 確認したが問題なし（新規に再検証した主な項目）
- `/operator/login`: `sameAccountSignedIn`（既存業者セッション時のバナー＋ダッシュボードリンク＋
  サインアウト導線）・`otherAccountSignedIn`（依頼者セッション時のバナー）が相互排他で両立せず実装
  されている。`callbackUrl` は `/operator` 配下のみに制限（`rawCallbackUrl === "/operator" ||
  rawCallbackUrl.startsWith("/operator/")`）、既定値 `/operator` は実在ルート
  （`web/src/app/operator/page.tsx`）。`middleware.ts:31` の `OPERATOR_PUBLIC` は
  `/operator/login`・`/operator/signup` のみで変更なし。
- 停止業者・停止依頼者のログイン失敗文言: `web/src/auth.ts` の `AccountSuspendedError`
  （`code="account_suspended"`）が `login/page.tsx`・`operator/login/page.tsx` 双方で
  同一構造（バナー＋`/contact`リンク）に展開されており対称。r4-verify-crosscut の R4-M7
  却下判定（`/contact`リンクは実在）を再確認、齟齬なし。
- `/operator/signup` の招待コード登録直後: `signIn` 成功パス（`page.tsx:70-73`）は
  `clearRedirectLoopStorage()` を呼ばないままだが、このファイルは 885f2ec→3da71de で
  変更されていない（`git log` 0件）ため回帰ではない。r4-vendor.md の「対象外」判断を維持。
- 業者審査SLA・問い合わせ返信SLAとも文書横断で「3営業日」に統一（`beta-operator-onboarding.md:21`・
  `ApprovalPendingNotice.tsx:29,35`・`business/page.tsx:711,720`・`faq/page.tsx:412`・
  `contact/page.tsx:274,308`）。
- 横断 grep（「古物営業法に基づく」「2営業日」「1営業日」「2026年6月25日」「登録メールアドレス」
  「メールの代わりに」「任意）」「LINEにも」「3日間」「受取先」）: `/contact`・`/notifications`・
  `/operator/login` 文脈での旧文言残存は0件。`mypage/bank-account/page.tsx:176,214`・
  `password-reset/page.tsx:23` の「登録メールアドレス」はログイン中ユーザー宛の別文脈で正当、
  誤検知として除外。

## 未解決（本ラウンドでは回帰ではないが申し送り）
- **R4-M6（β手数料の税区分・告知手段）は本ラウンドで一切手を付けられていない**: `terms/TermsTabs.tsx:147,152`・
  `legal/page.tsx:113,120` は「買取金額の8%」（税込表記なし）・「事前にメールでお知らせします」のまま。
  対象ファイルが3da71deの差分に含まれないため回帰ではないが、r4-verify-crosscutが是正案を出した
  Mediumが未着手のまま残っている。
- 実ブラウザでの動作確認（停止アカウントの実ログイン、`/operator/login`のバナー表示、`/privacy`表示）は
  本監査でも未実施（禁止事項によりファイル編集・実操作は範囲外、コード読解のみで判定）。

---

## 末尾サマリ
✅ 依頼者・業者ログインの対称性、通知チャネル文言、SLA文言、法務文書の是正、招待テンプレの必須化は
いずれも3da71deで正しく反映されたことをコード直読で確認した。r4系の High 3件・主要Medium・ADD-H1は
全て解消。
⚠️ 「文言残存の是正」を掲げた3da71de自身が、同種の残存を2件新たに取りこぼした（R5-M1: 本人確認
docstringが3箇所中1箇所未修正／R5-M2: プライバシーポリシー収集項目表の新設行がカテゴリ項目を欠く）。
いずれもMedium・修正は数行で完結する。
❌ R4-M6（手数料税区分・告知手段）は本ラウンドで未着手のまま残存。実ブラウザでの最終確認は未実施。
