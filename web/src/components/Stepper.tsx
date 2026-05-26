/**
 * 査定フローの進捗ステッパー。
 * analyzing / condition / result の 3 画面で共通利用し、現在地を明示する。
 */

import { Icon } from "@/components/Icon";

/** ステップ定義（順序固定） */
const STEPS = ["画像解析", "コンディション", "査定額"] as const;

interface StepperProps {
  /** 現在のステップ: 0=画像解析, 1=コンディション, 2=査定額 */
  current: 0 | 1 | 2;
}

/**
 * 3 段階の進捗インジケーター。完了・現在・未到達を視覚的に区別する。
 */
export function Stepper({ current }: StepperProps) {
  return (
    <ol className="flex items-start" aria-label="査定の進捗">
      {STEPS.map((label, index) => {
        const isDone = index < current;
        const isActive = index === current;
        const isFirst = index === 0;
        const isLast = index === STEPS.length - 1;

        return (
          <li key={label} className="flex flex-1 flex-col items-center">
            <div className="flex w-full items-center">
              {/* 左の連結線 */}
              <span
                className={[
                  "h-[3px] flex-1 rounded-full",
                  isFirst ? "opacity-0" : index <= current ? "bg-brand-600" : "bg-slate-200",
                ].join(" ")}
              />

              {/* ステップ番号 / 完了マーク */}
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

              {/* 右の連結線 */}
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
                isActive ? "font-semibold text-brand-700" : isDone ? "text-slate-600" : "text-slate-400",
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
