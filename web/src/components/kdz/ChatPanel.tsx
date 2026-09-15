"use client";

/**
 * 交渉チャット本体（共有コンポーネント）。
 * 元は /chat/[id]/page.tsx に直書きされていたメッセージ取得・送信・日程確定・
 * 既読化のロジックとUIをそのまま抽出したもの。以下の2箇所から使う。
 * - web/src/app/chat/[id]/page.tsx（standalone: 専用ページ。ヘッダー・成約案件サイドバーは
 *   呼び出し元が描画し、本コンポーネントは chat-main（相手ヘッダー/バナー/メッセージ/入力欄）のみを担当）
 * - web/src/app/cases/[id]/page.tsx（embedded: 案件詳細ページの成約パネル内にインライン表示。
 *   別ページへの遷移なしで「業者を選ぶ→そのままチャット」を完結させるため、
 *   chat-page 相当のラッパーごと自前で描画し、固定高のパネルとして収める）
 *
 * スタイルは web/src/app/chat/[id]/chat.css をそのまま流用する（katazuke.css の CSS変数を
 * 継承する設計のため、cases/[id] 側の Tailwind/kdz-Ui.tsx 基盤とは別スタイル基盤の混在を許容する。
 * これは本コンポーネントのスコープ外の統一は行わない、というタスク方針に基づく）。
 */

import "@/app/chat/[id]/chat.css";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useToken } from "@/components/kdz/Ui";
import {
  CANCELLED_BY_LABEL,
  confirmSchedule as apiConfirmSchedule,
  getTransaction,
  KdzApiError,
  listMessages,
  markMessagesRead,
  sendMessage,
  toDisplayMessage,
  TXN_STATUS_LABEL,
  type MessageOut,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

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

/* ---- カレンダー線画（スプライト未収録のため inline。絵文字は使わない） ---- */
function CalendarIc({ className }: { className?: string }) {
  return (
    <svg className={`ic${className ? ` ${className}` : ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 9h16M8 3v4M16 3v4" />
    </svg>
  );
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

export interface ChatPanelProps {
  /** チャット対象の取引ID（transaction_id）。 */
  transactionId: string;
  /**
   * 表示先。
   * - "standalone"（既定）: /chat/[id] 専用ページ内。ヘッダー・成約案件サイドバーは
   *   呼び出し元（chat-page ラッパー）が描画済みの前提で、chat-main のみを描画する。
   * - "embedded": 他ページのカード内にインライン表示する。chat-page 相当のラッパーごと
   *   自前で描画し、100vh 全画面ではなく固定高のパネルとして収める。
   */
  variant?: "standalone" | "embedded";
  /**
   * embedded 時、成約詳細（TransactionDetail）を再取得するたびに呼び出し元へ通知する。
   * 未読件数バッジ等、呼び出し元が保持する成約状態をチャット側の更新に追従させるために使う。
   */
  onDetailChange?: (detail: TransactionDetail) => void;
  /** embedded 時、外枠 div に追加するクラス（余白調整等）。 */
  className?: string;
}

/**
 * 交渉チャット（相手ヘッダー・通知バナー・メッセージ一覧・日程確定カード・送信欄）。
 * メッセージ取得は初回全件 + 5秒間隔ポーリング（document.hidden 時は停止）、
 * 送信は楽観的にローカル配列へ追加する。
 */
export function ChatPanel({
  transactionId,
  variant = "standalone",
  onDetailChange,
  className,
}: ChatPanelProps) {
  const { token, loading: tokenLoading } = useToken();

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

  /* ---- 成約詳細取得 ---- */
  const reloadDetail = useCallback(async () => {
    if (!token || !transactionId) return;
    try {
      const d = await getTransaction(transactionId, token);
      setDetail(d);
      setDetailError(null);
      onDetailChange?.(d);
    } catch (e) {
      setDetailError(toDisplayMessage(e, "成約情報の取得に失敗しました"));
    }
    // onDetailChange は呼び出し元の再レンダーのたびに新しい関数参照になり得るため、
    // 依存配列から除外する（無限リロードを防ぐ。呼び出し側の最新の値は closure 経由で使われる）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      // r8-fix-frontend2 H3 是正: 409 transaction_closed（取引終了後の送信）を
      // 受けた場合、detail が古いままだと入力欄が有効なまま残るため再取得する。
      if (e instanceof KdzApiError && e.status === 409) await reloadDetail();
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
      // r8-fix-frontend2 H3 是正: 409 transaction_closed（取引終了後の日程確定）を
      // 受けた場合、detail を再取得して終了バナー・ボタン無効化に反映させる。
      if (e instanceof KdzApiError && e.status === 409) await reloadDetail();
    } finally {
      setConfirmingMsgId(null);
    }
  }

  const biz = detail?.operator ?? null;
  const bizInitial = biz?.company_name?.charAt(0) ?? "業";
  // r8-fix-frontend2 H3 是正: キャンセル済み・完了済みの取引ではチャットの続行操作
  // （送信・日程提案の確定）を無効化し、事実に即した終了表示に切り替える。
  const isClosed = detail?.status === "cancelled" || detail?.status === "completed";
  // r8-fix-frontend5 対応: 落札業者が退会済みの場合、送信・日程確定に進めないよう無効化する。
  const operatorDeleted = detail?.operator_deleted === true;

  const mainContent = (
    <div className="chat-main" aria-label="交渉チャット">
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
              <div className="peer-bid-label">成約金額</div>
              <div className="peer-bid-amount">
                ¥{(detail?.final_amount ?? detail?.initial_amount ?? 0).toLocaleString()}
              </div>
            </div>
          </div>

          {/* r8-fix-frontend2 H3 是正: キャンセル済み・完了済みの取引では、通常のLINE通知
              バナーの代わりに終了案内を出す（送信欄・候補日確定は無効化される）。 */}
          {operatorDeleted ? (
            <div
              style={{
                margin: "0 20px 12px",
                borderRadius: 0,
                border: "1px solid var(--danger)",
                background: "rgba(215,0,53,0.06)",
                padding: 12,
                fontSize: 13,
                lineHeight: 1.6,
                color: "var(--danger)",
              }}
              role="alert"
            >
              この業者は退会したため、この取引は進められません。キャンセルして新しく出品してください
            </div>
          ) : isClosed ? (
            <>
              <div className="line-banner" role="status">
                <span className="line-dot" aria-hidden="true" />
                この取引は終了しています（{detail ? TXN_STATUS_LABEL[detail.status] : ""}）。新しいメッセージは送信できません。
              </div>
              {/* r10-O-H-1 是正: キャンセル理由の表示（cases/[id] と同じ部品・語彙）。 */}
              {detail?.cancellation ? (
                <div
                  style={{
                    margin: "0 20px 12px",
                    borderRadius: 0,
                    border: "1px solid var(--line)",
                    background: "var(--pale, #f7f7f5)",
                    padding: 12,
                    fontSize: 13,
                    lineHeight: 1.6,
                    color: "var(--body)",
                  }}
                  role="status"
                >
                  <p style={{ fontWeight: 600, margin: 0 }}>
                    キャンセル: {CANCELLED_BY_LABEL[detail.cancellation.cancelled_by]}による
                  </p>
                  <p style={{ marginTop: 4, fontSize: 12, color: "var(--body-soft)" }}>
                    {new Date(detail.cancellation.cancelled_at).toLocaleString("ja-JP")}
                  </p>
                  {detail.cancellation.reason ? (
                    <p style={{ marginTop: 4, wordBreak: "break-word" }}>理由: {detail.cancellation.reason}</p>
                  ) : (
                    <p style={{ marginTop: 4, color: "var(--body-soft)" }}>理由の記載なし</p>
                  )}
                </div>
              ) : null}
            </>
          ) : (
            <div className="line-banner">
              <span className="line-dot" aria-hidden="true" />
              新着メッセージの通知は、LINE連携済みの方にLINEでお知らせします（メールでの新着通知はありません）。返信はこのページで行えます。
            </div>
          )}

          {messagesError ? (
            <div style={{ padding: "8px 20px", fontSize: 12.5, color: "var(--danger)" }}>{messagesError}</div>
          ) : null}

          {/* メッセージ */}
          <div className="messages-area" ref={messagesRef} role="log" aria-live="polite" aria-relevant="additions">
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
                        disabled={confirmingMsgId === m.id || detail?.status !== "pending" || operatorDeleted}
                      >
                        {operatorDeleted
                          ? "業者退会のため確定できません"
                          : isClosed && detail
                            ? TXN_STATUS_LABEL[detail.status]
                            : detail?.status !== "pending"
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

          {/* 入力エリア（終了済み取引・業者退会時は非表示にし、案内のみ出す） */}
          {operatorDeleted ? (
            <div className="input-area" style={{ color: "var(--body-soft)", fontSize: 13, padding: "12px 20px" }}>
              この業者は退会したため送信できません
            </div>
          ) : isClosed ? (
            <div className="input-area" style={{ color: "var(--body-soft)", fontSize: 13, padding: "12px 20px" }}>
              この取引は終了しています
            </div>
          ) : (
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
          )}
        </>
      )}
    </div>
  );

  if (variant === "embedded") {
    return (
      <div className={`chat-page chat-embed-panel${className ? ` ${className}` : ""}`}>
        {mainContent}
        {toast ? (
          <div className="kdz-toast" role="status">
            {toast}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <>
      {mainContent}
      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
    </>
  );
}
