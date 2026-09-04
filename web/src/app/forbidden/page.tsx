import "../not-found.css";
import { ForbiddenContent } from "./ForbiddenContent";

/**
 * 権限不足ページ（/forbidden）。
 * r3 セキュリティレビュー H-2 是正: middleware.ts が「ログイン済みだが非admin」の
 * ユーザーが /admin 配下を踏んだ際の送り先。/login へ送ると login/page.tsx の
 * 認証済み自動 replace が callbackUrl（/admin配下）へ送り返し、ミドルウェアが
 * 再度弾く無限リダイレクトループになりうるため、再ログインを促さない静的な
 * 案内ページとして分離する。デザインは 404 ページ（not-found.tsx）の
 * カード意匠（.nf-*）を流用し、新規CSSは追加しない。
 *
 * r3 再レビュー N-3 是正: middleware.ts は「ログイン済みだが accountType 不一致」
 * （業者セッションが依頼者向けページを踏んだ等）もここへ送るようになった。
 * ?reason=account_type の出し分けは ForbiddenContent（client, useSearchParams/
 * useSession）に委譲する（metadata export はサーバーコンポーネントでのみ可能なため分離）。
 */
export const metadata = {
  title: "アクセス権限がありません",
};

export default function Forbidden() {
  return <ForbiddenContent />;
}
