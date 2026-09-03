import type { Config } from "tailwindcss";

/**
 * カタヅケ デザインシステム — Tailwind トークン定義
 *
 * 方向性: 「White × Cobalt / あたたかさとつながり」。基幹は彩度を上げたコバルト #1447e0。
 * デザインハンドオフ（katazuke-main.css）の正典トークンを Tailwind に橋渡しし、
 * ユーティリティ（text-navy / bg-pale / shadow-m / rounded-kdz / font-head）でも
 * 同じ値に到達できるようにする。ピクセル忠実な実体は src/app/katazuke.css。
 */
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        /** 基幹ブランドカラー: 彩度を一段上げたコバルト（brand-600 = ハンドオフ --blue） */
        brand: {
          50: "#eef4ff",
          100: "#d9e6ff",
          200: "#bcd4ff",
          300: "#8eb6ff",
          400: "#598ffb",
          500: "#336bf2",
          600: "#1447e0", // primary action（ハンドオフ --blue）
          700: "#0f37b4", // hover（ハンドオフ --blue-d）
          800: "#1d3c92",
          900: "#1d3677",
          950: "#141f48",
        },
        /** 補助カラー: 価値・成功・前向きシグナル（エメラルド） */
        accent: {
          50: "#ecfdf5",
          100: "#d1fae5",
          200: "#a7f3d0",
          300: "#6ee7b7",
          400: "#34d399",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
        },
        /** ハンドオフ正典トークン（katazuke.css :root と一致） */
        kdz: {
          blue: "#1447e0",
          blued: "#0f37b4",
          navy: "#241f1c",
          ink: "#2f2924",
          body: "#5e5750",
          bodysoft: "#8d857c",
          line: "#ebe5dd",
          linesoft: "#f4f0ea",
          pale: "#f0f5ff",
          green: "#0e8a5a",
          gold: "#b9892f",
          line2: "#06c755", // LINE ブランドグリーン
        },
        /** よく使う面・文字色のショートハンド */
        navy: "#241f1c",
        ink: "#2f2924",
        pale: "#f0f5ff",
      },
      fontFamily: {
        head: ['"Zen Maru Gothic"', '"Zen Kaku Gothic New"', '"Hiragino Kaku Gothic ProN"', '"Yu Gothic UI"', "sans-serif"],
        sans: [
          '"Noto Sans JP"',
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          '"Hiragino Kaku Gothic ProN"',
          '"Hiragino Sans"',
          "Meiryo",
          '"Yu Gothic UI"',
          "Roboto",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(20 31 72 / 0.06)",
        card: "0 1px 2px 0 rgb(20 31 72 / 0.04), 0 6px 18px -6px rgb(20 31 72 / 0.10)",
        "card-hover":
          "0 2px 4px 0 rgb(20 31 72 / 0.05), 0 14px 32px -10px rgb(20 31 72 / 0.18)",
        elevated:
          "0 10px 30px -8px rgb(20 31 72 / 0.18), 0 28px 56px -20px rgb(20 31 72 / 0.20)",
        cta: "0 10px 24px -8px rgb(20 71 224 / 0.45)",
        /** ハンドオフ正典シャドウ（--shadow-s / m / l） */
        "kdz-s": "0 1px 2px rgba(36,31,28,.045), 0 6px 18px -10px rgba(36,31,28,.14)",
        "kdz-m": "0 2px 6px rgba(36,31,28,.04), 0 22px 46px -24px rgba(20,71,224,.30)",
        "kdz-l": "0 30px 72px -34px rgba(20,71,224,.40), 0 10px 26px -18px rgba(36,31,28,.20)",
      },
      borderRadius: {
        "4xl": "1.75rem",
        kdz: "24px",
        "kdz-s": "16px",
      },
      maxWidth: {
        container: "72rem",
        kdz: "1140px",
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
