/**
 * PhotoGuide — 1 商品に対する推奨撮影アングルガイド。
 *
 * 設計:
 * - 必須ではなくレコメンド表示。ユーザーは 1 枚でも進める。
 * - 撮影済みアングルにチェックを付け、達成感を演出（型番ラベル撮影率向上）。
 * - 状態を親から受け取るピュアな表示コンポーネント（Server / Client 両対応）。
 *
 * Phase 3 で「1 商品 = N 枚」化する際は、このコンポーネントの shotsCompleted を
 * 動的に更新する形に拡張する。現状（1 商品 = 1 枚）では参考表示のみ。
 */

import { Icon, type IconName } from "@/components/Icon";

export interface PhotoAngleHint {
  /** 内部識別子 */
  key: string;
  /** ラベル（UI 表示） */
  label: string;
  /** 補足説明 */
  hint: string;
  /** アイコン */
  icon: IconName;
  /** 必須か推奨か（true なら強調） */
  important: boolean;
}

const ANGLE_HINTS: PhotoAngleHint[] = [
  {
    key: "front",
    label: "正面",
    hint: "商品全体が枠内に収まるように",
    icon: "image",
    important: true,
  },
  {
    key: "back",
    label: "背面",
    hint: "型番シール・銘板が読める明るさで",
    icon: "scan",
    important: true,
  },
  {
    key: "side",
    label: "側面・上下",
    hint: "厚みや角の状態が分かる斜め写真",
    icon: "device",
    important: false,
  },
  {
    key: "label",
    label: "型番ラベル",
    hint: "メーカー名・型番・製造年が刻印された箇所",
    icon: "sparkle",
    important: true,
  },
  {
    key: "defect",
    label: "傷の接写",
    hint: "傷・汚れ・破損がある箇所を真上から接写",
    icon: "alert",
    important: false,
  },
];

interface PhotoGuideProps {
  /** 既に撮影済みのアングル key（チェックを付ける） */
  shotsCompleted?: string[];
  /** 簡易表示モード（折りたたみ前提） */
  compact?: boolean;
}

export function PhotoGuide({ shotsCompleted = [], compact = false }: PhotoGuideProps) {
  const completedSet = new Set(shotsCompleted);

  return (
    <details
      className="group rounded-xl border border-slate-200 bg-white px-3.5 py-3 open:bg-slate-50"
      open={!compact}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <Icon name="sparkle" className="h-4 w-4 text-brand-600" />
          査定精度を上げる撮影ガイド
          <span className="ml-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
            {completedSet.size}/{ANGLE_HINTS.length}
          </span>
        </span>
        <Icon
          name="chevron-down"
          className="h-4 w-4 shrink-0 text-slate-500 transition-transform group-open:rotate-180"
          strokeWidth={2.25}
        />
      </summary>

      <ul className="mt-3 space-y-2">
        {ANGLE_HINTS.map(({ key, label, hint, icon, important }) => {
          const done = completedSet.has(key);
          return (
            <li
              key={key}
              className={[
                "flex items-start gap-2.5 rounded-lg border px-3 py-2 transition-colors",
                done
                  ? "border-accent-200 bg-accent-50"
                  : important
                    ? "border-brand-200 bg-brand-50/40"
                    : "border-slate-200 bg-white",
              ].join(" ")}
            >
              <span
                className={[
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                  done ? "bg-accent-600 text-white" : "bg-white text-brand-600 ring-1 ring-brand-100",
                ].join(" ")}
              >
                <Icon
                  name={done ? "check" : icon}
                  className="h-4 w-4"
                  strokeWidth={done ? 2.75 : 2}
                />
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-900">
                  {label}
                  {important && !done && (
                    <span className="rounded-full bg-brand-600 px-1.5 py-0.5 text-[9px] font-bold text-white">
                      推奨
                    </span>
                  )}
                </p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-600">{hint}</p>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        ※ 1 枚だけでも査定可能ですが、複数アングル + 型番ラベルを撮影すると AI の特定精度と業者の入札額が大きく上がります。
      </p>
    </details>
  );
}
