"use client";

import "./schedule.css";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { AppHeader } from "@/components/kdz/AppHeader";
import { useToken } from "@/components/kdz/Ui";
import {
  confirmSchedule,
  getTransaction,
  listMessages,
  listTransactions,
  toDisplayMessage,
  type MessageOut,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

/* ============================================================
   訪問日程調整ページ（カタヅケ）
   ?transaction_id= で対象成約を指定。未指定時は自分の成約一覧から
   「訪問日調整中（pending）」の最初の1件を自動選択する。
   カレンダー選択 + 時間帯選択で confirmSchedule を実送信する。
   業者が propose_schedule で提示した候補（チャット由来）があれば
   優先候補として表示するが、無くても任意の未来日を選べる。
   ============================================================ */

/** 進捗ステップ（出品→入札・交渉→日程調整→訪問・完了）。今回は「日程調整」がactive。 */
const PROGRESS_STEPS = [
  { state: "done" as const, label: "出品" },
  { state: "done" as const, label: "入札・交渉" },
  { state: "active" as const, label: "日程調整" },
  { state: "todo" as const, label: "訪問・完了" },
];

/** 希望時間帯。 */
const TIME_SLOTS: { value: string; label: string }[] = [
  { value: "9:00〜12:00", label: "午前" },
  { value: "12:00〜15:00", label: "昼" },
  { value: "15:00〜18:00", label: "午後" },
  { value: "18:00〜21:00", label: "夜" },
  { value: "時間指定なし", label: "業者に一任" },
];

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"];

type SelectedDate = { key: string; label: string; year: number; month: number; day: number };

/** 数値を `1,234` 形式に整形（円表示用）。 */
const yen = (n: number) => n.toLocaleString();

/** 業者が propose_schedule で提示した候補日文字列から日付を抽出（例: "7月5日（土）10:00〜12:00"）。 */
function parseSlotDate(slot: string): { month: number; day: number } | null {
  const m = slot.match(/(\d{1,2})月(\d{1,2})日/);
  if (!m) return null;
  const month = Number(m[1]);
  const day = Number(m[2]);
  if (!Number.isInteger(month) || !Number.isInteger(day) || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }
  return { month, day };
}

export default function SchedulePage() {
  return (
    <Suspense
      fallback={
        <div className="schedule-page">
          <AppHeader unread />
          <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>読み込み中…</div>
        </div>
      }
    >
      <SchedulePageInner />
    </Suspense>
  );
}

function SchedulePageInner() {
  const searchParams = useSearchParams();
  const requestedTxnId = searchParams.get("transaction_id");
  const { token, loading: tokenLoading } = useToken();

  const [transactionId, setTransactionId] = useState<string | null>(requestedTxnId);
  const [detail, setDetail] = useState<TransactionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [proposedSlots, setProposedSlots] = useState<string[]>([]);

  /* ---- transaction_id 未指定時: pending状態の取引を自動選択 ---- */
  useEffect(() => {
    if (!token || requestedTxnId) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listTransactions(token);
        const pending = list.find((t) => t.status === "pending");
        if (!cancelled) {
          if (pending) setTransactionId(pending.id);
          else {
            setLoadError("日程調整が必要な成約が見つかりません。");
            setLoading(false);
          }
        }
      } catch (e) {
        if (!cancelled) {
          setLoadError(toDisplayMessage(e, "成約情報の取得に失敗しました"));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, requestedTxnId]);

  /* ---- 成約詳細 + 業者提示済み候補日（チャットの schedule_proposal から抽出） ---- */
  const load = useCallback(async () => {
    if (!token || !transactionId) return;
    setLoading(true);
    try {
      const d = await getTransaction(transactionId, token);
      setDetail(d);
      setLoadError(null);

      let messages: MessageOut[] = [];
      try {
        messages = await listMessages(transactionId, token);
      } catch {
        /* 候補日の補助表示に過ぎないため、取得失敗しても致命的ではない */
      }
      const latestProposal = [...messages].reverse().find((m) => m.kind === "schedule_proposal");
      const slots = Array.isArray(latestProposal?.meta?.slots) ? (latestProposal?.meta?.slots as string[]) : [];
      setProposedSlots(slots);
    } catch (e) {
      setLoadError(toDisplayMessage(e, "成約情報の取得に失敗しました"));
    } finally {
      setLoading(false);
    }
  }, [token, transactionId]);

  useEffect(() => {
    void load();
  }, [load]);

  /* ---- カレンダー表示月（今日を含む月から開始） ---- */
  const today = useMemo(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }, []);
  const [viewYear, setViewYear] = useState(() => today.getFullYear());
  const [viewMonth, setViewMonth] = useState(() => today.getMonth());

  /* ---- 業者提示候補日のハイライト用セット ---- */
  const proposedDayKeys = useMemo(() => {
    const set = new Set<string>();
    for (const slot of proposedSlots) {
      const parsed = parseSlotDate(slot);
      if (!parsed) continue;
      let year = today.getFullYear();
      const candidate = new Date(year, parsed.month - 1, parsed.day);
      if (candidate < today) year += 1;
      set.add(`${year}-${parsed.month}-${parsed.day}`);
    }
    return set;
  }, [proposedSlots, today]);

  /* ---- 選択状態 ---- */
  const [selectedDate, setSelectedDate] = useState<SelectedDate | null>(null);
  const [selectedTime, setSelectedTime] = useState<string | null>(null);
  const [note, setNote] = useState("");

  /* ---- 送信状態 ---- */
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  /** 表示月のセル配列（先頭の空白＋各日）を算出。 */
  const cells = useMemo(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const firstDow = first.getDay();
    const lastDay = new Date(viewYear, viewMonth + 1, 0).getDate();

    const out: {
      key: string | null;
      day: number | null;
      dow: number;
      past: boolean;
      today: boolean;
      proposed: boolean;
    }[] = [];

    for (let i = 0; i < firstDow; i++) {
      out.push({ key: null, day: null, dow: i, past: false, today: false, proposed: false });
    }
    for (let day = 1; day <= lastDay; day++) {
      const date = new Date(viewYear, viewMonth, day);
      const key = `${viewYear}-${viewMonth + 1}-${day}`;
      out.push({
        key,
        day,
        dow: date.getDay(),
        past: date < today,
        today: date.getTime() === today.getTime(),
        proposed: proposedDayKeys.has(key),
      });
    }
    return out;
  }, [viewYear, viewMonth, today, proposedDayKeys]);

  const monthLabel = `${viewYear}年${viewMonth + 1}月`;

  function gotoPrevMonth() {
    setViewMonth((m) => {
      if (m <= 0) {
        setViewYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  }
  function gotoNextMonth() {
    setViewMonth((m) => {
      if (m >= 11) {
        setViewYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  }

  function selectDay(cell: { key: string; day: number; dow: number }) {
    const label = `${viewMonth + 1}月${cell.day}日（${DOW_LABELS[cell.dow]}）`;
    setSelectedDate({ key: cell.key, label, year: viewYear, month: viewMonth + 1, day: cell.day });
    setSelectedTime(null);
  }

  const canConfirm = !!selectedDate && !!selectedTime && !submitting;
  const confirmDateText = selectedDate ? `${selectedDate.year}年${selectedDate.label}` : null;

  async function handleConfirm() {
    if (!selectedDate || !selectedTime || !token || !transactionId || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const mm = String(selectedDate.month).padStart(2, "0");
      const dd = String(selectedDate.day).padStart(2, "0");
      await confirmSchedule(
        transactionId,
        {
          visit_date: `${selectedDate.year}-${mm}-${dd}`,
          visit_time_slot: selectedTime,
          note: note.trim() || undefined,
        },
        token,
      );
      setDone(true);
    } catch (e) {
      setSubmitError(toDisplayMessage(e, "日程の確定に失敗しました"));
    } finally {
      setSubmitting(false);
    }
  }

  const vendorName = detail?.operator?.company_name ?? "業者";
  const vendorInitial = vendorName.charAt(0) || "業";
  const vendorAmount = detail?.final_amount ?? detail?.initial_amount ?? 0;

  if (tokenLoading || (loading && !loadError)) {
    return (
      <div className="schedule-page">
        <AppHeader unread />
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>読み込み中…</div>
      </div>
    );
  }

  if (loadError || !detail || !transactionId) {
    return (
      <div className="schedule-page">
        <AppHeader unread />
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>
          {loadError ?? "成約情報が見つかりません。"}
        </div>
      </div>
    );
  }

  return (
    <div className="schedule-page">
      <AppHeader unread />

      {/* 進捗ステップ + チャット戻り導線 */}
      <div className="sch-progress">
        <div className="container">
          <div className="sch-progress-inner">
            <div className="sch-steps">
              {PROGRESS_STEPS.map((s, i) => (
                <span key={s.label} style={{ display: "contents" }}>
                  <div className={`sch-step${s.state === "done" ? " done" : s.state === "active" ? " active" : ""}`}>
                    <div className="step-num">
                      {s.state === "done" ? (
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M5 12.5l4.5 4.5L19 7" />
                        </svg>
                      ) : (
                        i + 1
                      )}
                    </div>
                    {s.label}
                  </div>
                  {i < PROGRESS_STEPS.length - 1 ? (
                    <div className={`step-sep${s.state === "done" ? " done" : ""}`} />
                  ) : null}
                </span>
              ))}
            </div>
            <Link href={`/chat/${transactionId}`} className="sch-back-chat">
              <Ic name="chat" />
              チャットに戻る
            </Link>
          </div>
        </div>
      </div>

      <div className="sch-wrap">
        {/* 左：メインエリア */}
        <div className="sch-main">
          {/* 業者情報 */}
          <div className="biz-card">
            <div className="biz-avatar">{vendorInitial}</div>
            <div>
              <div className="biz-name">{vendorName}</div>
              <div className="biz-sub">
                <Ic name="pin" />
                {detail.case?.prefecture} {detail.case?.city}
              </div>
            </div>
            <div className="biz-amount">
              <div className="label">成約買取額</div>
              <div className="amount">
                ¥{yen(vendorAmount)}
                <span>円</span>
              </div>
            </div>
          </div>

          {/* カレンダー */}
          <div className="cal-card">
            <div className="cal-header">
              <div className="cal-month">{monthLabel}</div>
              <div className="cal-nav">
                <button type="button" className="cal-nav-btn" onClick={gotoPrevMonth} title="前月" aria-label="前の月">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
                <button type="button" className="cal-nav-btn" onClick={gotoNextMonth} title="翌月" aria-label="次の月">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M9 18l6-6-6-6" />
                  </svg>
                </button>
              </div>
            </div>
            <div className="cal-grid-header">
              {DOW_LABELS.map((d, i) => (
                <div key={d} className={`cal-dow${i === 0 ? " sun" : i === 6 ? " sat" : ""}`}>
                  {d}
                </div>
              ))}
            </div>
            <div className="cal-grid">
              {cells.map((c, i) => {
                if (c.key === null) {
                  return <div key={`empty-${i}`} className="cal-day empty" aria-hidden="true" />;
                }
                const isSelected = selectedDate?.key === c.key;
                const classes = ["cal-day"];
                if (c.dow === 0) classes.push("sun");
                else if (c.dow === 6) classes.push("sat");
                if (c.past) classes.push("past", "disabled");
                else if (isSelected) classes.push("selected");
                else if (c.proposed) classes.push("available");
                if (c.today && !isSelected) classes.push("today");

                if (c.past) {
                  return (
                    <div key={c.key} className={classes.join(" ")}>
                      {c.day}
                    </div>
                  );
                }
                return (
                  <button
                    type="button"
                    key={c.key}
                    className={classes.join(" ")}
                    aria-pressed={isSelected}
                    onClick={() => selectDay({ key: c.key as string, day: c.day as number, dow: c.dow })}
                  >
                    {c.day}
                  </button>
                );
              })}
            </div>
            <div className="cal-legend">
              {proposedDayKeys.size > 0 ? (
                <span>
                  <span className="legend-dot" style={{ background: "var(--green)" }} />
                  業者提示の候補日
                </span>
              ) : null}
              <span>
                <span className="legend-dot" style={{ background: "var(--blue)" }} />
                選択中
              </span>
              <span>
                <span className="legend-dot" style={{ background: "var(--line)" }} />
                選択不可（過去日）
              </span>
            </div>
          </div>

          {/* 時間帯 */}
          {selectedDate ? (
            <div className="time-card">
              <div className="time-card-title">
                <Ic name="clock" />
                希望時間帯を選んでください
              </div>
              <div className="time-slots">
                {TIME_SLOTS.map((slot) => {
                  const isSelected = selectedTime === slot.value;
                  return (
                    <button
                      type="button"
                      key={slot.value}
                      className={`time-slot${isSelected ? " selected" : ""}`}
                      aria-pressed={isSelected}
                      onClick={() => setSelectedTime(slot.value)}
                    >
                      {slot.value}
                      <div className="ts-label">{slot.label}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* 備考 */}
          {selectedDate ? (
            <div className="note-card">
              <label htmlFor="note-input">
                <Ic name="chat" />
                業者へのひとこと（任意）
              </label>
              <textarea
                className="note-textarea"
                id="note-input"
                placeholder="例：玄関前に荷物をまとめておきます。ご来訪前にお電話ください。"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <p className="note-hint">入力した内容は業者へ共有されます。</p>
            </div>
          ) : null}
        </div>

        {/* 右：確認パネル */}
        <div className="sch-side">
          <div className="confirm-card">
            <div className="confirm-title">
              <Ic name="clock" />
              日程確認
            </div>
            <div className="confirm-row">
              <span className="confirm-lbl">業者</span>
              <span className="confirm-val">{vendorName}</span>
            </div>
            <div className="confirm-row">
              <span className="confirm-lbl">買取額</span>
              <span className="confirm-val">¥{yen(vendorAmount)}</span>
            </div>
            <div className="confirm-row">
              <span className="confirm-lbl">訪問日</span>
              <span className={`confirm-val${confirmDateText ? "" : " pending"}`}>
                {confirmDateText ?? "日付を選んでください"}
              </span>
            </div>
            <div className="confirm-row">
              <span className="confirm-lbl">時間帯</span>
              <span className={`confirm-val${selectedTime ? "" : " pending"}`}>
                {selectedTime ?? "時間帯を選んでください"}
              </span>
            </div>
            {submitError ? (
              <p style={{ marginTop: 10, fontSize: 12.5, color: "#e05c5c" }}>{submitError}</p>
            ) : null}
            <button type="button" className="confirm-btn" disabled={!canConfirm} onClick={() => void handleConfirm()}>
              <Ic name="check" />
              {submitting ? "確定中…" : "この日程で確定する"}
            </button>
          </div>

          <div className="notice-box">
            <Ic name="clock" />
            日程確定後はLINEで通知が届きます。変更が必要な場合はチャットで業者へご連絡ください。
          </div>

          <div className="notice-box warn">
            <Ic name="clock" />
            訪問買取は特定商取引法によりクーリングオフの対象です。詳しくは
            <Link href="/legal">こちら</Link>。
          </div>
        </div>
      </div>

      {/* 完了モーダル（共通 .kdz-overlay / .kdz-modal を利用） */}
      {done ? (
        <div className="kdz-overlay" role="dialog" aria-modal="true" aria-label="日程確定の完了">
          <div className="kdz-modal sch-modal">
            <div className="sch-modal-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 12.5l4.5 4.5L19 7" />
              </svg>
            </div>
            <h2>訪問日程を確定しました</h2>
            <p>
              {vendorName}が
              <br />
              <strong>{confirmDateText}</strong>
              <br />
              <strong>{selectedTime}</strong>に訪問します。
              <br />
              LINEにも通知が届きます。
            </p>
            <div className="sch-modal-btns">
              <Link href="/cases" className="btn btn-primary btn-lg">
                申し込み状況を確認する
                <Ic name="arrow" className="arw" />
              </Link>
              <Link href="/mypage" className="btn btn-ghost btn-lg">
                マイページへ
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
