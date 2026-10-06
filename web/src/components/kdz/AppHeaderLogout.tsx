"use client";

import { signOut } from "next-auth/react";
import { clearAllUserLocalState } from "@/lib/user-local-state";
import { clearHeaderBellCache } from "./AppHeaderBell";

export function AppHeaderLogout() {
  return (
    <button
      type="button"
      onClick={() => {
        clearHeaderBellCache();
        // 共用端末で次の人に下書き・既読を見せない（security L-5・L-6）。
        clearAllUserLocalState();
        void signOut({ callbackUrl: "/" });
      }}
      className="inline-flex min-h-[44px] items-center px-1 text-[14px] font-semibold text-kdz-bodysoft transition-colors hover:text-kdz-blue"
    >
      ログアウト
    </button>
  );
}
