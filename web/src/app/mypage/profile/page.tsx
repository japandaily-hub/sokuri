"use client";

/** プロフィール編集（マイページ）。
 *  変更検知 → 固定保存バー「未保存の変更があります」+ 保存後トースト、
 *  パスワード変更のインラインエラー、エリア選択チップ、通知トグルを React 化。
 *  バックエンド未配線: 保存・パスワード変更・画像変更は UI 挙動のみ（デモ）。 */

import { useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
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
const ICON_BELL = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
  </svg>
);
const ICON_LOCK = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 018 0v4" />
  </svg>
);
const ICON_EDIT_BADGE = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);
const ICON_CHECK = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
);
const ICON_EYE = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M1 12S5 5 12 5s11 7 11 7-4 7-11 7S1 12 1 12z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

/* お住まいのエリア選択肢（デモ／モジュール定数） */
const AREAS = [
  { id: "tokyo", label: "東京都" },
  { id: "kanagawa", label: "神奈川県" },
  { id: "saitama", label: "埼玉県" },
  { id: "chiba", label: "千葉県" },
  { id: "osaka", label: "大阪府" },
  { id: "aichi", label: "愛知県" },
  { id: "fukuoka", label: "福岡県" },
  { id: "other", label: "その他" },
] as const;

/* 通知設定の初期値（デモ） */
const NOTIFY_DEFS = [
  { id: "bid", title: "入札が届いたとき", desc: "LINE通知", on: true },
  { id: "message", title: "メッセージが届いたとき", desc: "メール通知", on: true },
  { id: "news", title: "お知らせ・キャンペーン", desc: "メール通知", on: false },
] as const;

/** パスワード表示トグル付き入力（このページ固有・共通 .pw-wrap を使用）。 */
function PwInput({
  id,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="pw-wrap">
      <input
        type={show ? "text" : "password"}
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
      />
      <button
        type="button"
        className="pw-toggle"
        aria-label="パスワードを表示/非表示"
        onClick={() => setShow((s) => !s)}
      >
        {ICON_EYE}
      </button>
    </div>
  );
}

export default function ProfileEditPage() {
  // 基本情報
  const [sei, setSei] = useState("山田");
  const [mei, setMei] = useState("花子");
  const [seiKana, setSeiKana] = useState("ヤマダ");
  const [meiKana, setMeiKana] = useState("ハナコ");
  const [phone, setPhone] = useState("090-1234-5678");
  const [seiErr, setSeiErr] = useState<string | null>(null);
  const [meiErr, setMeiErr] = useState<string | null>(null);

  // エリア
  const [area, setArea] = useState<string>("tokyo");

  // 通知設定
  const [notify, setNotify] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(NOTIFY_DEFS.map((n) => [n.id, n.on])),
  );

  // 変更検知・保存状態
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showToast, setShowToast] = useState(false);

  // パスワード変更
  const [pwCur, setPwCur] = useState("");
  const [pwNew, setPwNew] = useState("");
  const [pwConf, setPwConf] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [pwChanging, setPwChanging] = useState(false);
  const [pwDone, setPwDone] = useState(false);

  const markDirty = () => {
    setDirty(true);
    setSaved(false);
  };

  const selectArea = (id: string) => {
    setArea(id);
    markDirty();
  };

  const toggleNotify = (id: string) => {
    setNotify((prev) => ({ ...prev, [id]: !prev[id] }));
    markDirty();
  };

  // 保存（デモ：実処理なし、UI 挙動のみ）
  const onSave = () => {
    let ok = true;
    if (!sei.trim()) {
      setSeiErr("姓を入力してください");
      ok = false;
    } else setSeiErr(null);
    if (!mei.trim()) {
      setMeiErr("名を入力してください");
      ok = false;
    } else setMeiErr(null);
    if (!ok) return;

    setSaving(true);
    window.setTimeout(() => {
      setSaving(false);
      setDirty(false);
      setSaved(true);
      setShowToast(true);
      window.setTimeout(() => setShowToast(false), 2500);
    }, 800);
  };

  // パスワード変更（デモ：インラインバリデーションのみ）
  const onChangePw = () => {
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
    setPwErr(null);
    setPwChanging(true);
    window.setTimeout(() => {
      setPwChanging(false);
      setPwDone(true);
      setPwCur("");
      setPwNew("");
      setPwConf("");
    }, 800);
  };

  const saveStatusText = dirty ? "未保存の変更があります" : saved ? "保存済み" : "変更なし";

  return (
    <div className="profile-page">
      <AppHeader unread />

      <main id="main">
        <div className="profile-wrap">
          {/* アバター */}
          <div className="form-card">
            <div className="avatar-row">
              <div className="avatar-circle">
                山
                <div className="avatar-edit-badge">{ICON_EDIT_BADGE}</div>
              </div>
              <div className="avatar-info">
                <strong>山田 花子</strong>
                <span>プロフィール画像</span>
                <br />
                <button type="button" className="btn-avatar" onClick={markDirty}>
                  画像を変更
                </button>
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
                value="hanako@example.com"
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
              {AREAS.map((a) => (
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

          {/* 通知設定 */}
          <div className="edit-section-title">
            {ICON_BELL}
            通知設定
          </div>
          <div className="form-card">
            <div className="notify-list">
              {NOTIFY_DEFS.map((n) => {
                const on = notify[n.id];
                return (
                  <div key={n.id} className="notify-row">
                    <div>
                      <div className="notify-title">{n.title}</div>
                      <div className="notify-desc">{n.desc}</div>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={on}
                      aria-label={n.title}
                      className={`notify-toggle${on ? " on" : ""}`}
                      onClick={() => toggleNotify(n.id)}
                    >
                      <span className="track" />
                      <span className="knob" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* パスワード変更 */}
          <div className="edit-section-title">
            {ICON_LOCK}
            パスワード変更
          </div>
          <div className="form-card">
            <div className="field">
              <label htmlFor="inp-pw-cur">現在のパスワード</label>
              <PwInput
                id="inp-pw-cur"
                value={pwCur}
                onChange={(v) => {
                  setPwCur(v);
                  setPwDone(false);
                }}
                placeholder="現在のパスワード"
              />
            </div>
            <div className="field">
              <label htmlFor="inp-pw-new">
                新しいパスワード<span className="opt">8文字以上</span>
              </label>
              <PwInput
                id="inp-pw-new"
                value={pwNew}
                onChange={(v) => {
                  setPwNew(v);
                  setPwDone(false);
                }}
                placeholder="新しいパスワード"
              />
            </div>
            <div className="field">
              <label htmlFor="inp-pw-conf">新しいパスワード（確認）</label>
              <PwInput
                id="inp-pw-conf"
                value={pwConf}
                onChange={(v) => {
                  setPwConf(v);
                  setPwDone(false);
                }}
                placeholder="もう一度入力"
              />
            </div>

            {pwErr ? <div className="pw-change-error">{pwErr}</div> : null}

            <button
              type="button"
              className="btn btn-ghost"
              style={{ width: "100%", marginTop: 2, color: pwDone ? "var(--green)" : undefined }}
              onClick={onChangePw}
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
          </div>

          {/* 危険ゾーン */}
          <div className="danger-zone">
            <div className="danger-title">アカウントの削除</div>
            <div className="danger-desc">
              アカウントを削除すると、すべての出品データ・メッセージ・取引履歴が完全に消去されます。この操作は取り消せません。
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
          <button type="button" className="btn btn-primary" onClick={onSave} disabled={saving}>
            {saving ? <span className="spinning">↻</span> : "変更を保存"}
          </button>
        </div>
      </div>

      {/* 保存トースト */}
      {showToast ? (
        <div className="profile-toast" role="status">
          {ICON_CHECK}
          プロフィールを保存しました（デモ）
        </div>
      ) : null}
    </div>
  );
}
