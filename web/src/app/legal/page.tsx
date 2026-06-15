/**
 * 特定商取引法に基づく表記（特商法ページ）
 * 運営者情報を反映済み（2026-06-16）。
 * 所在地（番地）・電話番号・代表者名は、特商法第11条および同法施行規則第10条に基づき
 * 「請求があった場合に遅滞なく開示する」省略運用としている（メールでの開示請求に対応すること）。
 */

export const metadata = {
  title: "特定商取引法に基づく表記 | カタヅケ",
  description: "カタヅケの特定商取引法に基づく表記ページです。",
};

export default function LegalPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-14">
      <h1 className="text-2xl font-bold text-slate-900">特定商取引法に基づく表記</h1>

      <dl className="mt-8 divide-y divide-slate-100 text-sm">
        <Row label="販売事業者">カタヅケ運営事務局</Row>
        <Row label="代表者名">ご請求に応じて遅滞なく開示いたします</Row>
        <Row label="所在地">
          神奈川県横浜市（番地を含む正確な所在地は、ご請求に応じて遅滞なく開示いたします）
        </Row>
        <Row label="電話番号">
          ご請求に応じて遅滞なく開示いたします（お問い合わせはメールにて承ります）
        </Row>
        <Row label="メールアドレス">
          <a
            href="mailto:katazuke-support@gmail.com"
            className="text-brand-700 underline hover:text-brand-900"
          >
            katazuke-support@gmail.com
          </a>
        </Row>
        <Row label="サービス名">カタヅケ（片付け案件マッチングプラットフォーム）</Row>
        <Row label="サービス内容">
          家庭内の不要品・遺品整理・引越しに伴う片付けを希望する依頼者と、
          登録リユース業者とをマッチングするプラットフォームサービス。
          カタヅケは取引の「場」を提供するものであり、実際の買取・回収・運搬は各業者が行います。
        </Row>
        <Row label="手数料・費用">
          <span className="font-semibold">β期間中は完全無料</span>（依頼者・業者ともに手数料なし）。
          将来有料化する場合は、事前にメール通知および本ページにて告知します。
        </Row>
        <Row label="支払時期・方法">
          β期間中は費用が発生しないため、支払は不要です。
        </Row>
        <Row label="サービスの提供時期">
          依頼登録後、業者入札は通常24〜72時間以内に開始されます（業者登録状況による）。
        </Row>
        <Row label="返品・キャンセル">
          マッチング成立前であればキャンセル可能です。
          業者訪問日確定後のキャンセルについては各業者の規定に従います。
          デジタルサービスの性質上、成約後のキャンセルについては業者と依頼者間で協議してください。
        </Row>
        <Row label="免責事項">
          カタヅケは業者紹介・マッチングの場を提供するサービスです。
          査定額はAIおよび業者による参考値であり、実際の買取額は業者による現物確認後に決定します。
          カタヅケは買取金額・作業品質・トラブルに関して一切の保証を行いません。
          取引に関する最終判断は依頼者ご自身の責任において行ってください。
        </Row>
        <Row label="個人情報の取扱い">
          <a href="/privacy" className="text-brand-700 underline hover:text-brand-900">
            プライバシーポリシー
          </a>
          をご確認ください。
        </Row>
        <Row label="メール配信停止">
          カタヅケからのご案内メールの配信停止を希望される方は、メール本文内の配信停止リンク、
          または{" "}
          <a
            href="/unsubscribe"
            className="text-brand-700 underline hover:text-brand-900"
          >
            配信停止ページ
          </a>
          {" "}よりお手続きください。
        </Row>
      </dl>

      <p className="mt-8 text-xs text-slate-500 leading-relaxed">
        ※ 所在地（番地）・電話番号・代表者名は、特定商取引法第11条および同法施行規則第10条に基づき、
        消費者の皆様からのご請求があった場合に、上記メールアドレス宛のご連絡により遅滞なく開示いたします。
      </p>

      <p className="mt-6 text-xs text-slate-400">
        最終更新: 2026年6月16日
      </p>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-4 py-4">
      <dt className="font-semibold text-slate-700">{label}</dt>
      <dd className="col-span-2 text-slate-600 leading-relaxed">{children}</dd>
    </div>
  );
}
