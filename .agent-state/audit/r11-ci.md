# r11 CI 新設 (2026-09-05)

- `.github/workflows/ci.yml` 新設: push(main)/PR で backend(pytest) と web(tsc/eslint/next build) を並列実行。concurrency でブランチ内旧実行キャンセル、各20分タイムアウト。
- backend: setup-python 3.12 + pipキャッシュ → `pip install -e ".[dev]"` → `pytest -q`。秘密情報不要（conftest.pyが自前でAPP_ENCRYPTION_KEY等をsetdefault）。
- web: setup-node 20 + npmキャッシュ → `npm ci` → `tsc --noEmit` → `eslint src`（警告許容・エラーのみ失敗）→ `next build`。build用にダミー env（NEXT_PUBLIC_API_URL/AUTH_SECRET/APP_BASE_URL）。LINE_CLIENT_ID等は未設定で問題なし（fail-safe設計済み）。
- `docs/TODO.md` 04に「CIが赤ならpush止める」を追記。
- ローカル検証: pytest 855 passed（197s）／tsc --noEmit エラー0／eslint src エラー0。YAML構文は `yaml.safe_load` でOK。next build 自体はローカル未実行（正本の.nextを壊さないため、指示通り）。
