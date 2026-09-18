/** 依頼者・業者のモデルケース（架空）。`/`・`/examples`・`/business` が共有する単一の正本。
 *
 *  【景品表示法（優良誤認・打消し表示）】
 *  ここにある人物・店舗名・肖像・金額・入札数・日数・件数はすべて架空である。表示側は必ず
 *  - `MODEL_CASE_CHIP`（または `VENDOR_CASE_NOTE` を伴うチップ）を **金額より手前** に、
 *  - `MODEL_CASE_NOTE` / `VENDOR_CASE_NOTE` を **カード群より手前** に
 *  置くこと。「実際の」「お客様の声」「導入実績」「累計」など実在の取引を示唆する語は使わない。
 *  サイト全体の集計値（累計・平均・成約率・利用者数）はここにも表示側にも作らない。
 *
 *  実データ（実際の取引）に差し替えるときは、チップ・注記・`（仮名）`表記をまとめて外すこと。 */

export type CaseItem = {
  id: number;
  tag: string;
  persona: string;
  avatar: string;
  name: string;
  amount: number;
  bidCount: number;
  days: number;
  cats: string[];
  count: number;
  quote: string;
  /** トップのカードに出す短縮版。quote の中の 1 文をそのまま抜いたもの（要約・書き換え禁止） */
  quoteShort?: string;
  /** 主役画像の id（/img/v2/<lot>.webp・1536x1024 → 1600×1067）。 */
  lot: string;
  /** 主役画像の alt（images.json の値をそのまま使う）。 */
  lotAlt: string;
  /** 主役画像に添える小2枚（既存 3D シリーズ /img/real/cat-*.webp）。 */
  thumbs: [string, string];
  /** 人物肖像の画像 id（/img/v2/<portrait>.webp・1024x1024 → 表示 800）。spec_people.json 準拠。
   *  **トップのモデルケース節でのみ使う**（/examples では肖像を出さない・R4_BRIEF B.3） */
  portrait?: string;
  /** 肖像の alt。spec_people.json の alt をそのまま使う（portrait があるとき必須） */
  portraitAlt?: string;
  /** トップ「利用イメージ」に出す 3 件だけ true */
  featured?: boolean;
};

/** 依頼者のモデルケース 6 件（並び順は /examples の現行どおり）。
 *  ラウンド5 指摘（37）で bidCount を 3〜5 の範囲に下げた（旧 11/7/6/8/4/9）。理由:
 *  稼働直前・登録業者0・対応4都県の段階で 11社・9社の入札は業者側に「9社に負ける市場」と読まれ、
 *  /business の「過度な値引き競争ではない」という説明と矛盾する。「複数業者が競う」は3社でも成立する。
 *  id:5 だけ 4 のまま（quote 内の「4社の査定を見比べて」と一致させる。数値と本文は必ず揃える）。
 *  金額・日数・点数は変更しない（ここが /`・`/examples` の単一の正本）。 */
export const CASES: CaseItem[] = [
  {
    id: 1,
    tag: "実家整理",
    persona: "60代・女性（東京都練馬区）",
    avatar: "田",
    name: "田中さん",
    amount: 148000,
    bidCount: 5,
    days: 2,
    cats: ["家電・PC", "家具", "ブランド品", "時計", "カメラ"],
    count: 32,
    quote:
      "実家の片付けで途方に暮れていましたが、1点ずつ撮ってまとめて出すだけで業者さんが競ってくれるとは。運び出しを別の業者に頼むこともなく、スタッフ2名で丁寧に運んでくれました。",
    quoteShort:
      "実家の片付けで途方に暮れていましたが、1点ずつ撮ってまとめて出すだけで業者さんが競ってくれるとは。",
    lot: "ex-lot-jikka",
    lotAlt: "実家整理のモデルケース。まとめて出す品物を和室に並べたイメージ",
    thumbs: ["cat-kaden", "cat-watch"],
    portrait: "mc-jikka",
    portraitAlt: "和室で品物を整理する60代の女性（架空のモデルケース）",
    featured: true,
  },
  {
    id: 2,
    tag: "引越し",
    persona: "30代・男性（東京都渋谷区）",
    avatar: "鈴",
    name: "鈴木さん",
    amount: 72000,
    bidCount: 3,
    days: 3,
    cats: ["家電・PC", "カメラ", "ブランド品"],
    count: 14,
    quote:
      "引越しを前に、使わない家電やカメラをまとめて出品。1点ずつ売る手間がなく、1回の出品で引き取りまで終わりました。",
    quoteShort: "1点ずつ売る手間がなく、1回の出品で引き取りまで終わりました。",
    lot: "ex-lot-moving",
    lotAlt: "引越しのモデルケース。新居に持っていかない家具と箱をまとめたイメージ",
    thumbs: ["cat-camera", "cat-brand"],
    portrait: "mc-moving",
    portraitAlt: "引越し前のリビングでスマートフォンを持つ30代の男性（架空のモデルケース）",
    featured: true,
  },
  {
    id: 3,
    tag: "断捨離",
    persona: "40代・女性（神奈川県横浜市）",
    avatar: "佐",
    name: "佐藤さん",
    amount: 58000,
    bidCount: 4,
    days: 2,
    cats: ["ブランド品", "時計", "衣類・靴", "その他"],
    count: 11,
    quote:
      "ブランド品を10点ほど。1点ずつフリマアプリに出すのが億劫で試してみたら、出品から引き取りまで1回で片付きました。何より、選ぶまで業者から連絡が来ないのが助かりました。",
    lot: "ex-lot-closet",
    lotAlt: "断捨離のモデルケース。衣類や小物をまとめたイメージ",
    thumbs: ["cat-fashion", "cat-other"],
  },
  {
    id: 4,
    tag: "遺品整理",
    persona: "50代・男性（千葉県船橋市）",
    avatar: "山",
    name: "山口さん",
    amount: 95000,
    bidCount: 5,
    days: 2,
    cats: ["家電・PC", "家具", "音楽", "ゲーム"],
    count: 24,
    quote:
      "父の遺品整理で、品物が大量にありました。まとめて見てもらえたのでとても楽でした。業者の方も丁寧に対応してくれ、感謝しています。",
    quoteShort: "まとめて見てもらえたのでとても楽でした。",
    lot: "ex-lot-ihin",
    lotAlt: "遺品整理のモデルケース。品物を種類ごとに分けて並べたイメージ",
    thumbs: ["cat-music", "cat-game"],
    portrait: "mc-ihin",
    portraitAlt: "静かな部屋で小さな木箱を手にする50代の男性（架空のモデルケース）",
    featured: true,
  },
  {
    id: 5,
    tag: "模様替え",
    persona: "20代・女性（東京都世田谷区）",
    avatar: "中",
    name: "中村さん",
    amount: 31000,
    bidCount: 4,
    days: 3,
    cats: ["家具", "衣類・靴", "食器"],
    count: 9,
    quote:
      "模様替えで不要になった家具と洋服を出品。4社の査定を見比べて、一番コメントが丁寧な業者さんに決めました。重い家具も玄関まで出してもらえて、部屋がすっきりしました。",
    lot: "ex-lot-rearrange",
    lotAlt: "模様替えのモデルケース。入れ替える家具をリビングにまとめたイメージ",
    thumbs: ["cat-furniture", "cat-tableware"],
  },
  {
    id: 6,
    tag: "引越し",
    persona: "30代・夫婦（埼玉県さいたま市）",
    avatar: "小",
    name: "小林さん夫婦",
    amount: 112000,
    bidCount: 3,
    days: 1,
    cats: ["家電・PC", "家具", "スポーツ", "工具・DIY"],
    count: 19,
    quote:
      "2LDKの引越しで家電・家具をまるごと出品。引越し当日に合わせて引き取り日を調整してもらえ、タイミングもぴったりでした。",
    lot: "ex-lot-kitchen",
    lotAlt: "引越しのモデルケース。台所用品と小型家電をまとめたイメージ",
    thumbs: ["cat-sport", "cat-tools"],
  },
];

/** トップ「利用イメージ」に出す 3 件（並び順は CASES 準拠）。 */
/** トップの「利用イメージ」に出す件。肖像（portrait / portraitAlt）を必ず持つ型に絞る:
 *  featured だけ付いた件が混ざると /img/v2/undefined.webp の 404 と alt 無しの画像が静かに出るため。 */
export type FeaturedCase = CaseItem & { portrait: string; portraitAlt: string };
export const FEATURED_CASES: FeaturedCase[] = CASES.filter(
  (c): c is FeaturedCase => !!c.featured && !!c.portrait && !!c.portraitAlt
);

/** 表示名は必ずこれを通す（例「田中さん（仮名）」）。CASES の name の値自体は変更しない。
 *  業者の店舗名だけ「（仮名）」が付いて人物側に付かない、という非対称を作らないため。 */
export const caseName = (c: CaseItem) => `${c.name}（仮名）`;

/** 架空であることの打消し表示。カードの先頭・**金額より手前**に置く。 */
export const MODEL_CASE_CHIP = "モデルケース（架空の利用イメージ）";

/** 依頼者モデルケースの注記。カード群より手前に置く（肖像を出す面では省略不可）。 */
export const MODEL_CASE_NOTE =
  "※ 掲載している事例・人物・肖像・金額・入札数はいずれも、利用の流れを説明するための架空のモデルケースです。人物の画像はすべて生成したもので、実在の人物ではありません（肖像のないケースも同じ架空のモデルケースです）。実際の取引実績ではなく、買取額等の成果を保証するものではありません。";

export type VendorCase = {
  id: "vc-1" | "vc-2";
  /** 仮名の店舗名（末尾に「（仮名）」。実在の市区町村名・地名を屋号に使わない） */
  shop: string;
  /** 都県まで（市区まで書かない） */
  area: string;
  /** 業態・規模 1行 */
  kind: string;
  /** 話者の肩書と年代（可視テキスト） */
  speaker: string;
  /** 肖像の画像 id。表示は 220px（SP 140px）なので派生 `<portrait>-440.webp`（440x440）を使う */
  portrait: string;
  /** 肖像の alt。spec_people.json の alt をそのまま使う */
  portraitAlt: string;
  /** 当該モデルケース1件の例示値。amount は「成約1件あたりの買取総額（このケースの例）」。
   *  ラベルに「平均」「累計」の語を使わない（集計値に見えるため）。
   *  入札件数（bids）は持たない: 成約件数と並べると読者が割り算で成約率を得るため。 */
  month: { deals: number; amount: number };
  quote: string;
};

/** 業者のモデルケース 2 件（架空）。/business の「参加のモデルケース」節の正本。
 *  **「/vendors」（実在業者の一覧）ではこの店舗名・数値を使わない**（実在の登録業者と読まれるため）。 */
export const VENDOR_CASES: VendorCase[] = [
  {
    id: "vc-1",
    shop: "リユースショップ みなも（仮名）",
    area: "神奈川県内",
    kind: "店舗1・スタッフ3名。家電と家具が中心",
    speaker: "店主（50代）",
    portrait: "vc-owner",
    portraitAlt: "店の棚の前に立つリユース店の店主（架空のモデルケース）",
    month: { deals: 4, amount: 86000 },
    quote:
      "写真と品目を見て入札しています。下見に行かなくて済み、1回の訪問でまとまった点数を見られるのが助かっています。",
  },
  {
    id: "vc-2",
    shop: "まるごと買取サービス（仮名）",
    area: "千葉県内",
    kind: "出張買取が中心。トラック1台・スタッフ2名",
    speaker: "引き取り担当（30代）",
    portrait: "vc-staff",
    portraitAlt: "搬出口で台車に手を添える買取スタッフ（架空のモデルケース）",
    month: { deals: 6, amount: 52000 },
    /* ラウンド5 指摘（32/36）: 「訪問が空振りにならない」は断定で、同じカード内の打消し
       （現物確認で条件が合わない場合、依頼者が取引を断ることがある）と正面から矛盾する。
       空振りゼロの約束にならないよう「事前に点数と状態が分かる＝不安が小さい」まで格下げする。 */
    quote:
      "引き取りは家まるごとの単位なので、ルートが組みやすいです。訪問の前に点数と状態が分かるので、空振りの不安が小さいです。",
  },
];

/** 業者モデルケースの注記。カード群より手前に置く。 */
export const VENDOR_CASE_NOTE =
  "※ 店舗名・人物・肖像・数値はすべて架空です。参加した場合の使われ方をイメージしていただくためのもので、実際の取引実績や成果を示すものではありません。店舗名は架空のもので、同名・類似名の実在する事業者とは一切関係ありません。";
