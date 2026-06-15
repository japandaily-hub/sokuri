import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "利用規約 | カタヅケ",
  description: "カタヅケの利用規約です。",
};

export default function TermsPage() {
  return (
    <div className="container-aw max-w-3xl py-16">
      <h1 className="text-2xl font-bold text-slate-900">カタヅケ 利用規約</h1>
      <p className="mt-3 text-sm text-slate-500">最終更新：2026年6月15日</p>

      <p className="mt-6 text-sm leading-relaxed text-slate-600">
        本規約は、カタヅケ運営事務局が提供するマッチングサービス「カタヅケ」の利用条件を定めるものです。
        サービスをご利用いただく前に必ずお読みください。ご利用をもって、本規約に同意いただいたものとみなします。
      </p>

      <section className="mt-10 space-y-8">
        <div>
          <h2 className="text-lg font-bold text-slate-900">第1条（サービスの性質）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            「カタヅケ」（以下「本サービス」といいます）は、カタヅケ運営事務局（以下「当方」といいます）が運営する、
            ユーザーと買取業者をつなぐマッチング（媒介）の「場」です。当方自身は、物品の買取・販売・回収・運搬を行いません。
            物品の売買契約は、ユーザーと買取業者との間で直接成立し、当方はその当事者となりません。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第2条（利用登録）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            本サービスの一部機能は、メールアドレスおよびパスワードによる登録が必要です。
            登録情報は正確に入力してください。虚偽の登録が判明した場合、利用を停止することがあります。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第3条（禁止事項）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">次の行為を禁止します。</p>
          <ul className="mt-2 list-disc pl-5 text-sm leading-relaxed text-slate-600 space-y-1">
            <li>法令または公序良俗に違反する行為</li>
            <li>他のユーザーまたは第三者を欺く行為</li>
            <li>虚偽の品物情報・写真の投稿</li>
            <li>本サービスの運営を妨害する行為</li>
            <li>スパムや無断の広告行為</li>
          </ul>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第4条（AI査定の性質）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            本サービスが提供するAI査定額は、写真と品目情報をもとにした参考値です。
            実際の買取額は各業者の現物査定により決まり、当方はその金額を保証しません。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第5条（個人情報の取り扱い）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            ユーザーが投稿した写真・品目情報等は、AIによる査定および買取業者とのマッチングの目的の範囲で利用されます。
            詳細は<a href="/privacy" className="text-brand-600 underline">プライバシーポリシー</a>に定めます。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第6条（訪問買取と消費者保護）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            訪問による買取には特定商取引法が適用されます。法定書面の交付、8日間のクーリングオフ権、
            その期間中の物品引き渡し拒絶権など、消費者としての保護を受けられます。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第7条（免責事項）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            当方は、ユーザーと買取業者間で生じたトラブル（価格の相違、品物の損傷、未払い等）について、
            仲介者として可能な範囲での情報提供は行いますが、直接の責任を負いません。
            取引は各自の判断と責任において行ってください。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第8条（規約の変更）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            当方は、必要に応じて本規約を変更できます。変更後は本ページで告知し、継続利用をもって同意とみなします。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第9条（お問い合わせ）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            本規約に関するお問い合わせは{" "}
            <a href="mailto:katazuke.support@gmail.com" className="text-brand-600 underline">
              katazuke.support@gmail.com
            </a>{" "}
            までご連絡ください。
          </p>
        </div>
      </section>

      <div className="mt-12 rounded-xl border border-slate-200 bg-slate-50 p-5 text-xs leading-relaxed text-slate-500">
        <dl className="space-y-1">
          <div className="flex gap-2"><dt className="font-semibold">運営者</dt><dd>カタヅケ運営事務局（個人運営）</dd></div>
          <div className="flex gap-2"><dt className="font-semibold">所在地</dt><dd>神奈川県横浜市</dd></div>
          <div className="flex gap-2"><dt className="font-semibold">連絡先</dt><dd><a href="mailto:katazuke.support@gmail.com" className="underline">katazuke.support@gmail.com</a></dd></div>
        </dl>
      </div>
    </div>
  );
}
