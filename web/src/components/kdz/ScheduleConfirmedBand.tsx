"use client";

/**
 * 「訪問日程が確定しました」の帯（日程構造化 DESIGN §13.4）。
 * 依頼者のチャット（components/kdz/ChatPanel.tsx）と業者のチャット（app/operator/chat/[id]/page.tsx）の
 * 両方で、kind="schedule_confirmed" のメッセージを吹き出しの代わりにこの帯で描く
 * （運営名義の吹き出しに業者の文字列が並ばないようにする。SEC-I8）。
 * - meta v2: サーバーが構造化データから作った meta.label を出す（表示時にも制御文字を除去する二重の防御）
 * - 旧データ・未知の版: 本文に業者の文字列・ひとことが入りうるため、改行以外の制御文字を除去して出す
 * スタイルは呼び出し側のページ CSS（.chat-page / .opchat-page 配下の .sched-confirmed）に置く。
 */

import { useId } from "react";
import { Ic } from "@/components/kdz/Icons";
import { stripControlChars, stripControlCharsKeepNewlines } from "@/lib/categories";
import { parseScheduleConfirmedMeta } from "@/lib/visit-slots";

export function ScheduleConfirmedBand({ body, meta }: { body: string; meta: unknown }) {
  const titleId = useId();
  const parsed = parseScheduleConfirmedMeta(meta);
  const detailText = parsed.version === 2 ? stripControlChars(parsed.label) : stripControlCharsKeepNewlines(body);
  return (
    <div className="sched-confirmed" role="group" aria-labelledby={titleId}>
      <span className="sched-confirmed-title" id={titleId}>
        <Ic name="check" />
        訪問日程が確定しました
      </span>
      {detailText ? <span className="sched-confirmed-label">{detailText}</span> : null}
    </div>
  );
}
