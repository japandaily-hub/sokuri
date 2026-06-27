"use client";

/**
 * 業者 交渉チャット（/operator/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/業者チャット.html をピクセル忠実に再現。
 * これは業者(operator)側の画面。送信メッセージ（自社=グ）は青バブルで右、相手（ユーザー=山田様）は白バブルで左。
 *
 * 動的ルート([id])。/operator は SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + 業者管理バッジ + 会社名 + 通知ベル）と全画面レイアウトを描く。
 *
 * クライアント化の理由（純表示では不可）:
 *  - 案件リストの選択切替（サイドバー active / 相手ヘッダー差し替え / 未読消化）
 *  - メッセージ送信 + ユーザーの自動返信デモ
 *  - 日程提案カードの候補日 追加/削除/編集 + 送信（カードを畳んでメッセージ化）
 *  - 入力ツールの📅ボタン / 右パネルの提案ボタンでカード表示トグル
 *  - id（動的ルート）の参照に useParams を使用
 * バックエンド未配線: 案件・メッセージ・日程はモック定数。送信/提案は実処理せず UI 挙動のみ（トースト）。
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

/* ---- メッセージ型（me=業者自社 / them=ユーザー） ---- */
type ChatMsg = { mine: boolean; text: string; time: string };

type CaseStatus = "negotiating" | "scheduled" | "waiting";

/* ---- 交渉中の案件（デモ）。amount は数値で保持し表示時に整形する。 ---- */
type Cas = {
  caseId: string;
  status: CaseStatus;
  statusLabel: string;
  initial: string;
  name: string;
  area: string;
  amount: number;
  fee: number;
  itemCount: number;
  time: string;
  preview: string;
  unread: boolean;
  statusBar: string;
  msgs: ChatMsg[];
};

const CASES: Cas[] = [
  {
    caseId: "KTZ-2026-04821",
    status: "negotiating",
    statusLabel: "交渉中",
    initial: "山",
    name: "山田 花子 様",
    area: "東京都 世田谷区",
    amount: 72000,
    fee: 5760,
    itemCount: 14,
    time: "15:42",
    preview: "家電・ブランド品 他12点",
    unread: false,
    statusBar: "交渉成立済み。引き取り日程を確定してください。",
    msgs: [
      { mine: true, text: "家電・ブランド品を中心に高評価しております。値がつかないものも含めてまとめて回収いたします。引き取りは弊社スタッフ2名でお伺いしますので、重いものも安心してお任せください。", time: "13:11" },
      { mine: false, text: "ご連絡ありがとうございます。金額について、もう少し上げていただくことは可能でしょうか？", time: "13:45" },
      { mine: true, text: "ご要望ありがとうございます。社内で検討いたしました。カメラ機材の評価を見直し、¥72,000での買取であれば対応可能です。いかがでしょうか。", time: "14:20" },
      { mine: false, text: "ありがとうございます。¥72,000でお願いします。日程はいつ頃が可能ですか？", time: "15:10" },
    ],
  },
  {
    caseId: "KTZ-2026-04756",
    status: "scheduled",
    statusLabel: "日程確定",
    initial: "田",
    name: "田中 一郎 様",
    area: "神奈川県 横浜市",
    amount: 45000,
    fee: 3600,
    itemCount: 8,
    time: "昨日",
    preview: "家具・インテリア 他8点",
    unread: false,
    statusBar: "引き取り日程が確定しています。当日はスタッフ2名でお伺いください。",
    msgs: [
      { mine: false, text: "家具とインテリアをまとめてお願いしたいです。引き取り可能でしょうか？", time: "10:02" },
      { mine: true, text: "もちろん可能です。¥45,000でのお引き取りをご提案いたします。7月6日（日）13:00〜でいかがでしょうか。", time: "10:40" },
      { mine: false, text: "その日程で大丈夫です。よろしくお願いします。", time: "11:15" },
      { mine: true, text: "ありがとうございます。7月6日（日）13:00にお伺いします。当日は10分前を目安にご連絡いたします。", time: "11:20" },
    ],
  },
  {
    caseId: "KTZ-2026-04690",
    status: "waiting",
    statusLabel: "返信待ち",
    initial: "鈴",
    name: "鈴木 美咲 様",
    area: "東京都 練馬区",
    amount: 38000,
    fee: 3040,
    itemCount: 5,
    time: "6/22",
    preview: "ブランド品・時計 他5点",
    unread: true,
    statusBar: "お客様からのご返信をお待ちしています。",
    msgs: [
      { mine: true, text: "はじめまして。ブランド品・時計を中心に高く評価しております。¥38,000でのお引き取りをご提案いたします。ご検討いただけますと幸いです。", time: "6/22 18:30" },
    ],
  },
];

/* ---- 日程提案カードの初期候補日（デモ） ---- */
const DEFAULT_SLOTS = [
  "7月5日（土）10:00〜12:00",
  "7月6日（日）13:00〜15:00",
  "7月12日（土）10:00〜12:00",
];

/* ---- 送信に対するユーザーの自動返信（デモ） ---- */
const AUTO_REPLIES = [
  "ご連絡ありがとうございます。確認いたします。",
  "承知しました。よろしくお願いいたします。",
  "ありがとうございます。検討してご返信します。",
];

/* ---- 右パネル 出品内容のサムネ（実アセット未投入のためアイコン代替） ---- */
const ITEM_THUMBS: { ic: "scan" | "bag" | "camera"; label: string }[] = [
  { ic: "scan", label: "家電・PC" },
  { ic: "bag", label: "バッグ" },
  { ic: "camera", label: "カメラ" },
];

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
function nowLabel(): string {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function yen(n: number): string {
  return `¥${n.toLocaleString()}`;
}

export default function OperatorChatPage() {
  // 動的ルートの id（client component なので useParams で取得）。補助表示に使う。
  const params = useParams<{ id: string }>();
  const routeId = Array.isArray(params?.id) ? params.id[0] : params?.id;

  /* ---- 選択中の案件 ---- */
  const [activeIdx, setActiveIdx] = useState(0);
  const [read, setRead] = useState<boolean[]>(() => CASES.map((c) => !c.unread));

  /* ---- 案件ごとの送信メッセージ / 自動返信 ---- */
  const [opMsgs, setOpMsgs] = useState<ChatMsg[][]>(() => CASES.map(() => []));
  const [userReplies, setUserReplies] = useState<ChatMsg[][]>(() => CASES.map(() => []));
  const [draft, setDraft] = useState("");

  /* ---- 日程提案カード（案件1のみ。候補日の編集 + 送信） ---- */
  const [slots, setSlots] = useState<string[]>(DEFAULT_SLOTS);
  const [scheduleVisible, setScheduleVisible] = useState(true);
  const [scheduleSent, setScheduleSent] = useState(false);

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

  const cas = CASES[activeIdx];

  // 表示順: 案件の初期メッセージ → 各送信と対応する自動返信を交互に。
  const renderedMsgs: ChatMsg[] = useMemo(() => {
    const extra = opMsgs[activeIdx].flatMap((u, i) => {
      const r = userReplies[activeIdx][i];
      return r ? [u, r] : [u];
    });
    return [...cas.msgs, ...extra];
  }, [activeIdx, opMsgs, userReplies, cas.msgs]);

  /* ---- 自動スクロール ---- */
  const messagesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [activeIdx, renderedMsgs.length, scheduleSent, scheduleVisible]);

  function selectCase(idx: number) {
    setActiveIdx(idx);
    setRead((prev) => prev.map((v, i) => (i === idx ? true : v)));
  }

  function pushUserReply(idx: number) {
    window.setTimeout(() => {
      const reply = AUTO_REPLIES[Math.floor(Math.random() * AUTO_REPLIES.length)];
      setUserReplies((prev) => prev.map((arr, i) => (i === idx ? [...arr, { mine: false, text: reply, time: nowLabel() }] : arr)));
    }, 1200);
  }

  function appendOpMsg(idx: number, text: string) {
    setOpMsgs((prev) => prev.map((arr, i) => (i === idx ? [...arr, { mine: true, text, time: nowLabel() }] : arr)));
  }

  function sendMsg() {
    const text = draft.trim();
    if (!text) return;
    const idx = activeIdx;
    appendOpMsg(idx, text);
    setDraft("");
    pushUserReply(idx);
  }

  /* ---- 日程提案カード操作 ---- */
  function updateSlot(i: number, value: string) {
    setSlots((prev) => prev.map((s, idx) => (idx === i ? value : s)));
  }
  function removeSlot(i: number) {
    setSlots((prev) => prev.filter((_, idx) => idx !== i));
  }
  function addSlot() {
    setSlots((prev) => [...prev, ""]);
  }
  function toggleScheduleCard() {
    if (activeIdx !== 0 || scheduleSent) {
      showToast("日程提案は交渉中の案件で行えます（デモ）");
      return;
    }
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
  function sendSchedule() {
    const dates = slots.map((s) => s.trim()).filter(Boolean);
    if (dates.length === 0) {
      showToast("候補日を1つ以上入力してください");
      return;
    }
    setScheduleVisible(false);
    setScheduleSent(true);
    const body = `引き取り候補日：\n${dates.map((d) => `・${d}`).join("\n")}\n\nご都合の良い日程をお選びください。`;
    appendOpMsg(0, body);
    pushUserReply(0);
    showToast("候補日を送信しました（デモ）");
  }

  // 日程提案カードは案件1（交渉中）のスレッドで、表示状態かつ未送信のときのみ描画。
  const showScheduleCard = activeIdx === 0 && scheduleVisible && !scheduleSent;

  return (
    <div className="opchat-page">
      {/* 専用ヘッダー（戻る矢印 + ロゴ + タイトル + 業者管理バッジ + 会社名 + 通知ベル） */}
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
          <span className="ch-company">グリーンリサイクル東京</span>
          <Link href="/operator" className="ch-bell" aria-label="通知・お知らせ">
            <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 01-3.46 0" />
            </svg>
            <span className="bell-dot" aria-hidden="true" />
          </Link>
        </div>
      </header>

      <div className="chat-layout">
        {/* 案件リスト（左サイドバー） */}
        <nav className="case-sidebar" aria-label="交渉中の案件">
          <div className="case-sidebar-head">交渉中の案件</div>
          {CASES.map((c, i) => (
            <button
              key={c.caseId}
              type="button"
              className={`case-item${i === activeIdx ? " active" : ""}`}
              onClick={() => selectCase(i)}
              aria-current={i === activeIdx ? "true" : undefined}
            >
              <span className={`case-status status-${c.status}`}>{c.statusLabel}</span>
              <div className="case-id">{c.caseId}</div>
              <div className="case-preview">{c.preview}</div>
              <div className="case-bid-row">
                <span className="case-bid">{yen(c.amount)}</span>
                <span className="case-time">{c.time}</span>
              </div>
              {!read[i] ? <span className="case-unread" aria-label="未読あり" /> : null}
            </button>
          ))}
        </nav>

        {/* チャット本体 */}
        <div className="chat-main">
          {/* 相手（ユーザー）ヘッダー */}
          <div className="chat-peer-header">
            <div className="peer-avatar">{cas.initial}</div>
            <div className="peer-info">
              <div className="peer-name">{cas.name}</div>
              <div className="peer-sub">
                {cas.area}　{cas.caseId}
              </div>
            </div>
            <div className="amount-chip">
              <div className="amount-label">合意額</div>
              <div className="amount-val">{yen(cas.amount)}</div>
            </div>
          </div>

          {/* ステータスバー */}
          <div className="status-bar">
            <span className="status-dot" aria-hidden="true" />
            {cas.statusBar}
          </div>

          {/* メッセージ */}
          <div className="messages-area" ref={messagesRef}>
            {renderedMsgs.map((m, i) => (
              <div key={i} className={`msg ${m.mine ? "me" : "them"}`}>
                <div className="msg-avatar">{m.mine ? "グ" : cas.initial}</div>
                <div>
                  <div className="msg-time">{m.time}</div>
                  <div className="bubble">{m.text}</div>
                </div>
              </div>
            ))}

            {activeIdx === 0 ? (
              <>
                <div className="date-sep">6月24日（火）</div>

                {showScheduleCard ? (
                  <div className="schedule-propose" id="schedule-propose">
                    <div className="sp-head">
                      <CalendarIc />
                      引き取り候補日を提案する
                    </div>
                    <div className="sp-options">
                      {slots.map((slot, i) => (
                        <div className="sp-opt-row" key={i}>
                          <input
                            type="text"
                            className="sp-date-input"
                            value={slot}
                            placeholder="日程を入力（例：7月13日（日）10:00〜12:00）"
                            onChange={(e) => updateSlot(i, e.target.value)}
                            aria-label={`候補日 ${i + 1}`}
                          />
                          <button type="button" className="sp-remove" onClick={() => removeSlot(i)} aria-label={`候補日 ${i + 1} を削除`}>
                            <Ic name="x" />
                          </button>
                        </div>
                      ))}
                    </div>
                    <button type="button" className="btn-add-slot" onClick={addSlot}>
                      ＋ 候補日を追加
                    </button>
                    <button type="button" className="btn-send-schedule" onClick={sendSchedule}>
                      候補日を送信する
                    </button>
                  </div>
                ) : null}

                <div className="msg me" style={{ marginTop: 4 }}>
                  <div className="msg-avatar">グ</div>
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
            <div className="input-tools">
              <button type="button" className="tool-btn" title="日程を提案" aria-label="日程を提案" onClick={toggleScheduleCard}>
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

        {/* 右パネル（出品内容） */}
        <aside className="detail-panel" aria-label="出品内容">
          <div className="dp-head">出品内容</div>
          <div className="dp-case-id">
            <div className="lbl">案件ID</div>
            <div className="val">{cas.caseId}</div>
          </div>
          <div className="dp-items-grid">
            {ITEM_THUMBS.map((it) => (
              <div className="dp-item-thumb" key={it.label}>
                <Ic name={it.ic} />
                <div className="dp-item-label">{it.label}</div>
              </div>
            ))}
            <div className="dp-item-thumb more">+{Math.max(cas.itemCount - ITEM_THUMBS.length, 0)}</div>
          </div>
          <div className="dp-info">
            <div className="dp-row">
              <span className="lbl">点数</span>
              <span className="val">{cas.itemCount}点</span>
            </div>
            <div className="dp-row">
              <span className="lbl">エリア</span>
              <span className="val">{cas.area}</span>
            </div>
            <div className="dp-row">
              <span className="lbl">合意額</span>
              <span className="val blue">{yen(cas.amount)}</span>
            </div>
            <div className="dp-row">
              <span className="lbl">手数料(8%)</span>
              <span className="val">{yen(cas.fee)}</span>
            </div>
            <div className="dp-row">
              <span className="lbl">ステータス</span>
              <span className="val green">{cas.statusLabel}</span>
            </div>
          </div>
          <button type="button" className="btn-propose" onClick={toggleScheduleCard}>
            <CalendarIc />
            引き取り日程を提案
          </button>
        </aside>
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
