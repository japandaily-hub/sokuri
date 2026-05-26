'use client';

/**
 * よくあるご質問セクション（アコーディオン）。
 * 開閉状態を持つため client コンポーネント。
 */

import { useState } from "react";
import { Icon } from "@/components/Icon";

const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: "査定にお金はかかりますか？",
    a: "完全無料です。会員登録も不要で、何度でもご利用いただけます。",
  },
  {
    q: "どんな商品に対応していますか？",
    a: "家電・デジタル機器、ファッション、ブランド品、時計・貴金属、ホビー、家具・インテリアなど幅広いカテゴリに対応しています。",
  },
  {
    q: "写真はどのように撮ればいいですか？",
    a: "商品全体が明るく写るように1枚撮影してください。型番やブランドのロゴが分かると、より正確に判定できます。",
  },
  {
    q: "表示された査定額で必ず売れますか？",
    a: "査定額はAIが算出する参考値です。実際の価格は、各フリマサービスや買取店での確認をもって確定します。",
  },
  {
    q: "しつこい営業電話は来ますか？",
    a: "ソクウリは最適な売却チャネルを提案するサービスです。一括査定のように多数の業者から一斉に電話が来ることはありません。",
  },
  {
    q: "個人情報の登録は必要ですか？",
    a: "査定の利用に会員登録や個人情報の入力は不要です。写真をアップロードするだけで査定できます。",
  },
];

export function Faq() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="bg-white py-16 sm:py-20 lg:py-24">
      <div className="container-aw">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">FAQ</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            よくあるご質問
          </h2>
        </div>

        <div className="mx-auto mt-10 max-w-2xl divide-y divide-slate-200 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
          {FAQ_ITEMS.map((item, index) => {
            const isOpen = openIndex === index;
            const panelId = `faq-panel-${index}`;
            return (
              <div key={item.q}>
                <h3>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-600"
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    onClick={() => setOpenIndex(isOpen ? null : index)}
                  >
                    <span
                      className={[
                        "text-sm font-semibold",
                        isOpen ? "text-brand-700" : "text-slate-900",
                      ].join(" ")}
                    >
                      {item.q}
                    </span>
                    <span
                      className={[
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-all duration-200",
                        isOpen
                          ? "rotate-180 bg-brand-600 text-white"
                          : "bg-slate-100 text-slate-500",
                      ].join(" ")}
                    >
                      <Icon name="chevron-down" className="h-4 w-4" strokeWidth={2.25} />
                    </span>
                  </button>
                </h3>
                {isOpen && (
                  <div
                    id={panelId}
                    className="px-5 pb-5 text-sm leading-relaxed text-slate-600"
                  >
                    {item.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
