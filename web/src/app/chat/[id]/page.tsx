"use client";

/**
 * 交渉チャット（/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/chat.html をピクセル忠実に再現。
 * 動的ルート([id])。SiteChrome の BARE_PREFIXES（/chat）対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + ID + 通知ベル）と全画面レイアウトを描く。
 *
 * クライアント化の理由（純表示では不可）:
 *  - 業者リストの選択切替（サイドバー active / 相手ヘッダー差し替え / 未読消化）
 *  - メッセージ送信 + 業者の自動返信デモ
 *  - 引き取り候補日のラジオ選択 + 日程確定（業者ごとに状態保持）
 *  - id（動的ルート）の参照に useParams を使用
 * バックエンド未配線: メッセージ・入札・日程はモック定数。送信/確定は実処理せず UI 挙動のみ。
 */

import "./chat.css";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";

/* ---- カレンダー線画（スプライト未収録のため inline。絵文字は使わない） ---- */
function CalendarIc({ className }: { className?: string }) {
  return (
    <svg className={`ic${className ? ` ${className}` : ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 9h16M8 3v4M16 3v4" />
    </svg>
  );
}

/* ---- メッセージ型 ---- */
type ChatMsg = { mine: boolean; text: string; time: string };

/* ---- 業者（デモ）。amount は数値で保持し、表示時に整形する。 ---- */
type RankStyle = "gold" | "silver" | "bronze";
type Biz = {
  rank: number;
  rankStyle: RankStyle;
  initial: string;
  name: string;
  area: string;
  amount: number;
  time: string;
  preview: string;
  unread: boolean;
  msgs: ChatMsg[];
};

const BIZ: Biz[] = [
  {
    rank: 1,
    rankStyle: "gold",
    initial: "グ",
    name: "グリーンリサイクル東京",
    area: "東京都・神奈川県対応",
    amount: 72000,
    time: "15:42",
    preview: "引き取り日程はご都合の…",
    unread: false,
    msgs: [
      { mine: false, text: "家電・ブランド品を中心に高評価しております。値がつかないものも含めてまとめて回収いたします。引き取りは弊社スタッフ2名でお伺いしますので、重いものも安心してお任せください。", time: "13:11" },
      { mine: true, text: "ご連絡ありがとうございます。金額について、もう少し上げていただくことは可能でしょうか？", time: "13:45" },
      { mine: false, text: "ご要望ありがとうございます。社内で検討いたしました。カメラ機材の評価を見直し、¥72,000での買取であれば対応可能です。いかがでしょうか。", time: "14:20" },
      { mine: true, text: "ありがとうございます。¥72,000でお願いします。日程はいつ頃が可能ですか？", time: "15:10" },
    ],
  },
  {
    rank: 2,
    rankStyle: "silver",
    initial: "ア",
    name: "アクトリユース",
    area: "東京都・埼玉県対応",
    amount: 62000,
    time: "14:31",
    preview: "ご検討いただきましたら…",
    unread: true,
    msgs: [
      { mine: false, text: "アクトリユースと申します。ブランド品・時計を中心に高く評価しております。¥62,000でのお引き取りをご提案します。", time: "11:05" },
      { mine: false, text: "梱包は不要です。玄関先までお出しいただければ回収いたします。ご検討いただきましたらご返信ください。", time: "14:31" },
    ],
  },
  {
    rank: 3,
    rankStyle: "bronze",
    initial: "エ",
    name: "エコステーション千葉",
    area: "千葉県・東京都対応",
    amount: 58000,
    time: "13:05",
    preview: "はじめまして。この度は…",
    unread: true,
    msgs: [
      { mine: false, text: "はじめまして。この度はご出品ありがとうございます。エコステーション千葉です。家電・カメラが得意分野で、値がつかないものもまとめて回収可能です。¥58,000でご提案いたします。", time: "13:05" },
    ],
  },
];

/* ---- 引き取り候補日（デモ） ---- */
const SCHEDULE_OPTIONS = [
  "7月5日（土）10:00〜12:00",
  "7月6日（日）13:00〜15:00",
  "7月12日（土）10:00〜12:00",
];

/* ---- 送信に対する業者の自動返信（デモ） ---- */
const AUTO_REPLIES = [
  "ありがとうございます。確認して折り返しご連絡いたします。",
  "かしこまりました。ご都合のよい日時をお知らせください。",
  "詳細を確認次第ご連絡いたします。引き続きよろしくお願いいたします。",
];

const APP_ID = "KTZ-2026-04821";

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
function nowLabel(): string {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function ChatPage() {
  // 動的ルートの id（client component なので useParams で取得）。表示は申込IDを優先しつつ補助表示に使う。
  const params = useParams<{ id: string }>();
  const routeId = Array.isArray(params?.id) ? params.id[0] : params?.id;

  /* ---- 選択中の業者 ---- */
  const [activeIdx, setActiveIdx] = useState(0);
  const [read, setRead] = useState<boolean[]>(() => BIZ.map((b) => !b.unread));

  /* ---- 業者ごとの送信メッセージ / 自動返信 ---- */
  const [userMsgs, setUserMsgs] = useState<ChatMsg[][]>(() => BIZ.map(() => []));
  const [coReplies, setCoReplies] = useState<ChatMsg[][]>(() => BIZ.map(() => []));
  const [draft, setDraft] = useState("");

  /* ---- 引き取り候補日（業者1のカードのみ。選択 + 確定） ---- */
  const [schedulePick, setSchedulePick] = useState(0);
  const [scheduleConfirmed, setScheduleConfirmed] = useState(false);
  const [scheduleHandled, setScheduleHandled] = useState(false);

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

  const biz = BIZ[activeIdx];

  // 表示順: 業者の初期メッセージ → 日程カード（業者1） → 各ユーザー送信と対応する業者自動返信を交互に。
  const renderedMsgs: ChatMsg[] = useMemo(() => {
    const extra = userMsgs[activeIdx].flatMap((u, i) => {
      const r = coReplies[activeIdx][i];
      return r ? [u, r] : [u];
    });
    return [...biz.msgs, ...extra];
  }, [activeIdx, userMsgs, coReplies, biz.msgs]);

  /* ---- 自動スクロール ---- */
  const messagesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [activeIdx, renderedMsgs.length, scheduleConfirmed]);

  function selectBiz(idx: number) {
    setActiveIdx(idx);
    setRead((prev) => prev.map((v, i) => (i === idx ? true : v)));
  }

  function sendMsg() {
    const text = draft.trim();
    if (!text) return;
    const t = nowLabel();
    const idx = activeIdx;
    setUserMsgs((prev) => prev.map((arr, i) => (i === idx ? [...arr, { mine: true, text, time: t }] : arr)));
    setDraft("");
    window.setTimeout(() => {
      const reply = AUTO_REPLIES[Math.floor(Math.random() * AUTO_REPLIES.length)];
      setCoReplies((prev) => prev.map((arr, i) => (i === idx ? [...arr, { mine: false, text: reply, time: nowLabel() }] : arr)));
    }, 1200);
  }

  function scrollToSchedule() {
    document.getElementById("schedule-card")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function confirmSchedule() {
    if (scheduleConfirmed) return;
    const label = SCHEDULE_OPTIONS[schedulePick];
    setScheduleConfirmed(true);
    setScheduleHandled(true);
    // ユーザー確定メッセージ + 業者からの確認返信（業者1のスレッドに追加）
    setUserMsgs((prev) => prev.map((arr, i) => (i === 0 ? [...arr, { mine: true, text: `${label} でお願いします。よろしくお願いいたします！`, time: nowLabel() }] : arr)));
    window.setTimeout(() => {
      setCoReplies((prev) => prev.map((arr, i) => (i === 0 ? [...arr, { mine: false, text: `ありがとうございます。${label} にお伺いします。当日は10分前を目安にご連絡いたします。`, time: nowLabel() }] : arr)));
    }, 1200);
    showToast("日程を選択しました（デモ）");
  }

  // 日程カードは業者1（rank1）のスレッドにのみ表示。
  const showScheduleCard = activeIdx === 0;
  // アクションバーは日程未確定かつ業者1のときのみ表示。
  const showActionBar = activeIdx === 0 && !scheduleHandled;

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
        <span className="ch-id">{APP_ID}</span>
        <Link href="/notifications" className="ch-bell" aria-label="通知・お知らせ">
          <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
          <span className="bell-dot" aria-hidden="true" />
        </Link>
      </header>

      <div className="chat-layout">
        {/* 業者リスト */}
        <nav className="biz-sidebar" aria-label="上位の業者">
          <div className="biz-sidebar-head">上位の業者</div>
          {BIZ.map((b, i) => (
            <button
              key={b.name}
              type="button"
              className={`biz-item${i === activeIdx ? " active" : ""}`}
              onClick={() => selectBiz(i)}
              aria-current={i === activeIdx ? "true" : undefined}
            >
              <div className="biz-meta">
                <span className={`biz-rank ${i === activeIdx ? "gold" : b.rankStyle}`}>{b.rank}</span>
                <span className="biz-time">{b.time}</span>
              </div>
              <div className="biz-name">{b.name}</div>
              <div className="biz-preview">{b.preview}</div>
              <span className="biz-bid">¥{b.amount.toLocaleString()}</span>
              {!read[i] ? <span className="biz-unread" aria-label="未読あり" /> : null}
            </button>
          ))}
        </nav>

        {/* チャット本体 */}
        <div className="chat-main">
          {/* 相手ヘッダー */}
          <div className="chat-peer-header">
            <div className="peer-avatar">{biz.initial}</div>
            <div className="peer-name-block">
              <div className="peer-name">{biz.name}</div>
              <div className="peer-sub">
                {biz.area}　古物商許可あり
                <Link href="/vendors/1" className="peer-link">
                  プロフィールを見る
                </Link>
              </div>
            </div>
            <div className="peer-bid-chip">
              <div className="peer-bid-label">入札額</div>
              <div className="peer-bid-amount">¥{biz.amount.toLocaleString()}</div>
            </div>
          </div>

          {/* アクションバー（日程確定誘導） */}
          {showActionBar ? (
            <div className="action-bar">
              <span className="action-bar-ic">
                <CalendarIc />
              </span>
              <span className="action-bar-text">
                <strong>引き取り日程を確定しましょう</strong>　業者が候補日を提案しています
              </span>
              <button type="button" className="btn-action" onClick={scrollToSchedule}>
                確認する
              </button>
            </div>
          ) : null}

          {/* LINE通知バナー */}
          <div className="line-banner">
            <span className="line-dot" aria-hidden="true" />
            新着メッセージはLINEにも通知されます。返信はこのページで行えます。
          </div>

          {/* メッセージ */}
          <div className="messages-area" ref={messagesRef}>
            {renderedMsgs.map((m, i) => (
              <div key={i} className={`msg ${m.mine ? "me" : "them"}`}>
                <div className="msg-avatar">{m.mine ? "山" : biz.initial}</div>
                <div>
                  <div className="msg-time">{m.time}</div>
                  <div className="bubble">{m.text}</div>
                </div>
              </div>
            ))}

            {showScheduleCard ? (
              <>
                <div className="date-sep">6月24日（火）</div>

                <div className="schedule-card" id="schedule-card">
                  <div className="schedule-card-head">
                    <CalendarIc />
                    引き取り候補日
                  </div>
                  <div className="schedule-options" role="radiogroup" aria-label="引き取り候補日">
                    {SCHEDULE_OPTIONS.map((opt, i) => (
                      <div className="schedule-opt" key={opt}>
                        <input
                          type="radio"
                          name="schedule"
                          id={`s${i + 1}`}
                          checked={schedulePick === i}
                          disabled={scheduleConfirmed}
                          onChange={() => setSchedulePick(i)}
                        />
                        <label htmlFor={`s${i + 1}`}>{opt}</label>
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    className={`btn-schedule${scheduleConfirmed ? " confirmed" : ""}`}
                    onClick={confirmSchedule}
                    disabled={scheduleConfirmed}
                  >
                    {scheduleConfirmed
                      ? `${SCHEDULE_OPTIONS[schedulePick]} ✓ 選択済み`
                      : `${SCHEDULE_OPTIONS[schedulePick]} を選ぶ`}
                  </button>
                </div>

                <div className="msg them" style={{ marginTop: 4 }}>
                  <div className="msg-avatar">{biz.initial}</div>
                  <div>
                    <div className="msg-time">09:31</div>
                    <div className="bubble">
                      引き取り日程の候補をお送りしました。ご都合の良い日程をお選びください。当日はスタッフ2名でお伺いします。
                    </div>
                  </div>
                </div>
              </>
            ) : null}
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
                  sendMsg();
                }
              }}
              aria-label="メッセージを入力"
            />
            <button type="button" className="btn-send" aria-label="送信" disabled={!draft.trim()} onClick={sendMsg}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M22 2L11 13" />
                <path d="M22 2L15 22l-4-9-9-4 20-7z" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* ルートID補助（開発時の確認用・視覚上は非表示） */}
      <span hidden data-route-id={routeId} />

      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
