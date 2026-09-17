/**
 * ビジュアル刷新プロジェクトで追加した装飾イラスト（ブルー×ホワイト基調＋自然物のみワンポイント差し色）。
 * 素材は web/public/img/ill/ill-*.webp に配置済み（480x480・透過WebP）。alt="" は純装飾のため意図的。
 */
export type IllName =
  | "box"
  | "books"
  | "plant"
  | "folding-hands"
  | "house-tree"
  | "truck";

export const ILLUSTRATIONS: Record<IllName, { w: number; h: number; alt: string }> = {
  box: { w: 480, h: 480, alt: "" },
  books: { w: 480, h: 480, alt: "" },
  plant: { w: 480, h: 480, alt: "" },
  "folding-hands": { w: 480, h: 480, alt: "" },
  "house-tree": { w: 480, h: 480, alt: "" },
  truck: { w: 480, h: 480, alt: "" },
};

/**
 * 循環イラスト帯(.ill-loop)の円周上の位置(%)。katazuke-motion.css の .ill-item が
 * top:var(--ill-top,50%);left:var(--ill-left,50%) を参照する前提の唯一の正典。
 * 元は `.ill-item--box{top:2%;left:50%}` のようなBEM修飾子セレクタを6つ並べる形だったが、
 * このプロジェクトのビルド環境(postcss-import + Tailwind layer平坦化)でその形の時だけ
 * 6ルールが最終CSSから原因不明のまま消える現象を実機検証で確認したため、
 * CSS変数(インラインstyle)経由に変更した。新しい位置を追加する場合もここに1行足すだけにし、
 * katazuke-motion.css 側に `.ill-item--xxx{top:...;left:...}` 形のセレクタを増やさないこと。
 */
export const ILL_POSITIONS: Record<IllName, { top: string; left: string }> = {
  box: { top: "2%", left: "50%" },
  truck: { top: "24%", left: "90%" },
  "house-tree": { top: "76%", left: "90%" },
  "folding-hands": { top: "98%", left: "50%" },
  books: { top: "76%", left: "10%" },
  plant: { top: "24%", left: "10%" },
};

/** 480px以下で間引く2点(katazuke-motion.cssの [data-ill-thin] ルールと対応)。 */
export const ILL_THIN_ON_MOBILE: readonly IllName[] = ["books", "plant"];

export function illSrc(name: IllName) {
  // name は現状すべて静的配列由来で閉じているが、将来 API/クエリ経由に変わっても
  // パストラバーサルやクラス名汚染に繋がらないよう、型消失後も実行時に許可リストで検証する
  // （セキュリティレビュー Low-3 対応）。
  if (!Object.prototype.hasOwnProperty.call(ILLUSTRATIONS, name)) {
    throw new Error(`unknown illustration: ${String(name)}`);
  }
  return `/img/ill/ill-${name}.webp`;
}
