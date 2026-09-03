/**
 * Hero 直下の信頼バー（trust strip）。
 *
 * 方針: 捏造した利用実績数値（例: 「累計査定 12,300 件」）は使わない。
 * 検証可能な実値・実装属性のみで構成する:
 *   - 対応カテゴリ数: page.tsx の CATEGORIES 配列実数
 *   - 対応チャネル数: page.tsx の CHANNELS 配列実数（拡張中）
 *   - 平均完了時間: 30 秒（プロダクト仕様）
 *   - AI モデル: Google Gemini Vision（バックエンド app/services/vision.py 実装）
 *   - 提供形態: ベータ版運用中（透明性）
 *
 * Server Component（状態なし）。
 */

import { Icon, type IconName } from "@/components/Icon";

interface TrustItem {
  icon: IconName;
  value: string;
  label: string;
}

const TRUST_ITEMS: TrustItem[] = [
  { icon: "sparkle", value: "12+", label: "対応カテゴリ" },
  { icon: "yen", value: "8+", label: "売却チャネル比較" },
  { icon: "scan", value: "30秒", label: "平均査定時間" },
  { icon: "lock", value: "0件", label: "営業電話・登録" },
];

export function TrustStrip() {
  return (
    <section
      aria-label="サービスの主要指標"
      className="border-y border-slate-200 bg-white/70 backdrop-blur-sm"
    >
      <div className="container-aw py-6 sm:py-7">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 sm:gap-6">
          {TRUST_ITEMS.map(({ icon, value, label }) => (
            <div
              key={label}
              className="flex items-center gap-3 sm:justify-center"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                <Icon name={icon} className="h-5 w-5" />
              </span>
              <div>
                <p className="text-lg font-bold leading-tight tracking-tight text-slate-900 sm:text-xl">
                  {value}
                </p>
                <p className="text-xs leading-tight text-slate-600">{label}</p>
              </div>
            </div>
          ))}
        </div>

        {/* 透明性: AI ベンダー明示・ベータ表記 */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1.5">
            <Icon name="sparkle" className="h-3.5 w-3.5 text-brand-500" />
            Powered by Google Gemini Vision
          </span>
          <span className="hidden h-3 w-px bg-slate-300 sm:block" />
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-800">
            ベータ版運用中
          </span>
        </div>
      </div>
    </section>
  );
}
