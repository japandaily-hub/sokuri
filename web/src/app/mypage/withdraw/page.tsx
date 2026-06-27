"use client";

/**
 * 退会・アカウント削除（/mypage/withdraw）。
 * デザイン正典: docs/design_handoff_katazuke/退会・アカウント削除.html をピクセル忠実に再現。
 * このルートは SiteChrome の BARE_PREFIXES（/mypage）対象で共通クロムが付かないため、
 * ページ自身が AppHeader（アプリ共通ヘッダー）と本文を描く。
 *
 * クライアント化の理由（純表示では不可）:
 *  - 3つの確認チェックが全てオンのときだけ削除ボタンを有効化（チェック連動）
 *  - パスワード未入力時のインラインエラー表示
 *  - 削除実行（デモ）→ スピナー → 完了パネルへ切替（バックエンド未配線のため実削除はしない）
 *
 * バックエンド未配線:
 *  - 削除対象データの件数（出品/成約数）は代表的なモック値。
 *  - 「アカウントを完全に削除する」は確認UIのみ。実際の削除APIは呼ばず、完了パネル表示で挙動を表現する。
 *  - パスワード照合も行わない（入力有無のチェックのみ）。
 */

import "./withdraw.css";

import { useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Field, PasswordField } from "@/components/kdz/auth";

// 削除対象データ（デモ。実際の件数はバックエンド集計に差し替える）
const DELETE_ITEMS: { icon: "user" | "list" | "chat"; title: string; desc: string }[] = [
  { icon: "user", title: "アカウント情報", desc: "名前・メールアドレス・設定" },
  { icon: "list", title: "出品データ・取引履歴", desc: "3件の出品・2件の成約記録" },
  { icon: "chat", title: "メッセージ履歴", desc: "業者とのやり取りすべて" },
];

const CHECK_ITEMS = [
  "上記のデータがすべて削除されることを理解しています",
  "進行中の取引・入札がある場合、自動的にキャンセルされます",
  "この操作は元に戻せないことを理解しています",
];

// スプライト未収録のアイコンはインラインで描画（trash / list / user）。
function DeleteItemIcon({ icon }: { icon: "user" | "list" | "chat" }) {
  if (icon === "chat") {
    // i-chat はスプライトに存在するが、退会画面では赤線・サイズ統一のため明示 SVG を使う
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" />
      </svg>
    );
  }
  if (icon === "list") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    );
  }
  // user
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

export default function WithdrawPage() {
  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [password, setPassword] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const allChecked = checks.every(Boolean);

  function toggleCheck(index: number) {
    setChecks((prev) => prev.map((v, i) => (i === index ? !v : v)));
  }

  function onDelete() {
    if (!password) {
      setPwErr("パスワードを入力してください");
      return;
    }
    setPwErr(null);
    setBusy(true);
    // バックエンド未配線: 実削除はせず、UI挙動（スピナー → 完了パネル）のみで表現する。
    window.setTimeout(() => {
      setBusy(false);
      setDone(true);
    }, 1500);
  }

  return (
    <div className="withdraw-page">
      <AppHeader unread />

      <main id="main">
        <div className="del-wrap">
          {/* 確認画面 */}
          <div className={`panel${done ? "" : " active"}`} id="panel-confirm">
            <div className="warn-banner">
              <div className="warn-ic">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 3.5L21 19H3L12 3.5z" />
                  <path d="M12 10v4M12 17h.01" />
                </svg>
              </div>
              <div className="warn-body">
                <strong>この操作は取り消せません</strong>
                <span>アカウントを削除すると、以下のデータがすべて完全に削除されます。</span>
              </div>
            </div>

            <div className="form-card">
              <div className="form-card-title">削除されるデータ</div>
              <div className="del-list">
                {DELETE_ITEMS.map((item) => (
                  <div className="del-item" key={item.title}>
                    <div className="del-item-ic">
                      <DeleteItemIcon icon={item.icon} />
                    </div>
                    <div className="del-item-body">
                      <strong>{item.title}</strong>
                      <span>{item.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 確認チェック */}
            <div className="form-card">
              <div className="form-card-title">削除前の確認</div>
              <div className="check-list">
                {CHECK_ITEMS.map((text, i) => (
                  <div className="check-row" key={i}>
                    <input
                      type="checkbox"
                      id={`chk${i + 1}`}
                      checked={checks[i]}
                      onChange={() => toggleCheck(i)}
                    />
                    <label htmlFor={`chk${i + 1}`}>{text}</label>
                  </div>
                ))}
              </div>
            </div>

            {/* パスワード確認 */}
            <div className="form-card">
              <div className="form-card-title">パスワードを入力して確認</div>
              <Field label="現在のパスワード" htmlFor="inp-pw" error={pwErr}>
                <PasswordField
                  id="inp-pw"
                  value={password}
                  onChange={(v) => {
                    setPassword(v);
                    if (pwErr) setPwErr(null);
                  }}
                  placeholder="パスワードを入力"
                />
              </Field>
            </div>

            <button
              type="button"
              className="btn-delete"
              id="btn-delete"
              disabled={!allChecked || busy}
              onClick={onDelete}
            >
              {busy ? (
                <>
                  <span className="spinning">↻</span> 削除中…
                </>
              ) : (
                <>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
                    <path d="M10 11v6M14 11v6" />
                    <path d="M9 6V4h6v2" />
                  </svg>
                  アカウントを完全に削除する
                </>
              )}
            </button>
            <div className="del-cancel">
              <Link href="/mypage/profile">キャンセルして戻る</Link>
            </div>
          </div>

          {/* 完了画面 */}
          <div className={`panel${done ? " active" : ""}`} id="panel-done">
            <div className="done-screen">
              <div className="done-mark">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M4 12.5l5.5 5.5L20 7" />
                </svg>
              </div>
              <h1 className="done-title">アカウントを削除しました</h1>
              <p className="done-sub">
                ご利用いただきありがとうございました。
                <br />
                またのご利用をお待ちしています。
              </p>
              <Link href="/" className="btn btn-primary btn-lg">
                トップページへ
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
