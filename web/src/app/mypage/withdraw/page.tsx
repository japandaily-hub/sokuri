"use client";

/**
 * 退会・アカウント削除（/mypage/withdraw）— 実配線済み。
 * デザイン正典: docs/design_handoff_katazuke/退会・アカウント削除.html をピクセル忠実に再現。
 * このルートは SiteChrome の BARE_PREFIXES（/mypage）対象で共通クロムが付かないため、
 * ページ自身が AppHeader（アプリ共通ヘッダー）と本文を描く。
 *
 * バックエンド: DELETE /users/me（katadzuke-api.ts の deleteMyAccount）。
 * 進行中のお取引がある場合は 409 でブロックされる（自動キャンセルはしない）。
 * has_password === false（LINEログイン専用）のユーザーはパスワード確認欄を表示せず、
 * 3チェックのみで削除ボタンを活性化する。
 *
 * 削除成功後の挙動: signOut({ redirect: false }) でセッションを即時失効させたうえで
 * （ページ遷移はしない）ローカル state のみで完了パネルへ切り替える。/mypage 配下は
 * middleware.ts が認証必須のため、ここで signOut 後に router 遷移すると保護に阻まれて
 * 完了パネルが見せられなくなる。「トップページへ」の Link 遷移だけは "/" が非保護のため
 * 問題なく機能する。
 */

import "./withdraw.css";

import { useCallback, useEffect, useState } from "react";
import { signOut } from "next-auth/react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Field, PasswordField } from "@/components/kdz/auth";
import { useToken } from "@/components/kdz/Ui";
import {
  deleteMyAccount,
  getMyProfile,
  listMyCases,
  listTransactions,
  toDisplayMessage,
  KdzApiError,
  type UserProfile,
} from "@/lib/katadzuke-api";

const CHECK_ITEMS = [
  "上記のデータの取り扱い（個人情報の削除・成約済み取引記録の保持）を理解しています",
  "進行中のお取引がある場合は退会できません（お取引の完了またはキャンセル後に退会できます）",
  "この操作は元に戻せないことを理解しています",
];

// スプライト未収録のアイコンはインラインで描画（trash / list / user）。
function DeleteItemIcon({ icon }: { icon: "user" | "list" | "chat" }) {
  if (icon === "chat") {
    // i-chat はスプライトに存在するが、退会画面では赤線・サイズ統一のため明示 SVG を使う
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" />
      </svg>
    );
  }
  if (icon === "list") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    );
  }
  // user
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

export default function WithdrawPage() {
  const { token, loading: tokenLoading } = useToken();

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [caseCount, setCaseCount] = useState<number | null>(null);
  const [completedCount, setCompletedCount] = useState<number | null>(null);

  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [password, setPassword] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const p = await getMyProfile(token);
      setProfile(p);
      setProfileError(null);
    } catch (e) {
      setProfileError(toDisplayMessage(e, "情報の取得に失敗しました"));
    }
    // 件数の取得は失敗しても致命的ではないため、失敗時は件数なしの汎用文言にフォールバックする。
    try {
      const cases = await listMyCases(token);
      setCaseCount(cases.length);
    } catch {
      setCaseCount(null);
    }
    try {
      const txns = await listTransactions(token);
      setCompletedCount(txns.filter((t) => t.status === "completed").length);
    } catch {
      setCompletedCount(null);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const allChecked = checks.every(Boolean);
  const hasPassword = profile?.has_password ?? true;

  function toggleCheck(index: number) {
    setChecks((prev) => prev.map((v, i) => (i === index ? !v : v)));
  }

  async function onDelete() {
    if (hasPassword && !password) {
      setPwErr("パスワードを入力してください");
      return;
    }
    if (!token) return;
    setPwErr(null);
    setDeleteError(null);
    setBusy(true);
    try {
      await deleteMyAccount({ password: hasPassword ? password : undefined, confirm: true }, token);
      // 旧セッションを即時失効させる（ページ遷移はしない。完了パネルはローカル state で表示する）。
      await signOut({ redirect: false });
      setDone(true);
    } catch (e) {
      if (e instanceof KdzApiError && e.status === 400) {
        setPwErr(toDisplayMessage(e, "パスワードが正しくありません。"));
      } else if (e instanceof KdzApiError && e.status === 409) {
        setDeleteError(toDisplayMessage(e, "進行中のお取引があるため退会できません。"));
      } else {
        setDeleteError(toDisplayMessage(e, "退会処理に失敗しました。時間をおいて再度お試しください。"));
      }
    } finally {
      setBusy(false);
    }
  }

  const countsDesc =
    caseCount != null && completedCount != null
      ? `${caseCount}件の出品・${completedCount}件の成約記録`
      : "これまでの出品・取引の記録";

  // 実挙動（backend DELETE /users/me）に忠実な説明にする: アカウントの個人情報は削除、
  // 未成約の出品はキャンセル+住所削除。成約済みのお取引に関する記録（住所・メッセージ
  // 内容を含む）は業者側の取引記録として保持される（securityレビュー指摘対応:
  // 「匿名化」「全データ完全削除」といった実態より強い表現は使わない）。
  const deleteItems: { icon: "user" | "list" | "chat"; title: string; desc: string }[] = [
    {
      icon: "user",
      title: "アカウント情報 — 削除されます",
      desc: "名前・メールアドレス・電話番号・LINE連携",
    },
    {
      icon: "list",
      title: "出品データ — キャンセル・住所情報削除",
      desc: `${countsDesc}（未成約の出品は自動キャンセルされます）`,
    },
    {
      icon: "chat",
      title: "取引・メッセージ履歴 — 業者側の記録として保持",
      desc: "成約済みのお取引の記録（住所・メッセージ内容を含む）は、取引相手の業者の取引記録として保持されます",
    },
  ];

  if (done) {
    return (
      <div className="withdraw-page">
        <AppHeader unread={false} />
        <main id="main">
          <div className="del-wrap">
            <div className="panel active" id="panel-done">
              <div className="done-screen">
                <div className="done-mark">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M4 12.5l5.5 5.5L20 7" />
                  </svg>
                </div>
                <h1 className="done-title">退会手続きが完了しました</h1>
                <p className="done-sub">
                  ご利用いただきありがとうございました。
                  <br />
                  またのご利用をお待ちしております。
                </p>
                <Link href="/" className="btn btn-primary btn-lg">
                  トップページへ
                </Link>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  const sessionExpired = !tokenLoading && !token;

  if (sessionExpired) {
    return (
      <div className="withdraw-page">
        <AppHeader unread={false} />
        <main id="main">
          <div className="del-wrap">
            <div
              role="alert"
              style={{
                padding: "12px 16px",
                borderRadius: "var(--radius-s)",
                background: "#fff5f5",
                color: "#dc2626",
                fontSize: 13,
                border: "1px solid #fca5a5",
              }}
            >
              セッションが切れました。再ログインしてください。
              <Link href="/login" style={{ marginLeft: 8, fontWeight: 700, textDecoration: "underline" }}>
                ログインへ
              </Link>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (tokenLoading || (!profile && !profileError)) {
    return (
      <div className="withdraw-page">
        <AppHeader unread={false} />
        <main id="main">
          <div className="del-wrap" style={{ textAlign: "center", padding: "60px 20px", color: "var(--body-soft)" }}>
            読み込み中…
          </div>
        </main>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="withdraw-page">
        <AppHeader unread={false} />
        <main id="main">
          <div className="del-wrap">
            <div
              role="alert"
              style={{
                padding: "12px 16px",
                borderRadius: "var(--radius-s)",
                background: "#fff5f5",
                color: "#dc2626",
                fontSize: 13,
                border: "1px solid #fca5a5",
              }}
            >
              {profileError ?? "情報の取得に失敗しました"}
              <button
                type="button"
                onClick={() => void load()}
                style={{ marginLeft: 8, fontWeight: 700, textDecoration: "underline", background: "none", border: "none", color: "inherit", cursor: "pointer" }}
              >
                再読み込み
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="withdraw-page">
      <AppHeader unread={false} />

      <main id="main">
        <div className="del-wrap">
          {/* 確認画面 */}
          <div className="panel active" id="panel-confirm">
            <div className="warn-banner">
              <div className="warn-ic">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 3.5L21 19H3L12 3.5z" />
                  <path d="M12 10v4M12 17h.01" />
                </svg>
              </div>
              <div className="warn-body">
                <strong>この操作は取り消せません</strong>
                <span>
                  アカウントを削除すると個人情報は削除され、アカウントは利用できなくなります。データの取り扱いは以下のとおりです。
                </span>
              </div>
            </div>

            {deleteError ? (
              <div
                role="alert"
                style={{
                  marginBottom: 14,
                  padding: "12px 16px",
                  borderRadius: "var(--radius-s)",
                  background: "#fff5f5",
                  color: "#dc2626",
                  fontSize: 13,
                  border: "1px solid #fca5a5",
                }}
              >
                {deleteError}
                <Link href="/mypage" style={{ marginLeft: 8, fontWeight: 700, textDecoration: "underline" }}>
                  マイページへ戻る
                </Link>
              </div>
            ) : null}

            <div className="form-card">
              <div className="form-card-title">退会時のデータの取り扱い</div>
              <div className="del-list">
                {deleteItems.map((item) => (
                  <div className="del-item" key={item.title}>
                    <div className="del-item-ic">
                      <DeleteItemIcon icon={item.icon} />
                    </div>
                    <div className="del-item-body">
                      <strong>{item.title}</strong>
                      <span>{item.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 確認チェック */}
            <div className="form-card">
              <div className="form-card-title">削除前の確認</div>
              <div className="check-list">
                {CHECK_ITEMS.map((text, i) => (
                  <div className="check-row" key={i}>
                    <input
                      type="checkbox"
                      id={`chk${i + 1}`}
                      checked={checks[i]}
                      onChange={() => toggleCheck(i)}
                    />
                    <label htmlFor={`chk${i + 1}`}>{text}</label>
                  </div>
                ))}
              </div>
            </div>

            {/* パスワード確認（LINE専用アカウントは非表示） */}
            {hasPassword ? (
              <div className="form-card">
                <div className="form-card-title">パスワードを入力して確認</div>
                <Field label="現在のパスワード" htmlFor="inp-pw" error={pwErr}>
                  <PasswordField
                    id="inp-pw"
                    value={password}
                    onChange={(v) => {
                      setPassword(v);
                      if (pwErr) setPwErr(null);
                    }}
                    placeholder="パスワードを入力"
                  />
                </Field>
              </div>
            ) : null}

            <button
              type="button"
              className="btn-delete"
              id="btn-delete"
              disabled={!allChecked || busy}
              onClick={() => void onDelete()}
            >
              {busy ? (
                <>
                  <span className="spinning">↻</span> 削除中…
                </>
              ) : (
                <>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
                    <path d="M10 11v6M14 11v6" />
                    <path d="M9 6V4h6v2" />
                  </svg>
                  アカウントを完全に削除する
                </>
              )}
            </button>
            <div className="del-cancel">
              <Link href="/mypage/profile">キャンセルして戻る</Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
