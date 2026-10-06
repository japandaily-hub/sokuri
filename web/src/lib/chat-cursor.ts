/**
 * チャットの差分ポーリング（`GET /transactions/{id}/messages?after=...`）のカーソル計算と重複排除（React 非依存）。
 *
 * 背景（QA M2）: backend の after は `created_at > after` の厳密比較。カーソルを
 * 「最後に取得した／自分が送信した created_at」にそのまま使うと、
 *  (a) 自分の送信成功でカーソルが進み、相手の発言が自分の送信より前にサーバーへ入っていると以後の差分に出ない
 *  (b) 作成時刻が同値・秒精度（SQLite。dev/E2E）だと厳密比較で同秒のメッセージが落ちる
 * ため取りこぼす。対策は「カーソルは取得したメッセージの最大 created_at だけで進める」＋
 * 「after には保持しているカーソルより CURSOR_OVERLAP_MS 手前を使い、返ってきた分は id で重複排除する」。
 * 根本対策（(created_at, id) の複合カーソル）は PROJECT_STATE の残課題。
 */

import { parseApiDateTime } from "./datetime.ts";

/** after に使うときにカーソルから引く重なり窓（ミリ秒）。ポーリング間隔 5 秒と同じ。 */
export const CURSOR_OVERLAP_MS = 5_000;

interface CursorMessage {
  id: string;
  created_at: string;
}

/** 取得したメッセージの最大 created_at（元の文字列のまま）。空・全て解釈不能なら undefined。 */
export function latestCreatedAt(messages: readonly CursorMessage[]): string | undefined {
  let best: string | undefined;
  let bestTime = Number.NEGATIVE_INFINITY;
  for (const m of messages) {
    const time = parseApiDateTime(m.created_at)?.getTime();
    if (time === undefined || Number.isNaN(time)) continue;
    if (time > bestTime) {
      bestTime = time;
      best = m.created_at;
    }
  }
  return best;
}

/**
 * 取得結果でカーソルを進める。単調増加（現在より古い値では戻さない）。
 * 取得が空なら現在のカーソルのまま。自分の送信成功ではこの関数を呼ばない（楽観的に一覧へ足すだけ）。
 */
export function advanceCursor(current: string | undefined, batch: readonly CursorMessage[]): string | undefined {
  const candidate = latestCreatedAt(batch);
  if (candidate === undefined) return current;
  if (current === undefined) return candidate;
  const currentTime = parseApiDateTime(current)?.getTime();
  const candidateTime = parseApiDateTime(candidate)?.getTime();
  if (currentTime === undefined || Number.isNaN(currentTime)) return candidate;
  if (candidateTime === undefined || Number.isNaN(candidateTime)) return current;
  return candidateTime > currentTime ? candidate : current;
}

/**
 * 差分取得の after クエリ値。カーソルが無い（初回）か解釈できなければ undefined（＝全件取得）。
 * 返す値は UTC の ISO 文字列（例 "2026-10-06T02:34:15.000Z"）。
 */
export function cursorToAfterParam(cursor: string | undefined, overlapMs: number = CURSOR_OVERLAP_MS): string | undefined {
  if (cursor === undefined) return undefined;
  const time = parseApiDateTime(cursor)?.getTime();
  if (time === undefined || Number.isNaN(time)) return undefined;
  return new Date(time - overlapMs).toISOString();
}

/** 既存の一覧へ、まだ無い id のメッセージだけを末尾に足す。足すものが無ければ同じ参照を返す（再描画を避ける）。 */
export function appendNewMessages<T extends { id: string }>(prev: readonly T[], batch: readonly T[]): readonly T[] {
  const knownIds = new Set(prev.map((m) => m.id));
  const fresh: T[] = [];
  for (const m of batch) {
    if (knownIds.has(m.id)) continue;
    knownIds.add(m.id);
    fresh.push(m);
  }
  return fresh.length > 0 ? [...prev, ...fresh] : prev;
}
