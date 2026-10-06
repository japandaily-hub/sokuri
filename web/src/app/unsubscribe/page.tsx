"use client";

/** メールの受け取りについてのご案内（/unsubscribe）。
 * カタヅケが送るのは取引に必要な通知のみで、広告宣伝メールは送らない。
 * 抑制リスト等のバックエンド実装は存在しないため、このページでは
 * 「配信停止を受け付けた」という事実に反する表示は行わず、
 * 通知設定（/notifications）と退会（/mypage/withdraw）へ案内する。
 *
 * デザインレビュー A-2 対応: 完了系画面（signup/create-complete）と同じ
 * 共通 .form-card/.btn の語彙に揃える。ヘッダー/フッターは他の静的ページ
 * （terms/contact 等）と同様、共通 SiteChrome のマーケ用クロムのままとする。
 */

import "./unsubscribe.css";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

function UnsubscribeContent() {
  const params = useSearchParams();
  const email = params.get("email") ?? "";

  return (
    <main id="main" className="unsub-page">
      {/* N-10（2周目監査）: スキップリンク（#main）の飛び先を持たせる。 */}
      <div className="form-card">
        <h1>メールの受け取りについて</h1>
        <p>
          カタヅケからお送りするのは、出品の受付・入札のお知らせ・成約・訪問日程のご連絡など、
          <strong style={{ color: "var(--navy)" }}>お取引に必要な通知のみ</strong>
          です。広告・宣伝を目的としたメールをお送りすることはありません。
        </p>
        {email ? (
          <p>
            <strong style={{ color: "var(--navy)" }}>{email}</strong> 宛てのご連絡についても同様です。
          </p>
        ) : null}
        <p>
          通知の受け取り方（メール・LINE）は、マイページの
          <Link href="/notifications">通知設定</Link>
          から変更できます。
        </p>
        <p>
          アカウントそのものの削除をご希望の場合は、
          <Link href="/mypage/withdraw">退会手続き</Link>
          からお手続きください。
        </p>
        {/* N-5（2周目監査・中）: 「法令上の期間を除き遅滞なく削除」は実装・プライバシーポリシー第8条と合わない
            （残す記録の理由は法令ではなく取引の整合と紛争への対応。保存期間の定めもない）。第8条の要旨に揃えて参照させる。 */}
        <p>
          退会されると、氏名・電話番号・住所・振込口座・本人確認書類の画像などを消去します。出品の内容や入札・取引・チャット・評価の記録は、取引の相手方の記録でもあるため、取引の整合と紛争への対応のために残します。消去する情報と残す記録の詳細は、
          <Link href="/privacy#pp-8">プライバシーポリシー 第8条</Link>
          をご覧ください。
        </p>
        <div style={{ marginTop: 28 }}>
          <Link href="/" className="btn btn-primary">
            トップへ戻る
          </Link>
        </div>
      </div>
      <p className="unsub-footnote">
        ご不明な点は <a href="mailto:katazuke.info@gmail.com">katazuke.info@gmail.com</a> までお問い合わせください。
      </p>
    </main>
  );
}

export default function UnsubscribePage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "50vh", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "var(--body-soft)" }}>処理中…</div>}>
      <UnsubscribeContent />
    </Suspense>
  );
}
