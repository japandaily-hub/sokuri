"use client";

import "./schedule.css";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { AppHeader } from "@/components/kdz/AppHeader";

/* ============================================================
   訪問日程調整ページ（カタヅケ）
   バックエンド未配線：業者情報・対応可能日・時間帯はデモ用モックデータ。
   日付/時間帯の選択は "use client" + useState で再現。確定は実処理せず
   完了モーダルを表示するのみ（虚偽の成功断定はしない）。
   ============================================================ */

/** 進捗ステップ（出品→入札・交渉→日程調整→訪問・完了）。今回は「日程調整」がactive。 */
const PROGRESS_STEPS = [
  { state: "done" as const, label: "出品" },
  { state: "done" as const, label: "入札・交渉" },
  { state: "active" as const, label: "日程調整" },
  { state: "todo" as const, label: "訪問・完了" },
];

/** 成約業者（デモ）。 */
const VENDOR = {
  initial: "緑",
  name: "グリーンリサイクル株式会社",
  shortName: "グリーンリサイクル",
  area: "東京都世田谷区エリア対応",
  amount: 72000,
};

/** デモ固定の「今日」。過去日判定の基準。 */
const TODAY = new Date(2026, 5, 25); // 2026-06-25

/** 業者対応可能日（デモ）。キーは `${year}-${month1}-${day}`。 */
const AVAILABLE: Record<string, true> = {
  "2026-7-2": true, "2026-7-3": true, "2026-7-4": true,
  "2026-7-7": true, "2026-7-8": true, "2026-7-9": true, "2026-7-10": true,
  "2026-7-14": true, "2026-7-15": true, "2026-7-16": true,
  "2026-7-21": true, "2026-7-22": true, "2026-7-23": true,
  "2026-7-28": true, "2026-7-29": true, "2026-7-30": true,
};

/** 希望時間帯（デモ）。夜は業者非対応（disabled）。 */
const TIME_SLOTS: { value: string; label: string; disabled?: boolean }[] = [
  { value: "9:00〜12:00", label: "午前" },
  { value: "12:00〜15:00", label: "昼" },
  { value: "15:00〜18:00", label: "午後" },
  { value: "18:00〜21:00", label: "夜（×）", disabled: true },
  { value: "時間指定なし", label: "業者に一任" },
];

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"];

type SelectedDate = { key: string; label: string };

/** 数値を `1,234` 形式に整形（円表示用）。 */
const yen = (n: number) => n.toLocaleString();

export default function SchedulePage() {
  /* ---- カレンダー表示月（デモ：2026年7月から） ---- */
  const [viewYear, setViewYear] = useState(2026);
  const [viewMonth, setViewMonth] = useState(6); // 0-indexed：7月

  /* ---- 選択状態 ---- */
  const [selectedDate, setSelectedDate] = useState<SelectedDate | null>(null);
  const [selectedTime, setSelectedTime] = useState<string | null>(null);
  const [note, setNote] = useState("");

  /* ---- 完了モーダル ---- */
  const [done, setDone] = useState(false);

  /** 表示月のセル配列（先頭の空白＋各日）を算出。 */
  const cells = useMemo(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const firstDow = first.getDay();
    const lastDay = new Date(viewYear, viewMonth + 1, 0).getDate();
    const todayMidnight = new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate());

    const out: {
      key: string | null;
      day: number | null;
      dow: number;
      past: boolean;
      today: boolean;
      available: boolean;
    }[] = [];

    for (let i = 0; i < firstDow; i++) {
      out.push({ key: null, day: null, dow: i, past: false, today: false, available: false });
    }
    for (let day = 1; day <= lastDay; day++) {
      const date = new Date(viewYear, viewMonth, day);
      const key = `${viewYear}-${viewMonth + 1}-${day}`;
      out.push({
        key,
        day,
        dow: date.getDay(),
        past: date < todayMidnight,
        today: date.toDateString() === TODAY.toDateString(),
        available: !!AVAILABLE[key],
      });
    }
    return out;
  }, [viewYear, viewMonth]);

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
    setSelectedDate({ key: cell.key, label });
    setSelectedTime(null);
  }

  const canConfirm = !!selectedDate && !!selectedTime;
  const confirmDateText = selectedDate ? `2026年${selectedDate.label}` : null;

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
            <Link href="/chat/1" className="sch-back-chat">
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
            <div className="biz-avatar">{VENDOR.initial}</div>
            <div>
              <div className="biz-name">{VENDOR.name}</div>
              <div className="biz-sub">
                <Ic name="pin" />
                {VENDOR.area}
              </div>
            </div>
            <div className="biz-amount">
              <div className="label">成約買取額</div>
              <div className="amount">
                ¥{yen(VENDOR.amount)}<span>円</span>
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
                const isDisabled = c.past || !c.available;
                const classes = ["cal-day"];
                if (c.dow === 0) classes.push("sun");
                else if (c.dow === 6) classes.push("sat");
                if (c.past) classes.push("past", "disabled");
                else if (isSelected) classes.push("selected");
                else if (c.available) classes.push("available");
                if (c.today && !isSelected) classes.push("today");
                if (!c.available && !c.past) classes.push("disabled");

                if (isDisabled) {
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
              <span>
                <span className="legend-dot" style={{ background: "var(--green)" }} />
                業者対応可能日
              </span>
              <span>
                <span className="legend-dot" style={{ background: "var(--blue)" }} />
                選択中
              </span>
              <span>
                <span className="legend-dot" style={{ background: "var(--line)" }} />
                選択不可
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
                      className={`time-slot${slot.disabled ? " disabled" : ""}${isSelected ? " selected" : ""}`}
                      disabled={slot.disabled}
                      aria-pressed={isSelected}
                      onClick={() => !slot.disabled && setSelectedTime(slot.value)}
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
              <span className="confirm-val">{VENDOR.shortName}</span>
            </div>
            <div className="confirm-row">
              <span className="confirm-lbl">買取額</span>
              <span className="confirm-val">¥{yen(VENDOR.amount)}</span>
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
            <button
              type="button"
              className="confirm-btn"
              disabled={!canConfirm}
              onClick={() => setDone(true)}
            >
              <Ic name="check" />
              この日程で確定する
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
            <h2>日程が確定しました！</h2>
            <p>
              {VENDOR.name}が
              <br />
              <strong>{confirmDateText}</strong>
              <br />
              <strong>{selectedTime}</strong>に訪問します。
              <br />
              LINEにも通知が届きます。
            </p>
            <div className="sch-modal-btns">
              <Link href="/applications" className="btn btn-primary btn-lg">
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
