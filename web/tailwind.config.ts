import type { Config } from "tailwindcss";

/**
 * カタヅケ デザインシステム — Tailwind トークン定義
 *
 * 方向性: 「見本 v12 / 藍 × 生成り × 丸ゴ・角ゴ × 角丸6px」。基幹は藍 #2e4a7d。
 * 正典トークン（src/app/katazuke.css :root / SPEC-4-decisions.md §4.1）を Tailwind に
 * 橋渡しし、ユーティリティ（text-navy / bg-pale / rounded-kdz / font-head）でも
 * 同じ値に到達できるようにする。ピクセル忠実な実体は src/app/katazuke.css。
 */
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    /** 見本 v12: 角丸は katazuke.css の --radius(6px)/--radius-s(4px) の1段に固定（2xl 以上は 0 のまま・full は円形アバター用に据え置き）。影は全段 none */
    borderRadius: { none: "0px", sm: "var(--radius)", DEFAULT: "var(--radius)", md: "var(--radius)", lg: "var(--radius)", xl: "var(--radius)", "2xl": "0px", "3xl": "0px", "4xl": "0px", kdz: "var(--radius)", "kdz-s": "var(--radius-s)", full: "9999px" },
    boxShadow: { none: "none", sm: "none", DEFAULT: "none", md: "none", lg: "none", xl: "none", "2xl": "none", inner: "none", xs: "none", card: "none", "card-hover": "none", elevated: "none", cta: "none", "kdz-s": "none", "kdz-m": "none", "kdz-l": "none" },
    extend: {
      /**
       * 色は katazuke.css :root の変数への参照。var() 参照なので Tailwind の不透明度修飾子（bg-brand-600/50 等）は
       * 効かない（現状の使用は0件）。半透明が要るときは CSS 側で rgba(var(--primary-rgb),.5) を書く。
       */
      colors: {
        /** 基幹ブランドカラー: 藍（brand-600 = 正典 --primary） */
        brand: {
          50: "var(--indigo-tint)",
          100: "#c9d2e1",
          200: "#aebbd3",
          300: "#8d9fc0",
          400: "var(--primary-l)",
          500: "var(--primary-l)",
          600: "var(--primary)", // primary action（正典 --primary）
          700: "var(--primary-d)", // hover（正典 --primary-d）
          800: "var(--deep)",
          900: "var(--deep)",
          950: "var(--ink)",
        },
        /** 補助カラー: 成功・完了・前向きシグナル（主色=藍とは別系統の緑に固定） */
        accent: {
          50: "#ecfdf3",
          100: "#d1fae1",
          200: "#a6f0c6",
          300: "#6fdca4",
          400: "#3cbf7f",
          500: "#22a366",
          600: "var(--green)",
          700: "#116832",
        },
        /** 正典トークン（katazuke.css :root を参照。旧名 blue/blued はエイリアス） */
        kdz: {
          blue: "var(--primary)",
          blued: "var(--primary-d)",
          navy: "var(--navy)",
          ink: "var(--ink)",
          body: "var(--body)",
          bodysoft: "var(--body-soft)",
          headgray: "var(--head-gray)",
          line: "var(--line)",
          linesoft: "var(--line-soft)",
          pale: "var(--pale)",
          green: "var(--green)", // 成功/完了などの意味色（主色=藍とは別系統）
          lime: "var(--lime)",
          marker: "var(--marker)",
          gold: "var(--gold)",
          danger: "var(--danger)",
          line2: "var(--line-green)", // LINE ブランドグリーン（AA 対象外の文書化例外）
          /** モーション拡張（ビジュアル刷新 Phase 0）: RevealLines のマーカー下線色 */
          markerDraw: "var(--marker-draw)",
        },
        /** よく使う面・文字色のショートハンド */
        navy: "var(--navy)",
        ink: "var(--ink)",
        pale: "var(--pale)",
      },
      /** 書体は katazuke.css の変数へ一本化（見本 v12: 丸ゴ見出し × 角ゴ本文 × Inter 数字） */
      fontFamily: {
        head: ["var(--head)"],
        maru: ["var(--maru)"],
        sans: ["var(--sans)"],
        ui: ["var(--ui)"],
        num: ["var(--num)"],
        /** 旧名（廃止予定）。--en/--en-display は角ゴ・Inter の別名になった */
        en: ["var(--en)"],
        "en-display": ["var(--en-display)"],
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
        kdz: "var(--radius)",
        "kdz-s": "var(--radius-s)",
      },
      maxWidth: {
        container: "72rem",
        kdz: "1140px",
        "kdz-text": "760px",
      },
      transitionTimingFunction: {
        kdz: "cubic-bezier(.22,.61,.36,1)",
        /** モーション拡張（ビジュアル刷新 Phase 0）: katazuke.css の --ease-* と一致させる */
        "expo-out": "var(--ease-expo-out)",
        "circ-out": "var(--ease-circ-out)",
        "power3-out": "var(--ease-power3-out)",
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
