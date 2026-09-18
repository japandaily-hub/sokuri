"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

type TabKey = "user" | "biz";

/** 各ペインの目次（ラウンド5 指摘 12）。label は本文の h2 と同じ文字列、id は h2 の id。
 *  条を増減したときは本文の h2 と必ず対で直す（無効なアンカーを作らない）。 */
const TOC_USER: { id: string; label: string }[] = [
  { id: "tu-1", label: "第1条　適用" },
  { id: "tu-2", label: "第2条　サービス概要" },
  { id: "tu-3", label: "第3条　利用登録" },
  { id: "tu-4", label: "第4条　出品・査定について" },
  { id: "tu-5", label: "第5条　個人情報の開示タイミング" },
  { id: "tu-6", label: "第6条　ユーザーの費用" },
  { id: "tu-7", label: "第7条　禁止事項" },
  { id: "tu-8", label: "第8条　契約の解除等" },
  { id: "tu-9", label: "第9条　免責事項" },
  { id: "tu-10", label: "第10条　規約の変更" },
  { id: "tu-11", label: "第11条　準拠法・裁判管轄" },
];
const TOC_BIZ: { id: string; label: string }[] = [
  { id: "tb-1", label: "第1条　適用" },
  { id: "tb-2", label: "第2条　登録要件" },
  { id: "tb-3", label: "第3条　利用料金" },
  { id: "tb-4", label: "第4条　入札のルール" },
  { id: "tb-5", label: "第5条　買取金額の変更" },
  { id: "tb-6", label: "第6条　個人情報の取り扱い" },
  { id: "tb-7", label: "第7条　特定商取引法の遵守" },
  { id: "tb-8", label: "第8条　禁止事項" },
  { id: "tb-9", label: "第9条　登録の停止・取消" },
  { id: "tb-10", label: "第10条　準拠法・裁判管轄" },
];

/** URL ハッシュ → タブ。#biz / #pane-biz のどちらでも業者側を開く。
 *  ラウンド5 指摘（12）で各条に id を振ったので、条アンカー（tu-N / tb-N）も
 *  どちらのペインを開くべきかの手がかりとして扱う（/terms の要点ブロックの
 *  「業者利用規約 第5条」リンクは #tb-5 を指す）。 */
function tabFromHash(hash: string): TabKey | null {
  const h = hash.replace(/^#/, "");
  if (h === "biz" || h === "pane-biz") return "biz";
  if (h === "user" || h === "pane-user") return "user";
  if (/^tb-\d+$/.test(h)) return "biz";
  if (/^tu-\d+$/.test(h)) return "user";
  return null;
}

/**
 * 利用規約のタブ切替（ユーザー / 業者）。
 * デザイン（利用規約.html）の data-tab + .active トグル挙動を React state で再現する。
 * 切替時はデザイン同様トップへスムーズスクロールする。
 *
 * ラウンド4 指摘（Med・業者視点）: /business のフォームが同意を求める「業者利用規約」への
 * リンクが /terms を指しており、着地するとユーザー側のペインが開いたままで、同意対象の本文に
 * たどり着けたか分からなかった（業者利用規約そのものはこのタブの中に全条ある）。
 * タブの状態を URL ハッシュ（#biz）で受け取れるようにし、リンク1本で同意対象を開けるようにする。
 * - 初回マウントと hashchange の両方を見る（同一ページ内の <a href="#biz"> でも切り替わる）
 * - 非アクティブのペインは display:none なのでブラウザのアンカースクロールは効かない。
 *   タブ列（sticky）を自前で scrollIntoView して、開いた側の先頭を見せる
 * - タブのクリックでもハッシュを replaceState で書き戻し、URL を共有可能にする
 *   （replaceState は hashchange を発火させないので上のリスナーとは循環しない）
 */
export function TermsTabs() {
  const [tab, setTab] = useState<TabKey>("user");
  const tabWrapRef = useRef<HTMLDivElement>(null);
  /** 最新の tab。applyHash は deps 空（リスナーを張り替えない）ため state を直接読めない。 */
  const tabRef = useRef<TabKey>("user");
  /** 切り替え後に送る条アンカー（#tu-6 / #tb-5）。ペインが表示に変わった後で使う。 */
  const pendingAnchorRef = useRef<string | null>(null);

  /** ハッシュ経由の切替。タブ列を画面内に入れるだけで、ページ先頭へは戻さない。 */
  const applyHash = useCallback(() => {
    const hash = window.location.hash.replace(/^#/, "");
    const next = tabFromHash(window.location.hash);
    if (!next) return;
    const anchor = /^t[ub]-\d+$/.test(hash) ? hash : null;
    if (next === tabRef.current) {
      /* 開いているペイン内のアンカーは、要素が表示されているのでブラウザのアンカー送りが
         そのまま効く（余白は terms.css の h2{scroll-margin-top}）。ここで割り込まない。 */
      if (!anchor) tabWrapRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    /* 非アクティブのペインは display:none なのでブラウザのアンカー送りは効かず、
       requestAnimationFrame では React の再描画前に走ることがある（ラウンド5 実測で
       #tb-5 が無反応）。commit 後に必ず走る useEffect まで持ち越して送る。 */
    pendingAnchorRef.current = anchor;
    tabRef.current = next;
    setTab(next);
    if (!anchor) tabWrapRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  /** ペインが表示に切り替わった後に、持ち越した条アンカーへ送る。 */
  useEffect(() => {
    const id = pendingAnchorRef.current;
    if (!id) return;
    pendingAnchorRef.current = null;
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [tab]);

  useEffect(() => {
    applyHash();
    window.addEventListener("hashchange", applyHash);
    return () => window.removeEventListener("hashchange", applyHash);
  }, [applyHash]);

  const select = (key: TabKey) => {
    tabRef.current = key;
    setTab(key);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", key === "biz" ? "#biz" : "#user");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  return (
    <>
      <div className="tab-wrap" ref={tabWrapRef}>
        <div className="tab-inner">
          <div className="legal-tabs" role="tablist" aria-label="利用規約の種別">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "user"}
              className={`legal-tab${tab === "user" ? " active" : ""}`}
              onClick={() => select("user")}
            >
              ユーザー利用規約
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "biz"}
              className={`legal-tab${tab === "biz" ? " active" : ""}`}
              onClick={() => select("biz")}
            >
              業者利用規約
            </button>
          </div>
        </div>
      </div>

      {/* ユーザー利用規約 */}
      <div className={`legal-pane${tab === "user" ? " active" : ""}`} id="pane-user">
        <div className="legal-body">
          {/* 戻り導線はペイン末尾（.legal-foot）に置く。タブ直下・第1条の直前に挟むと
              タブと本文を分断してしまうため（r1 レビュー）。/privacy と同位置。 */}
          {/* 目次（ラウンド5 指摘 12）: 帯の下がすぐ長文で、#biz 以外に読み進めの
              手がかりが無かった。/privacy・/legal にも同じ構えで置く。 */}
          <nav className="terms-toc" aria-label="ユーザー利用規約の目次">
            <p className="terms-toc__label">この規約の条一覧</p>
            <ol className="terms-toc__list">
              {TOC_USER.map((t) => (
                <li key={t.id}>
                  <a href={`#${t.id}`}>{t.label}</a>
                </li>
              ))}
            </ol>
          </nav>

          <h2 id="tu-1">第1条　適用</h2>
          <p>
            本規約は、カタヅケ運営事務局（以下「当社」）が提供する不用品買取マッチングサービス「カタヅケ」（以下「本サービス」）を利用するすべてのユーザーに適用されます。本サービスをご利用いただくことで、本規約に同意したものとみなします。
          </p>

          <h2 id="tu-2">第2条　サービス概要</h2>
          <p>
            本サービスは、不用品を手放したいユーザーと買取業者をマッチングするプラットフォームです。当社はマッチングの場を提供するものであり、買取取引の当事者にはなりません。
          </p>

          <h2 id="tu-3">第3条　利用登録</h2>
          <p>
            本サービスの利用には登録が必要です。登録にあたり、正確な情報を提供してください。虚偽の情報による登録は禁止します。
          </p>

          <h2 id="tu-4">第4条　出品・査定について</h2>
          <ul>
            <li>出品できる品物は、法律上売買が許可されているものに限ります</li>
            <li>出品情報（写真・品目・地域・住居情報など。範囲は第5条のとおり）は登録業者に公開されます</li>
            <li>入札期間の上限は設けていません。入札の受付は、ユーザーが業者を選んだ時点で終了します</li>
            <li>入札がなかった場合でも、再出品することができます</li>
            <li>査定額・入札額は参考値であり、現物確認後に最終額が決定します</li>
          </ul>

          <h2 id="tu-5">第5条　個人情報の開示タイミング</h2>
          <p>
            取引交渉が成立した業者にのみ、引き取りに必要な詳細住所（番地・建物名など）と連絡用のメールアドレス（LINE連携のみの場合はLINEでの連絡のご案内）が開示されます。氏名・電話番号を業者に開示することはありません。査定段階で業者に渡るのは、写真・品目・利用目的・地域（都道府県・市区町村）・住居情報（住居種別・間取り・階数・エレベーターの有無）と、これらに基づくAI要約のみです。
          </p>
          <div className="note">
            連絡が来るのは、ユーザーが選択した成約業者1社のみです。それ以外の業者への連絡先開示・架電は行われません。なお、古物営業法により、1万円以上の買取など法令で定める場合には、買取業者が住所・氏名・職業・年齢を確認するため、訪問時に業者から身分証のご提示を求められることがあります。
          </div>

          <h2 id="tu-6">第6条　ユーザーの費用</h2>
          <p>
            ユーザーが本サービスを利用するための費用は<strong>一切かかりません</strong>。出品・査定・お断りまですべて無料です。
          </p>

          <h2 id="tu-7">第7条　禁止事項</h2>
          <ul>
            <li>虚偽の品物情報・写真の掲載</li>
            <li>法律で売買が禁止されている品物の出品</li>
            <li>業者への不当な要求・ハラスメント</li>
            <li>本サービスを経由せずに業者と直接取引を行うこと（登録業者との脱プラットフォーム行為）</li>
            <li>アカウントの第三者への譲渡・売買</li>
            <li>その他、当社が不適切と判断する行為</li>
          </ul>

          <h2 id="tu-8">第8条　契約の解除等</h2>
          <p>
            訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。クーリング・オフの可否は、品目（家具・家電等は対象外）や契約に至った経緯（ご自身の依頼で業者が訪問した場合は対象外となることがあります）によって異なります。業者から交付される書面をご確認ください。
          </p>
          <p>
            本条は、法令によりユーザーに認められる契約の申込みの撤回または解除の権利を制限するものではありません。クーリング・オフが適用される取引においては、書面または電磁的記録（メール等）により、業者へ申込みの撤回または契約の解除を通知することができます。
          </p>

          <h2 id="tu-9">第9条　免責事項</h2>
          <p>
            当社は、業者の買取額・品質・対応について保証しません。取引はユーザーと業者間の合意に基づくものです。ただし、登録業者の古物商許可確認等、安全なマッチング環境の整備に努めます。
          </p>

          <h2 id="tu-10">第10条　規約の変更</h2>
          <p>
            当社は必要に応じて本規約を変更できます。重要な変更はウェブサイト上で告知します。変更後も本サービスを利用した場合、変更後の規約に同意したものとみなします。
          </p>

          <h2 id="tu-11">第11条　準拠法・裁判管轄</h2>
          <p>
            本規約は日本法に準拠します。本サービスに関する紛争については、東京地方裁判所を第一審の専属的合意管轄裁判所とします。
          </p>
          <div className="legal-foot">
            <Link href="/" className="back-link">← トップへ戻る</Link>
          </div>
        </div>
      </div>

      {/* 業者利用規約 */}
      <div className={`legal-pane${tab === "biz" ? " active" : ""}`} id="pane-biz">
        <div className="legal-body">
          {/* 戻り導線はペイン末尾（.legal-foot）に置く（r1 レビュー） */}
          {/* 目次（ラウンド5 指摘 12）: 帯の下がすぐ長文で、#biz 以外に読み進めの
              手がかりが無かった。/privacy・/legal にも同じ構えで置く。 */}
          <nav className="terms-toc" aria-label="業者利用規約の目次">
            <p className="terms-toc__label">この規約の条一覧</p>
            <ol className="terms-toc__list">
              {TOC_BIZ.map((t) => (
                <li key={t.id}>
                  <a href={`#${t.id}`}>{t.label}</a>
                </li>
              ))}
            </ol>
          </nav>

          <h2 id="tb-1">第1条　適用</h2>
          <p>
            本規約は、カタヅケ運営事務局（以下「当社」）が提供する本サービスに登録業者として参加するすべての事業者（以下「業者」）に適用されます。
          </p>

          <h2 id="tb-2">第2条　登録要件</h2>
          <ul>
            <li>有効な古物商許可を取得していること</li>
            <li>法人または個人事業主として買取・リユース業を営んでいること</li>
            <li>対応エリア（東京都・千葉県・埼玉県・神奈川県のいずれか）で訪問買取が可能なこと</li>
            <li>特定商取引法を遵守していること</li>
          </ul>

          <h2 id="tb-3">第3条　利用料金</h2>
          <p>
            本サービスの利用料金（手数料を含みます）その他の契約条件は、当社が別途定め、登録のお申し込み後に登録業者へ個別に通知する内容によるものとします。
          </p>
          <div className="note">
            料金が発生する場合、当社はその条件を事前に登録業者へ通知し、登録業者が確認できる状態にしたうえで適用します。
          </div>

          <h2 id="tb-4">第4条　入札のルール</h2>
          <ul>
            <li>入札は買取総額（出品された商品すべてに対する金額）で行います</li>
            <li>業者は、ユーザーが業者を選択するまでの間、自社の入札額を現在の金額より高い金額へ何度でも引き上げることができます（引き下げることはできません）</li>
            <li>入札はすべてユーザーに提示され、ユーザーが選択した1社のみが取引に進めます</li>
            <li>選択されなかった入札には自動でお断り通知が送られ、ユーザーの連絡先は開示されません</li>
            <li>入札額は誠実な査定に基づくものとし、意図的な高額入札による落札後の大幅減額は禁止します</li>
          </ul>

          <h2 id="tb-5">第5条　買取金額の変更</h2>
          <p>
            提示した買取金額を下回る変更は、<strong>査定現場で商品を実際に確認し、変更理由を明示したうえでユーザーの了解を得た場合にのみ</strong>可能です。ユーザーの同意なく一方的に減額することはできません。
          </p>
          <div className="important">
            正当な理由のない大幅減額・強引な交渉は、登録停止・除名処分の対象となります。
          </div>

          <h2 id="tb-6">第6条　個人情報の取り扱い</h2>
          <ul>
            <li>取引を通じて取得したユーザーの個人情報は、当該取引目的のみに使用すること</li>
            <li>取引成立後に開示されたユーザーの連絡先を、取引以外の目的で使用することを禁止します</li>
            <li>第三者への個人情報提供・売買を禁止します</li>
          </ul>

          <h2 id="tb-7">第7条　特定商取引法の遵守</h2>
          <p>
            訪問買取においては特定商取引法を遵守し、法定書面の交付や、クーリング・オフが適用される取引における適切な対応を行ってください。違反が確認された場合、即時登録停止処分とします。
          </p>

          <h2 id="tb-8">第8条　禁止事項</h2>
          <ul>
            <li>虚偽の会社情報・古物商許可情報の提供</li>
            <li>サービスを経由せず直接ユーザーと取引するための情報収集（脱プラットフォーム行為）</li>
            <li>複数アカウントの作成・入札操作</li>
            <li>ユーザーへの不当な勧誘・ハラスメント</li>
            <li>古物商許可の失効後の継続利用</li>
          </ul>

          <h2 id="tb-9">第9条　登録の停止・取消</h2>
          <p>
            当社は、業者が本規約に違反した場合、または当社が不適切と判断した場合、事前通知なしに登録を停止または取消することができます。
          </p>

          <h2 id="tb-10">第10条　準拠法・裁判管轄</h2>
          <p>
            本規約は日本法に準拠します。本サービスに関する紛争については、東京地方裁判所を第一審の専属的合意管轄裁判所とします。
          </p>
          <div className="legal-foot">
            <Link href="/business" className="back-link">← 業者ページへ戻る</Link>
          </div>
        </div>
      </div>
    </>
  );
}
