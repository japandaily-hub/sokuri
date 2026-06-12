"use client";

import Link from "next/link";
import { SessionProvider, signOut, useSession } from "next-auth/react";
import { Icon } from "@/components/Icon";

function NavInner() {
  const { data: session, status } = useSession();

  const cta = (
    <Link
      href="/create"
      className="inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
    >
      <Icon name="camera" className="h-4 w-4" />
      無料で査定
    </Link>
  );

  if (status === "loading") return cta;

  if (!session) {
    return (
      <div className="flex items-center gap-3">
        <Link
          href="/login"
          className="hidden text-sm font-medium text-slate-700 transition-colors hover:text-brand-700 sm:inline"
        >
          ログイン
        </Link>
        {cta}
      </div>
    );
  }

  const isOperator = session.accountType === "operator";
  const links = isOperator
    ? [
        { href: "/operator/cases", label: "案件一覧" },
        { href: "/operator/transactions", label: "落札管理" },
      ]
    : [
        { href: "/cases", label: "マイ案件" },
        ...(session.role === "admin" ? [{ href: "/admin", label: "管理" }] : []),
      ];

  return (
    <div className="flex items-center gap-3">
      {links.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className="hidden text-sm font-medium text-slate-700 transition-colors hover:text-brand-700 sm:inline"
        >
          {l.label}
        </Link>
      ))}
      <button
        type="button"
        onClick={() => signOut({ callbackUrl: "/" })}
        className="hidden text-sm font-medium text-slate-500 transition-colors hover:text-slate-700 sm:inline"
      >
        ログアウト
      </button>
      {isOperator ? null : cta}
    </div>
  );
}

export function HeaderNav() {
  return (
    <SessionProvider>
      <NavInner />
    </SessionProvider>
  );
}
