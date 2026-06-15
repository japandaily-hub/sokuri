/**
 * 課題提起セクション。
 * 「これまでの手放し方」の課題 →「カタヅケの答え」という対比構成。
 */

import { Icon } from "@/components/Icon";

/** 従来の手放し方が抱える課題 */
const PROBLEMS: { label: string; title: string; desc: string }[] = [
  {
    label: "フリマ",
    title: "売る準備が、とにかく多い",
    desc: "撮影・説明文・価格設定・梱包・発送・購入者対応。1点売るだけでも作業が山積みです。",
  },
  {
    label: "一括査定",
    title: "申込んだ途端、電話が殺到",
    desc: "フォーム入力の手間に加え、多数の業者から営業電話が一斉にかかってくることがあります。",
  },
];

export function ServiceIntro() {
  return (
    <section id="about" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
      <div className="container-aw">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
            これまでの手放し方
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            売りたいのに、なぜか動けない
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-500">
            出品の手間、相場調べ、そして鳴り止まない営業電話。手放したい気持ちを止めていたのは、その面倒さでした。カタヅケは、その手間そのものをなくします。下の8つの場面で、変わっていく様子をご覧ください。
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
          {/* 課題カード */}
          {PROBLEMS.map((problem) => (
            <div
              key={problem.title}
              className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
                <Icon name="close" className="h-5 w-5" strokeWidth={2.25} />
              </span>
              <p className="mt-4 text-xs font-semibold text-slate-400">{problem.label}</p>
              <h3 className="mt-1 text-base font-bold text-slate-900">{problem.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">{problem.desc}</p>
            </div>
          ))}

          {/* 解決カード（強調） */}
          <div className="rounded-2xl border-2 border-brand-600 bg-white p-6 shadow-card-hover">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white">
              <Icon name="camera" className="h-6 w-6" />
            </span>
            <p className="mt-4 inline-flex rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-700">
              カタヅケ
            </p>
            <h3 className="mt-1.5 text-base font-bold text-slate-900">
              撮って待つだけ。業者から来る
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              品物を1点ずつ撮るだけ。AIが1点ずつ仮査定し、たまった品物をまとめて業者へ。査定はあなたのもとへ届き、連絡は同意した上位3社のみです。
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
