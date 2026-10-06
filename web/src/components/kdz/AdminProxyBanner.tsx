"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { shouldDisableChatInput, shouldShowProxyBanner } from "@/lib/admin-proxy";

/**
 * 運営（role=admin）が依頼者・業者向け画面を開いているときに、画面上部へ出す「代理閲覧中」の帯。
 * 共通レイアウト（app/layout.tsx）に 1 行で差し込む。運営以外・/admin 配下・公開ページでは何も描かない。
 *
 * チャット系画面では、運営の送信欄を使えなくする処理は ChatPanel／業者チャットの `readOnly`（呼び出し側が
 * 運営ロールを判定して渡す）が担う。ここは帯の文言だけを出す（DOM 属性の後付けはしない。backend の 403 は最終防衛）。
 */
export function AdminProxyBanner() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const role = session?.role;
  const visible = shouldShowProxyBanner(pathname, role);
  const disableChat = shouldDisableChatInput(pathname, role);

  if (!visible) return null;
  return (
    <div
      role="status"
      className="border-b border-amber-400 bg-amber-100 px-4 py-2 text-center text-sm text-amber-950"
      data-testid="admin-proxy-banner"
    >
      <strong className="font-semibold">運営が代理で閲覧中です。</strong>
      この画面は依頼者・業者の画面そのままで、確定・変更などの操作は当事者に反映されます。
      {disableChat ? "チャットは運営として送信できないため、入力欄を無効にしています。" : null}{" "}
      <Link href="/admin" className="underline">
        運営画面へ戻る
      </Link>
    </div>
  );
}
