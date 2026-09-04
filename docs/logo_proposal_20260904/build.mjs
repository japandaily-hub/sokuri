// カタヅケ ロゴ再設計 提案ビルダー（2026-09-04）
// 元 PNG（web/public/logo-icon.png 紺#1e2a44+金#e8b923・太線・丸角）を、現行テーマ
// （Noto Serif JP 400 / 主色 #1447e0 / 墨 #20242e / 角丸0・影0・.ic stroke 1.5）に合わせて
// ベクター化し、配色バリエーションと PNG を書き出す。実行: node build.mjs（web/node_modules の sharp を使用）
import { writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url);
const sharp = require("../../web/node_modules/sharp");

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "svg") + "/";
const PNG = join(HERE, "png") + "/";
mkdirSync(OUT, { recursive: true });
mkdirSync(PNG, { recursive: true });

// ---- 現行テーマのトークン（web/src/app/katazuke.css :root と一致） ----
const T = { ink: "#20242e", primary: "#1447e0", primaryL: "#5f86ee", lime: "#8fb4ff", gold: "#e5a323", white: "#ffffff", line: "#dce3ea" };

/**
 * アイコン本体（座標系 0〜100。書き出し viewBox は図形に密着した 0 0 100 86）。
 * 元図の比率を踏襲: 屋根の庇が壁より外へ張り出す／土台バーが壁より太い／目は2点／蝶ネクタイは屋根の真下。
 * 変更点: ①線幅を元の約9%→7%へ（UIアイコン .ic は 1.5/24=6.25%。ロゴは同階級〜半段上に置く／独立査読で 5.5% は「ナビアイコンに負ける」と判定）
 *         ②線端 butt・接合 miter（角丸0の作法。元は round）③蝶ネクタイの結び目を円→正方形
 * @param {object} c 配色 {house, tie, knot, eye}
 * @param {object} o 任意 {weight: 線幅(既定7), id: clipPath id サフィックス（同一文書内で一意にする）, tieOutline: ネクタイに輪郭線を引くか}
 */
function icon(c, o = {}) {
  const w = o.weight ?? 7;
  const base = w * 1.6; // 土台バーは線より太く（元図の重心の低さを継承）
  const tie = o.tieOutline
    ? `<path d="M35 55.5 L48 61 L35 66.5 Z M65 55.5 L52 61 L65 66.5 Z" fill="${c.tie}" stroke="${c.house}" stroke-width="${w * 0.55}" stroke-linejoin="miter"/>`
    : `<path d="M35 55.5 L48 61 L35 66.5 Z M65 55.5 L52 61 L65 66.5 Z" fill="${c.tie}"/>`;
  const cid = `eave-${o.id ?? Math.round(w * 10)}`;
  return `
  <defs><clipPath id="${cid}"><rect x="4" y="0" width="92" height="100"/></clipPath></defs>
  <g fill="none" stroke="${c.house}" stroke-width="${w}" stroke-linecap="butt" stroke-linejoin="miter" stroke-miterlimit="10">
    <!-- 屋根（庇は壁より外へ。線を長めに引き、垂直クリップで庇の端を垂直に切る＝角丸0の作法） -->
    <path d="M-2 52.3 L50 6 L102 52.3" clip-path="url(#${cid})"/>
    <!-- 壁 -->
    <path d="M13 38 V74 M87 38 V74"/>
  </g>
  <!-- 土台バー（塗り・角丸0） -->
  <rect x="${13 - w / 2}" y="${74 - base / 2}" width="${74 + w}" height="${base}" fill="${c.house}"/>
  <!-- 目 -->
  <circle cx="37" cy="47" r="3.2" fill="${c.eye}"/><circle cx="63" cy="47" r="3.2" fill="${c.eye}"/>
  <!-- 蝶ネクタイ（結び目は正方形） -->
  ${tie}
  <rect x="47.6" y="58.6" width="4.8" height="4.8" fill="${c.knot}"/>`;
}

const svg = (body, bg = "none", vb = "0 0 100 86", size = 512) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb}" width="${size}" height="${Math.round(size * 0.86)}" role="img" aria-label="カタヅケ">${bg !== "none" ? `<rect width="100%" height="100%" fill="${bg}"/>` : ""}${body}</svg>`;

// ---- 配色バリエーション ----
const VARIANTS = {
  "A_ink_blue":   { label: "A 墨＋青（推奨）",    bg: "none",     c: { house: T.ink, tie: T.primary, knot: T.ink, eye: T.ink } },
  "B_mono_ink":   { label: "B 墨 単色",           bg: "none",     c: { house: T.ink, tie: T.ink, knot: T.white, eye: T.ink } },
  "C_mono_blue":  { label: "C 青 単色",           bg: "none",     c: { house: T.primary, tie: T.primary, knot: T.white, eye: T.primary } },
  "D_ink_gold":   { label: "D 墨＋金（参考・非推奨: 現行パレット外の暖色）", bg: "none", c: { house: T.ink, tie: T.gold, knot: T.ink, eye: T.ink } },
  "E_white_on_blue": { label: "E 白抜き（青地・フッター/CTA帯用）", bg: T.primary, c: { house: T.white, tie: T.white, knot: T.primary, eye: T.white } },
  "F_white_on_ink":  { label: "F 白抜き（墨地）", bg: T.ink,      c: { house: T.white, tie: T.white, knot: T.ink, eye: T.white } },
};

const files = [];
for (const [key, v] of Object.entries(VARIANTS)) {
  const s = svg(icon(v.c, { id: key }), v.bg);
  writeFileSync(`${OUT}icon_${key}.svg`, s);
  files.push([`icon_${key}`, s]);
}
for (const w of [9, 7, 5.5]) { // 太さ比較（元図相当 9 / 提案 7 / 細身 5.5）
  const s = svg(icon(VARIANTS.A_ink_blue.c, { weight: w, id: `w${String(w).replace(".", "_")}` }));
  writeFileSync(`${OUT}weight_${String(w).replace(".", "_")}.svg`, s);
  files.push([`weight_${String(w).replace(".", "_")}`, s]);
}
// ファビコン用（16/32px で潰れないよう線幅を 8 に太らせ、目を大きく）
const fav = svg(`<g transform="translate(0 7)">${icon(VARIANTS.A_ink_blue.c, { weight: 8, id: "fav" }).replace(/r="3\.2"/g, 'r="4.2"')}</g>`, T.white, "0 0 100 100", 64).replace('height="55"','height="64"');
writeFileSync(`${OUT}favicon_A.svg`, fav);
files.push(["favicon_A", fav]);
// 16px 専用の面塗り版: 家を塗りシルエットにし、目を省き、蝶ネクタイを白抜きで残す（極小で「顔」が読めない問題への光学補正）
const favSolid = svg(`<g transform="translate(0 7)"><path d="M4 47 L50 6 L96 47 L89 53 L87 51 V78 H13 V51 L11 53 Z" fill="${T.ink}"/>
  <path d="M31 53 L48 61 L31 69 Z M69 53 L52 61 L69 69 Z" fill="${T.white}"/><rect x="46.5" y="57.5" width="7" height="7" fill="${T.primary}"/></g>`, T.white, "0 0 100 100", 64).replace('height="55"','height="64"');
writeFileSync(`${OUT}favicon_A_solid.svg`, favSolid);
files.push(["favicon_A_solid", favSolid]);
// apple-icon 用（白地・余白を広く・A配色）
const apple = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="180" height="180"><rect width="100" height="100" fill="#fff"/><g transform="translate(14 21) scale(0.72)">${icon(VARIANTS.A_ink_blue.c, { weight: 7, id: "apple" })}</g></svg>`;
writeFileSync(`${OUT}apple_icon_A.svg`, apple);
files.push(["apple_icon_A", apple]);

// ---- PNG 書き出し（sharp / librsvg） ----
for (const [name, s] of files) {
  const size = name.startsWith("favicon") ? 64 : name.startsWith("apple") ? 180 : 512;
  const h = name.startsWith("favicon") || name.startsWith("apple") ? size : Math.round(size * 0.86);
  await sharp(Buffer.from(s), { density: 384 }).resize(size, h).png().toFile(`${PNG}${name}.png`);
}
// 一覧シート（A〜F を横並び）
const cells = Object.entries(VARIANTS).map(([k, v], i) =>
  `<g transform="translate(${i * 120} 0)"><rect width="110" height="110" fill="${v.bg === "none" ? "#fff" : v.bg}" stroke="${T.line}"/><g transform="translate(5 5)">${icon(v.c, { id: `sheet-${k}` })}</g></g>`).join("");
const sheet = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${Object.keys(VARIANTS).length * 120 - 10} 110" width="${(Object.keys(VARIANTS).length * 120 - 10) * 3}" height="330">${cells}</svg>`;
writeFileSync(`${OUT}sheet_variants.svg`, sheet);
await sharp(Buffer.from(sheet), { density: 288 }).png().toFile(`${PNG}sheet_variants.png`);
console.log("written:", files.length, "svg +", files.length + 1, "png");
