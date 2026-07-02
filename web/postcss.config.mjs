/** @type {import('postcss').Config} */
const config = {
  plugins: {
    // tailwindcss より前に実行し、`@import "./katazuke.css" layer(components)` を
    // ビルド時にインライン展開して `@layer components { ... }` へ変換する。
    // これを Tailwind が消費・平坦化するため、Next.js 15.5 の lightningcss へ
    // ネイティブ @layer / `@import layer()` が渡らず、`@media layer(components)` への
    // 誤コンパイル（globals.css のトークン全消失）を根本回避する。順序は変更不可。
    "postcss-import": {},
    tailwindcss: {},
    autoprefixer: {},
  },
};

export default config;
