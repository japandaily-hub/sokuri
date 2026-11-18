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
          <h1 className="text-2xl font-bold text-kdz-ink">{title}</h1>
          {description ? (
            <p className="mt-1.5 text-[15px] text-kdz-bodysoft">{description}</p>
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
      className={`rounded-kdz border border-kdz-line bg-[var(--white)] p-5 ${className}`}
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
    info: "border-kdz-line bg-[var(--indigo-tint)] text-kdz-ink",
    warn: "border-[var(--gold)] bg-[var(--warm)] text-[var(--gold-text)]",
    error: "border-[var(--danger-border-soft)] bg-[var(--danger-bg-soft)] text-kdz-danger",
    success: "border-kdz-line bg-[var(--mint)] text-kdz-green",
  }[tone];
  return (
    <div className={`rounded-kdz-s border px-4 py-3 text-[15px] leading-relaxed ${styles}`}>
      {children}
    </div>
  );
}

/** 状態バッジの配色は4系統（進行中=藍の淡色／要対応=warm／完了=mint／終了・下書き=生成りの濃淡）。 */
const BADGE_ACTIVE = "bg-[var(--indigo-tint)] text-kdz-blued";
const BADGE_ATTENTION = "bg-[var(--warm)] text-[var(--gold-text)]";
const BADGE_DONE = "bg-[var(--mint)] text-kdz-green";
const BADGE_ENDED = "bg-[var(--paper-2)] text-kdz-bodysoft";
const BADGE_STYLES: Record<string, string> = {
  open: BADGE_ACTIVE,
  bidding: BADGE_ATTENTION,
  closed: BADGE_DONE,
  cancelled: BADGE_ENDED,
  draft: BADGE_ENDED,
  pending: BADGE_ATTENTION,
  visiting: BADGE_ACTIVE,
  completed: BADGE_DONE,
  selected: BADGE_DONE,
  rejected: BADGE_ENDED,
  approved: BADGE_DONE,
  unverified: BADGE_ENDED,
  withdrawn: BADGE_ENDED,
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
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-kdz-s px-2.5 py-1 text-[15px] font-bold ${
        BADGE_STYLES[value] ?? BADGE_ENDED
      }`}
    >
      {label}
    </span>
  );
}

export const btnPrimary =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-kdz bg-brand-600 px-5 py-2.5 text-[15px] font-bold text-white transition-colors hover:bg-brand-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-kdz border border-brand-600 bg-transparent px-5 py-2.5 text-[15px] font-bold text-brand-600 transition-colors hover:bg-brand-600 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-50";
export const btnDanger =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-kdz border border-[var(--danger-border-soft)] bg-[var(--white)] px-5 py-2.5 text-[15px] font-bold text-kdz-danger transition-colors hover:bg-[var(--danger-bg-soft)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-50";
export const inputBase =
  "w-full rounded-kdz border border-[var(--line-input)] bg-[var(--white)] px-3.5 py-2.5 text-[15px] text-kdz-ink placeholder:text-kdz-bodysoft focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200";

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
                  "h-[3px] flex-1 rounded-none",
                  isFirst ? "opacity-0" : index <= current ? "bg-brand-600" : "bg-kdz-line",
                ].join(" ")}
              />
              <span
                className={[
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-bold transition-colors",
                  isDone && "bg-brand-600 text-white",
                  isActive && "bg-brand-600 text-white ring-4 ring-brand-50",
                  !isDone && !isActive && "border-2 border-[var(--line-strong)] bg-[var(--white)] text-kdz-bodysoft",
                ]
                  .filter(Boolean)
                  .join(" ")}
                aria-current={isActive ? "step" : undefined}
              >
                {isDone ? <Icon name="check" className="h-4 w-4" strokeWidth={3} /> : index + 1}
              </span>
              <span
                className={[
                  "h-[3px] flex-1 rounded-none",
                  isLast ? "opacity-0" : index < current ? "bg-brand-600" : "bg-kdz-line",
                ].join(" ")}
              />
            </div>
            <span
              className={[
                "mt-2 text-[15px]",
                isActive
                  ? "font-bold text-brand-700"
                  : isDone
                    ? "text-kdz-body"
                    : "text-kdz-bodysoft",
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
