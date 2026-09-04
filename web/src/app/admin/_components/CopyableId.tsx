"use client";

import { useState } from "react";

/** ID（UUID）を先頭8桁だけ表示し、クリックで全文をクリップボードへコピーする。 */
export function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(id).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      title={id}
      aria-label={`ID ${id} をコピー`}
      className="rounded-none font-mono text-xs text-slate-500 underline decoration-dotted hover:text-brand-600"
    >
      {id.slice(0, 8)}…{copied ? "（コピー済）" : ""}
    </button>
  );
}
