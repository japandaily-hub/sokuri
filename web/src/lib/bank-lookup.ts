/**
 * 銀行名・支店名からの候補検索（bank.teraren.com 公開API・APIキー不要・CORS許可済み）。
 * https://bank.teraren.com/openapi/bank.teraren.com.yml
 *
 * postal-lookup.ts と同じ思想:「入力の補助」であり必須の検証経路ではない。
 * bank.teraren.com が落ちていても、あるいは該当が無くても、ユーザーは銀行名・支店名を
 * 従来どおり自由入力できる。そのため失敗時は例外を投げず空配列を返し、呼び出し側は
 * 「見つからなかった／取得できなかった」を区別せず静かにフォールバックする。
 *
 * 実装上の注意（2026-09-16 実機確認）:
 *  - `/banks.json` および `/banks/:code/branches.json` の `name` クエリは OpenAPI 上は
 *    フィルタ用パラメータに見えるが、実際には無視され常に先頭50件（1ページ目）が返る。
 *    部分一致検索には専用の検索エンドポイント `/banks/search.json` /
 *    `/banks/:code/branches/search.json` を使うこと（こちらは正しく絞り込まれる）。
 *  - 検索クエリには銀行名・支店名の文字列のみを送信する（氏名・口座番号等の個人情報は含めない）。
 */

import { useEffect, useState } from "react";

export interface BankSuggestion {
  /** 全銀コード（4桁）。支店検索の絞り込みに使う。 */
  code: string;
  /** 表示名（正式名称、例: "三菱UFJ銀行"）。選択時にそのまま入力欄へ反映する。 */
  name: string;
}

export interface BranchSuggestion {
  /** 支店コード（3桁）。 */
  code: string;
  /** 表示名（正式名称、例: "丸の内支店"）。 */
  name: string;
}

const BANKS_SEARCH_ENDPOINT = "https://bank.teraren.com/banks/search.json";
const BANKS_BASE = "https://bank.teraren.com/banks";

/** 一度に表示する候補の上限（多すぎるドロップダウンを避ける）。 */
const MAX_SUGGESTIONS = 20;

interface RawBankOrBranch {
  code: string;
  name: string;
  normalize?: { name?: string };
}

function toSuggestion(raw: RawBankOrBranch): BankSuggestion {
  // normalize.name は「三菱UFJ銀行」「丸の内支店」のように銀行/支店の接尾辞まで含む
  // 正式表記のため、通帳表記に近いこちらを優先して表示・入力する。
  return { code: raw.code, name: raw.normalize?.name || raw.name };
}

/** 全銀コード4桁の形式かどうか（支店検索に使えるかの簡易チェック）。 */
export function isValidBankCode(code: string): boolean {
  return /^\d{4}$/.test(code);
}

export async function searchBanks(query: string, signal?: AbortSignal): Promise<BankSuggestion[]> {
  const trimmed = query.trim();
  if (!trimmed) return [];
  try {
    const res = await fetch(`${BANKS_SEARCH_ENDPOINT}?name=${encodeURIComponent(trimmed)}`, { signal });
    if (!res.ok) return [];
    const data = (await res.json()) as RawBankOrBranch[];
    if (!Array.isArray(data)) return [];
    return data.slice(0, MAX_SUGGESTIONS).map(toSuggestion);
  } catch {
    // AbortError（入力し直し等での取消）・ネットワーク断・JSON不正のいずれも
    // 「候補を取得できなかった」として黙って諦める（呼び出し側で手入力を妨げない）。
    return [];
  }
}

export async function searchBranches(
  bankCode: string,
  query: string,
  signal?: AbortSignal,
): Promise<BranchSuggestion[]> {
  const trimmed = query.trim();
  if (!isValidBankCode(bankCode) || !trimmed) return [];
  try {
    const res = await fetch(
      `${BANKS_BASE}/${encodeURIComponent(bankCode)}/branches/search.json?name=${encodeURIComponent(trimmed)}`,
      { signal },
    );
    if (!res.ok) return [];
    const data = (await res.json()) as RawBankOrBranch[];
    if (!Array.isArray(data)) return [];
    return data.slice(0, MAX_SUGGESTIONS).map(toSuggestion);
  } catch {
    return [];
  }
}

/** 何文字目からデバウンス検索を開始するか（1文字だけでは候補が多すぎてノイズになる）。 */
const MIN_QUERY_LENGTH = 2;
/** デバウンス間隔（postal-lookup は即時1回叩きだが、こちらは1文字ごとにAPIを叩くため間引く）。 */
const DEBOUNCE_MS = 300;

export interface SuggestionState<T> {
  suggestions: T[];
  loading: boolean;
}

/**
 * 銀行名のオートコンプリート用フック。2文字以上の入力から300msデバウンスして検索する。
 * postal-lookup と同じ思想で、取得できなくても呼び出し側（フォーム入力）を妨げない
 * （suggestions が空になるだけで、入力欄の値そのものには一切手を入れない）。
 */
export function useBankSuggestions(query: string): SuggestionState<BankSuggestion> {
  const [suggestions, setSuggestions] = useState<BankSuggestion[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void searchBanks(trimmed, controller.signal).then((results) => {
        if (controller.signal.aborted) return;
        setSuggestions(results);
        setLoading(false);
      });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  return { suggestions, loading };
}

/**
 * 支店名のオートコンプリート用フック。銀行が選択されていない（bankCode が null・不正な形式）
 * 間は検索を行わず常に空を返す（銀行未選択でも支店名の自由入力自体は妨げない）。
 */
export function useBranchSuggestions(
  bankCode: string | null,
  query: string,
): SuggestionState<BranchSuggestion> {
  const [suggestions, setSuggestions] = useState<BranchSuggestion[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const trimmed = query.trim();
    if (!bankCode || !isValidBankCode(bankCode) || trimmed.length < MIN_QUERY_LENGTH) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void searchBranches(bankCode, trimmed, controller.signal).then((results) => {
        if (controller.signal.aborted) return;
        setSuggestions(results);
        setLoading(false);
      });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [bankCode, query]);

  return { suggestions, loading };
}
