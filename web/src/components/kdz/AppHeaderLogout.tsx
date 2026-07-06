"use client";

import { signOut } from "next-auth/react";

export function AppHeaderLogout() {
  return (
    <button
      type="button"
      onClick={() => signOut({ callbackUrl: "/" })}
      className="text-[14px] font-semibold text-kdz-bodysoft transition-colors hover:text-kdz-blue"
    >
      ログアウト
    </button>
  );
}
