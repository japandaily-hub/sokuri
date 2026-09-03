# operator-crosscut.md High指摘 反証結果
検証者: 独立QA検証（反証専門） / 対象: A1-A7, B1-H1〜H3, B3-H1/H2 / 2026-09-03

## 判定サマリ
| ID | 判定 |
|---|---|
| A1 | CONFIRMED（バックエンドも無検証と判明、指摘より深刻） |
| A2 | CONFIRMED（バックエンドにも解除APIが皆無と確定） |
| A3 | CONFIRMED |
| A4 | CONFIRMED（バックエンドFieldガードで実害は限定的） |
| A5 | CONFIRMED |
| A6 | CONFIRMED |
| A7 | CONFIRMED |
| B1-H1 | PARTIAL（ログアウト不在は誤り。他は真） |
| B1-H2 | CONFIRMED |
| B1-H3 | PARTIAL（3者同種の折返しではない） |
| B3-H1 | CONFIRMED（台帳の利用可能幅計算が甘く、実際はより深刻） |
| B3-H2 | CONFIRMED |

---

## A1. 許可証未提出でも一発active化 [High] -> CONFIRMED
- 根拠: web/src/app/admin/page.tsx:373-377(バッジ),384(openLicenseModalのdisabled),389-396(toggleVerifyボタン、disabled={busy}のみ)
- 追加裏取り: backend/app/api/v1/endpoints/admin.py:165-179 verify_operator は body.verified のみで vendor_status を active/pending に切替え、has_license_image を一切参照しない。フロントを直しても、API直叩きでは未提出のまま active 化できる。指摘より一段深刻。
- 修正案の妥当性: ボタンdisabled化自体は正しいが不十分。サーバー側ガードが未実装で backend/ は本タスク編集対象外のため、フロント修正だけでは脆弱性は残る。代替案: フロントはdisabled化で誤操作を防止しつつ、バックエンド是正は別チケット化する2段構え。

## A2. 停止解除導線が存在しない [High] -> CONFIRMED
- 根拠: web/src/app/admin/page.tsx:373(is_suspendedバッジのみ),389-396(toggleVerifyのみ)。web/src/lib/katadzuke-api.ts:32(is_suspended型),969-973(adminListOperators/adminVerifyOperatorのみ)。
- 追加裏取り: backend/app/api/v1/endpoints/admin.py の /admin 配下ルートを全列挙(112,128,147,156,165,182,230,243,255,299,346行)。is_suspendedを書き換えるエンドポイントは1つも存在しない。フロントの欠落ではなくバックエンドにも解除APIが存在しない。
- 修正案の妥当性: 「解除ボタン/APIをUIに追加」はAPIが無ければ実装不可能。backend/編集対象外の本タスクでは完遂できない。代替案: 新規バックエンドAPI追加を別ワーカーに依頼するまで、管理画面に「DB直接操作で対応」の注記を出すに留める。

## A3. 新着承認待ちバッジ・ソート順の保証なし [High] -> CONFIRMED
- 根拠: web/src/app/admin/page.tsx:54(statusFilter初期all),192-195(独自ソートなし),338-351(件数バッジなし)
- 追加裏取り: backend/app/api/v1/endpoints/admin.py:161 list_operators は order_by(created_at desc)のみ。notify.py:169-178 で admin宛メール通知の実在確認。
- 修正案の妥当性: 件数バッジ・初期ソートはadmin/page.tsx内で完結、低リスク。

## A4. バルク発行のクライアント側バリデーション欠如 [High] -> CONFIRMED
- 根拠: web/src/app/admin/page.tsx:137-155(issueBulk範囲チェックなし),282-289(number入力、type=buttonでネイティブ検証不発火)
- 追加裏取り: backend/app/schemas_katadzuke.py:600 InviteBulkCreateRequest.count は Field(ge=1, le=500) でサーバー側は不正値を422で弾く。実害は「エラー文言頼みのUX劣化」に限定され、High判定はやや過大(Medium相当が妥当[推測])。
- 修正案の妥当性: issueBulk冒頭での範囲チェックは安全・低リスク。

## A5. エラー表示が画面最上部固定のみ [Medium/High境界] -> CONFIRMED
- 根拠: web/src/app/admin/page.tsx:212-216(単一Notice配置)。業者一覧はmax-h制限なく縦に伸びる(A6と連動)ため下部操作時にバナーが視認外になる構造は事実。
- 追加裏取り: .kdz-toast は web/src/app/katazuke-pages.css:110 に実在(修正案の引用は正確)。
- 修正案の妥当性: トースト切替は安全。まずトースト化のみ着手が低リスク。

## A6. 検索/ページネーション欠如 [High] -> CONFIRMED
- 根拠: admin/page.tsx全文確認。招待コード一覧のみmax-h-64 overflow-y-auto(239行)、業者一覧は同種の制限が一切なく無制限に縦伸長(354行)。検索input・ソートUIは存在しない。
- 修正案の妥当性: クライアントサイドfilterはadmin/page.tsx内で完結、低リスク。

## A7. CSVインジェクション対策なし [Medium/推測含みHigh候補] -> CONFIRMED
- 根拠: web/src/app/admin/page.tsx:157-169 downloadBulkCsv はエスケープなしで連結。lot_nameは291-299行のtext inputで自由入力可能(schemas_katadzuke.py:601はmax_length=128のみで先頭文字制限なし)。
- 修正案の妥当性: 先頭が=,+,-,@の場合にシングルクォートを付与するサニタイズはOWASP標準対策と一致、admin/page.tsx内で完結、低リスク。

---

## B1-H1. /adminがAppHeaderを流用 [High] -> PARTIAL
- 根拠: web/src/app/admin/page.tsx:200,210(AppHeader使用) / web/src/components/kdz/AppHeader.tsx:17-40(通知ベル->/notifications, マイページ->/mypage 固定リンク)
- 反証: 「管理者専用ログアウトもAppHeaderには存在しない」は誤り。AppHeader.tsx:2,40 で AppHeaderLogout を描画しており、AppHeaderLogout.tsx:1-15 は signOut({callbackUrl:"/"}) を実行する汎用だが機能するログアウトボタン。管理者はログアウト自体は可能。
- 正しい方針: 真の欠陥は「管理者名の非表示」と「消費者向け導線(通知/マイページ)がadminにも出てしまうこと」の2点のみ。AppHeader全体を専用ヘッダーに置き換えるのは9ルート超で使い回されるコンポーネントへの副作用が大きく過剰。AppHeaderにvariant propを追加し/adminでは通知ベル・マイページのみ非表示にする最小差分が安全。

## B1-H2. OperatorHeader 920px以下でログアウト消滅 [High] -> CONFIRMED
- 根拠: web/src/components/kdz/operator-header.css:130-136(.op-nav,.op-user-name,.op-logoutをdisplay:none、.op-nav.openはNAV配列のみ復元、.op-logoutは含まれない) / OperatorHeader.tsx:94-100(signOut呼び出しはこの1箇所のみ)
- 追加裏取り: web/src/app/operator 配下をgrepした結果、signOut呼び出しは0件(該当コンポーネントはapp/operator配下外)。920px未満でログアウト手段が完全消滅するという主張は正確。
- 修正案の妥当性: operator-header.cssは編集対象外リストに含まれない(off-limitsはoperator-shared.css / cases/[id]/page.tsx / katadzuke-api.ts / backend/)。.op-nav.open末尾へのログアウト行追加は同ファイル内で完結し安全。

## B1-H3. ブレークポイント不統一(600/860/920px) [Medium/High境界] -> PARTIAL
- 根拠: SiteHeader->katazuke.css:613(860px、hamburger切替), AppHeader->katazuke.css:183-189(600px), OperatorHeader->operator-header.css:130(920px)
- 反証: katazuke.css:183-189を実読した結果、AppHeaderの600pxメディアクエリはハンバーガー等の折返しを行っていない。.app-actions{white-space:nowrap}のままgap/font-sizeを縮小するだけ。SiteHeader/OperatorHeaderが畳む設計なのに対しAppHeaderはそもそも畳む機構が無い別種の挙動であり「3者とも同種の折返しで閾値だけ違う」という前提が不正確。
- 正しい方針: (1)AppHeaderに折返しフォールバックが本当に不要か実機確認、(2)そのうえでブレークポイント値を統一する、の2段。値だけ揃える対応は本質的なギャップ(AppHeaderの無防備なnowrap)を見逃す。

## B3-H1. adminフィルタ行が375pxで収まらない [High] -> CONFIRMED（台帳の計算より深刻）
- 根拠: admin/page.tsx:335-352(flex items-center justify-between、flex-wrapなし) / Ui.tsx:60-66(Card=p-5=20px×2) / globals.css:66-68(.container-awはpx-5=20px×2)
- 台帳の誤り: 台帳は「Card内側p-5を差し引くと利用可能幅335px」としているが、外側の.container-awのpx-5(合計40px)を引き忘れている。375-40(container-aw)-40(Card)=295pxが実際の利用可能幅。フィルタボタン4つだけで概算270px超、見出し「業者アカウント」(概算112px)を足すと400px近くになり295pxを確実に超過。台帳の結論(はみ出し疑い高)は正しいが根拠の算数が誤っており、実際はより確実にオーバーフローする。
- 修正案の妥当性: flex-wrap追加はadmin/page.tsx内で完結、安全。

## B3-H2. admin業者liの右2ボタンが375pxで収まらない [High] -> CONFIRMED
- 根拠: admin/page.tsx:361,380-397 / Ui.tsx:121-124(btnPrimary/btnSecondaryはpx-4 py-2.5 text-sm=16px×2パディング+14pxフォント)
- 概算: 「許可証画像を確認」(9字)概算158px、「承認する（active化）」概算164px、gap-2で右側ボタン群だけで約330px。B3-H1で確定した実利用可能幅295pxを、左側コンテンツ抜きでも単独超過。CONFIRMED。
- 修正案の妥当性: 375px以下でボタンをフルwidth縦積みに切替はadmin/page.tsx内で完結、安全。

---

## 見落とされたHigh相当の欠陥（追加発見）

### 追加1. OperatorHeader: 会社名が長い場合、920px超(920〜1140px帯・PC分割ウィンドウ)でも横オーバーフローが確定するCSS構造 [High、CSS挙動として確定・具体的桁数は推測]
- 根拠: web/src/components/kdz/operator-header.css:92-98 .op-user-name{white-space:nowrap;...}にmin-width:0もtext-overflow:ellipsisも無い。flexboxの既定(min-width:auto)では、nowrapなテキストのcontentが縮小下限になるため、会社名がどれだけ長くても.op-user-nameは自身のテキスト全幅より縮まない。.op-header-inner(operator-header.css:16-21)はdisplay:flexでflex-wrap指定なし。920px閾値(B1-H3で既出)の外側、920px〜--maxw:1140px(katazuke.css:50)の間の画面幅で、日本語の長い会社名(15字超)が入ると.op-header-innerがコンテナ幅を超えて横スクロールまたは要素重なりを起こす。B1-H3は閾値の数値比較のみで、この「920px超でも壊れる」構造的欠陥には触れていない。
- 修正案: .op-user-nameにmax-width(例160px)+overflow:hidden+text-overflow:ellipsis+min-width:0を追加。operator-header.cssは編集対象外リストに含まれないため対応可能。

### 追加2. AppHeader: 375px以下で折返し機構が皆無(SiteHeader/OperatorHeaderと異なりハンバーガー化しない) [Medium〜High境界、静的推定・実機未測定]
- 根拠: katazuke.css:169-189。.header .inner{display:flex;...}(172行)にflex-wrap指定なし、.app-actions{...white-space:nowrap}(182行)。600px以下(183-189行)でもgap/font-sizeを縮めるのみで、SiteHeaderの.hamburger(613-617行)やOperatorHeaderの.op-nav-toggle(operator-header.css:114-136)に相当する折返し先が存在しない。ロゴ+通知ベル+「マイページ」文言リンク+ログアウトボタンが常に一列表示され続ける設計。
- 静的推定: 375px時は概算で収まる可能性が高い(利用可能幅約339px vs 要素合計概算228px)が、320px系端末や長いロゴ表記時は余白がほぼ無くなる。B1-H3は「3者の折返し閾値がバラバラ」としているが、正確にはAppHeaderは3者のうち唯一「折返し自体をしない」設計であり、この非対称性そのものが未指摘。
- 修正案: 実機/Playwrightで360px・320px幅を先に実測。必要なら600px以下でマイページ文言を非表示にしアイコン化する等の縮退を追加(katazuke.css内で完結、低リスク)。

3件目は根拠強度が上記2件に及ばないため不採用(admin内の他要素はB3-H1/H2に既に包含、bulk入力行はinputのw-full+shrink-0ボタンによりオーバーフロー無しと判定)。
