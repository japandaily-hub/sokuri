import type { Config } from "tailwindcss";

/**
 * カタヅケ デザインシステム — Tailwind トークン定義
 *
 * 方向性: 「人の森整合テーマ / 苔緑 × 明朝 × 直角」。基幹は苔色グリーン #527e52。
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
          50: "#eff3ef", // --pale
          100: "#d4efb3", // --marker（マーカー下線の若草）
          200: "#c3d7c3",
          300: "#a3bda3",
          400: "#7fa37f", // --primary-l
          500: "#649264",
          600: "#527e52", // primary action（正典 --primary）
          700: "#3f6640", // hover（正典 --primary-d）
          800: "#37573a",
          900: "#2f4a30", // --deep
          950: "#1f3320",
        },
        /** 補助カラー: 価値・成功・前向きシグナル（エメラルド） */
        accent: {
          50: "#eff3ef",
          100: "#e4ece4",
          200: "#d4efb3",
          300: "#a9c7a9",
          400: "#7fa37f",
          500: "#527e52",
          600: "#527e52",
          700: "#3f6640",
        },
        /** 正典トークン（katazuke.css :root と一致。旧名 blue/blued はエイリアス） */
        kdz: {
          blue: "#527e52",
          blued: "#3f6640",
          navy: "#333333",
          ink: "#333333",
          body: "#4a4a4a",
          bodysoft: "#6b6b6b",
          headgray: "#959595", // 24px 以上の見出し専用
          line: "#d9e0d6",
          linesoft: "#ecf1ec",
          pale: "#eff3ef",
          green: "#527e52",
          lime: "#c9d128",
          marker: "#d4efb3",
          gold: "#e5a323",
          danger: "#d70035",
          line2: "#06c755", // LINE ブランドグリーン（AA 対象外の文書化例外）
        },
        /** よく使う面・文字色のショートハンド */
        navy: "#333333",
        ink: "#333333",
        pale: "#eff3ef",
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
