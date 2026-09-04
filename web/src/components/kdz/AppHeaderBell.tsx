"use client";

/**
 * 通知ベルの未読ドット（AppHeader から分離した client コンポーネント）。
 * 通知専用の一覧APIが無いため、自分の成約一覧（listTransactions）を取得し、
 * キャンセル以外の直近 MAX_CHECK 件について getTransaction で未読メッセージ数
 * （unread_count）を確認する。1件でも未読があればドットを表示する。
 * ページ遷移のたびに N+1 リクエストを撃たないよう、判定結果は sessionStorage に
 * CACHE_TTL_MS だけキャッシュする（レート制限と体感速度への配慮）。
 * 取得に失敗しても画面は止めず、ドットを出さないまま console.warn するだけに留める。
 * 未ログイン時（401）は静かに無視する。backend JWT が失効している場合も、
 * listTransactions/getTransaction に { decorative: true } を渡すことで
 * 強制ログアウト後の画面遷移・文言表示を発生させない（r6-fix-frontend4）。
 */

import { useEffect, useState } from "react";
import { useToken } from "./Ui";
import { listTransactions, getTransaction, KdzApiError, LIST_MAX_LIMIT } from "@/lib/katadzuke-api";

/** 未読判定のために詳細取得する成約の上限件数。 */
const MAX_CHECK = 5;
/** 判定結果のキャッシュ有効期間（ミリ秒）。 */
const CACHE_TTL_MS = 60_000;
const CACHE_KEY_PREFIX = "kdz.headerBell.unread.";

/** トークン文字列から短い非可逆ハッシュを作る（キャッシュキーをユーザー単位に分けるためだけの用途）。 */
function cacheKeyFor(token: string): string {
  let h = 0;
  for (let i = 0; i < token.length; i++) h = (h * 31 + token.charCodeAt(i)) | 0;
  return CACHE_KEY_PREFIX + (h >>> 0).toString(36);
}

/** ログアウト時などに、この機能が書いた sessionStorage を全て捨てる。 */
export function clearHeaderBellCache() {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const k = window.sessionStorage.key(i);
      if (k && k.startsWith(CACHE_KEY_PREFIX)) keys.push(k);
    }
    keys.forEach((k) => window.sessionStorage.removeItem(k));
  } catch {
    /* sessionStorage が使えない環境では何もしない */
  }
}

function readCache(key: string): boolean | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const { unread, at } = JSON.parse(raw) as { unread: boolean; at: number };
    if (typeof unread !== "boolean" || typeof at !== "number") return null;
    return Date.now() - at < CACHE_TTL_MS ? unread : null;
  } catch {
    return null;
  }
}

function writeCache(key: string, unread: boolean) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify({ unread, at: Date.now() }));
  } catch {
    /* sessionStorage が使えない環境では単にキャッシュしない */
  }
}

export function AppHeaderBell() {
  const { token } = useToken();
  const [unread, setUnread] = useState(false);

  useEffect(() => {
    if (!token) return;
    const key = cacheKeyFor(token);
    const cached = readCache(key);
    if (cached !== null) {
      setUnread(cached);
      return;
    }
    let cancelled = false;

    (async () => {
      try {
        // limit 200（r6-verify L5）。それでも直近のアクティブな取引が0件（＝先頭が
        // キャンセル済みで埋まっている等）の場合のみ、2ページ目まで読みに行く。
        // decorative: true — このベルは装飾的な付随情報であり、backend JWT が
        // 失効していても強制ログアウト＋画面遷移を発生させてはならない
        // （r6-fix-frontend4）。
        const decorative = { decorative: true };
        let txns = await listTransactions(token, { limit: LIST_MAX_LIMIT, offset: 0 }, decorative);
        let active = txns.filter((t) => t.status !== "cancelled").slice(0, MAX_CHECK);
        if (active.length === 0 && txns.length === LIST_MAX_LIMIT) {
          const page2 = await listTransactions(
            token,
            { limit: LIST_MAX_LIMIT, offset: txns.length },
            decorative,
          );
          txns = txns.concat(page2);
          active = txns.filter((t) => t.status !== "cancelled").slice(0, MAX_CHECK);
        }
        let found = false;
        for (const t of active) {
          if (cancelled) return;
          const detail = await getTransaction(t.id, token, decorative);
          if (detail.unread_count > 0) {
            found = true;
            break;
          }
        }
        if (cancelled) return;
        writeCache(key, found);
        setUnread(found);
      } catch (err) {
        if (err instanceof KdzApiError && err.status === 401) return;
        console.warn("通知未読件数の取得に失敗しました", err instanceof Error ? err.message : String(err));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!unread) return null;
  return (
    <span
      aria-hidden="true"
      style={{
        position: "absolute",
        top: 7,
        right: 8,
        width: 9,
        height: 9,
        borderRadius: "50%",
        background: "var(--danger)",
        border: "2px solid var(--white)",
      }}
    />
  );
}
