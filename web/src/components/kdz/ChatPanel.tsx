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
 *
 * 日程の確定（日程構造化 DESIGN §13.4）: 業者の最新の提示（meta v2 の seq が最大のもの）だけ、
 * 候補ごとの「{label} で確定」ボタン → ConfirmModal → accept API で確定する。
 * ラベルを解析して confirm API に送る旧来の確定（handleConfirmSchedule）は撤去した。
 */

import "@/app/chat/[id]/chat.css";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ConfirmModal } from "@/components/kdz/ConfirmModal";
import { ScheduleConfirmedBand } from "@/components/kdz/ScheduleConfirmedBand";
import { useToken } from "@/components/kdz/Ui";
import { ChatSystemNotice } from "@/components/kdz/ChatSystemNotice";
import { stripControlChars } from "@/lib/categories";
import { isSystemNotice } from "@/lib/chat-system-notice";
import { formatJstDateSeparator, formatJstDateTime, formatJstTime } from "@/lib/datetime";
import { isImeComposingKey, messageLengthState } from "@/lib/message-length";
import { MessageLengthCounter } from "@/components/kdz/MessageLengthCounter";
import {
  acceptScheduleCandidate,
  CANCELLED_BY_LABEL,
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
import {
  isCandidateExpired,
  latestProposalId,
  parseScheduleConfirmedMeta,
  parseScheduleProposalMeta,
  type ParsedScheduleProposal,
} from "@/lib/visit-slots";

const POLL_INTERVAL_MS = 5000;

// 時刻・日付区切りは lib/datetime.ts（時差情報のない API 日時は UTC として解釈し、日本時間で表示）。
const formatTime = formatJstTime;
const formatDateSep = formatJstDateSeparator;

/* ---- カレンダー線画（スプライト未収録のため inline。絵文字は使わない） ---- */
function CalendarIc({ className }: { className?: string }) {
  return (
    <svg className={`ic${className ? ` ${className}` : ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 9h16M8 3v4M16 3v4" />
    </svg>
  );
}

/** 確認モーダルで確定しようとしている候補（提示メッセージの id・候補の添字・表示ラベル）。 */
type AcceptTarget = { proposalId: string; candidateIndex: number; label: string };

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

  /* ---- 日程確定操作の状態（日程構造化 DESIGN §13.4: 候補ごとのボタン＋確認モーダル） ---- */
  const [acceptTarget, setAcceptTarget] = useState<AcceptTarget | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  // 409（新しい提示・過ぎた候補・状態の変化）等で確定できなかった理由。モーダルを閉じた後も読めるよう残す。
  const [scheduleNotice, setScheduleNotice] = useState<string | null>(null);

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
          // 確定後・409 後の全件取り直しとポーリングの差分取得が重なっても、同じメッセージを二重に並べない。
          setMessages((prev) => {
            if (initial) return batch;
            const knownIds = new Set(prev.map((m) => m.id));
            const fresh = batch.filter((m) => !knownIds.has(m.id));
            return fresh.length > 0 ? [...prev, ...fresh] : prev;
          });
          // 日程調整ページ・運営の代理など別の経路で日程が確定した場合も、候補の確定ボタンが
          // 押せるまま残らないよう取引を取り直す（初回の全件取得は reloadDetail の effect が別に取る）。
          if (!initial && batch.some((m) => m.kind === "schedule_confirmed")) {
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

  /* ---- 確定できる「最新の提示」（seq が最大の v2。サーバーの superseded 判定と同じ定義） ---- */
  const latestId = useMemo(() => latestProposalId(messages), [messages]);

  async function handleSend() {
    const text = draft.trim();
    if (!text || !token || !transactionId || sending) return;
    // 上限超過は送信前に止める（理由は入力欄の下のカウンタに出ている。V-05）。
    if (messageLengthState(text).over) return;
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

  function openAcceptModal(target: AcceptTarget) {
    setAcceptError(null);
    setScheduleNotice(null);
    setAcceptTarget(target);
  }

  function closeAcceptModal() {
    setAcceptTarget(null);
    setAcceptError(null);
  }

  /**
   * 確認モーダルで「確定する」を押したときの処理（日程構造化 DESIGN §13.4）。
   * 成功したら取引とメッセージを取り直して「訪問日程が確定しました」の帯を出す。
   * 409（schedule_proposal_superseded・schedule_candidate_expired・pending 以外）・404（提示が無い）・
   * 422（schedule_proposal_legacy・添字の範囲外）は同じ候補では二度と確定できないため、モーダルを閉じて
   * サーバーの理由を出し、メッセージ（全件）と取引を取り直す。全件にするのは、created_at が
   * 前後して差分取得で取りこぼした新しい提示も確実に拾うため。
   * それ以外（通信失敗・5xx・429 等）はモーダル内にエラーを出し、そのまま再試行できるようにする。
   */
  async function handleAccept() {
    if (!acceptTarget || !token || !transactionId || accepting) return;
    setAccepting(true);
    setAcceptError(null);
    try {
      await acceptScheduleCandidate(transactionId, acceptTarget.proposalId, acceptTarget.candidateIndex, token);
      setAcceptTarget(null);
      setScheduleNotice(null);
      showToast("日程を確定しました");
      await Promise.all([reloadDetail(), fetchMessages(true)]);
    } catch (e) {
      const message = toDisplayMessage(e, "日程の確定に失敗しました");
      if (e instanceof KdzApiError && (e.status === 409 || e.status === 404 || e.status === 422)) {
        setAcceptTarget(null);
        setScheduleNotice(message);
        await Promise.all([reloadDetail(), fetchMessages(true)]);
      } else {
        setAcceptError(message);
      }
    } finally {
      setAccepting(false);
    }
  }

  // 入力中の本文の文字数状態（上限超過なら送信ボタンを無効化し、カウンタに理由を出す）。
  const draftLength = messageLengthState(draft);
  const biz = detail?.operator ?? null;
  const bizInitial = biz?.company_name?.charAt(0) ?? "業";
  // r8-fix-frontend2 H3 是正: キャンセル済み・完了済みの取引ではチャットの続行操作
  // （送信・日程提案の確定）を無効化し、事実に即した終了表示に切り替える。
  const isClosed = detail?.status === "cancelled" || detail?.status === "completed";
  // r8-fix-frontend5 対応: 落札業者が退会済みの場合、送信・日程確定に進めないよう無効化する。
  const operatorDeleted = detail?.operator_deleted === true;
  // 候補から確定できるのは pending（訪問日調整中）の取引だけ（backend も pending 以外は 409）。
  const canAcceptSchedule = detail?.status === "pending" && !operatorDeleted;
  // 確定できない状態のときに最新の候補カードへ出す理由（旧: 確定ボタンの文言）。
  const scheduleClosedNote = operatorDeleted
    ? "業者退会のため確定できません"
    : isClosed && detail
      ? `この取引は終了しています（${TXN_STATUS_LABEL[detail.status]}）`
      : "日程確定済み";
  const scheduleHref = `/schedule?transaction_id=${encodeURIComponent(transactionId)}`;
  // 過ぎた候補の判定（日本時間）は描画のたびに今の時刻で行う（確定時はサーバーが改めて判定する）。
  const now = new Date();

  /** 候補を文字だけで並べる（確定できない提示・置き換わった提示・旧形式の提示用）。 */
  function renderCandidateTexts(labels: string[]) {
    return (
      <ul className="schedule-cand-texts">
        {labels.map((label, li) => (
          <li key={li}>{label}</li>
        ))}
      </ul>
    );
  }

  /** 1件の schedule_proposal の候補カード本体を、版と状態ごとに描き分ける（日程構造化 DESIGN §13.4）。 */
  function renderProposalBody(message: MessageOut, proposal: ParsedScheduleProposal) {
    if (proposal.version === 2) {
      const labels = proposal.candidates.map((c) => stripControlChars(c.label));
      if (message.id !== latestId) {
        return (
          <>
            {renderCandidateTexts(labels)}
            <p className="schedule-card-note">新しい候補が届いています</p>
          </>
        );
      }
      if (!canAcceptSchedule) {
        return (
          <>
            {renderCandidateTexts(labels)}
            <p className="schedule-card-note">{scheduleClosedNote}</p>
          </>
        );
      }
      return (
        <>
          <ul className="schedule-cands">
            {proposal.candidates.map((candidate, ci) => {
              const label = labels[ci];
              const expired = isCandidateExpired(candidate, now);
              const noteId = `schedule-cand-note-${message.id}-${ci}`;
              return (
                <li className="schedule-cand" key={ci}>
                  <button
                    type="button"
                    className="btn-schedule-cand"
                    disabled={expired}
                    aria-describedby={expired ? noteId : undefined}
                    onClick={() => openAcceptModal({ proposalId: message.id, candidateIndex: ci, label })}
                  >
                    {label} で確定
                  </button>
                  {expired ? (
                    <span className="schedule-cand-note" id={noteId}>
                      過ぎた候補です
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <Link href={scheduleHref} className="schedule-card-link">
            どれも合わない場合は日程調整ページで選ぶ
          </Link>
        </>
      );
    }
    // 旧形式（v1: 業者の自由記述）・未知の版はチャットから確定できない（accept は 422 legacy）。
    // 文字だけ（制御文字を除去）を出し、確定は日程調整ページへ案内する。
    const legacyLabels =
      proposal.version === 1 ? proposal.slots.map(stripControlChars).filter((label) => label !== "") : [];
    return (
      <>
        {legacyLabels.length > 0 ? (
          renderCandidateTexts(legacyLabels)
        ) : (
          <p className="schedule-card-note">この候補日はここでは表示できません。</p>
        )}
        {canAcceptSchedule ? (
          <Link href={scheduleHref} className="schedule-card-link">
            日程調整ページで選ぶ
          </Link>
        ) : (
          <p className="schedule-card-note">{scheduleClosedNote}</p>
        )}
      </>
    );
  }

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
                    {formatJstDateTime(detail.cancellation.cancelled_at)}
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

          {/* 候補から確定できなかった理由（新しい提示が届いた・候補が過ぎた等。サーバーの文言をそのまま出す）。 */}
          {scheduleNotice ? (
            <div className="schedule-notice" role="alert">
              {scheduleNotice}
            </div>
          ) : null}

          {/* メッセージ */}
          <div className="messages-area" ref={messagesRef} role="log" aria-live="polite" aria-relevant="additions">
            {messages.map((m, i) => {
              const showDateSep = i === 0 || formatDateSep(m.created_at) !== formatDateSep(messages[i - 1].created_at);
              // 運営名義（system）は吹き出しではなく中央寄せのお知らせ枠で出し、業者・自分の発言
              // （左右の吹き出し）と形で区別する（日程検証レビュー SEC-I8）。制御文字の除去
              // （SEC-L5）と日程確定の「業者が提示した候補」の別枠（SEC-L1）は ChatSystemNotice が行う。
              // 依頼者・業者の通常メッセージは絵文字の結合（ZWJ）等を壊さないよう本文を変えない。
              // 日程確定（v2）は日程構造化 DESIGN §13.4 の「訪問日程が確定しました」の帯で出す
              // （サーバーが作った meta.label だけを出す）。旧形式の日程確定は運営名義のお知らせ枠のまま
              // （2026-09-27 より前の本文と、業者の候補を別枠で出す operator_slot_label を保つ）。
              if (m.kind === "schedule_confirmed" && parseScheduleConfirmedMeta(m.meta).version === 2) {
                return (
                  <div key={m.id}>
                    {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                    <ScheduleConfirmedBand body={m.body} meta={m.meta} />
                  </div>
                );
              }
              if (isSystemNotice(m)) {
                return (
                  <div key={m.id}>
                    {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                    <ChatSystemNotice message={m} time={formatTime(m.created_at)} />
                  </div>
                );
              }
              if (m.kind === "schedule_proposal") {
                const proposal = parseScheduleProposalMeta(m.meta);
                // 灰色にするのは新しい提示に置き換わった v2 だけ（v1・unknown は日程調整ページへの案内を出す）。
                const isStale = proposal.version === 2 && m.id !== latestId;
                const headId = `schedule-card-head-${m.id}`;
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
                    <div
                      className={`schedule-card${isStale ? " is-stale" : ""}`}
                      id={`schedule-card-${m.id}`}
                      role="group"
                      aria-labelledby={headId}
                    >
                      <div className="schedule-card-head" id={headId}>
                        <CalendarIc />
                        引き取り候補日
                      </div>
                      {renderProposalBody(m, proposal)}
                    </div>
                  </div>
                );
              }
              return (
                <div key={m.id}>
                  {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                  <div className={`msg ${m.mine ? "me" : "them"}`}>
                    <div className="msg-avatar">{m.mine ? "自" : bizInitial}</div>
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
                  // 日本語入力の変換確定の Enter では送信しない（seller H-1）。Enter 送信自体は維持。
                  if (e.key === "Enter" && !e.shiftKey && !isImeComposingKey(e)) {
                    e.preventDefault();
                    void handleSend();
                  }
                }}
                aria-label="メッセージを入力"
                aria-describedby={`chat-length-${transactionId}`}
                aria-invalid={draftLength.over || undefined}
                disabled={sending}
              />
              <button
                type="button"
                className="btn-send"
                aria-label="送信"
                disabled={!draft.trim() || sending || draftLength.over}
                onClick={() => void handleSend()}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M22 2L11 13" />
                  <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                </svg>
              </button>
              <MessageLengthCounter id={`chat-length-${transactionId}`} text={draft} />
            </div>
          )}
        </>
      )}
    </div>
  );

  /* ---- 画面の上に重ねる要素（トースト・日程確定の確認モーダル） ---- */
  // 確認モーダル（position: fixed）は document.body へポータルで描く。embedded 時は案件詳細の
  // 表示アニメーション（transform）を持つ祖先の中に入りうるため、その箱に閉じ込められないようにする。
  // acceptTarget はボタン操作でしか立たない（サーバー描画では常に null）ため document を参照してよい。
  const overlays = (
    <>
      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
      {acceptTarget
        ? createPortal(
            <ConfirmModal
              title="訪問日程を確定しますか？"
              message={`${acceptTarget.label} で確定しますか？確定すると業者に通知され、変更はメッセージでの相談になります。`}
              confirmLabel="確定する"
              cancelLabel="やめる"
              busy={accepting}
              error={acceptError}
              onCancel={closeAcceptModal}
              onConfirm={() => void handleAccept()}
            />,
            document.body,
          )
        : null}
    </>
  );

  if (variant === "embedded") {
    return (
      <div className={`chat-page chat-embed-panel${className ? ` ${className}` : ""}`}>
        {mainContent}
        {overlays}
      </div>
    );
  }

  return (
    <>
      {mainContent}
      {overlays}
    </>
  );
}
