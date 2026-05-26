'use client';

import type { RecommendedChannel } from "@/lib/api";
import { Icon } from "@/components/Icon";

interface ChannelCardProps {
  channel: RecommendedChannel;
}

/**
 * 推奨チャネル 1 件分のカード。
 * rank=1 はブランドカラーで強調し、is_sponsored=true は「PR」バッジで広告性を明示する
 * （中立な査定と広告性のある送客の分離 / ステマ規制対応）。
 */
export default function ChannelCard({ channel }: ChannelCardProps) {
  const isTop = channel.rank === 1;

  return (
    <div
      className={[
        "flex flex-col gap-3 rounded-2xl border bg-white p-4 transition-shadow",
        isTop ? "border-brand-300 shadow-card" : "border-slate-200 shadow-xs",
      ].join(" ")}
    >
      {/* ヘッダー: ランク + チャネル名 + PR バッジ */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span
            className={[
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums",
              isTop ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500",
            ].join(" ")}
          >
            {channel.rank}
          </span>
          <h3 className="text-sm font-bold leading-snug text-slate-900">
            {channel.channel_name}
          </h3>
          {isTop && (
            <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-bold text-brand-700">
              イチオシ
            </span>
          )}
        </div>

        {channel.is_sponsored && (
          <span className="shrink-0 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-bold text-amber-700">
            PR
          </span>
        )}
      </div>

      {/* 推奨理由 */}
      {channel.reason && (
        <p className="text-sm leading-relaxed text-slate-600">{channel.reason}</p>
      )}

      {/* アクションボタン */}
      {channel.outbound_url ? (
        <a
          href={channel.outbound_url}
          target="_blank"
          rel="noopener noreferrer"
          className={[
            "inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2",
            isTop
              ? "bg-brand-600 text-white shadow-cta hover:bg-brand-700"
              : "border border-brand-200 bg-brand-50 text-brand-700 hover:bg-brand-100",
          ].join(" ")}
        >
          このサイトで売る
          <Icon name="external" className="h-3.5 w-3.5" strokeWidth={2.25} />
        </a>
      ) : (
        <span className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-medium text-slate-400">
          <Icon name="lock" className="h-3.5 w-3.5" />
          リンク準備中
        </span>
      )}
    </div>
  );
}
