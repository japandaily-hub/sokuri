"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { shouldDisableChatInput, shouldShowProxyBanner } from "@/lib/admin-proxy";

/** チャット入力欄（ChatPanel の .input-area）。ChatPanel 本体は別担当の所有のため、DOM 側から無効化する。 */
const CHAT_INPUT_SELECTOR = ".chat-main .input-area";
const DISABLED_TITLE = "運営は代理で送信できません";

/**
 * 運営（role=admin）が依頼者・業者向け画面を開いているときに、画面上部へ出す「代理閲覧中」の帯。
 * 共通レイアウト（app/layout.tsx）に 1 行で差し込む。運営以外・/admin 配下・公開ページでは何も描かない。
 *
 * チャット系画面では、運営の送信が依頼者名義として保存されてしまう（backend 側は別途是正予定）ため、
 * 送信欄を無効化（inert）して「運営は代理で送信できません」と示す。ChatPanel は非改変のまま、
 * MutationObserver で描画後の入力欄に属性を付ける（admin 以外ではこの処理自体を走らせない）。
 */
export function AdminProxyBanner() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const role = session?.role;
  const visible = shouldShowProxyBanner(pathname, role);
  const disableChat = shouldDisableChatInput(pathname, role);

  useEffect(() => {
    if (!disableChat) return;
    const lock = () => {
      document.querySelectorAll<HTMLElement>(CHAT_INPUT_SELECTOR).forEach((el) => {
        if (el.hasAttribute("inert")) return;
        el.setAttribute("inert", "");
        el.setAttribute("title", DISABLED_TITLE);
        el.style.opacity = "0.45";
      });
    };
    lock();
    const observer = new MutationObserver(lock);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      document.querySelectorAll<HTMLElement>(CHAT_INPUT_SELECTOR).forEach((el) => {
        el.removeAttribute("inert");
        el.removeAttribute("title");
        el.style.opacity = "";
      });
    };
  }, [disableChat]);

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
