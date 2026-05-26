/**
 * サービス説明セクション。
 * 「従来の選択肢の課題」→「ソクウリの答え」という対比構成。
 */

import { Icon } from "@/components/Icon";

/** 従来の選択肢が抱える課題 */
const PROBLEMS: { label: string; title: string; desc: string }[] = [
  {
    label: "これまでの選択肢 ①",
    title: "フリマは、とにかく手間",
    desc: "写真撮影・説明文・価格設定・梱包・発送・購入者対応。1点売るだけでも作業が山積みです。",
  },
  {
    label: "これまでの選択肢 ②",
    title: "一括査定は、電話が殺到",
    desc: "フォーム入力の手間に加え、申し込んだ途端に多数の業者から営業電話がかかってきます。",
  },
];

export function ServiceIntro() {
  return (
    <section id="about" className="bg-white py-16 sm:py-20 lg:py-24">
      <div className="container-aw">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">About</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            「売りたい」と「めんどくさい」を、AIが解決
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-500">
            不要品の売却にはいつも手間がついて回ります。ソクウリはその手間そのものをなくします。
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
          {/* 課題カード */}
          {PROBLEMS.map((problem) => (
            <div
              key={problem.title}
              className="rounded-2xl border border-slate-200 bg-white p-6"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
                <Icon name="close" className="h-5 w-5" strokeWidth={2.25} />
              </span>
              <p className="mt-4 text-xs font-semibold text-slate-400">{problem.label}</p>
              <h3 className="mt-1 text-base font-bold text-slate-900">{problem.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">{problem.desc}</p>
            </div>
          ))}

          {/* 解決カード（強調） */}
          <div className="rounded-2xl border border-brand-200 bg-brand-50/50 p-6 shadow-card ring-1 ring-brand-100">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-100 text-accent-600">
              <Icon name="check" className="h-5 w-5" strokeWidth={2.5} />
            </span>
            <p className="mt-4 inline-flex rounded-full bg-brand-600 px-2.5 py-0.5 text-xs font-bold text-white">
              ソクウリの答え
            </p>
            <h3 className="mt-1.5 text-base font-bold text-slate-900">
              撮るだけ。あとはAIに任せる
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              AIが商品・状態・相場を判定し、最適な売却チャネルを提案。あなたは案内に沿って売るだけです。
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
