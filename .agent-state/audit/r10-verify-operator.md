# r10 運営導線監査の独立検証（2026-09-05）

対象台帳: `.agent-state/audit/r10-operator.md`（High 3・Medium 9）。立案者と無関係に file:line を実読して判定。
判定基準: 事実性 → 重大度較正 → 最小修正。迷えば却下寄り。編集は本ファイルの Write のみ。

## 集計

| 判定 | 件数 |
|---|---|
| CONFIRMED | 8（H-1, M-1, M-2, M-3, M-4, M-5, M-6, M-9） |
| PARTIAL | 4（H-2, H-3, M-7, M-8） |
| REJECTED | 0 |
| 重大度の修正 | 4（H-2 High→Medium／H-3 High→Medium／M-7 Medium→Low／M-8 Medium→Low） |
| 追加 High | 2（ADD-H1, ADD-H2） |

---

## High

### H-1 強制終了メールの着地ページに理由が無い → **CONFIRMED（High 維持）**

事実性は完全に一致する。

- `backend/app/services/notify.py:315-338` — `send_transaction_cancelled_by_admin` は
  `path = f"/chat/{transaction_id}" if recipient_party == "user" else f"/operator/transactions/{...}"`、
  本文は「詳細と理由を確認する」。docstring 自身が「理由は画面（成約詳細の cancellation）で確認してもらう」と宣言している。
- `web/src/app/chat/[id]/page.tsx` — `grep -n "cancellation"` の**ヒット 0 件**。`:388-392` は
  「この取引は終了しています（{TXN_STATUS_LABEL}）」のみ。メールが約束した「理由」はこのページに存在しない。
- 対照 `web/src/app/operator/transactions/[id]/page.tsx:194-204` — `txn.cancellation` の
  `cancelled_by` / `cancelled_at` / `reason` を表示（コメントに「r8-fix-frontend2 H2 是正: キャンセルの理由が
  相手方に一切届かなかった問題への対応」）。業者側だけ是正され、依頼者側が取り残されている。
- `backend/app/api/v1/endpoints/admin.py:729-745` — 理由必須の宣言（summary「理由必須・当事者双方へ通知」）。

**最小修正の判定（台帳より踏み込む）**: 台帳は「`/cases/{case_id}` へ変更 or chat に表示」を並置し後者推奨としているが、
**前者は実質的に不可**である。`send_transaction_cancelled_by_admin(to_email, transaction_id, recipient_party)` は
`case_id` を持たず、呼び出し元・`notify_dispatch` まで引数を通す改修が要る。一方 chat 側は
`web/src/app/chat/[id]/page.tsx:99` が既に `useState<TransactionDetail | null>` を保持し、
`web/src/lib/katadzuke-api.ts:292` の `TransactionDetail` に `cancellation: TransactionCancellation | null` が
**既に存在**する（backend も `schemas_katadzuke.py:768` で返済み）。したがって
**フロント 1 ファイルへの描画ブロック追加のみで完結**し、API・型・通知の変更は一切不要。後者が唯一の最小構成。

**スコープ拡大（台帳の見落とし）**: 同じ欠陥が `notify.py:300-312` の `send_transaction_cancelled`
（**当事者間のキャンセル**）にもある。こちらも依頼者を `/chat/{id}` へ送り「詳細を確認する」と書くが理由は出ない。
修正は同一ブロック 1 個で両方に効くため、H-1 の是正範囲は「運営の強制終了」に限定せず記述すべき。

### H-2 `degraded_config` を外形監視が使っていない → **PARTIAL（High → Medium）**

**構造の指摘は事実**:
- `backend/app/main.py:308-316` — 「未設定があっても status は ready のまま維持する」とコメントで明示。
- `scripts/uptime_check.py:78-89` — `ok = status == 200 and data.get("status") == "ready" and data.get("db") == "ok" and head_ok`。
  `degraded_config` の参照は皆無。
- `docs/ops/alerting.md:45-49`（検知条件 > 外形監視）に `degraded_config` の記載なし。全文確認済み。

**しかし影響の記述が誤り**。台帳は「BREVO_API_KEY 失効・未設定は 100% 緑のまま無通知で進行する」と断定するが、
`backend/app/services/notify.py:67-82` は **キー未設定を検知して `severity="critical"` のアラートを発火**する
（`key="notify_brevo_api_key_missing"`、初回のみ）。さらに `:98-115` は送信時の 401／429／402 を捕捉して
「メール送信に失敗しています（Brevo）」を発火する（コメントに「r6 H-3」と明記＝既に是正済みの論点）。
つまり台帳が根拠に挙げた 2026-09-04 の実障害クラスは、現在は**別経路で検知される**。

真に無検知のまま残るのは `admin_emails`（`contact.py:194-199` は未設定時 `logger.warning` のみで問い合わせが黙って消える）と
`frontend_base_url` の localhost 混入。これは実害があるが、台帳が主張する「メール全断が無検知」ではない。
**Medium が妥当**。修正案（`uptime_check.py` に `degraded_config` 非空で Warning）は 3 行で正しく、そのまま採用可。
`docs/ops/alerting.md:49` の直後に 1 行追記も妥当。

### H-3 アラート基盤の死活が検証できない → **PARTIAL（High → Medium）**

**根拠 3 点のうち 1 点が古い**。台帳は `alerts.py:186`「`fire_and_forget` は例外を握るだけ」を挙げるが、
実コードは `alerts.py:183-186` で `_inflight_tasks.add(task)` により**強参照を保持済み**
（「GC 回収による送信取りこぼし防止」とコメント。`docs/TODO.md:35,36-④` の「Task 参照を保持しない」は既に陳腐化）。
残る 2 点は事実: `alerts.py:66-70`（メール未設定は `logger.info` でスキップ）、`:97-118`（LINE 失敗は `logger.error` のみ、
戻り値 `ok` はどこでも判定されない）、`main.py:140-146`（`_config_readiness` に `alert_*` なし）。

**部分的な緩和が既にある**: `_config_readiness` の `brevo` はアラートメールと同一キーを見ているため、
アラート経路の 1/3 は既に `/readyz` から可視である。また `.github/workflows/uptime-alert.yml:12-17,49-66` に
`force_notify` の手動疎通テストがあり、`docs/ops/alerting.md`「動作確認手順」1 が初期設定時の検証を規定している。
欠けているのは**継続的な**デッドマンスイッチのみ。

**修正案 (a) は単独では無効**: `_config_readiness` に `alerts_channel` を足しても、H-2 が未修正なら
`uptime_check.py` はそれを読まない。(a) は H-2 の修正を前提とする依存関係を明記すべき。
実効性は (b) の週次 heartbeat がほぼ全てであり、しかも下記 ADD-H1 の方が同じ目的をより確実に達成する。
**Medium が妥当**。

---

## Medium

### M-1 本人確認の審査待ちがバッジにも通知にも出ない → **CONFIRMED（Medium 維持）**
`admin.py:1358-1363` は `response_model=list[UserIdentityDocumentAdminOut]`（`total` 不在）。
`web/src/app/admin/identity-documents/page.tsx:281` が `total={null}`。
`web/src/app/admin/page.tsx:390-400` は事前申込に赤バッジ、`:410-412` の「本人確認書類の審査へ」は素の Link。
`backend/app/api/v1/endpoints/user_identity.py:167-180` の `submit_identity_document` に `notify`／`alerts` 呼び出しなし。
**補強**: 同ページ `:285-286` の Pager は `onNext={() => setOffset(offset + LIMIT)}` で上限を持たないため、
`total` 不在は「末尾を越えて空ページに着地し、審査待ちゼロと誤読する」経路も生む。修正案（`{items,total}` 化）で同時に解消。

### M-2 tie-breaker 欠落 → **CONFIRMED（Medium 維持）**
`admin.py:1392` は `.order_by(UserIdentityDocument.submitted_at.desc())` 単独。
対照 `:884-886` は `.order_by(User.created_at.desc(), User.id.desc())` でコメントに「QA M3対応」と是正理由まで書かれており、
本人確認一覧だけがその横展開から漏れている。修正案（`, UserIdentityDocument.id.desc()` 追加）は 1 行で正しい。

### M-3 検索 `q` が無い → **CONFIRMED（Medium 維持）**
`admin.py:1363-1372` のシグネチャは `status_filter` / `limit` / `offset` / `admin` / `session` のみ。
対照 `admin_list_users`（`:844-872`）は email/name の `ilike`（`_escape_ilike_value` で無害化）+ UUID 厳密一致を実装済み。
`stmt` は既に `User` を JOIN 済み（`:1385`）なので、`or_` 節を 1 個足すだけで流用できる。修正案は妥当。

### M-4 pending に「許可証提出済み」の内訳が無い → **CONFIRMED（Medium 維持）**
`admin.py:250-258` の `status_filter` は `Literal["all","pending","limited","active","rejected","suspended"]` で許可証軸なし。
`admin.py:372-375` が `has_license_image` 偽で 409。`schemas_katadzuke.py:111-124` の `OperatorListCounts` は
`all/pending/limited/active/rejected/suspended` の 6 フィールドで、承認可能件数を表現できない。
`web/src/app/admin/page.tsx:362-369` の counts ボタン列も同じ 6 軸。
修正案（`OperatorListCounts` に 1 フィールド追加＝`case(...)` 1 個）が最小で正しい。

### M-5 依頼者一覧の `include_deleted`／停止絞り込み欠落 → **CONFIRMED（Medium 維持）**
`web/src/lib/katadzuke-api.ts:2014-2019` — `params: Pick<AdminListParams, "q" | "limit" | "offset">` で型レベルに閉じている。
`admin.py:847-852` — backend は `include_deleted: bool = Query(default=False, ...)` を実装済み。
`admin_list_users` の引数に `suspended` フィルタは無く（`:844-853` を実読）、業者側の
`status=suspended`（`:251-256`）と非対称。**backend 実装済みの機能がフロント型で殺されている**点で、
修正コストが最小（型の `Pick` 拡張 + トグル）の割に効果が大きい。

### M-6 停止解除依頼の受け皿が無い → **CONFIRMED（Medium 維持）**
`backend/app/api/deps.py:79-83` — `SUSPENDED_ACCOUNT_DETAIL` は「お問い合わせ窓口までご連絡ください。」。
`backend/app/api/v1/endpoints/contact.py:194-212` — `admin_emails` へ `background.add_task(notify.send_contact_received, ...)`
のみで、**DB 保存処理は一切無い**（関数末尾は `return ContactCreateResponse(ok=True)`）。
`docs/TODO.md:36-②` は `/contact` の**レート上限**の話であり本件と別論点のため、重複による REJECT には当たらない。
「当面の回避は M-5 の停止中フィルタ」という段階的提案は運用上正しい。

### M-7 `docs/LINE_SETUP.md` の陳腐化 → **PARTIAL（Medium → Low）**
`docs/LINE_SETUP.md:6` の「Render は `LINE_CLIENT_ID` 未設定（exchange が 503）」は陳腐化が**確定**
（`docs/TODO.md:62`「exchange が 503→401 に変わり LINE_CLIENT_ID 設定済みを確認」）。
しかし同じ 6 行目の「`LINE_CHANNEL_ACCESS_TOKEN` 未設定」は**誤りと断定できない**。
`TODO.md:62` は「LINE_CHANNEL_ACCESS_TOKEN（push 用）は外形から確認できないため、実際に通知が届くことを
1 回実機で確認推奨」と明示しており、未検証のまま残っている。台帳が主張する被害
（「設定済みを未設定と誤認して再発行し稼働中の通知を壊す」）は、この半分については前提が立たない。
Low が妥当。修正案（「現状」節を削除し確認手順だけ残す）は方向として正しく、そのまま採用可。

### M-8 管理者追加の runbook が無い → **PARTIAL（Medium → Low）**
事実は確認: `ls docs/ops/` = `alerting.md` の 1 本のみ。`docs/TODO.md:12`（01-6 末尾）の
「2人目以降の管理者は管理画面『管理者にする』で追加する」が唯一の記述。
ただし**運用上の到達性は担保されている**: 経路は `/admin/users` の画面上に露出しており、
`admin.py:1017-1022` の docstring が前提条件を記述し、`admin.py:1046-1060, 1103-1114` が
昇格・降格で critical アラートを発火するため、誤操作は事後に必ず可視化される。
文書化されていないことによる**実害の経路が無い**ため Low。新設案の内容（①〜③）は妥当。

### M-9 業者オンボーディング文書の欠落 → **CONFIRMED（Medium 維持）**
`docs/beta-operator-onboarding.md` 全文確認。手順 4 は「入札は運営の承認後（通常3営業日以内・許可証画像の提出が
必要）」で止まり、提出先の記載なし。「■ 減額申請について（重要）」節にも回数上限の記載なし。
`backend/app/api/v1/endpoints/reductions.py:35` — `_MAX_REDUCTION_REQUESTS = 2`、`:109-113` が
409「減額申請は1つの取引につき2回までです。」を返す。M-4 との因果（提出先不明 → pending 滞留 → 承認可能件数不明）も成立。

---

## 追加の High（同観点で台帳が見落としたもの）

### ADD-H1. 外形監視の通知が**全チャネル失敗しても**「通知: なし」としか記録されず、正常時と区別できない
- 重大度: High
- 根拠: `scripts/uptime_check.py:193-233` — `sent = notify(...)` の**戻り値をどこでも判定していない**。
  `notify()`（`:117-152`）は各チャネルの成否を `sent` に積むだけで、全滅時は空リストを返す。
  `main()` は `:233` で `f"状態: {status} / 通知: {', '.join(sent) if sent else 'なし'}"` と書き `:235` で常に `return 0`。
  正常時（通知不要）の Step Summary も「通知: なし」であり、**障害検知に成功したが 1 通も送れなかった実行と
  文字列が完全に一致する**。`_post_json`（`:106-114`）の失敗は stderr の 1 行のみで、終了コードにも Summary にも出ない。
- なぜ High か: H-3 が指摘する「アラート基盤の死亡」の中で、**唯一その場で機械的に判定できる**シグナルを
  握り潰している。ALERT_LINE トークン失効・Brevo の Authorised IPs 制限・Secrets の消失のいずれでも、
  障害発生時に運営へ何も届かず、GitHub Actions は緑のまま残る。
- 最小修正: `main()` 末尾で `if (failures or slow_transition) and not sent:` を判定し、
  (a) Step Summary に `**通知全滅**` 行を追加、(b) `return 1` にして Actions の実行を赤くする
  （GitHub の workflow 失敗メールが最後の砦になる）。docstring `:21` の「終了コード: 常に 0」は
  「通知に成功した限り 0」へ改める。H-3 の週次 heartbeat より確実かつ実装が小さい。

### ADD-H2. Brevo が 201 を返して受理後に破棄する経路は、H-2 の修正案を入れても検知できない
- 重大度: High
- 根拠: `docs/ops/alerting.md`「Brevo（メール）で実際に詰まった点」節が
  「未認証の差出人からの送信は Brevo が受理後に『rejected（sender not validated）』で捨てる
  （API は 201 を返すので気づきにくい）」と**実経験として記録**している。
  この経路は `notify.py:89-97` の `res.raise_for_status()` を通過するため `:98-115` の失敗アラートに掛からず、
  `main.py:140-146` の `brevo`（`bool(settings.brevo_api_key)`）にも掛からない。
  さらに同節は「本番の差出人 `noreply@katadzuke.jp` はドメイン未認証のため送れない。当面 `MAIL_FROM` と
  `ALERT_MAIL_FROM` を `katazuke.support@gmail.com` にしている」と記しており、**差出人設定が 1 箇所ずれた瞬間に
  全メールが無言で消える構成が現に本番で動いている**。
- なぜ High か: H-2 の修正（`degraded_config` を監視に載せる）を入れても閉じない残穴であり、
  かつ 2026-09-04 に実際に踏んだ失敗モードと同一クラス。「修正したのに再発する」を生む。
- 最小修正: `uptime_check.py` に日次 1 回（`cron` の分岐 or 別 workflow）
  `GET https://api.brevo.com/v3/smtp/statistics/events?limit=50` を叩き、`event` に
  `error` / `blocked` / `hardBounce` が含まれていたら Warning 通知。Brevo の既存 API キーで足り、追加の秘密情報は不要。
  併せて `alerting.md` の「今後の拡張候補」に置かれている「通知メール送信失敗」を本節へ格上げする。

---

## 台帳の付表（1日の業務一覧・通知一覧・実務量・PII）について

抜き取り検証した範囲では誤りなし。ただし 2 点の補正が必要。
- 「本番設定の欠落（Brevo/LINE/暗号鍵）| 通知 ✗」の行は不正確。Brevo に限り
  `notify.py:67-82, 98-115` の critical アラートが存在する（H-2 参照）。
- 「成約の強制終了 | 双方 | △」の脚注は、当事者間キャンセル（`notify.py:300-312`）にも同じ △ が付く。

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r10-verify-operator.md`

## サマリ
- ❌ 実修正が要る High は **H-1（chat 側 1 ファイルの描画追加で完結）／ADD-H1（通知全滅の無警告）／ADD-H2（Brevo の 201 後破棄）** の 3 件
- ⚠️ H-2・H-3 は構造の指摘としては正しいが影響を過大評価しており Medium へ降格（H-3 の修正案 (a) は H-2 の修正に依存）。M-7・M-8 は実害経路が無く Low へ降格
- ✅ M-1〜M-6・M-9 は file:line まで一致し、修正案も最小構成として妥当。REJECTED（`docs/TODO.md` 03 との重複・事実誤認）は 0 件
