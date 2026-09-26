"use client";

/**
 * 業者 交渉チャット（/operator/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/業者チャット.html をピクセル忠実に再現。
 * これは業者(operator)側の画面。送信メッセージ（自社）は青バブルで右、相手（ユーザー）は白バブルで左。
 *
 * 動的ルート([id])。/operator は SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + 業者管理バッジ + 会社名 + 通知ベル）と全画面レイアウトを描く。
 *
 * [id] は transaction_id として扱う。サイドバー「交渉中の案件」は listTransactions（業者向け）。
 * メッセージは listMessages のポーリング（表示中5秒間隔・document.hidden 時は停止）+ sendMessage。
 * 日程提示は proposeSchedule に接続する。
 */

import "./chat.css";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { signOut } from "next-auth/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { useToken } from "@/components/kdz/Ui";
import { stripControlChars, stripControlCharsKeepNewlines } from "@/lib/categories";
import {
  CANCELLED_BY_LABEL,
  TXN_STATUS_LABEL,
  getTransaction,
  KdzApiError,
  listMessages,
  listTransactions,
  LIST_MAX_LIMIT,
  markMessagesRead,
  proposeSchedule,
  sendMessage,
  toDisplayMessage,
  type MessageOut,
  type TransactionDetail,
  type TransactionListItem,
} from "@/lib/katadzuke-api";
import { VISIT_TIME_SLOTS, formatSlotLabel, toIsoDateString } from "@/lib/visit-slots";

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
function yen(n: number): string {
  return `¥${n.toLocaleString()}`;
}

/** 候補日提案フォームの1行分の入力状態（日付 + 時間帯）。 */
type SlotDraft = { date: string; time: string | null };

/** 候補日の提案件数の上限（「＋ 候補日を追加」を無効化する閾値。2026-09-26 ボタン化）。 */
const MAX_SLOT_DRAFTS = 10;

/** 候補日入力の日付レンジ（何日後まで許可するか）。 */
const MAX_SLOT_DATE_RANGE_DAYS = 364;

/** base から days 日後の Date を作る（元の Date は変更しない）。 */
function addDays(base: Date, days: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

export default function OperatorChatPage() {
  const params = useParams<{ id: string }>();
  const transactionId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const router = useRouter();
  const { token, loading: tokenLoading } = useToken();

  /* ---- サイドバー: 交渉中の案件一覧（業者向け listTransactions） ---- */
  const [transactions, setTransactions] = useState<TransactionListItem[]>([]);
  const [sideLoading, setSideLoading] = useState(true);

  /* ---- 現在の成約詳細（相手ユーザー情報・合意額・案件） ---- */
  const [detail, setDetail] = useState<TransactionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  /* ---- メッセージ ---- */
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const lastFetchedAtRef = useRef<string | undefined>(undefined);

  /* ---- 日程提案カード（候補日の編集 + 送信） ---- */
  const [slots, setSlots] = useState<SlotDraft[]>([{ date: "", time: null }]);
  const [scheduleVisible, setScheduleVisible] = useState(false);
  const [proposing, setProposing] = useState(false);
  // 候補日入力の日付レンジ（今日から364日後まで）。画面を開いたまま日付をまたぐと
  // min/max が古いままになり過去日を選べてしまうため、useMemo でキャッシュせず
  // 描画のたびに new Date() から求める（送信時のバリデーションは handleSendSchedule
  // 内で改めて計算し直す。こちらは <input type="date"> の min/max 表示専用）。
  const todayIso = toIsoDateString(new Date());
  const maxSlotDateIso = toIsoDateString(addDays(new Date(), MAX_SLOT_DATE_RANGE_DAYS));

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

  /* ---- サイドバー: 交渉中の案件取得 ---- */
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listTransactions(token, { limit: LIST_MAX_LIMIT, offset: 0 });
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
          // detail（txn.status/visit_date）が画面を開いた時点のまま止まっていると、
          // 依頼者が日程確定・完了確定した直後も pending/visiting 判定が古いままになり、
          // 候補日の提示可否や完了確定ボタンの押せない条件が実情とズレる。
          // schedule_confirmed（日程確定）・completed（完了確定）のメッセージが新たに
          // 届いたら detail を取り直す。
          if (batch.some((m) => m.kind === "schedule_confirmed" || m.kind === "completed")) {
            await reloadDetail();
          }
        } else if (initial) {
          setMessages([]);
        }
        setMessagesError(null);
      } catch (e) {
        setMessagesError(toDisplayMessage(e, "メッセージの取得に失敗しました"));
      }
    },
    [token, transactionId, reloadDetail],
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

  /* ---- 既読化 ---- */
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
  }, [messages.length, scheduleVisible]);

  function selectTransaction(id: string) {
    if (id === transactionId) return;
    router.push(`/operator/chat/${id}`);
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
      // r8-fix-frontend2 H3 是正: 409 transaction_closed（取引終了後の送信）を
      // 受けた場合、detail が古いままだと入力欄が有効なまま残るため再取得する。
      if (e instanceof KdzApiError && e.status === 409) await reloadDetail();
    } finally {
      setSending(false);
    }
  }

  /* ---- 日程提案カード操作 ---- */
  function updateSlotDate(i: number, value: string) {
    setSlots((prev) => prev.map((s, idx) => (idx === i ? { ...s, date: value } : s)));
  }
  function updateSlotTime(i: number, value: string) {
    setSlots((prev) => prev.map((s, idx) => (idx === i ? { ...s, time: value } : s)));
  }
  function removeSlot(i: number) {
    setSlots((prev) => prev.filter((_, idx) => idx !== i));
  }
  function addSlot() {
    setSlots((prev) => (prev.length >= MAX_SLOT_DRAFTS ? prev : [...prev, { date: "", time: null }]));
  }
  function toggleScheduleCard() {
    // ボタン自体を disabled にしているが、万一の誤発火に備えて関数側でも防ぐ
    // （訪問日程が確定済みの取引では新しい候補日を提示させない）。
    if (isVisiting) return;
    setScheduleVisible((v) => {
      const next = !v;
      if (next) {
        window.setTimeout(() => {
          document.getElementById("schedule-propose")?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 0);
      }
      return next;
    });
  }
  async function handleSendSchedule() {
    // 未完成行（日付・時間帯のどちらかが未選択）が1つでもあれば送信させない。
    // 初期状態の1行だけ空のまま送信した場合もここに含まれる（従来の「候補日を
    // 1つ以上入力してください」に相当）。
    if (slots.length === 0 || slots.some((s) => !s.date || !s.time)) {
      showToast("候補日の日付と時間帯を選んでください");
      return;
    }
    // iOS は <input type="date"> の min/max 属性を強制しないため、送信時にも検査する。
    // 画面を開いたまま日付をまたいだ場合に備え、描画時の todayIso/maxSlotDateIso ではなく
    // 送信ボタンを押した瞬間の new Date() で改めて求めた値と比較する。
    const submitTodayIso = toIsoDateString(new Date());
    const submitMaxSlotDateIso = toIsoDateString(addDays(new Date(), MAX_SLOT_DATE_RANGE_DAYS));
    if (slots.some((s) => s.date < submitTodayIso || s.date > submitMaxSlotDateIso)) {
      showToast("候補日は本日から1年以内の日付を選んでください");
      return;
    }
    if (!token || !transactionId || proposing) return;
    // 同一ラベル（同じ日付・同じ時間帯の重複行）は順序を保って重複除去する（Set は挿入順を保持する）。
    const dates = Array.from(new Set(slots.map((s) => formatSlotLabel(s.date, s.time as string))));
    setProposing(true);
    try {
      const msg = await proposeSchedule(transactionId, dates, token);
      setMessages((prev) => [...prev, msg]);
      lastFetchedAtRef.current = msg.created_at;
      setScheduleVisible(false);
      setSlots([{ date: "", time: null }]);
      showToast("候補日を送信しました");
    } catch (e) {
      showToast(toDisplayMessage(e, "候補日の送信に失敗しました"));
      // r8-fix-frontend2 H3 是正: 409 transaction_closed（取引終了後の候補日提案）を
      // 受けた場合、detail を再取得して終了バナー・提案ボタンの無効化に反映させる。
      if (e instanceof KdzApiError && e.status === 409) await reloadDetail();
    } finally {
      setProposing(false);
    }
  }

  const peerInitial = "客";
  const caseIdShort = detail?.case_id ? detail.case_id.slice(0, 8).toUpperCase() : "";
  const statusLabel = detail ? TXN_STATUS_LABEL[detail.status] : "";
  // r8-fix-frontend2 H3 是正: キャンセル済み・完了済みの取引ではチャットの続行操作
  // （送信・日程提案）を無効化し、事実に即した終了表示に切り替える。
  const isClosed = detail?.status === "cancelled" || detail?.status === "completed";
  // 2026-09-26 ボタン化: 訪問日程が確定済み（visiting）の取引は、依頼者が候補日を確定できず
  // 確定API も 409 を返すため、業者側でも新しい候補日の提示を止める（送信済み候補日の表示自体は
  // 既存どおり残す）。変更したい場合はメッセージで直接相談してもらう。
  const isVisiting = detail?.status === "visiting";

  return (
    <div className="opchat-page">
      {/* 専用ヘッダー */}
      <header className="ch-header">
        <Link href="/operator/cases" className="ch-back" aria-label="案件一覧へ戻る">
          <Ic name="arrow" />
        </Link>
        <Link href="/operator" className="ch-logo" aria-label="業者ダッシュボードへ">
          <KdzLogo size={20} />
        </Link>
        <span className="ch-divider" aria-hidden="true" />
        <span className="ch-title">交渉チャット</span>
        <span className="ch-badge">業者管理画面</span>
        <div className="ch-right">
          <Link href="/operator" className="ch-bell" aria-label="通知・お知らせ">
            <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 01-3.46 0" />
            </svg>
            <span className="bell-dot" aria-hidden="true" />
          </Link>
          <Link href="/operator/transactions" className="ch-txn-link">
            取引一覧へ
          </Link>
          <button
            type="button"
            className="ch-logout"
            onClick={() => signOut({ callbackUrl: "/operator/login" })}
          >
            ログアウト
          </button>
        </div>
      </header>

      <div className="chat-layout">
        {/* 案件リスト（左サイドバー） */}
        <nav className="case-sidebar" aria-label="交渉中の案件">
          <div className="case-sidebar-head">交渉中の案件</div>
          {sideLoading ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>読み込み中…</div>
          ) : transactions.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>落札済みの案件はありません</div>
          ) : (
            transactions.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`case-item${t.id === transactionId ? " active" : ""}`}
                onClick={() => selectTransaction(t.id)}
                aria-current={t.id === transactionId ? "true" : undefined}
              >
                <span className={`case-status status-${t.status === "pending" ? "waiting" : t.status === "visiting" ? "scheduled" : "negotiating"}`}>
                  {TXN_STATUS_LABEL[t.status]}
                </span>
                <div className="case-id">{t.id.slice(0, 8).toUpperCase()}</div>
                <div className="case-preview">
                  {t.prefecture} {t.city}
                </div>
                <div className="case-bid-row">
                  <span className="case-bid">
                    {yen(t.final_amount ?? t.initial_amount)}
                  </span>
                </div>
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
              {/* 相手（ユーザー）ヘッダー */}
              <div className="chat-peer-header">
                <div className="peer-avatar">{peerInitial}</div>
                <div className="peer-info">
                  <div className="peer-name">お客様</div>
                  <div className="peer-sub">
                    {detail?.case?.prefecture} {detail?.case?.city}　{caseIdShort}
                  </div>
                </div>
                <div className="amount-chip">
                  <div className="amount-label">合意額</div>
                  <div className="amount-val">{yen(detail?.final_amount ?? detail?.initial_amount ?? 0)}</div>
                </div>
              </div>

              {/* ステータスバー */}
              <div className="status-bar">
                <span className="status-dot" aria-hidden="true" />
                {statusLabel}
              </div>

              {/* r8-fix-frontend2 H3 是正: キャンセル済み・完了済みの取引では続行操作
                  （送信・日程提案）ができないことを明示する。 */}
              {isClosed ? (
                <div style={{ padding: "8px 20px", fontSize: 12.5, color: "var(--body-soft)" }} role="status">
                  この取引は終了しています。メッセージの送信・日程提案はできません。
                </div>
              ) : isVisiting ? (
                <div style={{ padding: "8px 20px", fontSize: 12.5, color: "var(--body-soft)" }} role="status">
                  訪問日程は確定済みです。変更が必要な場合はメッセージでご相談ください。
                </div>
              ) : null}

              {/* r10 O-H-1 是正: 取引詳細には出ているキャンセルの記録（誰が・なぜ・いつ）が
                  チャットには一切出ず、相手が突然応答しなくなったようにしか見えなかった。 */}
              {detail?.status === "cancelled" && detail.cancellation ? (
                <div
                  style={{
                    padding: "8px 20px",
                    fontSize: 12.5,
                    color: "var(--body-soft)",
                    wordBreak: "break-word",
                    overflowWrap: "anywhere",
                  }}
                  role="status"
                >
                  キャンセル: {CANCELLED_BY_LABEL[detail.cancellation.cancelled_by]}による（
                  {new Date(detail.cancellation.cancelled_at).toLocaleString("ja-JP")}）
                  <br />
                  {detail.cancellation.reason ? `理由: ${detail.cancellation.reason}` : "理由の記載なし"}
                </div>
              ) : null}

              {messagesError ? (
                <div style={{ padding: "8px 20px", fontSize: 12.5, color: "var(--danger)" }}>{messagesError}</div>
              ) : null}

              {/* メッセージ */}
              <div className="messages-area" ref={messagesRef}>
                {/* 空状態の案内は進行中の取引だけに出す。終了済みでは日程提案ができず
                    上部の終了案内とも重なるため、空状態ごと出さない（2026-09-25 モバイル監査）。 */}
                {messages.length === 0 && !isClosed ? (
                  <div className="ch-empty">
                    まだメッセージはありません。
                    <br />
                    まずは「引き取り日程を提案」からお客様に候補日を送りましょう。
                  </div>
                ) : null}
                {messages.map((m, i) => {
                  const showDateSep = i === 0 || formatDateSep(m.created_at) !== formatDateSep(messages[i - 1].created_at);
                  return (
                    <div key={m.id}>
                      {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                      <div className={`msg ${m.mine ? "me" : "them"}`}>
                        <div className="msg-avatar">{m.mine ? "自" : m.sender_type === "system" ? "運" : peerInitial}</div>
                        <div>
                          <div className="msg-time">{formatTime(m.created_at)}</div>
                          {/* 日程検証レビュー SEC-L5: 本対応前に保存された運営名義（system）メッセージへの
                              二重の防御として表示直前に制御文字（改行以外）を除去する。依頼者・
                              業者の通常メッセージは絵文字の結合（ZWJ）等を壊さないよう変えない。 */}
                          <div className="bubble">
                            {m.sender_type === "system" ? stripControlCharsKeepNewlines(m.body) : m.body}
                          </div>
                          {m.kind === "schedule_proposal" && Array.isArray(m.meta?.slots) ? (
                            <ul className="msg-slots" aria-label="提示した候補日">
                              {(m.meta?.slots as unknown[])
                                .filter((s): s is string => typeof s === "string")
                                .map((slot, si) => (
                                  <li key={`${si}-${slot}`}>{stripControlChars(slot)}</li>
                                ))}
                            </ul>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {scheduleVisible && !isClosed && !isVisiting ? (
                  <div className="schedule-propose" id="schedule-propose">
                    <div className="sp-head">
                      <CalendarIc />
                      引き取り候補日を提案する
                    </div>
                    <div className="sp-options">
                      {slots.map((slot, i) => {
                        const preview = slot.date && slot.time ? formatSlotLabel(slot.date, slot.time) : null;
                        return (
                          <div className="sp-opt-row" role="group" aria-label={`候補日 ${i + 1}`} key={i}>
                            <div className="sp-opt-head">
                              <input
                                type="date"
                                className="sp-date-input"
                                value={slot.date}
                                min={todayIso}
                                max={maxSlotDateIso}
                                onChange={(e) => updateSlotDate(i, e.target.value)}
                                aria-label={`候補日 ${i + 1} の日付`}
                              />
                              <button type="button" className="sp-remove" onClick={() => removeSlot(i)} aria-label={`候補日 ${i + 1} を削除`}>
                                <Ic name="x" />
                              </button>
                            </div>
                            <div className="sp-time-slots">
                              {VISIT_TIME_SLOTS.map((ts) => {
                                const isSelected = slot.time === ts.value;
                                // 業者向けだけ「時間指定なし」の小見出しを「時間は相談」に読み替える。
                                // VISIT_TIME_SLOTS.label 自体は依頼者側と共有のため変えない。
                                const sub = ts.value === "時間指定なし" ? "時間は相談" : ts.label;
                                return (
                                  <button
                                    type="button"
                                    key={ts.value}
                                    className={`sp-time-btn${isSelected ? " selected" : ""}`}
                                    aria-pressed={isSelected}
                                    onClick={() => updateSlotTime(i, ts.value)}
                                  >
                                    {ts.value}
                                    <span className="sp-time-sub">{sub}</span>
                                  </button>
                                );
                              })}
                            </div>
                            {preview ? (
                              <div className="sp-slot-preview">{preview}</div>
                            ) : (
                              <div className="sp-slot-preview sp-slot-preview-empty">
                                日付と時間帯を選ぶと、送信される候補がここに表示されます
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    <button type="button" className="btn-add-slot" onClick={addSlot} disabled={slots.length >= MAX_SLOT_DRAFTS}>
                      ＋ 候補日を追加
                    </button>
                    <button
                      type="button"
                      className="btn-send-schedule"
                      onClick={() => void handleSendSchedule()}
                      disabled={proposing}
                    >
                      {proposing ? "送信中…" : "候補日を送信する"}
                    </button>
                  </div>
                ) : null}
              </div>

              {/* 入力エリア（終了済み取引では非表示にし、終了案内のみ出す） */}
              {isClosed ? (
                <div className="input-area" style={{ color: "var(--body-soft)", fontSize: 13, padding: "12px 20px" }}>
                  この取引は終了しています
                </div>
              ) : (
                <div className="input-area">
                  <div className="input-tools">
                    <button
                      type="button"
                      className="tool-btn"
                      title="日程を提案"
                      aria-label="日程を提案"
                      onClick={toggleScheduleCard}
                      disabled={isVisiting}
                    >
                      <CalendarIc />
                    </button>
                  </div>
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
                    className={`btn-send${sending ? " is-sending" : ""}`}
                    aria-label={sending ? "送信中…" : "送信"}
                    aria-busy={sending}
                    disabled={!draft.trim() || sending}
                    onClick={() => void handleSend()}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true" className={sending ? "spinning" : undefined}>
                      <path d="M22 2L11 13" />
                      <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                    </svg>
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* 右パネル（出品内容） */}
        <aside className="detail-panel" aria-label="出品内容">
          <div className="dp-head">出品内容</div>
          <div className="dp-case-id">
            <div className="lbl">案件ID</div>
            <div className="val">{caseIdShort}</div>
          </div>
          <div className="dp-info">
            <div className="dp-row">
              <span className="lbl">エリア</span>
              <span className="val">
                {detail?.case?.prefecture} {detail?.case?.city}
              </span>
            </div>
            <div className="dp-row">
              <span className="lbl">合意額</span>
              <span className="val blue">{yen(detail?.final_amount ?? detail?.initial_amount ?? 0)}</span>
            </div>
            {/* 2026-09-18: 料率が未定のため、手数料予定額の行は一旦外した（ユーザー指示）。 */}
            <div className="dp-row">
              <span className="lbl">ステータス</span>
              <span className="val green">{statusLabel}</span>
            </div>
          </div>
          <button type="button" className="btn-propose" onClick={toggleScheduleCard} disabled={isClosed || isVisiting}>
            <CalendarIc />
            引き取り日程を提案
          </button>
        </aside>
      </div>

      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
