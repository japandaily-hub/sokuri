"use client";

import { signOut } from "next-auth/react";
import { clearHeaderBellCache } from "./AppHeaderBell";

export function AppHeaderLogout() {
  return (
    <button
      type="button"
      onClick={() => {
        clearHeaderBellCache();
        void signOut({ callbackUrl: "/" });
      }}
      className="inline-flex min-h-[44px] items-center px-1 text-[14px] font-semibold text-kdz-bodysoft transition-colors hover:text-kdz-blue"
    >
      ログアウト
    </button>
  );
}
