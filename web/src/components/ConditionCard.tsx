'use client';

import type { Condition } from "@/lib/api";

interface ConditionMeta {
  label: string;
  description: string;
  /** 査定額への係数（表示用） */
  multiplier: string;
}

/** 各コンディションの表示メタ情報 */
const CONDITION_META: Record<Condition, ConditionMeta> = {
  new: {
    label: "新品・未使用",
    description: "開封・使用歴なし。タグや付属品が揃っている状態。",
    multiplier: "×1.10",
  },
  like_new: {
    label: "ほぼ新品",
    description: "数回使用のみ。目立つ傷・汚れなし。",
    multiplier: "×1.00",
  },
  good: {
    label: "良い",
    description: "通常使用の範囲内の軽微な傷のみ。",
    multiplier: "×0.80",
  },
  fair: {
    label: "普通",
    description: "使用感あり。目立つ傷や汚れが数箇所。",
    multiplier: "×0.50",
  },
  poor: {
    label: "悪い",
    description: "大きなダメージあり。動作・機能に影響する場合も。",
    multiplier: "×0.10",
  },
};

/** コンディションの表示順（良い状態から悪い状態へ） */
export const CONDITION_ORDER: Condition[] = [
  "new",
  "like_new",
  "good",
  "fair",
  "poor",
];

interface ConditionCardProps {
  condition: Condition;
  selected: boolean;
  onSelect: (condition: Condition) => void;
}

/**
 * コンディション選択カード。
 * ラジオボタン相当の動作をカスタム UI で実装する。
 */
export default function ConditionCard({
  condition,
  selected,
  onSelect,
}: ConditionCardProps) {
  const meta = CONDITION_META[condition];

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={() => onSelect(condition)}
      className={[
        "w-full rounded-xl border-2 p-4 text-left transition-all duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2",
        selected
          ? "border-brand-600 bg-brand-50 shadow-card"
          : "border-slate-200 bg-white hover:border-brand-300 hover:bg-slate-50",
      ].join(" ")}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* ラジオボタン相当のインジケーター */}
          <span
            className={[
              "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
              selected ? "border-brand-600 bg-brand-600" : "border-slate-300 bg-white",
            ].join(" ")}
          >
            {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
          </span>

          <div>
            <p className="text-sm font-semibold text-slate-900">{meta.label}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{meta.description}</p>
          </div>
        </div>

        {/* 係数バッジ */}
        <span
          className={[
            "shrink-0 rounded-full px-2.5 py-1 text-xs font-bold tabular-nums transition-colors",
            selected ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500",
          ].join(" ")}
        >
          {meta.multiplier}
        </span>
      </div>
    </button>
  );
}
