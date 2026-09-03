"use client";

/**
 * 通知・お知らせ一覧。
 * デザイン: docs/design_handoff_katazuke/通知・お知らせ一覧.html を React 化。
 * 通知専用APIが無いため、案件/取引の実データからフロント側でサマリを導出する
 * 「案B」構成に置換した（2026-07-03）。架空 NOTIFICATIONS 定数・フィルタタブは廃止。
 *
 * サマリ3行:
 *  - 入札が届いている案件 N件（listMyCases: bid_count>0 && status!==closed/cancelled → /cases）
 *  - 進行中の取引 N件（listTransactions: pending|visiting → /cases/{case_id}）
 *  - 評価待ちの取引 N件（listTransactions: completed → /review?transaction_id={id}）
 *
 * LINE通知連携（2026-08-31 実配線）:
 *  - line_linked/has_password は GET /users/me/profile のレスポンスに含まれる。
 *  - has_password===true: 「LINEで通知を受け取る」「連携を解除」いずれもパスワード確認モーダル
 *    → POST /users/me/reauth-token で短命トークンを発行 →
 *    連携: reauth_tokenを付けて /api/line/link/start（Route Handler）へ遷移。
 *    解除: DELETE /users/me/line-link に current_password を添えて直接呼ぶ。
 *  - has_password===false（LINE専用アカウント）: モーダルを挟まず直接 /api/line/link/start へ
 *    遷移。「連携を解除」は解除の術がないためdisabled + 案内表示。
 *  - /api/line/link/callback からの遷移で
 *    ?linked=1 / ?error=already_linked|reauth_required|line_unavailable|link_failed
 *    が付く。読み取り後は router.replace でURLからクエリを消す。
 *    line_unavailable は環境変数の設定漏れ等（フロントの APP_BASE_URL/LINE_CLIENT_ID、
 *    バックエンドの LINE_CLIENT_ID）による「未構成」で、再試行しても回復しないため
 *    link_failed（一時障害）とは別文言にする（2026-09-02）。
 */

import { useCallback, useEffect, useRef, useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Field, PasswordField } from "@/components/kdz/auth";
import { useToken } from "@/components/kdz/Ui";
import {
  listMyCases,
  listTransactions,
  getMyProfile,
  requestLineReauthToken,
  unlinkLine,
  toDisplayMessage,
  KdzApiError,
  type CaseOut,
  type TransactionListItem,
  type UserProfile,
} from "@/lib/katadzuke-api";
import "./notifications.css";

/* ── アイコン（デザインHTMLの symbol を inline 化） ── */
type NotifIconName = "bid" | "chat" | "star" | "bell";

function NotifIcon({ name }: { name: NotifIconName }) {
  switch (name) {
    case "bid":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2l2 7h7l-5.5 4 2 7L12 17l-5.5 3 2-7L3 9h7z" />
        </svg>
      );
    case "chat":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" />
        </svg>
      );
    case "star":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
      );
    case "bell":
    default:
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
        </svg>
      );
  }
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

type SummaryRow = {
  key: string;
  icon: NotifIconName;
  iconTone: "blue" | "green" | "warn";
  title: string;
  text: string;
  badgeLabel: string;
  href: string;
};

/** LINE連携パスワード確認モーダルの種別。 */
type LineModalKind = "link" | "unlink";

/** クエリパラメータ（/api/line/link/callback からの遷移）に対応するバナー。 */
type LineNotice = { tone: "success" | "error"; text: string } | null;

function NotificationsContent() {
  const { token, loading } = useToken();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [transactions, setTransactions] = useState<TransactionListItem[] | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setCases(await listMyCases(token));
    } catch (e) {
      setError(toDisplayMessage(e, "案件の取得に失敗しました"));
    }
    try {
      setTransactions(await listTransactions(token));
    } catch (e) {
      setError((prev) => prev ?? toDisplayMessage(e, "取引の取得に失敗しました"));
    }
    try {
      setProfile(await getMyProfile(token));
    } catch (e) {
      setError((prev) => prev ?? toDisplayMessage(e, "プロフィールの取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /* ── /api/line/link/callback からの遷移パラメータ検知 ── */
  const [lineNotice, setLineNotice] = useState<LineNotice>(null);
  useEffect(() => {
    const linked = searchParams.get("linked");
    const err = searchParams.get("error");
    if (linked === "1") {
      setLineNotice({ tone: "success", text: "LINE連携が完了しました。今後は入札・メッセージの通知がLINEにも届きます。" });
    } else if (err === "already_linked") {
      setLineNotice({ tone: "error", text: "このLINEアカウントは既に別のアカウントと連携されています。" });
    } else if (err === "reauth_required") {
      setLineNotice({ tone: "error", text: "パスワード確認の有効期限が切れました。もう一度お試しください。" });
    } else if (err === "line_unavailable") {
      setLineNotice({
        tone: "error",
        text: "LINE連携は現在ご利用いただけません（設定準備中）。ご不便をおかけしますが、しばらくお待ちください。",
      });
    } else if (err === "link_failed") {
      setLineNotice({ tone: "error", text: "LINE連携に失敗しました。時間をおいて再度お試しください。" });
    }
    if (linked || err) {
      router.replace("/notifications", { scroll: false });
    }
    // 初回マウント時のみ（router/searchParamsの参照変化で再実行しない）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── LINE連携: パスワード確認モーダル ── */
  const [modal, setModal] = useState<LineModalKind | null>(null);
  const [pwCur, setPwCur] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [lineBusy, setLineBusy] = useState(false);
  const modalTriggerRef = useRef<HTMLButtonElement | null>(null);
  // 401（トークン自体が無効=セッション切れ）を検知した場合に true にする。
  // パスワード不一致（400）とは区別し、既存のセッション切れバナー（下記 sessionExpired）に合流させる。
  const [reauthSessionExpired, setReauthSessionExpired] = useState(false);

  function closeModal() {
    setModal(null);
    setPwCur("");
    setPwErr(null);
    modalTriggerRef.current?.focus();
  }

  useEffect(() => {
    if (!modal) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") closeModal();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modal]);

  function openModal(kind: LineModalKind, e: React.MouseEvent<HTMLButtonElement>) {
    setLineNotice(null);
    modalTriggerRef.current = e.currentTarget;
    setModal(kind);
  }

  function onClickLineSetting(e: React.MouseEvent<HTMLButtonElement>) {
    if (!profile) return;
    if (profile.has_password) {
      openModal("link", e);
    } else {
      // has_password===false（LINE専用アカウント）はパスワードを持たないため、
      // 確認モーダルを挟まず直接LINE連携フローへ。
      window.location.href = "/api/line/link/start";
    }
  }

  async function onConfirmModal(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !modal) return;
    if (!pwCur) {
      setPwErr("パスワードを入力してください");
      return;
    }
    setPwErr(null);
    setLineBusy(true);
    try {
      if (modal === "link") {
        const { reauth_token } = await requestLineReauthToken(pwCur, token);
        window.location.href = `/api/line/link/start?reauth_token=${encodeURIComponent(reauth_token)}`;
        return;
      }
      await unlinkLine(pwCur, token);
      setModal(null);
      setPwCur("");
      setLineNotice({ tone: "success", text: "LINE連携を解除しました。" });
      await reload();
    } catch (err) {
      // 400: パスワード不一致（change_my_password/delete_my_account と同じ規約）。モーダル内で個別表示する。
      // 401: トークン自体が無効（セッション切れ）。パスワード不一致とは区別し、モーダルを閉じて
      //      ページ上部のセッション切れバナーに合流させる。
      if (err instanceof KdzApiError && err.status === 401) {
        closeModal();
        setReauthSessionExpired(true);
      } else if (err instanceof KdzApiError && err.status === 400) {
        setPwErr("パスワードが正しくありません。");
      } else if (err instanceof KdzApiError && err.status === 409) {
        setPwErr("LINEログイン専用アカウントのため、この操作はできません。");
      } else {
        setPwErr(toDisplayMessage(err, "処理に失敗しました。時間をおいて再度お試しください。"));
      }
    } finally {
      setLineBusy(false);
    }
  }

  const biddingCases = (cases ?? []).filter(
    (c) => c.bid_count > 0 && c.status !== "closed" && c.status !== "cancelled",
  );
  const negotiatingTxns = (transactions ?? []).filter(
    (t) => t.status === "pending" || t.status === "visiting",
  );
  const reviewWaitingTxns = (transactions ?? []).filter(
    (t) => t.status === "completed" && !t.has_review,
  );

  const rows: SummaryRow[] = [];
  if (biddingCases.length > 0) {
    rows.push({
      key: "bidding",
      icon: "bid",
      iconTone: "blue",
      title: "入札が届いている案件",
      text: `${biddingCases.length}件の案件に業者からの入札が届いています。内容をご確認ください。`,
      badgeLabel: "入札",
      href: "/cases",
    });
  }
  if (negotiatingTxns.length > 0) {
    rows.push({
      key: "negotiating",
      icon: "chat",
      iconTone: "green",
      title: "進行中の取引",
      text: `${negotiatingTxns.length}件の取引が訪問日調整・訪問予定として進行中です。`,
      badgeLabel: "進行中",
      href: negotiatingTxns.length === 1 ? `/cases/${negotiatingTxns[0].case_id}` : "/cases",
    });
  }
  if (reviewWaitingTxns.length > 0) {
    rows.push({
      key: "review",
      icon: "star",
      iconTone: "warn",
      title: "評価待ちの取引",
      text: `${reviewWaitingTxns.length}件の取引が完了しています。業者の評価にご協力ください。`,
      badgeLabel: "評価待ち",
      href:
        reviewWaitingTxns.length === 1
          ? `/review?transaction_id=${reviewWaitingTxns[0].id}`
          : "/mypage",
    });
  }

  const isLoading = loading || (!cases && !transactions && !profile && !error);
  const sessionExpired = (!loading && !token) || reauthSessionExpired;

  return (
    <div className="notif-page">
      <AppHeader unread={rows.length > 0} />

      <main id="main">
        <div className="notif-wrap">
          {/* LINE通知連携バナー */}
          {profile ? (
            <>
              <div className="notif-settings-banner">
                <NotifIcon name="bell" />
                <div className="notif-settings-text">
                  {profile.line_linked ? (
                    <>
                      <strong>LINE連携済み</strong>
                      <br />
                      入札・メッセージの通知がLINEにも届きます。
                    </>
                  ) : (
                    <>
                      <strong>LINE通知が届いていません。</strong>
                      <br />
                      入札・メッセージをLINEで即座に受け取れます。
                    </>
                  )}
                </div>
                {profile.line_linked ? (
                  <button
                    type="button"
                    className="btn-notif-setting"
                    disabled={!profile.has_password}
                    onClick={(e) => openModal("unlink", e)}
                  >
                    連携を解除
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn-notif-setting"
                    disabled={lineBusy}
                    onClick={onClickLineSetting}
                  >
                    LINEで通知を受け取る
                  </button>
                )}
              </div>
              {profile.line_linked && !profile.has_password ? (
                <p className="notif-settings-note">
                  LINEログイン専用アカウントのため、連携解除はできません。
                </p>
              ) : null}
            </>
          ) : null}

          <div className="notif-toolbar">
            <h1 className="notif-toolbar-title">通知・お知らせ</h1>
          </div>

          {lineNotice ? (
            <div
              role="alert"
              style={{
                marginBottom: 20,
                padding: "12px 16px",
                borderRadius: "var(--radius-s)",
                background: lineNotice.tone === "success" ? "#e8faf0" : "rgba(215,0,53,.06)",
                color: lineNotice.tone === "success" ? "var(--green)" : "var(--danger)",
                fontSize: 13,
                border: `1px solid ${lineNotice.tone === "success" ? "#86efac" : "rgba(215,0,53,.35)"}`,
              }}
            >
              {lineNotice.text}
            </div>
          ) : null}

          {sessionExpired ? (
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
              セッションが切れました。再ログインしてください。
              <Link href="/login" style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline" }}>
                ログインへ
              </Link>
            </div>
          ) : null}

          {error ? (
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
              {error}
            </div>
          ) : null}

          {sessionExpired ? null : isLoading ? (
            <div className="flex min-h-[30vh] items-center justify-center">
              <Spinner className="h-6 w-6 text-brand-600" />
            </div>
          ) : (
            <div id="notif-list">
              {rows.length > 0 ? (
                <div className="notif-group">
                  {rows.map((row) => (
                    <Link key={row.key} href={row.href} className="notif-card unread">
                      <div className="notif-card-inner">
                        <div className={`notif-icon ${row.iconTone}`}>
                          <NotifIcon name={row.icon} />
                        </div>
                        <div className="notif-body">
                          <div className="notif-title">{row.title}</div>
                          <div className="notif-text">{row.text}</div>
                          <div className="notif-meta">
                            <span className={`notif-badge ${row.iconTone}`}>{row.badgeLabel}</span>
                          </div>
                        </div>
                        <div className="notif-arrow">
                          <ArrowIcon />
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="notif-empty">
                  <div className="notif-empty-ic">
                    <NotifIcon name="bell" />
                  </div>
                  <h3>新しいお知らせはありません</h3>
                  <p>
                    入札や取引が始まるとここに表示されます。
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </main>

      {/* ===== LINE連携 パスワード確認モーダル ===== */}
      <div className={`modal-overlay${modal ? " show" : ""}`}>
        {modal ? (
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="lineModalTitle">
            <h2 className="modal-title" id="lineModalTitle">
              {modal === "link" ? "LINE連携のため本人確認をします" : "LINE連携を解除しますか？"}
            </h2>
            <p className="modal-sub">
              {modal === "link"
                ? "本人確認のため、現在のパスワードを入力してください。"
                : "解除すると、以後の入札・メッセージ通知はLINEに届かなくなります。本人確認のため、現在のパスワードを入力してください。"}
            </p>
            <form onSubmit={(e) => void onConfirmModal(e)}>
              <Field label="現在のパスワード" htmlFor="line-modal-pw" error={pwErr}>
                <PasswordField
                  id="line-modal-pw"
                  value={pwCur}
                  onChange={(v) => {
                    setPwCur(v);
                    if (pwErr) setPwErr(null);
                  }}
                  placeholder="現在のパスワード"
                  autoComplete="current-password"
                />
              </Field>
              <div className="modal-actions" style={{ marginTop: 8 }}>
                <button type="button" className="btn-modal-cancel" onClick={closeModal} disabled={lineBusy}>
                  戻る
                </button>
                <button
                  type="submit"
                  className={`btn-modal-confirm${modal === "unlink" ? " danger" : ""}`}
                  disabled={lineBusy || !pwCur}
                >
                  {lineBusy ? "処理中…" : modal === "link" ? "次へ進む" : "解除する"}
                </button>
              </div>
            </form>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function NotificationsPage() {
  return (
    <Suspense>
      <NotificationsContent />
    </Suspense>
  );
}
