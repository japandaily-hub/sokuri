import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "プライバシーポリシー | カタヅケ",
  description: "カタヅケのプライバシーポリシーです。",
};

export default function PrivacyPage() {
  return (
    <div className="container-aw max-w-3xl py-16">
      <h1 className="text-2xl font-bold text-slate-900">カタヅケ プライバシーポリシー</h1>
      <p className="mt-3 text-sm text-slate-500">最終更新：2026年6月15日</p>

      <p className="mt-6 text-sm leading-relaxed text-slate-600">
        本ポリシーは、カタヅケ運営事務局が「カタヅケ」の運営にあたって取得する個人情報の取り扱いについて定めるものです。
      </p>

      <section className="mt-10 space-y-8">
        <div>
          <h2 className="text-lg font-bold text-slate-900">第1条（運営者）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            本サービス「カタヅケ」は、カタヅケ運営事務局（個人運営、所在地：神奈川県横浜市。以下「当方」といいます）が運営します。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第2条（取得する情報）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">当方が取得する情報は以下のとおりです。</p>
          <ul className="mt-2 list-disc pl-5 text-sm leading-relaxed text-slate-600 space-y-1">
            <li>メールアドレス・パスワード（アカウント登録時）</li>
            <li>お名前・住所・電話番号（取引成立後、業者への開示に際して）</li>
            <li>投稿写真・品目情報（査定依頼時）</li>
            <li>利用端末・アクセスログ（サービス改善のため）</li>
          </ul>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第3条（利用目的）</h2>
          <ul className="mt-3 list-disc pl-5 text-sm leading-relaxed text-slate-600 space-y-1">
            <li>AIによる査定・品目分類</li>
            <li>登録業者への案件共有（写真・品目のみ）</li>
            <li>取引成立後の業者への連絡先開示（ユーザーの同意のもと）</li>
            <li>サービスの運営・改善・不正利用防止</li>
            <li>お問い合わせ対応</li>
          </ul>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第4条（第三者への提供）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            査定段階で業者へ共有するのは「写真と品目」のみです。
            連絡先・住所は、交渉が成立した業者にのみ、ユーザーの同意のうえで開示します。
            法令に基づく場合を除き、その他の第三者へ個人情報を提供することはありません。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第5条（データの保管と削除）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            投稿された画像・データは、査定およびマッチングの目的に必要な範囲で保管します。
            ご自身の投稿データの削除をご希望の場合は、{" "}
            <a href="mailto:katazuke-support@gmail.com" className="text-brand-600 underline">
              katazuke-support@gmail.com
            </a>{" "}
            までご連絡ください。ご本人からのご依頼であることを確認のうえ、合理的な範囲で速やかに対応します。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第6条（Cookie・アクセス解析）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            本サービスでは、サービス改善のためアクセスログを取得することがあります。
            個人を特定する目的では使用しません。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第7条（安全管理）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            当方は、取得した個人情報の漏洩・滅失・毀損を防止するため、合理的なセキュリティ対策を講じます。
          </p>
        </div>

        <div>
          <h2 className="text-lg font-bold text-slate-900">第8条（お問い合わせ・開示請求）</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            本ポリシーおよび個人情報の取り扱いに関するお問い合わせ・ご請求は、{" "}
            <a href="mailto:katazuke-support@gmail.com" className="text-brand-600 underline">
              katazuke-support@gmail.com
            </a>{" "}
            までご連絡ください。
          </p>
        </div>
      </section>

      <div className="mt-12 rounded-xl border border-slate-200 bg-slate-50 p-5 text-xs leading-relaxed text-slate-500">
        <dl className="space-y-1">
          <div className="flex gap-2"><dt className="font-semibold">運営者</dt><dd>カタヅケ運営事務局（個人運営）</dd></div>
          <div className="flex gap-2"><dt className="font-semibold">所在地</dt><dd>神奈川県横浜市</dd></div>
          <div className="flex gap-2"><dt className="font-semibold">連絡先</dt><dd><a href="mailto:katazuke-support@gmail.com" className="underline">katazuke-support@gmail.com</a></dd></div>
        </dl>
      </div>
    </div>
  );
}
