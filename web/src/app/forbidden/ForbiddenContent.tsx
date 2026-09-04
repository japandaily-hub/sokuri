"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { Ic } from "@/components/kdz/Icons";

/**
 * r3 再レビュー N-3 是正: middleware.ts がログイン済みだが accountType 不一致
 * （業者セッションが依頼者向けページを踏んだ等）のセッションをここへ送る際、
 * ?reason=account_type を付与する。ログイン中の accountType に応じて
 * 「どちらのアカウントで、どのページが使えないか」を明示し、/login への
 * 再ログイン誘導（＝無限リダイレクトループの原因）を促さず、状況を理解した上で
 * 自分のアカウント種別向けページへ戻れるようにする。
 */
function ForbiddenBody() {
  const params = useSearchParams();
  const { data: session } = useSession();
  const reason = params.get("reason");
  // r3 再レビュー3回目 是正: 権限不足のまま行き止まりにせず、サインアウトして
  // 別アカウントでログインし直す導線を明示する。
  const [signOutBusy, setSignOutBusy] = useState(false);
  async function onSignOut() {
    setSignOutBusy(true);
    await signOut({ callbackUrl: "/" });
  }

  let line1 = "お使いのアカウントには、このページを表示する権限がありません。";
  let line2 = "URLが正しいかご確認のうえ、トップページからやり直してください。";
  if (reason === "account_type") {
    if (session?.accountType === "operator") {
      line1 = "業者アカウントでログイン中です。";
      line2 = "依頼者向けページは依頼者アカウントでご利用ください。";
    } else if (session?.accountType === "user") {
      line1 = "依頼者アカウントでログイン中です。";
      line2 = "業者向けページは業者アカウントでご利用ください。";
    } else {
      line1 = "現在ログイン中のアカウントでは、このページをご利用いただけません。";
      line2 = "トップページからやり直してください。";
    }
  }

  return (
    <main id="main" className="nf-main">
      <div className="nf-card">
        <div className="nf-icon" aria-hidden="true">
          <Ic name="box" />
        </div>
        <h1 className="nf-title">このページを表示する権限がありません</h1>
        <p className="nf-sub">
          {line1}
          <br />
          {line2}
        </p>

        <Link href="/" className="nf-back">
          <Ic name="arrow" style={{ transform: "scaleX(-1)" }} />
          トップページへ戻る
        </Link>
        {session ? (
          <button
            type="button"
            className="nf-back"
            style={{ marginTop: 8, background: "none", border: "none", cursor: "pointer" }}
            onClick={() => void onSignOut()}
            disabled={signOutBusy}
          >
            {signOutBusy ? "サインアウト中…" : "サインアウトする"}
          </button>
        ) : null}
      </div>
    </main>
  );
}

export function ForbiddenContent() {
  return (
    <Suspense>
      <ForbiddenBody />
    </Suspense>
  );
}
