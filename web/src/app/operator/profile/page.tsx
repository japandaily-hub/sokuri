"use client";

/**
 * 業者プロフィール編集（/operator/profile）。
 * デザイン正典: docs/design_handoff_katazuke/業者プロフィール.html をベースに、
 * 公開プロフィールの「編集画面」（会社情報 / 対応エリア / 取扱カテゴリ /
 * 古物商許可番号 / 公開情報）として operator 側に再構成。
 *
 * /operator は SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、
 * このページが業者向けヘッダー（ロゴ + 業者ナビ + 業者名 + ログアウト）を自前で描く。
 *
 * クライアント化の理由（純表示では不可）:
 *  - 各フィールドの編集と変更検知（保存バーの出し分け）
 *  - 対応エリア / 取扱カテゴリのトグル選択・「得意」星付け
 *  - 公開情報のスイッチ切替
 *  - サイドバーのライブプレビュー・入力完成度の再計算
 *  - 保存/破棄・許可証アップロード（トーストでのデモ挙動）
 * バックエンド未配線: 初期値はモック定数。保存・アップロード・ログアウトは
 * 実処理せず UI 挙動（トースト「保存しました（デモ）」等）のみ。実機能の案件操作は
 * 既存 /operator/cases ・ /operator/transactions へリンク誘導する。
 */

import "./profile.css";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";

/* ---- 業者ナビ（本番ルート） ---- */
const NAV: { href: string; label: string; active?: boolean }[] = [
  { href: "/operator", label: "ダッシュボード" },
  { href: "/operator/cases", label: "案件一覧" },
  { href: "/operator/transactions", label: "取引" },
  { href: "/operator/profile", label: "プロフィール", active: true },
];

/* ---- 対応エリア（東京・千葉・埼玉・神奈川が稼働、他は準備中） ---- */
const AREAS: { name: string; soon?: boolean }[] = [
  { name: "東京都" },
  { name: "神奈川県" },
  { name: "千葉県" },
  { name: "埼玉県" },
  { name: "茨城県", soon: true },
  { name: "栃木県", soon: true },
  { name: "群馬県", soon: true },
  { name: "山梨県", soon: true },
];

/* ---- 取扱カテゴリ（アイコンはスプライト名） ---- */
const CATEGORIES: { id: string; name: string; icon: IcName }[] = [
  { id: "kaden", name: "家電・PC", icon: "sun" },
  { id: "brand", name: "ブランド品", icon: "bag" },
  { id: "camera", name: "カメラ", icon: "camera" },
  { id: "watch", name: "時計・宝飾", icon: "clock" },
  { id: "fashion", name: "衣類・靴", icon: "tag" },
  { id: "furniture", name: "家具", icon: "sofa" },
  { id: "game", name: "ゲーム・玩具", icon: "box" },
  { id: "hobby", name: "楽器・趣味", icon: "spark" },
  { id: "other", name: "その他", icon: "house" },
];

/* ---- 公開情報トグル ---- */
type ToggleKey = "showStats" | "showReviews" | "showMessage" | "acceptUnsellable" | "publicListed";
const TOGGLES: { key: ToggleKey; title: string; desc: string }[] = [
  { key: "publicListed", title: "プロフィールを公開する", desc: "オフにすると入札先のユーザーにプロフィールが表示されません。" },
  { key: "showStats", title: "実績数を公開する", desc: "成約実績・入札履行率・平均引き取り日数を表示します。" },
  { key: "showReviews", title: "口コミを公開する", desc: "成約ユーザーからの評価・口コミを表示します。" },
  { key: "showMessage", title: "業者メッセージを公開する", desc: "自己紹介メッセージをプロフィール上部に表示します。" },
  { key: "acceptUnsellable", title: "値のつかない物もまとめて引き取る", desc: "「まとめて回収可」のバッジが付与され、まとめ出品で選ばれやすくなります。" },
];

/* ---- フォーム状態の型 ---- */
type ProfileState = {
  companyName: string;
  entityType: "法人" | "個人事業主";
  staffCount: string;
  hours: string;
  message: string;
  licenseNumber: string;
  licenseAuthority: string;
  areas: Record<string, boolean>;
  cats: Record<string, boolean>;
  strong: Record<string, boolean>;
  toggles: Record<ToggleKey, boolean>;
};

/* ---- 初期値（モック） ---- */
const INITIAL: ProfileState = {
  companyName: "グリーンリサイクル東京",
  entityType: "法人",
  staffCount: "2",
  hours: "平日・土日 9:00〜19:00",
  message:
    "はじめまして。グリーンリサイクル東京です。東京都・神奈川県を中心に、家電・ブランド品・カメラを得意とする買取業者です。\n\nまとめ買取を専門としており、1件の訪問でできるだけ多くの品物をまとめて買い取ることを大切にしています。値がつかないものも可能な限りまとめて引き取り、お客様の手間を最小限にします。",
  licenseNumber: "東京都公安委員会 第301012345678号",
  licenseAuthority: "東京都公安委員会",
  areas: { 東京都: true, 神奈川県: true },
  cats: { kaden: true, brand: true, camera: true, watch: true, fashion: true, furniture: true, game: true, other: true },
  strong: { kaden: true, brand: true, camera: true },
  toggles: { publicListed: true, showStats: true, showReviews: true, showMessage: true, acceptUnsellable: true },
};

/** ディープ等価判定（プリミティブ + 1階層オブジェクト）で変更検知する。 */
function eq(a: ProfileState, b: ProfileState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

const MESSAGE_MAX = 500;

export default function OperatorProfilePage() {
  const [state, setState] = useState<ProfileState>(INITIAL);
  const [navOpen, setNavOpen] = useState(false);

  /* ---- トースト ---- */
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  function showToast(msg: string) {
    setToast(msg);
    if (toastTimer.current !== undefined) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }
  useEffect(
    () => () => {
      if (toastTimer.current !== undefined) window.clearTimeout(toastTimer.current);
    },
    []
  );

  const dirty = useMemo(() => !eq(state, INITIAL), [state]);

  /* ---- 部分更新ヘルパー ---- */
  function patch<K extends keyof ProfileState>(key: K, value: ProfileState[K]) {
    setState((s) => ({ ...s, [key]: value }));
  }
  function toggleArea(name: string) {
    setState((s) => ({ ...s, areas: { ...s.areas, [name]: !s.areas[name] } }));
  }
  function toggleCat(id: string) {
    setState((s) => {
      const on = !s.cats[id];
      const strong = { ...s.strong };
      if (!on) delete strong[id]; // OFFにしたら「得意」も外す
      return { ...s, cats: { ...s.cats, [id]: on }, strong };
    });
  }
  function toggleStrong(id: string) {
    setState((s) => {
      if (!s.cats[id]) return s; // 取扱OFFのカテゴリは得意化しない
      return { ...s, strong: { ...s.strong, [id]: !s.strong[id] } };
    });
  }
  function toggleSwitch(key: ToggleKey) {
    setState((s) => ({ ...s, toggles: { ...s.toggles, [key]: !s.toggles[key] } }));
  }

  /* ---- 派生値（プレビュー・完成度） ---- */
  const selectedAreas = AREAS.filter((a) => state.areas[a.name]).map((a) => a.name);
  const selectedCats = CATEGORIES.filter((c) => state.cats[c.id]);
  const strongCats = CATEGORIES.filter((c) => state.cats[c.id] && state.strong[c.id]);
  const avatarInitial = state.companyName.trim().charAt(0) || "業";
  const areaSummary =
    selectedAreas.length === 0
      ? "未設定"
      : selectedAreas.length <= 2
        ? selectedAreas.join("・")
        : `${selectedAreas.slice(0, 2).join("・")} 他${selectedAreas.length - 2}件`;

  const checklist = [
    { label: "会社名を入力", done: state.companyName.trim().length > 0 },
    { label: "対応エリアを選択", done: selectedAreas.length > 0 },
    { label: "取扱カテゴリを選択", done: selectedCats.length > 0 },
    { label: "古物商許可番号を入力", done: state.licenseNumber.trim().length > 0 },
    { label: "業者メッセージを入力", done: state.message.trim().length >= 20 },
  ];
  const completion = Math.round((checklist.filter((c) => c.done).length / checklist.length) * 100);

  /* ---- 保存・破棄（デモ） ---- */
  function onSave() {
    if (!dirty) return;
    // 実処理は未配線。実際の保存APIに差し替える箇所。
    showToast("保存しました（デモ）");
    // デモのため初期値スナップショットは更新しない（再編集で差分が再び出る）。
    // 本配線時は INITIAL を最新値で置き換え、dirty を解消する。
  }
  function onRevert() {
    setState(INITIAL);
    showToast("変更を破棄しました");
  }

  return (
    <div className="op-profile">
      {/* ===== 業者ヘッダー（operator 独自） ===== */}
      <header className="op-header">
        <div className="container op-header-inner">
          <Link href="/operator" className="op-brand" aria-label="カタヅケ 業者ダッシュボードへ">
            <KdzLogo size={20} />
            <span className="op-brand-tag">BUYER</span>
          </Link>

          <nav className={`op-nav${navOpen ? " open" : ""}`} aria-label="業者メニュー">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={n.active ? "active" : undefined}
                aria-current={n.active ? "page" : undefined}
                onClick={() => setNavOpen(false)}
              >
                {n.label}
              </Link>
            ))}
          </nav>

          <div className="op-header-right">
            <div className="op-user">
              <span className="op-user-avatar" aria-hidden="true">
                {avatarInitial}
              </span>
              <span className="op-user-name">
                {state.companyName || "業者アカウント"}
                <small>{state.entityType}</small>
              </span>
            </div>
            <Link href="/operator/login" className="op-logout">
              ログアウト
            </Link>
            <button
              type="button"
              className="op-nav-toggle"
              aria-label="メニュー"
              aria-expanded={navOpen}
              onClick={() => setNavOpen((v) => !v)}
            >
              <Ic name="menu" />
            </button>
          </div>
        </div>
      </header>

      {/* ===== ヒーロー ===== */}
      <div className="prof-hero">
        <div className="container">
          <div className="prof-hero-inner">
            <div className="prof-avatar" aria-hidden="true">
              {avatarInitial}
            </div>
            <div className="prof-info">
              <span className="op-eyebrow">BUYER PROFILE</span>
              <div className="prof-name">{state.companyName || "業者名未設定"}</div>
              <div className="prof-tags">
                <span className="prof-tag verified">
                  <Ic name="shield" />
                  古物商許可証確認済み
                </span>
                <span className="prof-tag">{areaSummary}対応</span>
                <span className="prof-tag">2023年登録</span>
              </div>
            </div>
            <div className="prof-hero-actions">
              <Link href="/vendors/1" className="hero-link">
                <Ic name="zoom" />
                公開プレビュー
              </Link>
            </div>
          </div>
        </div>
      </div>

      <main>
        <div className="demo-note">
          <div className="demo-banner">
            <Ic name="shield" />
            <span>
              これは編集画面のデモです。保存・許可証アップロードはまだ本処理に接続されていません。入札可能な案件の確認・落札管理は{" "}
              <Link href="/operator/cases" style={{ color: "#9a3412", textDecoration: "underline", fontWeight: 700 }}>
                案件一覧
              </Link>{" "}
              ・{" "}
              <Link href="/operator/transactions" style={{ color: "#9a3412", textDecoration: "underline", fontWeight: 700 }}>
                取引
              </Link>{" "}
              から行えます。
            </span>
          </div>
        </div>

        <div className="prof-wrap">
          {/* ===== 左：編集フォーム ===== */}
          <div>
            {/* 会社情報 */}
            <section className="prof-card">
              <div className="prof-card-head">
                <span className="head-ic">
                  <Ic name="house" />
                </span>
                <h2>会社情報</h2>
              </div>
              <div className="prof-card-body">
                <div className="form-grid">
                  <div className="field span2">
                    <label htmlFor="companyName">
                      会社名・屋号<span className="req">*</span>
                    </label>
                    <input
                      id="companyName"
                      type="text"
                      value={state.companyName}
                      onChange={(e) => patch("companyName", e.target.value)}
                      placeholder="例：グリーンリサイクル東京"
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="entityType">事業形態</label>
                    <select
                      id="entityType"
                      value={state.entityType}
                      onChange={(e) => patch("entityType", e.target.value as ProfileState["entityType"])}
                    >
                      <option value="法人">法人</option>
                      <option value="個人事業主">個人事業主</option>
                    </select>
                  </div>

                  <div className="field">
                    <label htmlFor="staffCount">引き取りスタッフ人数</label>
                    <input
                      id="staffCount"
                      type="number"
                      min={1}
                      max={20}
                      value={state.staffCount}
                      onChange={(e) => patch("staffCount", e.target.value)}
                      placeholder="2"
                    />
                    <p className="field-hint">訪問時の標準人数。重い品物の対応可否の目安になります。</p>
                  </div>

                  <div className="field span2">
                    <label htmlFor="hours">対応時間</label>
                    <input
                      id="hours"
                      type="text"
                      value={state.hours}
                      onChange={(e) => patch("hours", e.target.value)}
                      placeholder="例：平日・土日 9:00〜19:00"
                    />
                  </div>

                  <div className="field span2">
                    <div className="field-top">
                      <label htmlFor="message">業者からのメッセージ</label>
                      <span className="char-count">
                        {state.message.length} / {MESSAGE_MAX}
                      </span>
                    </div>
                    <textarea
                      id="message"
                      value={state.message}
                      maxLength={MESSAGE_MAX}
                      onChange={(e) => patch("message", e.target.value)}
                      placeholder="得意分野や引き取りの方針、ユーザーへの一言などを記入してください。"
                    />
                    <p className="field-hint">プロフィール上部に表示されます。査定金額の根拠を丁寧に説明する姿勢などを書くと選ばれやすくなります。</p>
                  </div>
                </div>
              </div>
            </section>

            {/* 対応エリア */}
            <section className="prof-card">
              <div className="prof-card-head">
                <span className="head-ic">
                  <Ic name="pin" />
                </span>
                <h2>対応エリア</h2>
                <span className="head-sub">{selectedAreas.length}件 選択中</span>
              </div>
              <div className="prof-card-body">
                <div className="area-grid">
                  {AREAS.map((a) => {
                    const on = !!state.areas[a.name];
                    return (
                      <button
                        key={a.name}
                        type="button"
                        className={`area-chk${on ? " on" : ""}${a.soon ? " soon" : ""}`}
                        aria-pressed={on}
                        disabled={a.soon}
                        onClick={() => !a.soon && toggleArea(a.name)}
                      >
                        <span className="area-box" aria-hidden="true">
                          <Ic name="check" />
                        </span>
                        <span className="area-name">{a.name}</span>
                      </button>
                    );
                  })}
                </div>
                <p className="field-hint" style={{ marginTop: 14 }}>
                  対応エリアの案件のみ入札対象として表示されます。エリアは順次拡大予定です（準備中の都県は近日選択可能になります）。
                </p>
              </div>
            </section>

            {/* 取扱カテゴリ */}
            <section className="prof-card">
              <div className="prof-card-head">
                <span className="head-ic">
                  <Ic name="bag" />
                </span>
                <h2>取扱カテゴリ</h2>
                <span className="head-sub">{selectedCats.length}件 / 得意 {strongCats.length}件</span>
              </div>
              <div className="prof-card-body">
                <div className="cat-grid">
                  {CATEGORIES.map((c) => {
                    const on = !!state.cats[c.id];
                    const starred = on && !!state.strong[c.id];
                    return (
                      <span key={c.id} className={`cat-toggle${on ? " on" : ""}${starred ? " strong" : ""}`}>
                        <button
                          type="button"
                          aria-pressed={on}
                          onClick={() => toggleCat(c.id)}
                          style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "none", border: "none", cursor: "pointer", color: "inherit", font: "inherit", padding: 0 }}
                        >
                          <Ic name={c.icon} />
                          {c.name}
                        </button>
                        <button
                          type="button"
                          className={`cat-star${starred ? " starred" : ""}`}
                          aria-label={`${c.name}を得意カテゴリに${starred ? "外す" : "設定"}`}
                          aria-pressed={starred}
                          disabled={!on}
                          onClick={() => toggleStrong(c.id)}
                          title={on ? "得意カテゴリに設定" : "先に取扱カテゴリをオンにしてください"}
                        >
                          ★
                        </button>
                      </span>
                    );
                  })}
                </div>
                <div className="cat-legend">
                  <span className="legend-star">★</span>
                  <span>
                    を付けた<span className="legend-chip">得意</span>カテゴリは、公開プロフィールで強調表示され、まとめ出品で選ばれやすくなります。
                  </span>
                </div>
              </div>
            </section>

            {/* 古物商許可番号 */}
            <section className="prof-card">
              <div className="prof-card-head">
                <span className="head-ic">
                  <Ic name="shield" />
                </span>
                <h2>古物商許可</h2>
              </div>
              <div className="prof-card-body">
                <div className="license-status ok">
                  <span className="ls-ic">
                    <Ic name="check" />
                  </span>
                  <div className="ls-body">
                    <h3>確認済み</h3>
                    <p>運営が許可証を確認・審査済みです。番号を変更すると再審査となります。</p>
                  </div>
                </div>

                <div className="form-grid">
                  <div className="field span2">
                    <label htmlFor="licenseNumber">
                      古物商許可番号<span className="req">*</span>
                    </label>
                    <input
                      id="licenseNumber"
                      type="text"
                      value={state.licenseNumber}
                      onChange={(e) => patch("licenseNumber", e.target.value)}
                      placeholder="例：東京都公安委員会 第301012345678号"
                      inputMode="text"
                    />
                    <p className="field-hint">許可証に記載の公安委員会名と12桁の許可番号を入力してください。</p>
                  </div>
                  <div className="field span2">
                    <label htmlFor="licenseAuthority">交付公安委員会</label>
                    <input
                      id="licenseAuthority"
                      type="text"
                      value={state.licenseAuthority}
                      onChange={(e) => patch("licenseAuthority", e.target.value)}
                      placeholder="例：東京都公安委員会"
                    />
                  </div>
                </div>

                <div className="upload-row" style={{ marginTop: 4 }}>
                  <span className="upload-ic">
                    <Ic name="up" />
                  </span>
                  <div className="upload-body">
                    <strong>許可証の画像</strong>
                    <span>JPG / PNG / PDF・10MBまで。番号変更時は再アップロードが必要です。</span>
                  </div>
                  <button type="button" className="upload-btn" onClick={() => showToast("アップロードはデモです")}>
                    ファイルを選択
                  </button>
                </div>
              </div>
            </section>

            {/* 公開情報 */}
            <section className="prof-card">
              <div className="prof-card-head">
                <span className="head-ic">
                  <Ic name="lock" />
                </span>
                <h2>公開情報</h2>
                <span className="head-sub">ユーザーへの見え方</span>
              </div>
              <div className="prof-card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
                {TOGGLES.map((t) => {
                  const on = !!state.toggles[t.key];
                  return (
                    <div className="toggle-row" key={t.key}>
                      <div className="toggle-text">
                        <strong>{t.title}</strong>
                        <span>{t.desc}</span>
                      </div>
                      <button
                        type="button"
                        className={`switch${on ? " on" : ""}`}
                        role="switch"
                        aria-checked={on}
                        aria-label={t.title}
                        onClick={() => toggleSwitch(t.key)}
                      />
                    </div>
                  );
                })}
              </div>
            </section>
          </div>

          {/* ===== 右：サイドバー ===== */}
          <aside className="sidebar">
            {/* ライブプレビュー */}
            <section className="prof-card flush">
              <div className="prof-card-head">
                <h2>公開プレビュー</h2>
              </div>
              <div className="prof-card-body">
                <div className="preview-mini">
                  <span className="preview-avatar" aria-hidden="true">
                    {avatarInitial}
                  </span>
                  <div>
                    <div className="preview-name">{state.companyName || "業者名未設定"}</div>
                    <div className="preview-area">{areaSummary}対応 ・ {state.entityType}</div>
                  </div>
                </div>
                {strongCats.length > 0 ? (
                  <div className="preview-chips">
                    {strongCats.map((c) => (
                      <span className="preview-chip" key={c.id}>
                        {c.name}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="preview-empty">得意カテゴリを★で設定すると、ここに強調表示されます。</p>
                )}
              </div>
            </section>

            {/* 入力完成度 */}
            <section className="prof-card flush">
              <div className="prof-card-head">
                <h2>入力の完成度</h2>
              </div>
              <div className="prof-card-body">
                <div className="completion-row">
                  <span className="completion-num">
                    {completion}
                    <span>%</span>
                  </span>
                  <div className="completion-bar-wrap">
                    <div className="completion-bar" style={{ width: `${completion}%` }} />
                  </div>
                </div>
                <ul className="checklist">
                  {checklist.map((c) => (
                    <li key={c.label} className={c.done ? "done" : undefined}>
                      <span className="check-dot" aria-hidden="true">
                        <Ic name="check" />
                      </span>
                      {c.label}
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            {/* 手数料の案内 */}
            <section className="prof-card flush">
              <div className="prof-card-body">
                <div className="fee-note">
                  <span className="fee-note-ic">
                    <Ic name="yen" />
                  </span>
                  <div>
                    <h4>手数料は成約額の8%</h4>
                    <p>初期費用・月額費用は無料。費用が発生するのは成約時のみです。料金の詳細は登録時の規約に準じます。</p>
                  </div>
                </div>
              </div>
            </section>
          </aside>
        </div>
      </main>

      {/* ===== 保存バー（変更時のみ表示） ===== */}
      <div className={`save-bar${dirty ? " show" : ""}`} aria-hidden={!dirty}>
        <div className="save-bar-inner">
          <span className="save-bar-text">
            <span className="save-dot" aria-hidden="true" />
            未保存の変更があります
          </span>
          <div className="save-bar-actions">
            <button type="button" className="btn-revert" onClick={onRevert} disabled={!dirty}>
              変更を破棄
            </button>
            <button type="button" className="btn-save" onClick={onSave} disabled={!dirty}>
              <Ic name="check" />
              保存する
            </button>
          </div>
        </div>
      </div>

      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
