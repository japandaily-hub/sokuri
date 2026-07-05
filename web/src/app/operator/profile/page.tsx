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
 * バックエンド実配線: GET/PUT /operator/profile。
 * 会社名・古物商許可番号・審査状況（vendor_status/verified_at）は審査確定項目のため
 * 読み取り専用表示のみ（PUT には含めない）。編集可能項目（areas / categories /
 * strong_categories / staff_count / business_hours / intro_message / is_public /
 * show_stats / show_reviews / show_message / accept_unsellable）のみ保存対象。
 * 画像アップロードは今回もスコープ外（デモ挙動のまま）。
 */

import "./profile.css";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { OperatorHeader } from "@/components/kdz/OperatorHeader";
import { useToken } from "@/components/kdz/Ui";
import {
  getOperatorProfile,
  toDisplayMessage,
  updateOperatorProfile,
  type OperatorProfile,
} from "@/lib/katadzuke-api";

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

/* ---- 公開情報トグル（バックエンドフィールド名にマッピング） ---- */
type ToggleKey = "showStats" | "showReviews" | "showMessage" | "acceptUnsellable" | "publicListed";
const TOGGLES: { key: ToggleKey; title: string; desc: string }[] = [
  { key: "publicListed", title: "プロフィールを公開する", desc: "オフにすると入札先のユーザーにプロフィールが表示されません。" },
  { key: "showStats", title: "実績数を公開する", desc: "成約実績・入札履行率・平均引き取り日数を表示します。" },
  { key: "showReviews", title: "口コミを公開する", desc: "成約ユーザーからの評価・口コミを表示します。" },
  { key: "showMessage", title: "業者メッセージを公開する", desc: "自己紹介メッセージをプロフィール上部に表示します。" },
  { key: "acceptUnsellable", title: "値のつかない物もまとめて引き取る", desc: "「まとめて回収可」のバッジが付与され、まとめ出品で選ばれやすくなります。" },
];

/* ---- 編集可能項目のみのフォーム状態（審査確定項目は含めない） ---- */
type ProfileState = {
  staffCount: string;
  hours: string;
  message: string;
  areas: Record<string, boolean>;
  cats: Record<string, boolean>;
  strong: Record<string, boolean>;
  toggles: Record<ToggleKey, boolean>;
};

const EMPTY_STATE: ProfileState = {
  staffCount: "",
  hours: "",
  message: "",
  areas: {},
  cats: {},
  strong: {},
  toggles: {
    publicListed: true,
    showStats: true,
    showReviews: true,
    showMessage: true,
    acceptUnsellable: false,
  },
};

/** 星文字列（塗り★ + 空☆）。デザインレビュー M-4 対応: /vendors/[id] と同じロジックを共有。 */
function starString(rating: number): string {
  const filled = Math.round(rating);
  return "★".repeat(filled) + "☆".repeat(Math.max(0, 5 - filled));
}

/** バックエンドの OperatorProfile → 編集フォーム状態へ変換。 */
function toFormState(p: OperatorProfile): ProfileState {
  return {
    staffCount: p.staff_count != null ? String(p.staff_count) : "",
    hours: p.business_hours ?? "",
    message: p.intro_message ?? "",
    areas: Object.fromEntries(p.areas.map((a) => [a, true])),
    cats: Object.fromEntries(p.categories.map((c) => [c, true])),
    strong: Object.fromEntries(p.strong_categories.map((c) => [c, true])),
    toggles: {
      publicListed: p.is_public,
      showStats: p.show_stats,
      showReviews: p.show_reviews,
      showMessage: p.show_message,
      acceptUnsellable: p.accept_unsellable,
    },
  };
}

/** 編集フォーム状態 → PUT ペイロードへ変換。 */
function toUpdatePayload(s: ProfileState) {
  const areas = Object.entries(s.areas).filter(([, on]) => on).map(([name]) => name);
  const categories = Object.entries(s.cats).filter(([, on]) => on).map(([id]) => id);
  const strongCategories = Object.entries(s.strong).filter(([, on]) => on).map(([id]) => id);
  const staffCount = s.staffCount.trim() === "" ? null : Number(s.staffCount);
  return {
    areas,
    categories,
    strong_categories: strongCategories,
    staff_count: staffCount != null && Number.isFinite(staffCount) ? staffCount : null,
    business_hours: s.hours.trim() || null,
    intro_message: s.message.trim() || null,
    is_public: s.toggles.publicListed,
    show_stats: s.toggles.showStats,
    show_reviews: s.toggles.showReviews,
    show_message: s.toggles.showMessage,
    accept_unsellable: s.toggles.acceptUnsellable,
  };
}

/** ディープ等価判定（プリミティブ + 1階層オブジェクト）で変更検知する。 */
function eq(a: ProfileState, b: ProfileState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

const MESSAGE_MAX = 500;

export default function OperatorProfilePage() {
  const { token, loading: tokenLoading } = useToken();

  const [profile, setProfile] = useState<OperatorProfile | null>(null);
  const [initialState, setInitialState] = useState<ProfileState>(EMPTY_STATE);
  const [state, setState] = useState<ProfileState>(EMPTY_STATE);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
    [],
  );

  /* ---- 初回取得 ---- */
  const load = useCallback(async () => {
    if (!token) return;
    try {
      const p = await getOperatorProfile(token);
      setProfile(p);
      const formState = toFormState(p);
      setInitialState(formState);
      setState(formState);
      setLoadError(null);
    } catch (e) {
      setLoadError(toDisplayMessage(e, "プロフィールの取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(() => !eq(state, initialState), [state, initialState]);

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
  const companyName = profile?.company_name ?? "";
  const licenseNumber = profile?.license_number ?? "";
  const verified = profile?.verified_at != null;
  const selectedAreas = AREAS.filter((a) => state.areas[a.name]).map((a) => a.name);
  const selectedCats = CATEGORIES.filter((c) => state.cats[c.id]);
  const strongCats = CATEGORIES.filter((c) => state.cats[c.id] && state.strong[c.id]);
  const avatarInitial = companyName.trim().charAt(0) || "業";
  const areaSummary =
    selectedAreas.length === 0
      ? "未設定"
      : selectedAreas.length <= 2
        ? selectedAreas.join("・")
        : `${selectedAreas.slice(0, 2).join("・")} 他${selectedAreas.length - 2}件`;

  const checklist = [
    { label: "会社名を入力", done: companyName.trim().length > 0 },
    { label: "対応エリアを選択", done: selectedAreas.length > 0 },
    { label: "取扱カテゴリを選択", done: selectedCats.length > 0 },
    { label: "古物商許可番号を確認", done: licenseNumber.trim().length > 0 },
    { label: "業者メッセージを入力", done: state.message.trim().length >= 20 },
  ];
  const completion = Math.round((checklist.filter((c) => c.done).length / checklist.length) * 100);

  /* ---- 保存・破棄 ---- */
  async function onSave() {
    if (!dirty || !token || saving) return;
    setSaving(true);
    try {
      const updated = await updateOperatorProfile(toUpdatePayload(state), token);
      setProfile(updated);
      const formState = toFormState(updated);
      setInitialState(formState);
      setState(formState);
      showToast("保存しました");
    } catch (e) {
      showToast(toDisplayMessage(e, "保存に失敗しました"));
    } finally {
      setSaving(false);
    }
  }
  function onRevert() {
    setState(initialState);
    showToast("変更を破棄しました");
  }

  if (tokenLoading || (!profile && !loadError)) {
    return (
      <div className="op-profile">
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>読み込み中…</div>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="op-profile">
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>
          {loadError ?? "プロフィールが見つかりません。"}
        </div>
      </div>
    );
  }

  return (
    <div className="op-profile">
      {/* ===== 業者ヘッダー（共通 OperatorHeader）=====
          デザインレビュー B-5 対応: ダッシュボードと別実装だった独自ヘッダーを
          components/kdz/OperatorHeader.tsx へ統合。 */}
      <OperatorHeader active="profile" companyName={companyName} />

      {/* ===== ヒーロー ===== */}
      <div className="prof-hero">
        <div className="container">
          <div className="prof-hero-inner">
            <div className="prof-avatar" aria-hidden="true">
              {avatarInitial}
            </div>
            <div className="prof-info">
              <span className="op-eyebrow">BUYER PROFILE</span>
              <div className="prof-name">{companyName || "業者名未設定"}</div>
              <div className="prof-tags">
                {verified ? (
                  <span className="prof-tag verified">
                    <Ic name="shield" />
                    古物商許可証確認済み
                  </span>
                ) : (
                  <span className="prof-tag">審査中</span>
                )}
                <span className="prof-tag">{areaSummary}対応</span>
              </div>
            </div>
            <div className="prof-hero-actions">
              <Link href={`/vendors/${profile.operator_id}`} className="hero-link">
                <Ic name="zoom" />
                公開プレビュー
              </Link>
            </div>
          </div>
        </div>
      </div>

      <main>
        {loadError ? (
          <div className="demo-note">
            <div className="demo-banner">
              <Ic name="shield" />
              <span>{loadError}</span>
            </div>
          </div>
        ) : null}

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
                    <label htmlFor="companyName">会社名・屋号</label>
                    <input id="companyName" type="text" value={companyName} disabled readOnly />
                    <p className="field-hint">審査確定項目のため編集できません。変更が必要な場合は運営へお問い合わせください。</p>
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
                <div className={`license-status${verified ? " ok" : ""}`}>
                  <span className="ls-ic">
                    <Ic name="check" />
                  </span>
                  <div className="ls-body">
                    <h3>{verified ? "確認済み" : "審査中"}</h3>
                    <p>運営が許可証を確認・審査します。番号等の変更が必要な場合は運営へお問い合わせください。</p>
                  </div>
                </div>

                <div className="form-grid">
                  <div className="field span2">
                    <label htmlFor="licenseNumber">古物商許可番号</label>
                    <input id="licenseNumber" type="text" value={licenseNumber} disabled readOnly />
                    <p className="field-hint">審査確定項目のため編集できません。</p>
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
            {/* 評価サマリー（読み取り専用。デザインレビュー M-4 対応: 正典の score-row/stars を
                読み取り専用サマリーとして復元。詳細な評価分布・口コミは /vendors/[id] に集約） */}
            <section className="prof-card flush">
              <div className="prof-card-head">
                <h2>評価サマリー</h2>
                <span className="head-sub">ユーザーからの評価</span>
              </div>
              <div className="prof-card-body">
                {profile.rating != null ? (
                  <div className="rating-summary">
                    <div className="rating-summary-stars">{starString(profile.rating)}</div>
                    <div className="rating-summary-num">{profile.rating.toFixed(1)}</div>
                  </div>
                ) : (
                  <p className="preview-empty">まだ評価がありません。取引が完了すると表示されます。</p>
                )}
                <Link href={`/vendors/${profile.operator_id}`} className="rating-summary-link">
                  口コミを見る
                  <Ic name="arrow" />
                </Link>
              </div>
            </section>

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
                    <div className="preview-name">{companyName || "業者名未設定"}</div>
                    <div className="preview-area">{areaSummary}対応</div>
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
            <button type="button" className="btn-revert" onClick={onRevert} disabled={!dirty || saving}>
              変更を破棄
            </button>
            <button type="button" className="btn-save" onClick={() => void onSave()} disabled={!dirty || saving}>
              <Ic name="check" />
              {saving ? "保存中…" : "保存する"}
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
