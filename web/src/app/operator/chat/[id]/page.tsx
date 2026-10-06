"use client";

/**
 * 業者 交渉チャット（/operator/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/業者チャット.html をピクセル忠実に再現。
 * これは業者(operator)側の画面。送信メッセージ（自社）は青バブルで右、相手（ユーザー）は白バブルで左。
 * 運営名義（system）のメッセージは中央寄せのお知らせ枠（components/kdz/ChatSystemNotice）。
 *
 * 動的ルート([id])。/operator は SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + 業者管理バッジ + 会社名 + 通知ベル）と全画面レイアウトを描く。
 *
 * [id] は transaction_id として扱う。サイドバー「交渉中の案件」は listTransactions（業者向け）。
 * メッセージは listMessages のポーリング（表示中5秒間隔・document.hidden 時は停止）+ sendMessage。
 * 日程提示は proposeSchedule に接続する（日程構造化 DESIGN §13.4: 候補は {date,start,end} で送り、
 * 表示ラベルはサーバーが作る。確定は依頼者が最新の提示から選ぶ）。
 */

import "./chat.css";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { ScheduleConfirmedBand } from "@/components/kdz/ScheduleConfirmedBand";
import { useToken } from "@/components/kdz/Ui";
import { ChatSystemNotice } from "@/components/kdz/ChatSystemNotice";
import { stripControlChars } from "@/lib/categories";
import { advanceCursor, appendNewMessages, cursorToAfterParam } from "@/lib/chat-cursor";
import { isSystemNotice } from "@/lib/chat-system-notice";
import { formatJstDateSeparator, formatJstDateTime, formatJstTime } from "@/lib/datetime";
import { isImeComposingKey, messageLengthState } from "@/lib/message-length";
import { MessageLengthCounter } from "@/components/kdz/MessageLengthCounter";
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
  SCHEDULE_ERROR_CODE,
  sendMessage,
  toDisplayMessage,
  type MessageOut,
  type ScheduleCandidateInput,
  type TransactionDetail,
  type TransactionListItem,
} from "@/lib/katadzuke-api";
import {
  CUSTOM_END_TIME_OPTIONS,
  CUSTOM_START_TIME_OPTIONS,
  DEFAULT_CUSTOM_END_TIME,
  DEFAULT_CUSTOM_START_TIME,
  VISIT_TIME_SLOTS,
  addDaysIso,
  findVisitTimeSlot,
  formatSlotLabel,
  formatVisitTime,
  isCandidateExpired,
  isValidIsoDate,
  isValidVisitTimeRange,
  jstTodayIso,
  latestProposalId,
  parseScheduleConfirmedMeta,
  parseScheduleProposalMeta,
  type ParsedScheduleProposal,
  type ScheduleCandidate,
  type VisitTimeSlotValue,
} from "@/lib/visit-slots";

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

// 時刻・日付区切りは lib/datetime.ts（時差情報のない API 日時は UTC として解釈し、日本時間で表示。V-02）。
const formatTime = formatJstTime;
const formatDateSep = formatJstDateSeparator;
function yen(n: number): string {
  return `¥${n.toLocaleString()}`;
}

/** 「時刻を指定」（30分刻みの開始・終了を選ぶ）を表す時間帯の選択値。 */
const CUSTOM_TIME_CHOICE = "custom";

/**
 * 候補日提案フォームの1行分の入力状態。
 * choice: 固定の時間帯（VISIT_TIME_SLOTS の value）／"custom"（時刻を指定）／null（未選択）。
 * customStart/customEnd: 「時刻を指定」の開始・終了（"HH:MM"。choice が "custom" のときだけ使う）。
 */
type SlotDraft = {
  date: string;
  choice: VisitTimeSlotValue | typeof CUSTOM_TIME_CHOICE | null;
  customStart: string;
  customEnd: string;
};

/** 候補日の提案件数の上限（「＋ 候補日を追加」を無効化する閾値。2026-09-26 ボタン化）。 */
const MAX_SLOT_DRAFTS = 10;

/**
 * 候補日入力の日付レンジ（日本時間の今日から何日後まで許可するか）。サーバーは今日+365日まで
 * 受け付けるが（日程構造化 DESIGN §13.1）、端末の時計のずれに備えて1日の余裕を残す。
 */
const MAX_SLOT_DATE_RANGE_DAYS = 364;

/** 空の入力行（「時刻を指定」の既定は 10:00〜12:00）。 */
function emptySlotDraft(): SlotDraft {
  return { date: "", choice: null, customStart: DEFAULT_CUSTOM_START_TIME, customEnd: DEFAULT_CUSTOM_END_TIME };
}

/** 入力行が初期状態（1行・日付も時間帯も未選択）のままか。最新の提示で初期入力してよいかの判定に使う。 */
function isPristineDrafts(drafts: SlotDraft[]): boolean {
  return drafts.length === 1 && drafts[0].date === "" && drafts[0].choice === null;
}

/** 入力行から送信する時刻（start/end）を求める。時間帯が未選択なら null。 */
function draftTimes(draft: SlotDraft): { start: string | null; end: string | null } | null {
  if (draft.choice === null) return null;
  if (draft.choice === CUSTOM_TIME_CHOICE) return { start: draft.customStart, end: draft.customEnd };
  const fixed = VISIT_TIME_SLOTS.find((slot) => slot.value === draft.choice);
  return fixed ? { start: fixed.start, end: fixed.end } : null;
}

/** 提示済みの候補から入力行を作る（固定の時間帯に一致すればそのボタン、それ以外は「時刻を指定」）。 */
function draftFromCandidate(candidate: ScheduleCandidate): SlotDraft {
  const fixed = findVisitTimeSlot(candidate.start, candidate.end);
  if (fixed) return { ...emptySlotDraft(), date: candidate.date, choice: fixed.value };
  return {
    date: candidate.date,
    choice: CUSTOM_TIME_CHOICE,
    customStart: candidate.start ?? DEFAULT_CUSTOM_START_TIME,
    customEnd: candidate.end ?? DEFAULT_CUSTOM_END_TIME,
  };
}

export default function OperatorChatPage() {
  const params = useParams<{ id: string }>();
  const transactionId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const router = useRouter();
  const { token, loading: tokenLoading } = useToken();
  const { data: sessionData } = useSession();
  /** 運営が業者の画面を代理で開いているか（送信欄を使えなくする。backend の 403 は最終防衛）。 */
  const isAdminViewing = sessionData?.role === "admin";

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
  const [slots, setSlots] = useState<SlotDraft[]>(() => [emptySlotDraft()]);
  const [scheduleVisible, setScheduleVisible] = useState(false);
  const [proposing, setProposing] = useState(false);
  // 開いたままの古い画面と判定された（422 schedule_client_outdated）ときだけ「再読み込み」を出す。
  const [proposeOutdated, setProposeOutdated] = useState(false);
  // 候補日入力の日付レンジ（日本時間の今日から364日後まで）。画面を開いたまま日付をまたぐと
  // min/max が古いままになり過去日を選べてしまうため、useMemo でキャッシュせず
  // 描画のたびに new Date() から求める（送信時のバリデーションは handleSendSchedule
  // 内で改めて計算し直す。こちらは <input type="date"> の min/max・当日の終わった枠の表示専用）。
  const now = new Date();
  const todayIso = jstTodayIso(now);
  const maxSlotDateIso = addDaysIso(todayIso, MAX_SLOT_DATE_RANGE_DAYS);

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
        // after は保持カーソルの 5 秒手前（同秒・自分の送信との前後による取りこぼしを避ける。QA M2）。
        // 重なって返った分は id で重複排除する。
        const after = initial ? undefined : cursorToAfterParam(lastFetchedAtRef.current);
        const batch = await listMessages(transactionId, token, after);
        if (batch.length > 0) {
          // カーソルは「取得したメッセージの最大 created_at」だけで進める（自分の送信・提示では進めない）。
          lastFetchedAtRef.current = advanceCursor(initial ? undefined : lastFetchedAtRef.current, batch);
          setMessages((prev) => (initial ? batch : [...appendNewMessages(prev, batch)]));
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

  /* ---- 最新の提示（seq が最大の v2。依頼者が確定できるのはこの提示の候補だけ） ---- */
  const latestId = useMemo(() => latestProposalId(messages), [messages]);
  const latestCandidates = useMemo(() => {
    const latest = latestId ? messages.find((m) => m.id === latestId) : undefined;
    const parsed = latest ? parseScheduleProposalMeta(latest.meta) : null;
    return parsed?.version === 2 ? parsed.candidates : [];
  }, [messages, latestId]);

  function selectTransaction(id: string) {
    if (id === transactionId) return;
    router.push(`/operator/chat/${id}`);
  }

  async function handleSend() {
    const text = draft.trim();
    if (isAdminViewing || !text || !token || !transactionId || sending) return;
    // 上限超過は送信前に止める（理由は入力欄の下のカウンタに出ている。V-05）。
    if (messageLengthState(text).over) return;
    setSending(true);
    try {
      const sent = await sendMessage(transactionId, text, token);
      // 楽観的に一覧へ足すだけ。差分取得のカーソルは進めない（QA M2）。
      setMessages((prev) => [...appendNewMessages(prev, [sent])]);
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
  function updateSlotChoice(i: number, value: SlotDraft["choice"]) {
    setSlots((prev) => prev.map((s, idx) => (idx === i ? { ...s, choice: value } : s)));
  }
  function updateSlotCustomTime(i: number, field: "customStart" | "customEnd", value: string) {
    setSlots((prev) => prev.map((s, idx) => (idx === i ? { ...s, [field]: value } : s)));
  }
  function removeSlot(i: number) {
    setSlots((prev) => prev.filter((_, idx) => idx !== i));
  }
  function addSlot() {
    setSlots((prev) => (prev.length >= MAX_SLOT_DRAFTS ? prev : [...prev, emptySlotDraft()]));
  }
  function toggleScheduleCard() {
    // ボタン自体を disabled にしているが、万一の誤発火に備えて関数側でも防ぐ
    // （訪問日程が確定済みの取引では新しい候補日を提示させない）。
    if (isVisiting) return;
    const next = !scheduleVisible;
    if (next) {
      // 日程構造化 DESIGN §13.4: 最新の提示があれば、そのうち過ぎていない候補を最初から入れておく
      // （入力途中の行があればそれを優先し、上書きしない）。
      const openedAt = new Date();
      const prefill = latestCandidates
        .filter((candidate) => !isCandidateExpired(candidate, openedAt))
        .slice(0, MAX_SLOT_DRAFTS)
        .map(draftFromCandidate);
      if (prefill.length > 0 && isPristineDrafts(slots)) setSlots(prefill);
      window.setTimeout(() => {
        document.getElementById("schedule-propose")?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 0);
    }
    setScheduleVisible(next);
  }
  async function handleSendSchedule() {
    // 未完成行（日付・時間帯のどちらかが未選択）が1つでもあれば送信させない。
    // 初期状態の1行だけ空のまま送信した場合もここに含まれる（従来の「候補日を
    // 1つ以上入力してください」に相当）。
    if (slots.length === 0 || slots.some((s) => !s.date || s.choice === null)) {
      showToast("候補日の日付と時間帯を選んでください");
      return;
    }
    // iOS は <input type="date"> の min/max 属性を強制しないため、送信時にも検査する。
    // 画面を開いたまま日付をまたいだ場合に備え、描画時の todayIso/maxSlotDateIso ではなく
    // 送信ボタンを押した瞬間の日本時間で改めて求めた値と比較する。
    const submitNow = new Date();
    const submitTodayIso = jstTodayIso(submitNow);
    const submitMaxSlotDateIso = addDaysIso(submitTodayIso, MAX_SLOT_DATE_RANGE_DAYS);
    if (slots.some((s) => !isValidIsoDate(s.date) || s.date < submitTodayIso || s.date > submitMaxSlotDateIso)) {
      showToast("候補日は本日から1年以内の日付を選んでください");
      return;
    }
    const candidates: ScheduleCandidateInput[] = [];
    for (const s of slots) {
      const times = draftTimes(s);
      if (!times) {
        showToast("候補日の日付と時間帯を選んでください");
        return;
      }
      candidates.push({ date: s.date, start: times.start, end: times.end });
    }
    if (candidates.some((c) => !isValidVisitTimeRange(c.start, c.end))) {
      showToast("時刻は6:00〜22:00の間で、終了を開始の1時間以上あとにしてください");
      return;
    }
    if (candidates.some((c) => isCandidateExpired(c, submitNow))) {
      showToast("終わった時間帯は候補にできません");
      return;
    }
    if (!token || !transactionId || proposing) return;
    // 同じ日付・同じ時間帯の重複行は、順序を保って date|start|end で重複除去する（Set は挿入順を保持する）。
    const seenKeys = new Set<string>();
    const uniqueCandidates = candidates.filter((c) => {
      const key = `${c.date}|${c.start}|${c.end}`;
      if (seenKeys.has(key)) return false;
      seenKeys.add(key);
      return true;
    });
    setProposing(true);
    try {
      const msg = await proposeSchedule(transactionId, uniqueCandidates, token);
      setMessages((prev) => [...appendNewMessages(prev, [msg])]);
      setScheduleVisible(false);
      setSlots([emptySlotDraft()]);
      setProposeOutdated(false);
      showToast("候補日を送信しました");
    } catch (e) {
      showToast(toDisplayMessage(e, "候補日の送信に失敗しました"));
      // r8-fix-frontend2 H3 是正: 409 transaction_closed（取引終了後の候補日提案）を
      // 受けた場合、detail を再取得して終了バナー・提案ボタンの無効化に反映させる。
      if (e instanceof KdzApiError && e.status === 409) await reloadDetail();
      if (e instanceof KdzApiError && e.code === SCHEDULE_ERROR_CODE.outdated) setProposeOutdated(true);
    } finally {
      setProposing(false);
    }
  }

  /**
   * 送信済みの提示（自社の schedule_proposal）の候補一覧（日程構造化 DESIGN §13.4）。
   * v2 はサーバーが作ったラベル、v1 は制御文字を除去した旧形式の文字列を出す。
   * 依頼者が確定できる最新の提示に「（最新）」を付け、それ以前（v1 を含む）は灰色にする。
   */
  function renderSentProposal(messageId: string, proposal: ParsedScheduleProposal) {
    const isLatest = proposal.version === 2 && messageId === latestId;
    const captionId = `msg-slots-caption-${messageId}`;
    const labels =
      proposal.version === 2
        ? proposal.candidates.map((c) => stripControlChars(c.label))
        : proposal.version === 1
          ? proposal.slots.map(stripControlChars).filter((label) => label !== "")
          : [];
    return (
      <div className={`msg-slots-wrap${isLatest ? " is-latest" : " is-stale"}`}>
        <div className="msg-slots-caption" id={captionId}>
          提示した候補日{isLatest ? "（最新）" : ""}
        </div>
        {labels.length > 0 ? (
          <ul className="msg-slots" aria-labelledby={captionId}>
            {labels.map((label, si) => (
              <li key={si}>{label}</li>
            ))}
          </ul>
        ) : (
          <div className="msg-slots-empty">候補日を表示できません</div>
        )}
      </div>
    );
  }

  // 入力中の本文の文字数状態（上限超過なら送信ボタンを無効化し、カウンタに理由を出す）。
  const draftLength = messageLengthState(draft);
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
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>成約済みの案件はありません</div>
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
                  <div className="peer-name">依頼者</div>
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
                  {formatJstDateTime(detail.cancellation.cancelled_at)}）
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
                    まずは「引き取り日程を提案」から依頼者に候補日を送りましょう。
                    {!isVisiting ? (
                      <button type="button" className="ch-empty-action" onClick={toggleScheduleCard}>
                        <CalendarIc />
                        引き取り日程を提案
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {messages.map((m, i) => {
                  const showDateSep = i === 0 || formatDateSep(m.created_at) !== formatDateSep(messages[i - 1].created_at);
                  if (m.kind === "schedule_confirmed" && parseScheduleConfirmedMeta(m.meta).version === 2) {
                    // 日程構造化 DESIGN §13.4: v2 の確定は「訪問日程が確定しました」の帯で出す（旧形式は下のお知らせ枠）。
                    return (
                      <div key={m.id}>
                        {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                        <ScheduleConfirmedBand body={m.body} meta={m.meta} />
                      </div>
                    );
                  }
                  return (
                    <div key={m.id}>
                      {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                      {/* 運営名義（system）は吹き出しではなく中央寄せのお知らせ枠で出し、お客様の発言
                          （左の吹き出し）と形で区別する（日程検証レビュー SEC-I8）。制御文字の除去と
                          日程確定（旧形式）の「業者が提示した候補」の別枠は ChatSystemNotice が行う。
                          日程確定（v2）は上の帯（ScheduleConfirmedBand）で出す。依頼者・業者の
                          通常メッセージは絵文字の結合（ZWJ）等を壊さないよう本文を変えない。 */}
                      {isSystemNotice(m) ? (
                        <ChatSystemNotice message={m} time={formatTime(m.created_at)} />
                      ) : (
                        <div className={`msg ${m.mine ? "me" : "them"}`}>
                          <div className="msg-avatar">{m.mine ? "自" : peerInitial}</div>
                          <div>
                            <div className="msg-time">{formatTime(m.created_at)}</div>
                            <div className="bubble">{m.body}</div>
                            {m.kind === "schedule_proposal" ? renderSentProposal(m.id, parseScheduleProposalMeta(m.meta)) : null}
                          </div>
                        </div>
                      )}
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
                        const times = draftTimes(slot);
                        const rangeValid = times ? isValidVisitTimeRange(times.start, times.end) : false;
                        const dateOutOfRange = slot.date !== "" && (slot.date < todayIso || slot.date > maxSlotDateIso);
                        const slotExpired =
                          slot.date !== "" && times !== null && rangeValid && isCandidateExpired({ date: slot.date, end: times.end }, now);
                        // 行ごとの注意（送信時の検査と同じ順）。無ければプレビュー（formatSlotLabel）を出す。
                        const rowHint = dateOutOfRange
                          ? "候補日は本日から1年以内の日付を選んでください"
                          : times && !rangeValid
                            ? "終了は開始の1時間以上あとにしてください"
                            : slotExpired
                              ? "終わった時間帯は候補にできません"
                              : null;
                        const preview = !rowHint && slot.date && times ? formatSlotLabel(slot.date, times.start, times.end) : "";
                        const isCustom = slot.choice === CUSTOM_TIME_CHOICE;
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
                                const isSelected = slot.choice === ts.value;
                                // 業者向けだけ「時間指定なし」の小見出しを「時間は相談」に読み替える。
                                // VISIT_TIME_SLOTS.label 自体は依頼者側と共有のため変えない。
                                const sub = ts.value === "時間指定なし" ? "時間は相談" : ts.label;
                                // 日程構造化 DESIGN §13.4: 当日の終わった枠は選べない（日本時間で判定）。
                                const isOver = slot.date !== "" && isCandidateExpired({ date: slot.date, end: ts.end }, now);
                                return (
                                  <button
                                    type="button"
                                    key={ts.value}
                                    className={`sp-time-btn${isSelected ? " selected" : ""}`}
                                    aria-pressed={isSelected}
                                    disabled={isOver}
                                    onClick={() => updateSlotChoice(i, ts.value)}
                                  >
                                    {ts.value}
                                    <span className="sp-time-sub">{sub}</span>
                                  </button>
                                );
                              })}
                              <button
                                type="button"
                                className={`sp-time-btn${isCustom ? " selected" : ""}`}
                                aria-pressed={isCustom}
                                onClick={() => updateSlotChoice(i, CUSTOM_TIME_CHOICE)}
                              >
                                時刻を指定
                                <span className="sp-time-sub">30分刻み</span>
                              </button>
                            </div>
                            {isCustom ? (
                              <div className="sp-custom-time">
                                <label className="sp-custom-field">
                                  <span className="sp-custom-label">開始</span>
                                  <select
                                    className="sp-time-select"
                                    value={slot.customStart}
                                    onChange={(e) => updateSlotCustomTime(i, "customStart", e.target.value)}
                                    aria-label={`候補日 ${i + 1} の開始時刻`}
                                  >
                                    {CUSTOM_START_TIME_OPTIONS.map((time) => (
                                      <option key={time} value={time}>
                                        {formatVisitTime(time)}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <span className="sp-custom-sep" aria-hidden="true">
                                  〜
                                </span>
                                <label className="sp-custom-field">
                                  <span className="sp-custom-label">終了</span>
                                  <select
                                    className="sp-time-select"
                                    value={slot.customEnd}
                                    onChange={(e) => updateSlotCustomTime(i, "customEnd", e.target.value)}
                                    aria-label={`候補日 ${i + 1} の終了時刻`}
                                  >
                                    {CUSTOM_END_TIME_OPTIONS.map((time) => (
                                      <option
                                        key={time}
                                        value={time}
                                        disabled={slot.date !== "" && isCandidateExpired({ date: slot.date, end: time }, now)}
                                      >
                                        {formatVisitTime(time)}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              </div>
                            ) : null}
                            <div
                              className={`sp-slot-preview${rowHint ? " sp-slot-preview-error" : preview ? "" : " sp-slot-preview-empty"}`}
                              aria-live="polite"
                            >
                              {rowHint ?? (preview || "日付と時間帯を選ぶと、送信される候補がここに表示されます")}
                            </div>
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
                    {latestId ? (
                      <p className="sp-supersede-note">新しく送ると、前に送った候補は選べなくなります。</p>
                    ) : null}
                    {proposeOutdated ? (
                      <button type="button" className="btn-add-slot sp-reload" onClick={() => window.location.reload()}>
                        ページを再読み込みする
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {/* 入力エリア（終了済み取引では非表示にし、終了案内のみ出す） */}
              {isClosed ? (
                <div className="input-area" style={{ color: "var(--body-soft)", fontSize: 13, padding: "12px 20px" }}>
                  この取引は終了しています
                </div>
              ) : isAdminViewing ? (
                <div
                  className="input-area"
                  role="note"
                  data-testid="chat-read-only"
                  style={{ color: "var(--body-soft)", fontSize: 13, padding: "12px 20px" }}
                >
                  運営は代理で送信できません
                </div>
              ) : (
                <div className="input-area">
                  <div className="input-tools">
                    <button
                      type="button"
                      className="tool-btn"
                      onClick={toggleScheduleCard}
                      disabled={isVisiting}
                    >
                      <CalendarIc />
                      <span className="tool-btn-label">引き取り日程を提案</span>
                    </button>
                  </div>
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
                    className={`btn-send${sending ? " is-sending" : ""}`}
                    aria-label={sending ? "送信中…" : "送信"}
                    aria-busy={sending}
                    disabled={!draft.trim() || sending || draftLength.over}
                    onClick={() => void handleSend()}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true" className={sending ? "spinning" : undefined}>
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
