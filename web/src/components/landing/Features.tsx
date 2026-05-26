/**
 * 特徴セクション — ソクウリが選ばれる 3 つの理由。
 */

import { Icon, type IconName } from "@/components/Icon";

const FEATURES: { no: string; icon: IconName; title: string; desc: string }[] = [
  {
    no: "01",
    icon: "camera",
    title: "写真1枚でAI査定",
    desc: "商品名も型番も相場も、自分で調べる必要はありません。撮るだけでAIが識別し、査定します。",
  },
  {
    no: "02",
    icon: "scale",
    title: "複数チャネルを一括比較",
    desc: "メルカリ・ヤフオク・買取店など多数の売り先から、AIが最も高く売れるチャネルを提案します。",
  },
  {
    no: "03",
    icon: "package",
    title: "ほぼ全カテゴリに対応",
    desc: "家電・ファッション・ブランド品・ホビーから家具まで、幅広い商品を1つの入口で査定できます。",
  },
];

export function Features() {
  return (
    <section id="features" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
      <div className="container-aw">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
            Features
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            ソクウリが選ばれる3つの理由
          </h2>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-3">
          {FEATURES.map((feature) => (
            <div
              key={feature.no}
              className="group rounded-2xl border border-slate-200 bg-white p-6 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
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
