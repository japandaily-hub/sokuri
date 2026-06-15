/**
 * 特徴セクション — カタヅケが選ばれる 3 つの理由。
 */

import { Icon, type IconName } from "@/components/Icon";

const FEATURES: { no: string; icon: IconName; title: string; desc: string }[] = [
  {
    no: "01",
    icon: "camera",
    title: "撮るだけ・待つだけ",
    desc: "品物を1点ずつ撮るだけ。AIが1点ずつ仮査定し、たまった品物をまとめて依頼。相場調べも出品作業も不要で、査定はあなたのもとへ届きます。",
  },
  {
    no: "02",
    icon: "scale",
    title: "業者が競うから伸びやすい",
    desc: "複数の登録業者がオンラインで査定額を入札。競争原理がはたらくため、査定が伸びやすい仕組みです。",
  },
  {
    no: "03",
    icon: "shield",
    title: "連絡は上位3社だけ",
    desc: "連絡が来るのは査定額の上位3社のみ。それ以外には自動でお断りが入り、営業電話の一斉架電はありません。",
  },
];

export function Features() {
  return (
    <section id="features" className="bg-white py-16 sm:py-20 lg:py-24">
      <div className="container-aw">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
            Features
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            カタヅケが選ばれる3つの理由
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-500">
            あなたがするのは、品物を1点ずつ撮ること。あとは業者が競い、査定が届くのを待つだけです。
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-3">
          {FEATURES.map((feature) => (
            <div
              key={feature.no}
              className="group rounded-2xl border border-slate-200 bg-slate-50/60 p-6 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
            >
              <div className="flex items-center justify-between">
                <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition-colors group-hover:bg-brand-100">
                  <Icon name={feature.icon} className="h-6 w-6" />
                </span>
                <span className="text-sm font-bold tracking-widest text-slate-200">
                  {feature.no}
                </span>
              </div>
              <h3 className="mt-5 text-base font-bold text-slate-900">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">{feature.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
