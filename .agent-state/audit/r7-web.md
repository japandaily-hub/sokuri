# r7 web 回帰監査（対象: `git diff caaca3a HEAD -- web/src`、コミット 1b72a06・f5ffdc5・db32ddd）

編集禁止・読み取り専用で実施。docs/TODO.md 03 記載の既知課題（r6 の意図的未対応・r4/r3 の Low 群）は再指摘しない。

## H1（High）— 案件作成の冪等キーが「戻る→編集→再送信」で使い回され、編集内容が無言で破棄される

- **箇所**: `web/src/app/create/page.tsx:125`（`idempotencyKeyRef` は `useRef` でコンポーネント生存中1個だけ）／同:414-415（未設定時のみ発行、以降は使い回し）／同:429（`idempotency_key: idempotencyKeyRef.current`）／同:435,437（`catch` で `submitting=false` に戻すだけで `idempotencyKeyRef` はクリアしない）／同:854（`戻る` ボタンは `disabled={submitting}` のみで、送信エラー後（`submitting=false`）は常に活性）。
  対応する backend 側の照合は `backend/app/api/v1/endpoints/cases.py:361-372`（同一 `user_id`+`idempotency_key` が `_IDEMPOTENCY_WINDOW`（10分）内に存在すれば **新規作成せず既存案件をそのまま200で返す**。リクエストボディの新しい内容は一切反映されない）。
- **事象**: 送信が一度失敗しても（例: サーバは案件作成に成功したがレスポンスがタイムアウト・回線断で欠落した場合や、成功後の任意のUI起因の一時的エラー表示）、`idempotencyKeyRef` は再利用される。ユーザーが「戻る」で STEP1〜3 に戻り、住所・希望条件・写真を編集してから再度「送信」しても、backend は新しい内容を無視し、**最初の（編集前の）内容の案件**を200で返す。フロントはこれをエラーなく成功として扱い `/cases/{created.id}?created=1` に遷移するため、ユーザーは「編集内容が反映された」と誤認する。
- **再現手順**: (1) `/create` で STEP1〜3 を入力し送信 → ネットワーク断等で `catch` に入り「送信に失敗しました」表示（この時点で backend 側は案件作成に成功している想定、あるいは単に一度目の送信が成立するケースでも同様の窓が開く）。(2) 「戻る」で STEP3 の住所や STEP2 の希望条件を変更。(3) 再度「送信」→ 10分以内なら backend は最初の内容の案件をそのまま返し、編集後の内容は保存されない。エラー表示は出ない。
- **修正案**: `catch` ブロック（同:435 付近）で、少なくとも「案件がまだ存在しない」ことが確実でない限り `idempotencyKeyRef.current` を保持するのは妥当だが、ユーザーが STEP に戻って入力内容を変更した場合（例: `purpose`/`items`/`photos`/住所系 state の変更を検知、または単純に「戻る」ボタン押下時点）で `idempotencyKeyRef.current = null` にリセットし、新しい送信では新しい冪等キーを発行する。あわせて、backend が冪等一致で既存案件を返した場合（`response.status_code === 200`、`cases.py:371`）とフロントが実際に送った内容が食い違う可能性をユーザーに気付かせるため、200 応答時は `created=1` ではなく別クエリ（例 `?resumed=1`）で「以前の送信内容が使われた」旨を案内する経路も検討。

## M1（Medium）— 案件作成の送信が応答しないまま無限に「送信しています…」で停止する退路が消えた

- **箇所**: `web/src/app/create/page.tsx` の diff（caaca3a→HEAD）で `createTimeoutSignal` の import・使用・`timedOut` state・タイムアウト時の案内バナー（`解析に時間がかかっています…`）と `/mypage へ` の脱出リンクが全て削除された（旧: `createCase(payload, token, createTimeoutSignal(180_000))` → 新: `createCase(payload, token)`。第3引数省略）。
  `web/src/lib/katadzuke-api.ts:1450-1455` の `createCase(payload, token, signal?: AbortSignal)` は引数として `signal` を今も受け付けるが、呼び出し元（create/page.tsx）が渡さなくなったため機能していない。`createTimeoutSignal`（同:707 で定義）は web/src 全体で呼び出し箇所ゼロ（デッドコード化）。
- **事象**: 旧実装は「AI解析を同期実行するため長時間化しうる」という前提で180秒の `AbortSignal` タイムアウトを持ち、打ち切り時に「解析に時間がかかっています。しばらくしてからマイページで案件をご確認ください」＋「マイページで確認する」ボタンでユーザーを脱出させていた。r6 で AI 解析は背景化され `POST /cases` 自体は通常即応答するようになったためタイムアウトは不要という設計判断だが、**「即応答するはず」という前提が崩れるケース**（backend 側の一時的な遅延・DBプール枯渇・ネットワーク不調でリクエストそのものが返ってこない場合）に対する保護が一切なくなった。この場合、`submitting=true` のまま `beforeunload` ガード（同ファイル内、離脱確認）も張られた状態で、ユーザーは「送信しています…この画面を閉じないでください」の表示から抜け出す手段を失う（手動でタブを閉じる/リロードする以外に案内された退路がない）。
- **再現手順**: `POST /cases` へのレスポンスが（プロキシ/DB起因で）長時間返らない状況を作る（例: backend 側を一時的に応答遅延させる）→ `/create` から送信 → 「送信しています…」のまま無期限に停止し、以前あった180秒後の代替導線が表示されないことを確認。
- **修正案**: `createCase` 呼び出しに再度 `signal`（例: 30〜60秒程度。AI待ちではなく単純な疎通異常の検知用途に短縮）を渡し、タイムアウト時は「案件が作成されている可能性があります。マイページでご確認ください」の案内とマイページへの導線を復活させる。冪等キー（H1）と組み合わせれば、たとえタイムアウト後に再送信してもH1を先に直していれば安全に再試行できる。

## 確認したが回帰ではなかった主な項目（参考・再掲不要）

- r6-verify-fix.md が「未解消」とした L5（`listTransactions` 呼び出し元の limit 未指定）は、この diff の後続コミットで全呼び出し元（`AppHeaderBell.tsx:89`, `chat/[id]`, `operator/chat/[id]`, `notifications`, `schedule`, `mypage/withdraw`, `mypage`（全件ページング）, `operator/*`）に `limit`/`offset` が付与済みで解消されている。
- 同ドキュメントの N2（`operator/page.tsx` の「交渉中」「成約済み」タブが `hasMoreTxns` を共有し押しても増えない問題）は `loadMoreTxns(kind)` の自動追いページ（`operator/page.tsx:349-386`）で解消済み。`TXN_KIND_MATCH.neg/done`（同:358-360）は実際の表示フィルタ `negotiatingTxns`/`doneTxns`（同:408-415）と一致することを確認。
- `cases/[id]/page.tsx` の AI ポーリング（3秒→15秒、10分打ち切り＋再読み込み導線, 同:272-307）は unmount・`caseId` 切替でタイマーが確実に解除され、`ai_status` が pending から変わらない限り `startedAt` は再初期化されない実装になっており、回帰なし。
- `middleware.ts` の `config.matcher` と `lib/protected-routes.ts` の `USER_PROTECTED_PATHS`/`OPERATOR_PUBLIC_PATHS` は `/vendors` 除去後も一致。`/vendors`, `/vendors/[id]` のページはいずれも `token`/`useToken` を参照しておらず、公開化しても壊れない。
- `admin/_components/ConfirmModal.tsx` の focus trap（Esc/Tab）は `onCancel` を `useEffect(..., [])` で固定参照するが、実際に渡される `closeSuspendModal`/`closeVerifyModal`（`admin/page.tsx:268-281`）は前render依存のクロージャを持たない冪等な state リセットのみのため、stale closure でも挙動は変わらない。
- レイアウト群（`business`/`company`/`condition`/... 各 `layout.tsx`）への `alternates.canonical` 追加は全て既存の静的 `metadata` オブジェクトへのプロパティ追加のみで、`generateMetadata` 新設や title テンプレート構造の変更はなし。`vendors/[id]/layout.tsx` の `generateMetadata` は `params` を正しく `await` している。

## 保存パス

`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r7-web.md`
