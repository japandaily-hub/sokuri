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
import { useToken } from "@/components/kdz/Ui";
import {
  getMyProfile,
  updateMyProfile,
  changeMyPassword,
  toDisplayMessage,
  RESIDENCE_AREAS,
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

/** サーバー未到達・想定外エラー時のアラート帯（mypage/page.tsx と同じスタイル）。 */
function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      style={{
        marginBottom: 20,
        padding: "12px 16px",
        borderRadius: "var(--radius-s)",
        background: "#fff5f5",
        color: "#dc2626",
        fontSize: 13,
        border: "1px solid #fca5a5",
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
  const [seiErr, setSeiErr] = useState<string | null>(null);
  const [meiErr, setMeiErr] = useState<string | null>(null);

  // エリア
  const [area, setArea] = useState<string | null>(null);

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
      setArea(p.residence_area ?? null);
      setDirty(false);
      setSaved(false);
      setLoadError(null);
    } catch (e) {
      setLoadError(toDisplayMessage(e, "プロフィールの取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

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
        },
        token,
      );
      setProfile(updated);
      setSei(updated.family_name ?? "");
      setMei(updated.given_name ?? "");
      setSeiKana(updated.family_name_kana ?? "");
      setMeiKana(updated.given_name_kana ?? "");
      setPhone(updated.phone ?? "");
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
        <AppHeader unread={false} />
        <main id="main">
          <div className="profile-wrap">
            <ErrorBanner>
              セッションが切れました。再ログインしてください。
              <Link href="/login" style={{ marginLeft: 8, fontWeight: 700, textDecoration: "underline" }}>
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
        <AppHeader unread />
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
        <AppHeader unread />
        <main id="main">
          <div className="profile-wrap">
            <ErrorBanner>
              {loadError ?? "プロフィールの取得に失敗しました"}
              <button
                type="button"
                onClick={() => void load()}
                style={{ marginLeft: 8, fontWeight: 700, textDecoration: "underline", background: "none", border: "none", color: "inherit", cursor: "pointer" }}
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
      <AppHeader unread />

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

          {/* エリア */}
          <div className="edit-section-title">
            {ICON_PIN}
            お住まいのエリア
          </div>
          <div className="form-card">
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
