'use client';

/**
 * よくあるご質問セクション（アコーディオン）。
 * 開閉状態を持つため client コンポーネント。
 */

import { useState } from "react";
import { Icon } from "@/components/Icon";

// 不安解消を優先する並び: 営業電話 → 個人情報 → 費用 → 査定の性質 → 対応品目 → 撮り方 → 訪問買取
const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: "しつこい営業電話は来ますか？",
    a: "カタヅケは、あなたが選んだ1社のみが連絡する設計です。一括査定のような一斉架電は起こりません。辞退後の再勧誘も行われません。",
  },
  {
    q: "個人情報はどう扱われますか？",
    a: "査定段階で業者へ共有するのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみです。連絡用のメールアドレス・詳細住所は、交渉が成立した業者にのみ、あなたの同意のうえで開示します。お名前や電話番号を業者へ提供することはありません。",
  },
  {
    q: "利用にお金はかかりますか？",
    a: "査定の依頼にあたり、利用者から手数料はいただきません。AI仮査定は無料でお試しいただけます。業者登録は当面無料で運用しています。",
  },
  {
    q: "査定額はそのまま確定しますか？",
    a: "査定額はAIと業者による参考値です。実際の買取額は、業者の現物査定により決まります。複数の登録業者が査定額で競うため、査定が伸びやすい仕組みです。",
  },
  {
    q: "どんな物に対応していますか？",
    a: "家電・家具・ブランド品・ホビーなど、幅広い品目をまとめて依頼できます。値段がつかない物については、手放す導線を情報としてご案内します。",
  },
  {
    q: "写真はどう撮ればいいですか？",
    a: "品物全体が明るく写るように撮影してください。表札・顔・住所が分かる部分は写さないようご配慮ください。映り込みがある場合はマスキング等の措置に努めます。",
  },
  {
    q: "訪問買取に不安があります。",
    a: "訪問による買取には特定商取引法が適用され、法定書面の交付、8日間のクーリングオフ、その期間中の物品引き渡し拒絶権など、消費者としての保護を受けられます。訪問日時はあなたが選べます。",
  },
];

export function Faq() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
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
                    className="animate-fade-in px-5 pb-5 text-sm leading-relaxed text-slate-600"
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
