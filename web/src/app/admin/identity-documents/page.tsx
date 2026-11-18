/**
 * 管理画面: 本人確認書類の審査は廃止した（受付終了・画像は消去済み）。案内のみを表示する。
 * 表示内容は静的でデータ取得をしないため、権限の強制は backend（/admin 系 API）に任せる。
 * noindex は admin/layout.tsx の metadata で担保する。
 */

import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Card, PageShell, btnSecondary } from "@/components/kdz/Ui";

export default function AdminIdentityDocumentsPage() {
  return (
    <div className="admin-page">
      <AppHeader showBell={false} />
      <PageShell
        title="本人確認書類の審査"
        description="本人確認書類の受付は終了しました。"
        actions={
          <Link href="/admin" className={btnSecondary}>
            管理画面トップへ
          </Link>
        }
      >
        <Card>
          <p className="text-sm text-slate-700">
            本人確認書類の受付を終了しました。提出済みの画像は消去済みです。審査の対応は不要です。
          </p>
        </Card>
      </PageShell>
    </div>
  );
}
