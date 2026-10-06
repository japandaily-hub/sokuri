"use client";

import "./schedule.css";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { AppHeader } from "@/components/kdz/AppHeader";
import { useToken } from "@/components/kdz/Ui";
import { Notice } from "@/components/kdz/Notice";
import { stripControlCharsKeepNewlines } from "@/lib/categories";
import {
  confirmSchedule,
  getTransaction,
  listMessages,
  toDisplayMessage,
  type MessageOut,
  type TransactionDetail,
} from "@/lib/katadzuke-api";
import {
  VISIT_TIME_SLOTS as TIME_SLOTS,
  isCandidateExpired,
  jstTodayIso,
  latestProposalId,
  parseScheduleProposalMeta,
  type VisitTimeSlotValue,
} from "@/lib/visit-slots";

/* ============================================================
   訪問日程調整ページ（カタヅケ）
   ?transaction_id= で対象成約を指定する。未指定のときは、別の取引の日程画面を
   勝手に開かない（取り違え防止・S-4）ため、取引の一覧（/cases）へ誘導する。
   カレンダー選択 + 時間帯選択（固定5種）で confirmSchedule を実送信する。
   業者の最新の提示（チャットの schedule_proposal・meta v2）の候補日を
   優先候補としてハイライトするが、無くても任意の未来日を選べる
   （日程構造化 DESIGN §13.4。候補のラベルは解析しない）。
   「今日」「当日の終わった枠」はサーバーと同じく日本時間で判定する。
   ============================================================ */

/** 進捗ステップ（出品→入札・交渉→日程調整→訪問・完了）。今回は「日程調整」がactive。 */
const PROGRESS_STEPS = [
  { state: "done" as const, label: "出品" },
  { state: "done" as const, label: "入札・交渉" },
  { state: "active" as const, label: "日程調整" },
  { state: "todo" as const, label: "訪問・完了" },
];

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"];

type SelectedDate = { key: string; label: string; year: number; month: number; day: number };

/** 数値を `1,234` 形式に整形（円表示用）。 */
const yen = (n: number) => n.toLocaleString();

export default function SchedulePage() {
  return (
    <Suspense
      fallback={
        <div className="schedule-page">
          <AppHeader />
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

  const transactionId = requestedTxnId;
  const [detail, setDetail] = useState<TransactionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  /** 業者の最新の提示（v2）の候補日（"YYYY-MM-DD"）。ハイライト専用。 */
  const [proposedDates, setProposedDates] = useState<string[]>([]);

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
      // 日程構造化 DESIGN §13.4: ハイライトは最新の提示（seq が最大の v2）の候補の日付から作る。
      // 旧形式（v1）の自由記述はラベルを解析しないため、ハイライトしない（任意の日付は選べる）。
      const latestId = latestProposalId(messages);
      const latestProposal = latestId ? messages.find((m) => m.id === latestId) : undefined;
      const parsed = latestProposal ? parseScheduleProposalMeta(latestProposal.meta) : null;
      setProposedDates(parsed?.version === 2 ? parsed.candidates.map((c) => c.date) : []);
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
  // サーバーは「今日」を日本時間で判定するため、ブラウザのタイムゾーンに依らず日本時間の今日を使う
  // （年月日だけを new Date(y, m-1, d) のローカル日付として持ち、各セルのローカル日付と比べる）。
  const today = useMemo(() => {
    const [year, month, day] = jstTodayIso().split("-").map(Number);
    return new Date(year, month - 1, day);
  }, []);
  const [viewYear, setViewYear] = useState(() => today.getFullYear());
  const [viewMonth, setViewMonth] = useState(() => today.getMonth());

  /* ---- 業者提示候補日のハイライト用セット（ISO形式をこのページのキー形式へ変換） ---- */
  const proposedDayKeys = useMemo(() => {
    const set = new Set<string>();
    // proposedDates は parseScheduleProposalMeta が実在する "YYYY-MM-DD" だけを通したもの。
    for (const iso of proposedDates) {
      const [year, month, day] = iso.split("-").map(Number);
      set.add(`${year}-${month}-${day}`);
    }
    return set;
  }, [proposedDates]);

  /* ---- 選択状態 ---- */
  const [selectedDate, setSelectedDate] = useState<SelectedDate | null>(null);
  const [selectedTime, setSelectedTime] = useState<VisitTimeSlotValue | null>(null);
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
  /** 選択中の日付（"YYYY-MM-DD"）。当日の終わった枠の判定と確定リクエストに使う。 */
  const selectedIsoDate = selectedDate
    ? `${selectedDate.year}-${String(selectedDate.month).padStart(2, "0")}-${String(selectedDate.day).padStart(2, "0")}`
    : null;
  // 日程構造化 DESIGN §13.4: 当日の終わった枠（日本時間）は選べない。描画のたびに今の時刻で判定する
  // （確定時は handleConfirm で改めて判定し、最後はサーバーが判定する）。
  const renderNow = new Date();
  const isSlotOver = (end: string | null) =>
    selectedIsoDate !== null && isCandidateExpired({ date: selectedIsoDate, end }, renderNow);
  const hasOverSlot = TIME_SLOTS.some((slot) => isSlotOver(slot.end));

  async function handleConfirm() {
    if (!selectedDate || !selectedIsoDate || !selectedTime || !token || !transactionId || submitting) return;
    // 画面を開いたまま日付・時刻をまたいだ場合に備え、押した瞬間の日本時間で検査する
    // （サーバーの 422 と同じ文言。サーバー側でも同じ判定をする）。
    const submitNow = new Date();
    if (selectedIsoDate < jstTodayIso(submitNow)) {
      setSubmitError("訪問日は本日以降を指定してください。");
      return;
    }
    const selectedSlot = TIME_SLOTS.find((slot) => slot.value === selectedTime);
    if (isCandidateExpired({ date: selectedIsoDate, end: selectedSlot?.end ?? null }, submitNow)) {
      setSubmitError("終わった時間帯は選べません。別の時間帯か日付をお選びください。");
      return;
    }
    // ひとことは送信前に改行以外の制御文字（双方向制御・ゼロ幅等）を除去する
    // （backend は拒否して 422 になるため、コピペ由来の不可視文字で送信に失敗させない）。
    const cleanedNote = stripControlCharsKeepNewlines(note).trim();
    setSubmitting(true);
    setSubmitError(null);
    try {
      await confirmSchedule(
        transactionId,
        {
          visit_date: selectedIsoDate,
          visit_time_slot: selectedTime,
          note: cleanedNote || undefined,
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

  if (!tokenLoading && !requestedTxnId) {
    return (
      <div className="schedule-page">
        <AppHeader />
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)", lineHeight: 1.8 }}>
          <p>どの取引の日程を調整するかが指定されていません。</p>
          <p>取引の一覧から対象の取引を開き、「訪問日程を調整する」を押してください。</p>
          <p style={{ marginTop: 16 }}>
            <Link href="/cases" className="btn btn-primary">
              取引の一覧へ
            </Link>
          </p>
        </div>
      </div>
    );
  }

  if (tokenLoading || (loading && !loadError)) {
    return (
      <div className="schedule-page">
        <AppHeader />
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>読み込み中…</div>
      </div>
    );
  }

  if (loadError || !detail || !transactionId) {
    return (
      <div className="schedule-page">
        <AppHeader />
        <div style={{ padding: 60, textAlign: "center", color: "var(--body-soft)" }}>
          {loadError ?? "成約情報が見つかりません。"}
        </div>
      </div>
    );
  }

  return (
    <div className="schedule-page">
      <AppHeader />

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
              <div className="label">成約金額</div>
              <div className="amount">¥{yen(vendorAmount)}</div>
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
                  const isOver = isSlotOver(slot.end);
                  return (
                    <button
                      type="button"
                      key={slot.value}
                      className={`time-slot${isOver ? " disabled" : isSelected ? " selected" : ""}`}
                      aria-pressed={isSelected}
                      disabled={isOver}
                      onClick={() => setSelectedTime(slot.value)}
                    >
                      {slot.value}
                      <div className="ts-label">{slot.label}</div>
                    </button>
                  );
                })}
              </div>
              {hasOverSlot ? <p className="note-hint">終わった時間帯は選べません。</p> : null}
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
              <span className="confirm-lbl">成約金額</span>
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
              <Notice tone="danger" className="confirm-error">{submitError}</Notice>
            ) : null}
            <button type="button" className="confirm-btn" disabled={!canConfirm} onClick={() => void handleConfirm()}>
              <Ic name="check" />
              {submitting ? "確定中…" : "この日程で確定する"}
            </button>
          </div>

          <div className="notice-box">
            <Ic name="clock" />
            日程を確定すると、業者へ通知が送られます。確定内容はマイページとチャットで確認できます。変更が必要な場合はチャットで業者へご連絡ください。
          </div>

          <div className="notice-box warn">
            <Ic name="clock" />
            訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。クーリング・オフの可否は、品目（家具・家電等は対象外）や契約に至った経緯（ご自身の依頼で業者が訪問した場合は対象外となることがあります）によって異なります。業者から交付される書面をご確認ください。詳しくは
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
              業者に通知しました。確定内容はマイページとチャットで確認できます。
            </p>
            <div className="sch-modal-btns">
              <Link href={`/cases/${detail.case_id}`} className="btn btn-primary btn-lg">
                マイ案件を確認する
                <Ic name="arrow" />
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
