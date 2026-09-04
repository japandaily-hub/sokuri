"use client";

/**
 * 振込口座（/mypage/bank-account）。
 * カタヅケは買取代金の送金を行わない（当事者間精算）。ここに保存するのは、お振込みでの
 * 受け取りを希望する場合に業者へ伝えるための口座情報であり、業者へ自動開示はしない。
 *
 * デザインは既存の /mypage/profile（人の森整合テーマ）を踏襲する。form-card /
 * edit-section-title はページ間でクラスを共有しない既存の慣習に合わせ、
 * このページ専用スコープ（.bank-page）で再定義する。
 *
 * バックエンド: GET/PUT/DELETE /users/me/bank-account（katadzuke-api.ts）。
 * account_number はマスク済み（例 "***4567"）でのみ返る（生の口座番号は保存後に再取得できない）。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Field, PasswordField } from "@/components/kdz/auth";
import { useToken } from "@/components/kdz/Ui";
import {
  getMyBankAccount,
  updateMyBankAccount,
  deleteMyBankAccount,
  getMyProfile,
  toDisplayMessage,
  KdzApiError,
  type BankAccountOut,
  type BankAccountType,
  type UserProfile,
} from "@/lib/katadzuke-api";
import "./bank-account.css";

const ICON_BANK = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M3 10l9-6 9 6" />
    <path d="M4 10v9M9 10v9M15 10v9M20 10v9" />
    <path d="M2 21h20" />
  </svg>
);

/** 全角カタカナ + 全角スペースのみ許容（半角混在を防ぐ）。 */
const KANA_PATTERN = /^[ァ-ヶー　]+$/;

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

export default function BankAccountPage() {
  const { token, loading: tokenLoading } = useToken();

  const [account, setAccount] = useState<BankAccountOut | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [bankName, setBankName] = useState("");
  const [branchName, setBranchName] = useState("");
  const [accountType, setAccountType] = useState<BankAccountType>("普通");
  const [accountNumber, setAccountNumber] = useState("");
  const [accountHolderKana, setAccountHolderKana] = useState("");

  const [bankNameErr, setBankNameErr] = useState<string | null>(null);
  const [branchNameErr, setBranchNameErr] = useState<string | null>(null);
  const [accountNumberErr, setAccountNumberErr] = useState<string | null>(null);
  const [kanaErr, setKanaErr] = useState<string | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [currentPasswordErr, setCurrentPasswordErr] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // 削除確認（パスワード確認が必要なユーザーは window.confirm ではなくインラインの確認パネルで
  // 現在のパスワード入力を求める。LINE専用ユーザーは従来どおり window.confirm のみ）。
  const [deleteConfirming, setDeleteConfirming] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deletePasswordErr, setDeletePasswordErr] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const hasPassword = profile?.has_password ?? true;

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [a, p] = await Promise.all([getMyBankAccount(token), getMyProfile(token)]);
      setAccount(a);
      setProfile(p);
      setLoadError(null);
    } catch (e) {
      setLoadError(toDisplayMessage(e, "口座情報の取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  function startEdit() {
    setBankName(account?.bank_name ?? "");
    setBranchName(account?.branch_name ?? "");
    setAccountType(account?.account_type ?? "普通");
    setAccountNumber("");
    setAccountHolderKana(account?.account_holder_kana ?? "");
    setCurrentPassword("");
    setBankNameErr(null);
    setBranchNameErr(null);
    setAccountNumberErr(null);
    setKanaErr(null);
    setCurrentPasswordErr(null);
    setSaveError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setSaveError(null);
  }

  async function onSave() {
    let ok = true;
    if (!bankName.trim()) {
      setBankNameErr("銀行名を入力してください");
      ok = false;
    } else setBankNameErr(null);
    if (!branchName.trim()) {
      setBranchNameErr("支店名を入力してください");
      ok = false;
    } else setBranchNameErr(null);
    if (!/^\d{7}$/.test(accountNumber.trim())) {
      setAccountNumberErr("口座番号は7桁の数字で入力してください");
      ok = false;
    } else setAccountNumberErr(null);
    if (!KANA_PATTERN.test(accountHolderKana.trim())) {
      setKanaErr("口座名義は全角カタカナで入力してください");
      ok = false;
    } else setKanaErr(null);
    if (hasPassword && !currentPassword) {
      setCurrentPasswordErr("現在のパスワードを入力してください");
      ok = false;
    } else setCurrentPasswordErr(null);
    if (!ok || !token) return;

    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateMyBankAccount(
        {
          bank_name: bankName.trim(),
          branch_name: branchName.trim(),
          account_type: accountType,
          account_number: accountNumber.trim(),
          account_holder_kana: accountHolderKana.trim(),
          current_password: hasPassword ? currentPassword : null,
        },
        token,
      );
      setAccount(updated);
      setEditing(false);
      setToastMessage("口座情報を保存しました。登録メールアドレスに通知を送りました。");
      window.setTimeout(() => setToastMessage(null), 3200);
    } catch (e) {
      if (e instanceof KdzApiError && e.status === 400) {
        setCurrentPasswordErr(toDisplayMessage(e, "現在のパスワードが正しくありません。"));
      } else {
        setSaveError(toDisplayMessage(e, "保存に失敗しました。入力内容をご確認のうえ、もう一度お試しください。"));
      }
    } finally {
      setSaving(false);
    }
  }

  function startDeleteConfirm() {
    setDeletePassword("");
    setDeletePasswordErr(null);
    setDeleteError(null);
    setDeleteConfirming(true);
  }

  function cancelDeleteConfirm() {
    setDeleteConfirming(false);
    setDeletePasswordErr(null);
  }

  async function onDelete() {
    if (!token || deleting) return;
    if (hasPassword && !deletePassword) {
      setDeletePasswordErr("現在のパスワードを入力してください");
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    setDeletePasswordErr(null);
    try {
      await deleteMyBankAccount(hasPassword ? deletePassword : null, token);
      setDeleteConfirming(false);
      await load();
      setToastMessage("口座情報を削除しました。登録メールアドレスに通知を送りました。");
      window.setTimeout(() => setToastMessage(null), 3200);
    } catch (e) {
      if (e instanceof KdzApiError && e.status === 400) {
        setDeletePasswordErr(toDisplayMessage(e, "現在のパスワードが正しくありません。"));
      } else {
        setDeleteError(toDisplayMessage(e, "削除に失敗しました"));
      }
    } finally {
      setDeleting(false);
    }
  }

  const profileKanaName =
    [profile?.family_name_kana, profile?.given_name_kana].filter(Boolean).join("") || null;
  const kanaMismatch =
    !!profileKanaName &&
    accountHolderKana.trim() !== "" &&
    accountHolderKana.trim().replace(/　/g, "") !== profileKanaName.replace(/\s/g, "");

  const sessionExpired = !tokenLoading && !token;

  if (sessionExpired) {
    return (
      <div className="bank-page">
        <AppHeader />
        <main id="main">
          <div className="bank-wrap">
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

  if (tokenLoading || (!account && !loadError)) {
    return (
      <div className="bank-page">
        <AppHeader />
        <main id="main">
          <div className="bank-wrap" style={{ textAlign: "center", padding: "60px 20px", color: "var(--body-soft)" }}>
            読み込み中…
          </div>
        </main>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="bank-page">
        <AppHeader />
        <main id="main">
          <div className="bank-wrap">
            <ErrorBanner>
              {loadError ?? "口座情報の取得に失敗しました"}
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
    <div className="bank-page">
      <AppHeader />
      <main id="main">
        <div className="bank-wrap">
          {loadError ? <ErrorBanner>{loadError}</ErrorBanner> : null}

          <div className="edit-section-title">
            {ICON_BANK}
            振込口座
          </div>

          <div className="id-notice-box">
            <ul>
              <li>買取代金の受け取り方法（現金・お振込み）は、成約後に業者とチャットで調整します。お振込みを希望する場合に業者へお伝えする口座情報を、あらかじめここに保存できます。</li>
              <li>保存した口座情報は暗号化して保管し、業者へ自動で開示することはありません。</li>
              <li>ゆうちょ銀行は振込用の店名・口座番号（7桁）を入力してください。</li>
            </ul>
          </div>

          {!editing && account.has_bank_account ? (
            <div className="form-card">
              <dl className="bank-summary">
                <div>
                  <dt>銀行名</dt>
                  <dd>{account.bank_name}</dd>
                </div>
                <div>
                  <dt>支店名</dt>
                  <dd>{account.branch_name}</dd>
                </div>
                <div>
                  <dt>預金種別</dt>
                  <dd>{account.account_type}</dd>
                </div>
                <div>
                  <dt>口座番号</dt>
                  <dd>{account.account_number_masked}</dd>
                </div>
                <div>
                  <dt>口座名義</dt>
                  <dd>{account.account_holder_kana}</dd>
                </div>
                {account.updated_at ? (
                  <div>
                    <dt>更新日</dt>
                    <dd>{new Date(account.updated_at).toLocaleDateString("ja-JP")}</dd>
                  </div>
                ) : null}
              </dl>
              {!deleteConfirming ? (
                <div className="bank-actions">
                  <button type="button" className="btn btn-ghost" onClick={startEdit}>
                    変更する
                  </button>
                  <button type="button" className="btn-bank-delete" onClick={startDeleteConfirm}>
                    削除する
                  </button>
                </div>
              ) : (
                <div className="bank-delete-confirm">
                  {deleteError ? <div className="pw-change-error">{deleteError}</div> : null}
                  <p style={{ fontSize: 13, color: "var(--body-soft)", lineHeight: 1.75, margin: "0 0 12px" }}>
                    登録済みの振込口座を削除します。よろしいですか？
                  </p>
                  {hasPassword ? (
                    <Field label="現在のパスワード" htmlFor="inp-delete-pw" error={deletePasswordErr}>
                      <PasswordField
                        id="inp-delete-pw"
                        value={deletePassword}
                        onChange={(v) => {
                          setDeletePassword(v);
                          if (deletePasswordErr) setDeletePasswordErr(null);
                        }}
                        placeholder="パスワードを入力"
                      />
                    </Field>
                  ) : (
                    <p style={{ fontSize: 13, color: "var(--body-soft)", margin: "0 0 12px" }}>
                      LINEログインのため、パスワード確認は不要です。
                    </p>
                  )}
                  <div className="bank-actions">
                    <button type="button" className="btn btn-ghost" onClick={cancelDeleteConfirm} disabled={deleting}>
                      キャンセル
                    </button>
                    <button type="button" className="btn-bank-delete" onClick={() => void onDelete()} disabled={deleting}>
                      {deleting ? "削除中…" : "削除する"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : null}

          {!editing && !account.has_bank_account ? (
            <div className="form-card">
              <p style={{ fontSize: 13, color: "var(--body-soft)", lineHeight: 1.75, margin: 0 }}>
                まだ振込口座が登録されていません。お振込みでの受け取りを希望する場合に備えて、口座情報を保存しておくことができます（登録は任意です）。
              </p>
              <button type="button" className="btn btn-primary" style={{ marginTop: 14 }} onClick={startEdit}>
                口座を登録する
              </button>
            </div>
          ) : null}

          {editing ? (
            <div className="form-card">
              {saveError ? <div className="pw-change-error">{saveError}</div> : null}

              <div className={`field${bankNameErr ? " has-error" : ""}`}>
                <label htmlFor="inp-bank-name">
                  銀行名<span className="req">必須</span>
                </label>
                <input
                  type="text"
                  id="inp-bank-name"
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  placeholder="カタヅケ銀行"
                />
                {bankNameErr ? <div className="field-error">{bankNameErr}</div> : null}
              </div>
              <div className={`field${branchNameErr ? " has-error" : ""}`}>
                <label htmlFor="inp-branch-name">
                  支店名<span className="req">必須</span>
                </label>
                <input
                  type="text"
                  id="inp-branch-name"
                  value={branchName}
                  onChange={(e) => setBranchName(e.target.value)}
                  placeholder="本店"
                />
                {branchNameErr ? <div className="field-error">{branchNameErr}</div> : null}
              </div>
              <div className="field">
                <label>
                  預金種別<span className="req">必須</span>
                </label>
                <div className="bank-radio-row">
                  {(["普通", "当座"] as BankAccountType[]).map((t) => (
                    <label key={t} className="bank-radio">
                      <input
                        type="radio"
                        name="account_type"
                        value={t}
                        checked={accountType === t}
                        onChange={() => setAccountType(t)}
                      />
                      {t}
                    </label>
                  ))}
                </div>
              </div>
              <div className={`field${accountNumberErr ? " has-error" : ""}`}>
                <label htmlFor="inp-account-number">
                  口座番号<span className="req">必須</span>
                </label>
                <input
                  type="text"
                  id="inp-account-number"
                  value={accountNumber}
                  inputMode="numeric"
                  maxLength={7}
                  placeholder="1234567"
                  onChange={(e) => setAccountNumber(e.target.value.replace(/[^0-9]/g, ""))}
                />
                {accountNumberErr ? (
                  <div className="field-error">{accountNumberErr}</div>
                ) : (
                  <div className="field-hint">半角数字7桁で入力してください</div>
                )}
              </div>
              <div className={`field${kanaErr ? " has-error" : ""}`}>
                <label htmlFor="inp-kana">
                  口座名義（カナ）<span className="req">必須</span>
                </label>
                <input
                  type="text"
                  id="inp-kana"
                  value={accountHolderKana}
                  onChange={(e) => setAccountHolderKana(e.target.value)}
                  placeholder="カタヅケ タロウ"
                />
                {kanaErr ? (
                  <div className="field-error">{kanaErr}</div>
                ) : kanaMismatch ? (
                  <div className="field-hint bank-kana-warn">
                    プロフィールに登録したお名前（カナ）と異なります。ご本人名義の口座かご確認ください。
                  </div>
                ) : (
                  <div className="field-hint">全角カタカナで入力してください</div>
                )}
              </div>

              {hasPassword ? (
                <Field label="現在のパスワード" htmlFor="inp-current-pw" error={currentPasswordErr}>
                  <PasswordField
                    id="inp-current-pw"
                    value={currentPassword}
                    onChange={(v) => {
                      setCurrentPassword(v);
                      if (currentPasswordErr) setCurrentPasswordErr(null);
                    }}
                    placeholder="パスワードを入力"
                  />
                </Field>
              ) : (
                <p style={{ fontSize: 13, color: "var(--body-soft)", margin: "0 0 16px" }}>
                  LINEログインのため、パスワード確認は不要です。
                </p>
              )}

              <div className="bank-actions">
                <button type="button" className="btn btn-ghost" onClick={cancelEdit} disabled={saving}>
                  キャンセル
                </button>
                <button type="button" className="btn btn-primary" onClick={() => void onSave()} disabled={saving}>
                  {saving ? (
                    <>
                      <span className="spinning">↻</span> 保存中…
                    </>
                  ) : (
                    "保存する"
                  )}
                </button>
              </div>
            </div>
          ) : null}

          <div style={{ marginTop: 4 }}>
            <Link href="/mypage/profile" className="id-back-link">
              ← マイページ・設定にもどる
            </Link>
          </div>
        </div>
      </main>

      {toastMessage ? (
        <div className="bank-toast" role="status">
          {toastMessage}
        </div>
      ) : null}
    </div>
  );
}
