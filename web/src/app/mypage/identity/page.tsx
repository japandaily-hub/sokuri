/**
 * 本人確認書類の受付終了のお知らせ（/mypage/identity）。
 * 個人情報の取得を最小限にするため、本人確認書類の画像の受付は終了した（提出済みの画像も消去済み）。
 * 訪問時の本人確認は、古物営業法に基づき買取業者が現地で行う。静的な案内のためログイン必須ガードは置かない。
 * noindex は周囲の /mypage 配下と同じく mypage/layout.tsx の metadata で担保する。
 */

import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import "./identity.css";

const ICON_SHIELD = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3l7 3v6c0 4.7-3 7.9-7 9-4-1.1-7-4.3-7-9V6z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
);

export default function IdentityPage() {
  return (
    <div className="identity-page">
      <AppHeader />
      <main id="main">
        <div className="identity-wrap">
          <div className="edit-section-title">
            {ICON_SHIELD}
            本人確認書類の受付は終了しました
          </div>

          <div className="form-card">
            <p className="id-status-desc">
              本人確認書類の受付は終了しました。これまでにご提出いただいた画像は消去しました（システムのバックアップに残る分も、保存期間の経過後に消去されます）。
            </p>
            <p className="id-status-desc">
              古物営業法で定める場合には、買取業者が訪問時に本人確認を行います。
            </p>
          </div>

          <div style={{ marginTop: 4 }}>
            <Link href="/mypage" className="id-back-link">
              ← マイページにもどる
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
