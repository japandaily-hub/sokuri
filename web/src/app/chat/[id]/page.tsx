"use client";

/**
 * 交渉チャット（/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/chat.html をピクセル忠実に再現。
 * 動的ルート([id])。SiteChrome の BARE_PREFIXES（/chat）対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + ID + 通知ベル）と全画面レイアウトを描く。
 *
 * [id] は transaction_id として扱う（成約後は1業者につき1スレッドのため）。
 * サイドバーは「自分の成約案件一覧」（listTransactions）。メッセージは
 * listMessages のポーリング（表示中5秒間隔・document.hidden 時は停止）+ sendMessage。
 * 日程調整カード（kind==="schedule_proposal"）はメッセージストリーム内に inline 表示し、
 * meta.slots から選択して confirmSchedule を呼ぶ。
 */

import "./chat.css";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { useToken } from "@/components/kdz/Ui";
import {
  confirmSchedule as apiConfirmSchedule,
  getTransaction,
  listMessages,
  listTransactions,
  markMessagesRead,
  sendMessage,
  toDisplayMessage,
  type MessageOut,
  type TransactionDetail,
  type TransactionListItem,
} from "@/lib/katadzuke-api";

/* ---- カレンダー線画（スプライト未収録のため inline。絵文字は使わない） ---- */
function CalendarIc({ className }: { className?: string }) {
  return (
    <svg className={`ic${className ? ` ${className}` : ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 9h16M8 3v4M16 3v4" />
    </svg>
  );
}

const POLL_INTERVAL_MS = 5000;

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}
function formatDateSep(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ja-JP", { month: "long", day: "numeric", weekday: "short" });
}

/**
 * 業者が入力する候補日文字列（例: "7月5日（土）10:00〜12:00"）から
 * ISO日付（YYYY-MM-DD）を抽出する。「月」「日」の数字パターンのみに依存し、
 * 抽出できない場合は null を返す（呼び出し側でエラー表示にフォールバックする）。
 * 年は「今日以降で直近に来る年」を採用する（月が現在月より前なら来年扱い）。
 */
function parseSlotDate(slot: string): string | null {
  const m = slot.match(/(\d{1,2})月(\d{1,2})日/);
  if (!m) return null;
  const month = Number(m[1]);
  const day = Number(m[2]);
  if (!Number.isInteger(month) || !Number.isInteger(day) || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }
  const now = new Date();
  let year = now.getFullYear();
  const candidate = new Date(year, month - 1, day);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (candidate < today) year += 1;
  const mm = String(month).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${mm}-${dd}`;
}

export default function ChatPage() {
  // 動的ルートの id は transaction_id。
  const params = useParams<{ id: string }>();
  const transactionId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const router = useRouter();
  const { token, loading: tokenLoading } = useToken();

  /* ---- サイドバー: 自分の成約案件一覧 ---- */
  const [transactions, setTransactions] = useState<TransactionListItem[]>([]);
  const [sideLoading, setSideLoading] = useState(true);

  /* ---- 現在の成約詳細（相手業者情報・入札額） ---- */
  const [detail, setDetail] = useState<TransactionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  /* ---- メッセージ ---- */
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const lastFetchedAtRef = useRef<string | undefined>(undefined);

  /* ---- 日程確定操作の状態 ---- */
  const [schedulePickByMsg, setSchedulePickByMsg] = useState<Record<string, number>>({});
  const [confirmingMsgId, setConfirmingMsgId] = useState<string | null>(null);

  /* ---- トースト ---- */
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  function showToast(msg: string) {
    setToast(msg);
    if (toastTimer.current !== undefined) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }
  useEffect(() => () => {
    if (toastTimer.current !== undefined) window.clearTimeout(toastTimer.current);
  }, []);

  /* ---- サイドバー: 成約一覧取得 ---- */
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listTransactions(token);
        if (!cancelled) setTransactions(list);
      } catch (e) {
        if (!cancelled) showToast(toDisplayMessage(e, "案件一覧の取得に失敗しました"));
      } finally {
        if (!cancelled) setSideLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  /* ---- 成約詳細取得 ---- */
  const reloadDetail = useCallback(async () => {
    if (!token || !transactionId) return;
    try {
      const d = await getTransaction(transactionId, token);
      setDetail(d);
      setDetailError(null);
    } catch (e) {
      setDetailError(toDisplayMessage(e, "成約情報の取得に失敗しました"));
    }
  }, [token, transactionId]);

  useEffect(() => {
    void reloadDetail();
  }, [reloadDetail]);

  /* ---- メッセージ取得（初回全件 + ポーリング差分） ---- */
  const fetchMessages = useCallback(
    async (initial: boolean) => {
      if (!token || !transactionId) return;
      try {
        const after = initial ? undefined : lastFetchedAtRef.current;
        const batch = await listMessages(transactionId, token, after);
        if (batch.length > 0) {
          lastFetchedAtRef.current = batch[batch.length - 1].created_at;
          setMessages((prev) => (initial ? batch : [...prev, ...batch]));
        } else if (initial) {
          setMessages([]);
        }
        setMessagesError(null);
      } catch (e) {
        setMessagesError(toDisplayMessage(e, "メッセージの取得に失敗しました"));
      }
    },
    [token, transactionId],
  );

  useEffect(() => {
    lastFetchedAtRef.current = undefined;
    setMessages([]);
    void fetchMessages(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transactionId, token]);

  /* ---- ポーリング（表示中のみ・document.hidden 時は停止） ---- */
  useEffect(() => {
    if (!token || !transactionId) return;
    let timer: number | undefined;
    function schedule() {
      timer = window.setTimeout(async () => {
        if (!document.hidden) {
          await fetchMessages(false);
        }
        schedule();
      }, POLL_INTERVAL_MS);
    }
    schedule();
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [token, transactionId, fetchMessages]);

  /* ---- 既読化（メッセージ表示のたびに自分宛の未読を消化） ---- */
  useEffect(() => {
    if (!token || !transactionId || messages.length === 0) return;
    markMessagesRead(transactionId, token).catch(() => {
      /* 既読更新の失敗は致命的でないため無視する */
    });
  }, [token, transactionId, messages.length]);

  /* ---- 自動スクロール ---- */
  const messagesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  function selectTransaction(id: string) {
    if (id === transactionId) return;
    router.push(`/chat/${id}`);
  }

  async function handleSend() {
    const text = draft.trim();
    if (!text || !token || !transactionId || sending) return;
    setSending(true);
    try {
      const sent = await sendMessage(transactionId, text, token);
      setMessages((prev) => [...prev, sent]);
      lastFetchedAtRef.current = sent.created_at;
      setDraft("");
    } catch (e) {
      showToast(toDisplayMessage(e, "メッセージの送信に失敗しました"));
    } finally {
      setSending(false);
    }
  }

  async function handleConfirmSchedule(msg: MessageOut, slots: string[]) {
    if (!token || !transactionId || confirmingMsgId) return;
    const idx = schedulePickByMsg[msg.id] ?? 0;
    const slotLabel = slots[idx];
    if (!slotLabel) return;
    const visitDate = parseSlotDate(slotLabel);
    if (!visitDate) {
      showToast("候補日の形式を解析できませんでした。日程調整ページからお選びください。");
      return;
    }
    setConfirmingMsgId(msg.id);
    try {
      await apiConfirmSchedule(
        transactionId,
        { visit_date: visitDate, visit_time_slot: slotLabel },
        token,
      );
      showToast("日程を確定しました");
      await Promise.all([reloadDetail(), fetchMessages(false)]);
    } catch (e) {
      showToast(toDisplayMessage(e, "日程の確定に失敗しました"));
    } finally {
      setConfirmingMsgId(null);
    }
  }

  const biz = detail?.operator ?? null;
  const bizInitial = biz?.company_name?.charAt(0) ?? "業";
  const appId = detail?.id ? detail.id.slice(0, 8).toUpperCase() : "";

  return (
    <div className="chat-page">
      {/* 専用ヘッダー（戻る矢印 + ロゴ + タイトル + 申込ID + 通知ベル） */}
      <header className="chat-header">
        <Link href="/applications" className="ch-back" aria-label="申し込み状況へ戻る">
          <Ic name="arrow" />
        </Link>
        <Link href="/" className="ch-logo" aria-label="カタヅケ トップへ">
          <KdzLogo size={20} />
        </Link>
        <span className="ch-divider" aria-hidden="true" />
        <span className="ch-title">交渉チャット</span>
        {appId ? <span className="ch-id">{appId}</span> : null}
        <Link href="/notifications" className="ch-bell" aria-label="通知・お知らせ">
          <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
          <span className="bell-dot" aria-hidden="true" />
        </Link>
      </header>

      <div className="chat-layout">
        {/* 成約案件一覧 */}
        <nav className="biz-sidebar" aria-label="自分の成約案件">
          <div className="biz-sidebar-head">成約案件</div>
          {sideLoading ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>読み込み中…</div>
          ) : transactions.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>成約済みの案件はありません</div>
          ) : (
            transactions.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`biz-item${t.id === transactionId ? " active" : ""}`}
                onClick={() => selectTransaction(t.id)}
                aria-current={t.id === transactionId ? "true" : undefined}
              >
                <div className="biz-meta">
                  <span className="biz-time">{new Date(t.created_at).toLocaleDateString("ja-JP")}</span>
                </div>
                <div className="biz-name">{t.company_name ?? "業者"}</div>
                <div className="biz-preview">
                  {t.prefecture} {t.city}
                </div>
                <span className="biz-bid">
                  {t.final_amount != null ? `¥${t.final_amount.toLocaleString()}` : `¥${t.initial_amount.toLocaleString()}`}
                </span>
              </button>
            ))
          )}
        </nav>

        {/* チャット本体 */}
        <div className="chat-main">
          {tokenLoading || (!detail && !detailError) ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--body-soft)" }}>
              読み込み中…
            </div>
          ) : detailError ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--body-soft)" }}>
              {detailError}
            </div>
          ) : (
            <>
              {/* 相手ヘッダー */}
              <div className="chat-peer-header">
                <div className="peer-avatar">{bizInitial}</div>
                <div className="peer-name-block">
                  <div className="peer-name">{biz?.company_name ?? "業者"}</div>
                  <div className="peer-sub">
                    {detail?.case?.prefecture} {detail?.case?.city}
                    {biz ? (
                      <Link href={`/vendors/${biz.id}`} className="peer-link">
                        プロフィールを見る
                      </Link>
                    ) : null}
                  </div>
                </div>
                <div className="peer-bid-chip">
                  <div className="peer-bid-label">成約額</div>
                  <div className="peer-bid-amount">
                    ¥{(detail?.final_amount ?? detail?.initial_amount ?? 0).toLocaleString()}
                  </div>
                </div>
              </div>

              {/* LINE通知バナー */}
              <div className="line-banner">
                <span className="line-dot" aria-hidden="true" />
                新着メッセージはLINEにも通知されます。返信はこのページで行えます。
              </div>

              {messagesError ? (
                <div style={{ padding: "8px 20px", fontSize: 12.5, color: "#e05c5c" }}>{messagesError}</div>
              ) : null}

              {/* メッセージ */}
              <div className="messages-area" ref={messagesRef}>
                {messages.map((m, i) => {
                  const showDateSep = i === 0 || formatDateSep(m.created_at) !== formatDateSep(messages[i - 1].created_at);
                  if (m.kind === "schedule_proposal") {
                    const slots = Array.isArray(m.meta?.slots) ? (m.meta?.slots as string[]) : [];
                    const pick = schedulePickByMsg[m.id] ?? 0;
                    return (
                      <div key={m.id}>
                        {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                        <div className="msg them">
                          <div className="msg-avatar">{bizInitial}</div>
                          <div>
                            <div className="msg-time">{formatTime(m.created_at)}</div>
                            <div className="bubble">{m.body}</div>
                          </div>
                        </div>
                        <div className="schedule-card" id={`schedule-card-${m.id}`}>
                          <div className="schedule-card-head">
                            <CalendarIc />
                            引き取り候補日
                          </div>
                          <div className="schedule-options" role="radiogroup" aria-label="引き取り候補日">
                            {slots.map((opt, si) => (
                              <div className="schedule-opt" key={opt}>
                                <input
                                  type="radio"
                                  name={`schedule-${m.id}`}
                                  id={`s-${m.id}-${si}`}
                                  checked={pick === si}
                                  onChange={() =>
                                    setSchedulePickByMsg((prev) => ({ ...prev, [m.id]: si }))
                                  }
                                />
                                <label htmlFor={`s-${m.id}-${si}`}>{opt}</label>
                              </div>
                            ))}
                          </div>
                          <button
                            type="button"
                            className="btn-schedule"
                            onClick={() => handleConfirmSchedule(m, slots)}
                            disabled={confirmingMsgId === m.id || detail?.status !== "pending"}
                          >
                            {detail?.status !== "pending"
                              ? "日程確定済み"
                              : confirmingMsgId === m.id
                                ? "確定中…"
                                : `${slots[pick] ?? ""} を選ぶ`}
                          </button>
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div key={m.id}>
                      {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                      <div className={`msg ${m.mine ? "me" : "them"}`}>
                        <div className="msg-avatar">{m.mine ? "自" : m.sender_type === "system" ? "運" : bizInitial}</div>
                        <div>
                          <div className="msg-time">{formatTime(m.created_at)}</div>
                          <div className="bubble">{m.body}</div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* 入力エリア */}
              <div className="input-area">
                <input
                  type="text"
                  className="msg-input"
                  placeholder="メッセージを入力…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void handleSend();
                    }
                  }}
                  aria-label="メッセージを入力"
                  disabled={sending}
                />
                <button
                  type="button"
                  className="btn-send"
                  aria-label="送信"
                  disabled={!draft.trim() || sending}
                  onClick={() => void handleSend()}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M22 2L11 13" />
                    <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                  </svg>
                </button>
              </div>
            </>
          )}
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
