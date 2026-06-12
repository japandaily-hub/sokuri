"use client";

/**
 * カタヅケ画面の共有 UI 部品 + セッショントークンフック。
 * Stepper.tsx のビジュアルパターンを 4 ステップ対応に一般化した KdzStepper を含む。
 */

import { useSession } from "next-auth/react";
import { Icon } from "@/components/Icon";
import type {
  CaseStatus,
  ReductionStatus,
  TransactionStatus,
  BidStatus,
} from "@/lib/katadzuke-api";

/** session.accessToken を返す。未ログイン時は null。 */
export function useToken(): { token: string | null; loading: boolean } {
  const { data, status } = useSession();
  return {
    token: data?.accessToken ?? null,
    loading: status === "loading",
  };
}

export function PageShell({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="container-aw py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
          {description ? (
            <p className="mt-1.5 text-sm text-slate-500">{description}</p>
          ) : null}
        </div>
        {actions}
      </div>
      <div className="mt-8">{children}</div>
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function Notice({
  tone,
  children,
}: {
  tone: "info" | "warn" | "error" | "success";
  children: React.ReactNode;
}) {
  const styles = {
    info: "border-sky-200 bg-sky-50 text-sky-800",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    error: "border-red-200 bg-red-50 text-red-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  }[tone];
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm leading-relaxed ${styles}`}>
      {children}
    </div>
  );
}

const BADGE_STYLES: Record<string, string> = {
  open: "bg-sky-100 text-sky-700",
  bidding: "bg-amber-100 text-amber-700",
  closed: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-200 text-slate-500",
  draft: "bg-slate-100 text-slate-500",
  pending: "bg-amber-100 text-amber-700",
  visiting: "bg-sky-100 text-sky-700",
  completed: "bg-emerald-100 text-emerald-700",
  selected: "bg-emerald-100 text-emerald-700",
  rejected: "bg-slate-200 text-slate-500",
  approved: "bg-emerald-100 text-emerald-700",
};

export function StatusBadge({
  value,
  label,
}: {
  value: CaseStatus | TransactionStatus | BidStatus | ReductionStatus | string;
  label: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${
        BADGE_STYLES[value] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {label}
    </span>
  );
}

export const btnPrimary =
  "inline-flex items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary =
  "inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
export const btnDanger =
  "inline-flex items-center justify-center gap-1.5 rounded-xl border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50";
export const inputBase =
  "w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200";

/** Stepper.tsx のパターンを N ステップに一般化した進捗インジケーター。 */
export function KdzStepper({
  labels,
  current,
}: {
  labels: readonly string[];
  current: number;
}) {
  return (
    <ol className="flex items-start" aria-label="進捗">
      {labels.map((label, index) => {
        const isDone = index < current;
        const isActive = index === current;
        const isFirst = index === 0;
        const isLast = index === labels.length - 1;
        return (
          <li key={label} className="flex flex-1 flex-col items-center">
            <div className="flex w-full items-center">
              <span
                className={[
                  "h-[3px] flex-1 rounded-full",
                  isFirst ? "opacity-0" : index <= current ? "bg-brand-600" : "bg-slate-200",
                ].join(" ")}
              />
              <span
                className={[
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-colors",
                  isDone && "bg-brand-600 text-white",
                  isActive && "bg-brand-600 text-white ring-4 ring-brand-100",
                  !isDone && !isActive && "border-2 border-slate-300 bg-white text-slate-400",
                ]
                  .filter(Boolean)
                  .join(" ")}
                aria-current={isActive ? "step" : undefined}
              >
                {isDone ? <Icon name="check" className="h-4 w-4" strokeWidth={3} /> : index + 1}
              </span>
              <span
                className={[
                  "h-[3px] flex-1 rounded-full",
                  isLast ? "opacity-0" : index < current ? "bg-brand-600" : "bg-slate-200",
                ].join(" ")}
              />
            </div>
            <span
              className={[
                "mt-2 text-xs",
                isActive
                  ? "font-semibold text-brand-700"
                  : isDone
                    ? "text-slate-600"
                    : "text-slate-400",
              ].join(" ")}
            >
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
