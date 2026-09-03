import type { Config } from "tailwindcss";

/**
 * カタヅケ デザインシステム — Tailwind トークン定義
 *
 * 方向性: 「人の森整合テーマ / ブルー × 明朝 × 直角」。基幹はコバルトブルー #1447e0。
 * 正典トークン（src/app/katazuke.css :root / SPEC-4-decisions.md §4.1）を Tailwind に
 * 橋渡しし、ユーティリティ（text-navy / bg-pale / rounded-kdz / font-head）でも
 * 同じ値に到達できるようにする。ピクセル忠実な実体は src/app/katazuke.css。
 */
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    /** 人の森整合: Tailwind 既定の角丸・影を全段 0/none に固定（full は円形アバター用に据え置き） */
    borderRadius: { none: "0px", sm: "0px", DEFAULT: "0px", md: "0px", lg: "0px", xl: "0px", "2xl": "0px", "3xl": "0px", "4xl": "0px", kdz: "0px", "kdz-s": "0px", full: "9999px" },
    boxShadow: { none: "none", sm: "none", DEFAULT: "none", md: "none", lg: "none", xl: "none", "2xl": "none", inner: "none", xs: "none", card: "none", "card-hover": "none", elevated: "none", cta: "none", "kdz-s": "none", "kdz-m": "none", "kdz-l": "none" },
    extend: {
      colors: {
        /** 基幹ブランドカラー: 苔色グリーン（brand-600 = 正典 --primary） */
        brand: {
          50: "#eef3ff", // --pale
          100: "#d7e6ff", // --marker（マーカー下線）
          200: "#b9cffa",
          300: "#9ab4f5",
          400: "#5f86ee", // --primary-l
          500: "#3868e8",
          600: "#1447e0", // primary action（正典 --primary）
          700: "#0f37b4", // hover（正典 --primary-d）
          800: "#132c86",
          900: "#14235c", // --deep
          950: "#0c1533",
        },
        /** 補助カラー: 成功・完了・前向きシグナル（主色=青とは別系統の緑に固定） */
        accent: {
          50: "#ecfdf3",
          100: "#d1fae1",
          200: "#a6f0c6",
          300: "#6fdca4",
          400: "#3cbf7f",
          500: "#22a366",
          600: "#15803d",
          700: "#116832",
        },
        /** 正典トークン（katazuke.css :root と一致。旧名 blue/blued はエイリアス） */
        kdz: {
          blue: "#1447e0",
          blued: "#0f37b4",
          navy: "#20242e",
          ink: "#20242e",
          body: "#454e59",
          bodysoft: "#63707b",
          headgray: "#959595", // 24px 以上の見出し専用
          line: "#dce3ea",
          linesoft: "#eef1f6",
          pale: "#eef3ff",
          green: "#15803d", // 成功/完了などの意味色（主色=青とは別系統）
          lime: "#8fb4ff",
          marker: "#d7e6ff",
          gold: "#e5a323",
          danger: "#d70035",
          line2: "#06c755", // LINE ブランドグリーン（AA 対象外の文書化例外）
        },
        /** よく使う面・文字色のショートハンド */
        navy: "#20242e",
        ink: "#20242e",
        pale: "#eef3ff",
      },
      fontFamily: {
        /** 見出し・地の文は明朝（Noto Serif JP 先頭 = 全 OS で同じ明朝が出ること優先） */
        head: ['"Noto Serif JP"', '"Hiragino Mincho ProN"', '"Hiragino Mincho Pro"', '"Yu Mincho"', "YuMincho", '"游明朝体"', "serif"],
        sans: [
          '"Noto Serif JP"',
          '"Hiragino Mincho ProN"',
          '"Hiragino Mincho Pro"',
          '"Yu Mincho"',
          "YuMincho",
          '"游明朝体"',
          "serif",
        ],
        /** 入力値・数値・小さな UI ラベル用ゴシック（誤読コストを下げる） */
        ui: ['"Noto Sans JP"', '"Hiragino Kaku Gothic ProN"', '"Yu Gothic UI"', "sans-serif"],
        /** 英字ラベル / 英字ディスプレイ */
        en: ['"Montserrat"', "sans-serif"],
        "en-display": ['"Libre Baskerville"', "serif"],
      },
      /** 影ゼロの作法。立体感は使わず、ヘアラインと余白で区切る */
      boxShadow: {
        xs: "none",
        card: "none",
        "card-hover": "none",
        elevated: "none",
        cta: "none",
        "kdz-s": "none",
        "kdz-m": "none",
        "kdz-l": "none",
      },
      borderRadius: {
        "4xl": "0px",
        kdz: "0px",
        "kdz-s": "0px",
      },
      maxWidth: {
        container: "72rem",
        kdz: "1140px",
        "kdz-text": "760px",
      },
      transitionTimingFunction: {
        kdz: "cubic-bezier(.22,.61,.36,1)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        scan: {
          "0%": { transform: "translateY(-110%)" },
          "100%": { transform: "translateY(360%)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.6s cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fade-in 0.5s ease both",
        scan: "scan 1.9s cubic-bezier(0.45, 0, 0.55, 1) infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  corePlugins: {
    /** デザインハンドオフの .container（max-width:1140px）と衝突するため Tailwind 版を無効化 */
    container: false,
  },
  plugins: [],
};

export default config;
