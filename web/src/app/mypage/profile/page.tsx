"use client";

/**
 * 会員情報・設定（/mypage/profile）— 実配線済み。
 * デザイン正典: docs/design_handoff_katazuke/会員情報編集.html をピクセル忠実に再現。
 * バックエンド: GET/PUT /users/me/profile, PUT /users/me/password（katadzuke-api.ts）。
 *
 * 注意:
 *  - パスワード変更成功時、旧JWTは backend 側で即時失効するため、レスポンスの
 *    access_token を必ず useSession().update() でセッションへ反映すること
 *    （反映を忘れると直後から以降のAPIが全て401になる）。
 *  - has_password === false（LINEログイン専用）のユーザーはパスワード変更セクションを
 *    説明文に置き換える（変更不可のため）。
 *  - 通知設定・画像アップロードはバックエンドにデータ源が無いため実装しない
 *    （モック/デモ挙動の温存は禁止 — 2026-07-16 に一度 redirect 化された経緯があるため）。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { AppHeader } from "@/components/kdz/AppHeader";
import { PasswordField } from "@/components/kdz/auth";
import { StatusBadge, useToken } from "@/components/kdz/Ui";
import {
  getMyProfile,
  updateMyProfile,
  changeMyPassword,
  getMyAddress,
  updateMyAddress,
  toDisplayMessage,
  RESIDENCE_AREAS,
  PREFECTURES,
  OCCUPATIONS,
  IDENTITY_STATUS_LABEL,
  type AddressOut,
  type UserProfile,
} from "@/lib/katadzuke-api";
import "./profile.css";

/* セクションタイトル用アイコン（デザインHTMLの線画パスをそのまま移植） */
const ICON_USER = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);
const ICON_PIN = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
    <circle cx="12" cy="10" r="3" />
  </svg>
);
const ICON_LOCK = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 018 0v4" />
  </svg>
);
const ICON_CHECK = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
);
const ICON_SHIELD = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3l7 3v6c0 4.7-3 7.9-7 9-4-1.1-7-4.3-7-9V6z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
);
const ICON_BANK = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M3 10l9-6 9 6" />
    <path d="M4 10v9M9 10v9M15 10v9M20 10v9" />
    <path d="M2 21h20" />
  </svg>
);
const ICON_LINE = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" />
  </svg>
);

/** サーバー未到達・想定外エラー時のアラート帯（mypage/page.tsx と同じスタイル）。 */
function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      style={{
        marginBottom: 20,
        padding: "12px 16px",
        borderRadius: "var(--radius-s)",
        background: "rgba(215,0,53,.06)",
        color: "var(--danger)",
        fontSize: 13,
        border: "1px solid rgba(215,0,53,.35)",
      }}
    >
      {children}
    </div>
  );
}

export default function ProfileEditPage() {
  const { data: sessionData, update } = useSession();
  const { token, loading: tokenLoading } = useToken();

  // サーバーから取得したプロフィール
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 基本情報（フォーム状態）
  const [sei, setSei] = useState("");
  const [mei, setMei] = useState("");
  const [seiKana, setSeiKana] = useState("");
  const [meiKana, setMeiKana] = useState("");
  const [phone, setPhone] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [occupation, setOccupation] = useState("");
  const [seiErr, setSeiErr] = useState<string | null>(null);
  const [meiErr, setMeiErr] = useState<string | null>(null);

  // エリア
  const [area, setArea] = useState<string | null>(null);

  // 住所（別API・独立保存）
  const [address, setAddress] = useState<AddressOut | null>(null);
  const [addressLoadError, setAddressLoadError] = useState<string | null>(null);
  const [postalCode, setPostalCode] = useState("");
  const [prefecture, setPrefecture] = useState("");
  const [city, setCity] = useState("");
  const [addressLine1, setAddressLine1] = useState("");
  const [addressLine2, setAddressLine2] = useState("");
  const [addressDirty, setAddressDirty] = useState(false);
  const [addressSaving, setAddressSaving] = useState(false);
  const [addressSaved, setAddressSaved] = useState(false);
  const [addressError, setAddressError] = useState<string | null>(null);
  const [postalErr, setPostalErr] = useState<string | null>(null);
  const [prefErr, setPrefErr] = useState<string | null>(null);
  const [cityErr, setCityErr] = useState<string | null>(null);
  const [line1Err, setLine1Err] = useState<string | null>(null);

  // 変更検知・保存状態
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // パスワード変更
  const [pwCur, setPwCur] = useState("");
  const [pwNew, setPwNew] = useState("");
  const [pwConf, setPwConf] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [pwChanging, setPwChanging] = useState(false);
  const [pwDone, setPwDone] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const p = await getMyProfile(token);
      setProfile(p);
      setSei(p.family_name ?? "");
      setMei(p.given_name ?? "");
      setSeiKana(p.family_name_kana ?? "");
      setMeiKana(p.given_name_kana ?? "");
      setPhone(p.phone ?? "");
      setBirthDate(p.birth_date ?? "");
      setOccupation(p.occupation ?? "");
      setArea(p.residence_area ?? null);
      setDirty(false);
      setSaved(false);
      setLoadError(null);
    } catch (e) {
      setLoadError(toDisplayMessage(e, "プロフィールの取得に失敗しました"));
    }
  }, [token]);

  const loadAddress = useCallback(async () => {
    if (!token) return;
    try {
      const a = await getMyAddress(token);
      setAddress(a);
      setPostalCode(a.postal_code ?? "");
      setPrefecture(a.prefecture ?? "");
      setCity(a.city ?? "");
      setAddressLine1(a.address_line1 ?? "");
      setAddressLine2(a.address_line2 ?? "");
      setAddressDirty(false);
      setAddressSaved(false);
      setAddressLoadError(null);
    } catch (e) {
      setAddressLoadError(toDisplayMessage(e, "住所の取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void load();
    void loadAddress();
  }, [load, loadAddress]);

  const markAddressDirty = () => {
    setAddressDirty(true);
    setAddressSaved(false);
  };

  const onSaveAddress = async () => {
    let ok = true;
    const postalTrimmed = postalCode.trim();
    if (!/^\d{3}-?\d{4}$/.test(postalTrimmed)) {
      setPostalErr("郵便番号は7桁の数字（ハイフン可）で入力してください");
      ok = false;
    } else setPostalErr(null);
    if (!prefecture) {
      setPrefErr("都道府県を選択してください");
      ok = false;
    } else setPrefErr(null);
    if (!city.trim()) {
      setCityErr("市区町村を入力してください");
      ok = false;
    } else setCityErr(null);
    if (!addressLine1.trim()) {
      setLine1Err("番地を入力してください");
      ok = false;
    } else setLine1Err(null);
    if (!ok || !token) return;

    setAddressSaving(true);
    setAddressError(null);
    try {
      const updated = await updateMyAddress(
        {
          postal_code: postalTrimmed,
          prefecture,
          city: city.trim(),
          address_line1: addressLine1.trim(),
          address_line2: addressLine2.trim() || null,
        },
        token,
      );
      setAddress(updated);
      setPostalCode(updated.postal_code ?? "");
      setPrefecture(updated.prefecture ?? "");
      setCity(updated.city ?? "");
      setAddressLine1(updated.address_line1 ?? "");
      setAddressLine2(updated.address_line2 ?? "");
      // 住所保存時にバックエンド側で residence_area が自動同期されるため、既存の
      // 「お住まいのエリア」表示もサーバー値に追随させる。
      setArea(updated.residence_area ?? area);
      setAddressDirty(false);
      setAddressSaved(true);
      setShowToast(true);
      window.setTimeout(() => setShowToast(false), 2500);
    } catch (e) {
      setAddressError(
        toDisplayMessage(e, "住所の保存に失敗しました。入力内容をご確認のうえ、もう一度お試しください。"),
      );
    } finally {
      setAddressSaving(false);
    }
  };

  const markDirty = () => {
    setDirty(true);
    setSaved(false);
  };

  const selectArea = (id: string) => {
    setArea(id);
    markDirty();
  };

  // 保存
  const onSave = async () => {
    let ok = true;
    if (!sei.trim()) {
      setSeiErr("姓を入力してください");
      ok = false;
    } else setSeiErr(null);
    if (!mei.trim()) {
      setMeiErr("名を入力してください");
      ok = false;
    } else setMeiErr(null);
    if (!ok || !token) return;

    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateMyProfile(
        {
          family_name: sei.trim(),
          given_name: mei.trim(),
          family_name_kana: seiKana.trim() || null,
          given_name_kana: meiKana.trim() || null,
          phone: phone.trim() || null,
          residence_area: area,
          birth_date: birthDate || null,
          occupation: occupation || null,
        },
        token,
      );
      setProfile(updated);
      setSei(updated.family_name ?? "");
      setMei(updated.given_name ?? "");
      setSeiKana(updated.family_name_kana ?? "");
      setMeiKana(updated.given_name_kana ?? "");
      setPhone(updated.phone ?? "");
      setBirthDate(updated.birth_date ?? "");
      setOccupation(updated.occupation ?? "");
      setArea(updated.residence_area ?? null);
      setDirty(false);
      setSaved(true);
      setShowToast(true);
      window.setTimeout(() => setShowToast(false), 2500);
      // ヘッダー等が参照する session.user.name を即時反映する。
      void update({ name: `${updated.family_name ?? ""} ${updated.given_name ?? ""}`.trim() });
    } catch (e) {
      setSaveError(toDisplayMessage(e, "保存に失敗しました。入力内容をご確認のうえ、もう一度お試しください。"));
    } finally {
      setSaving(false);
    }
  };

  // パスワード変更
  const onChangePw = async () => {
    if (!pwCur) {
      setPwErr("現在のパスワードを入力してください");
      return;
    }
    if (pwNew.length < 8) {
      setPwErr("新しいパスワードは8文字以上で設定してください");
      return;
    }
    if (pwNew !== pwConf) {
      setPwErr("新しいパスワードが一致しません");
      return;
    }
    if (!token) return;

    setPwErr(null);
    setPwChanging(true);
    try {
      const res = await changeMyPassword({ current_password: pwCur, new_password: pwNew }, token);
      // 旧JWTは即時失効するため、新access_tokenでセッションを更新しないと以後のAPIが全て401になる。
      await update({ accessToken: res.access_token });
      setPwDone(true);
      setPwCur("");
      setPwNew("");
      setPwConf("");
    } catch (e) {
      setPwErr(toDisplayMessage(e, "パスワードの変更に失敗しました"));
    } finally {
      setPwChanging(false);
    }
  };

  const saveStatusText = dirty ? "未保存の変更があります" : saved ? "保存済み" : "変更なし";

  // 都道府県が保存済みなら、backend が residence_area を都道府県から自動決定して
  // body 側の residence_area を無視する仕様に合わせ、チップは読み取り専用にする。
  const prefectureSaved = !!address?.prefecture;

  const displayName =
    [profile?.family_name, profile?.given_name].filter(Boolean).join(" ") ||
    sessionData?.user?.name ||
    profile?.email ||
    "";
  const avatarInitial = (profile?.family_name || sessionData?.user?.name || profile?.email || "?").slice(0, 1);

  const sessionExpired = !tokenLoading && !token;

  if (sessionExpired) {
    return (
      <div className="profile-page">
        <AppHeader />
        <main id="main">
          <div className="profile-wrap">
            <ErrorBanner>
              セッションが切れました。再ログインしてください。
              <Link href="/login" style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline" }}>
                ログインへ
              </Link>
            </ErrorBanner>
          </div>
        </main>
      </div>
    );
  }

  if (tokenLoading || (!profile && !loadError)) {
    return (
      <div className="profile-page">
        <AppHeader />
        <main id="main">
          <div className="profile-wrap" style={{ textAlign: "center", padding: "60px 20px", color: "var(--body-soft)" }}>
            読み込み中…
          </div>
        </main>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="profile-page">
        <AppHeader />
        <main id="main">
          <div className="profile-wrap">
            <ErrorBanner>
              {loadError ?? "プロフィールの取得に失敗しました"}
              <button
                type="button"
                onClick={() => void load()}
                style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline", background: "none", border: "none", color: "inherit", cursor: "pointer" }}
              >
                再読み込み
              </button>
            </ErrorBanner>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="profile-page">
      <AppHeader />

      <main id="main">
        <div className="profile-wrap">
          {saveError ? <ErrorBanner>{saveError}</ErrorBanner> : null}

          {/* アバター */}
          <div className="form-card">
            <div className="avatar-row">
              <div className="avatar-circle">{avatarInitial}</div>
              <div className="avatar-info">
                <strong>{displayName}</strong>
                <span>プロフィール画像</span>
              </div>
            </div>
          </div>

          {/* 基本情報 */}
          <div className="edit-section-title">
            {ICON_USER}
            基本情報
          </div>
          <div className="form-card">
            <div className="row-2">
              <div className={`field${seiErr ? " has-error" : ""}`}>
                <label htmlFor="inp-sei">
                  姓<span className="req">必須</span>
                </label>
                <input
                  type="text"
                  id="inp-sei"
                  value={sei}
                  onChange={(e) => {
                    setSei(e.target.value);
                    markDirty();
                  }}
                  placeholder="山田"
                />
                {seiErr ? <div className="field-error">{seiErr}</div> : null}
              </div>
              <div className={`field${meiErr ? " has-error" : ""}`}>
                <label htmlFor="inp-mei">
                  名<span className="req">必須</span>
                </label>
                <input
                  type="text"
                  id="inp-mei"
                  value={mei}
                  onChange={(e) => {
                    setMei(e.target.value);
                    markDirty();
                  }}
                  placeholder="花子"
                />
                {meiErr ? <div className="field-error">{meiErr}</div> : null}
              </div>
            </div>
            <div className="row-2">
              <div className="field">
                <label htmlFor="inp-sei-kana">
                  セイ<span className="opt">任意</span>
                </label>
                <input
                  type="text"
                  id="inp-sei-kana"
                  value={seiKana}
                  onChange={(e) => {
                    setSeiKana(e.target.value);
                    markDirty();
                  }}
                  placeholder="ヤマダ"
                />
              </div>
              <div className="field">
                <label htmlFor="inp-mei-kana">
                  メイ<span className="opt">任意</span>
                </label>
                <input
                  type="text"
                  id="inp-mei-kana"
                  value={meiKana}
                  onChange={(e) => {
                    setMeiKana(e.target.value);
                    markDirty();
                  }}
                  placeholder="ハナコ"
                />
              </div>
            </div>
            <div className="field">
              <label htmlFor="inp-phone">
                電話番号<span className="opt">任意</span>
              </label>
              <input
                type="tel"
                id="inp-phone"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value);
                  markDirty();
                }}
                placeholder="090-0000-0000"
                inputMode="tel"
              />
              <div className="field-hint">訪問日程調整時の連絡に使用します</div>
            </div>
            <div className="row-2">
              <div className="field">
                <label htmlFor="inp-birth-date">
                  生年月日<span className="opt">任意</span>
                </label>
                <input
                  type="date"
                  id="inp-birth-date"
                  value={birthDate}
                  max={new Date().toISOString().slice(0, 10)}
                  onChange={(e) => {
                    setBirthDate(e.target.value);
                    markDirty();
                  }}
                />
                <div className="field-hint">本人確認書類の提出に必要です</div>
              </div>
              <div className="field">
                <label htmlFor="inp-occupation">
                  職業<span className="opt">任意</span>
                </label>
                <select
                  id="inp-occupation"
                  value={occupation}
                  onChange={(e) => {
                    setOccupation(e.target.value);
                    markDirty();
                  }}
                >
                  <option value="">選択してください</option>
                  {OCCUPATIONS.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="field">
              <label htmlFor="inp-email">メールアドレス</label>
              <input
                type="email"
                id="inp-email"
                className="input-disabled"
                value={profile.email}
                disabled
                readOnly
              />
              <div className="field-hint">
                メールアドレスの変更はサポートまでお問い合わせください
              </div>
            </div>
          </div>

          {/* 住所・連絡先 */}
          <div className="edit-section-title">
            {ICON_PIN}
            住所・連絡先
          </div>
          <div className="form-card">
            {addressLoadError ? <div className="pw-change-error">{addressLoadError}</div> : null}
            <div className={`field${postalErr ? " has-error" : ""}`}>
              <label htmlFor="inp-postal">
                郵便番号<span className="req">必須</span>
              </label>
              <input
                type="text"
                id="inp-postal"
                value={postalCode}
                inputMode="numeric"
                placeholder="123-4567"
                onChange={(e) => {
                  setPostalCode(e.target.value);
                  markAddressDirty();
                }}
              />
              {postalErr ? <div className="field-error">{postalErr}</div> : null}
            </div>
            <div className={`field${prefErr ? " has-error" : ""}`}>
              <label htmlFor="inp-prefecture">
                都道府県<span className="req">必須</span>
              </label>
              <select
                id="inp-prefecture"
                value={prefecture}
                onChange={(e) => {
                  setPrefecture(e.target.value);
                  markAddressDirty();
                }}
              >
                <option value="">選択してください</option>
                {PREFECTURES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              {prefErr ? <div className="field-error">{prefErr}</div> : null}
            </div>
            <div className={`field${cityErr ? " has-error" : ""}`}>
              <label htmlFor="inp-city">
                市区町村<span className="req">必須</span>
              </label>
              <input
                type="text"
                id="inp-city"
                value={city}
                placeholder="渋谷区"
                onChange={(e) => {
                  setCity(e.target.value);
                  markAddressDirty();
                }}
              />
              {cityErr ? <div className="field-error">{cityErr}</div> : null}
            </div>
            <div className={`field${line1Err ? " has-error" : ""}`}>
              <label htmlFor="inp-address1">
                番地<span className="req">必須</span>
              </label>
              <input
                type="text"
                id="inp-address1"
                value={addressLine1}
                placeholder="1-2-3"
                onChange={(e) => {
                  setAddressLine1(e.target.value);
                  markAddressDirty();
                }}
              />
              {line1Err ? <div className="field-error">{line1Err}</div> : null}
            </div>
            <div className="field">
              <label htmlFor="inp-address2">
                建物名・部屋番号<span className="opt">任意</span>
              </label>
              <input
                type="text"
                id="inp-address2"
                value={addressLine2}
                placeholder="カタヅケマンション101"
                onChange={(e) => {
                  setAddressLine2(e.target.value);
                  markAddressDirty();
                }}
              />
              <div className="field-hint">
                保存すると下の「お住まいのエリア」も自動的に更新されます
              </div>
            </div>

            {addressError ? <div className="pw-change-error">{addressError}</div> : null}

            <button
              type="button"
              className="btn btn-ghost"
              style={{ width: "100%", marginTop: 2, color: addressSaved && !addressDirty ? "var(--green)" : undefined }}
              onClick={() => void onSaveAddress()}
              disabled={addressSaving || !address}
            >
              {addressSaving ? (
                <>
                  <span className="spinning">↻</span> 保存中…
                </>
              ) : addressSaved && !addressDirty ? (
                "住所を保存しました ✓"
              ) : (
                "住所を保存する"
              )}
            </button>
          </div>

          {/* エリア */}
          <div className="edit-section-title">
            {ICON_PIN}
            お住まいのエリア
          </div>
          <div className="form-card">
            {prefectureSaved ? (
              <>
                <div className="area-grid">
                  {RESIDENCE_AREAS.map((a) => (
                    <span
                      key={a.id}
                      className={`area-chip${area === a.id ? " selected" : ""}`}
                      aria-current={area === a.id ? "true" : undefined}
                      style={{ cursor: "default", opacity: area === a.id ? 1 : 0.45 }}
                    >
                      {a.label}
                    </span>
                  ))}
                </div>
                <div className="field-hint" style={{ marginTop: 10 }}>
                  住所（都道府県）から自動的に決定されています。変更する場合は上の「住所・連絡先」欄を更新してください。
                </div>
              </>
            ) : (
              <div className="area-grid">
                {RESIDENCE_AREAS.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    className={`area-chip${area === a.id ? " selected" : ""}`}
                    aria-pressed={area === a.id}
                    onClick={() => selectArea(a.id)}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 本人確認・振込口座・LINE連携への導線 */}
          <div className="edit-section-title">
            {ICON_SHIELD}
            会員情報の入力状況
          </div>
          <div className="form-card link-card-list">
            <Link href="/mypage/identity" className="link-card-row">
              <span className="link-card-ic">{ICON_SHIELD}</span>
              <span className="link-card-body">
                <strong>本人確認</strong>
                <span>古物営業法に基づく住所・氏名・年齢の確認</span>
              </span>
              <StatusBadge
                value={profile.identity_status === "approved" ? "approved" : profile.identity_status}
                label={IDENTITY_STATUS_LABEL[profile.identity_status]}
              />
            </Link>
            <Link href="/mypage/bank-account" className="link-card-row">
              <span className="link-card-ic">{ICON_BANK}</span>
              <span className="link-card-body">
                <strong>振込口座</strong>
                <span>買取代金の受取先口座（業者には開示されません）</span>
              </span>
              <StatusBadge
                value={profile.has_bank_account ? "approved" : "unverified"}
                label={profile.has_bank_account ? "登録済み" : "未登録"}
              />
            </Link>
            <Link href="/notifications" className="link-card-row">
              <span className="link-card-ic">{ICON_LINE}</span>
              <span className="link-card-body">
                <strong>LINE連携</strong>
                <span>入札・メッセージの通知をLINEでも受け取る</span>
              </span>
              <StatusBadge
                value={profile.line_linked ? "approved" : "unverified"}
                label={profile.line_linked ? "連携済み" : "未連携"}
              />
            </Link>
          </div>

          {/* パスワード変更 */}
          <div className="edit-section-title">
            {ICON_LOCK}
            パスワード変更
          </div>
          <div className="form-card">
            {profile.has_password ? (
              <>
                <div className="field">
                  <label htmlFor="inp-pw-cur">現在のパスワード</label>
                  <PasswordField
                    id="inp-pw-cur"
                    value={pwCur}
                    onChange={(v) => {
                      setPwCur(v);
                      setPwDone(false);
                    }}
                    placeholder="現在のパスワード"
                    autoComplete="current-password"
                  />
                </div>
                <div className="field">
                  <label htmlFor="inp-pw-new">
                    新しいパスワード<span className="opt">8文字以上</span>
                  </label>
                  <PasswordField
                    id="inp-pw-new"
                    value={pwNew}
                    onChange={(v) => {
                      setPwNew(v);
                      setPwDone(false);
                    }}
                    placeholder="新しいパスワード"
                    autoComplete="new-password"
                  />
                </div>
                <div className="field">
                  <label htmlFor="inp-pw-conf">新しいパスワード（確認）</label>
                  <PasswordField
                    id="inp-pw-conf"
                    value={pwConf}
                    onChange={(v) => {
                      setPwConf(v);
                      setPwDone(false);
                    }}
                    placeholder="もう一度入力"
                    autoComplete="new-password"
                  />
                </div>

                {pwErr ? <div className="pw-change-error">{pwErr}</div> : null}

                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ width: "100%", marginTop: 2, color: pwDone ? "var(--green)" : undefined }}
                  onClick={() => void onChangePw()}
                  disabled={pwChanging}
                >
                  {pwChanging ? (
                    <>
                      <span className="spinning">↻</span> 変更中…
                    </>
                  ) : pwDone ? (
                    "パスワードを変更しました ✓"
                  ) : (
                    "パスワードを変更する"
                  )}
                </button>
              </>
            ) : (
              <p style={{ fontSize: 13, color: "var(--body-soft)", lineHeight: 1.75, margin: 0 }}>
                LINEログイン専用アカウントのため、パスワード変更はありません。
              </p>
            )}
          </div>

          {/* 危険ゾーン */}
          <div className="danger-zone">
            <div className="danger-title">アカウントの削除</div>
            <div className="danger-desc">
              アカウントを削除すると個人情報は削除され、アカウントは利用できなくなります。成約済みのお取引の記録は業者側の取引記録として保持されます。この操作は取り消せません。
            </div>
            <Link href="/mypage/withdraw" className="danger-link">
              アカウントを削除する →
            </Link>
          </div>
        </div>
      </main>

      {/* 保存バー（固定） */}
      <div className="profile-save-bar">
        <div className="profile-save-bar-inner">
          <span className={`save-changed${dirty ? " dirty" : ""}`}>{saveStatusText}</span>
          <Link href="/mypage" className="btn btn-ghost">
            キャンセル
          </Link>
          <button type="button" className="btn btn-primary" onClick={() => void onSave()} disabled={saving}>
            {saving ? <span className="spinning">↻</span> : "変更を保存"}
          </button>
        </div>
      </div>

      {/* 保存トースト */}
      {showToast ? (
        <div className="profile-toast" role="status">
          {ICON_CHECK}
          プロフィールを保存しました
        </div>
      ) : null}
    </div>
  );
}
