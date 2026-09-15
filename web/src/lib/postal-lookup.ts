/**
 * 郵便番号からの住所自動補完（zipcloud 公開API・APIキー不要・CORS許可済み）。
 * https://zipcloud.ibsnet.co.jp/doc/api
 *
 * この機能は「入力の補助」であり必須の検証経路ではない（zipcloud が落ちていても
 * ユーザーは都道府県・市区町村を手入力できる）。そのため失敗時は例外を投げず null を
 * 返し、呼び出し側は「見つからなかった／取得できなかった」を区別せず静かにフォールバックする。
 */

export interface PostalLookupResult {
  /** 都道府県（例: "東京都"）。PREFECTURES の表記と一致する。 */
  prefecture: string;
  /** 市区町村（例: "渋谷区"）。 */
  city: string;
  /** 町域（例: "恵比寿"）。番地の前に来る部分で、住所欄1のプリセットに使う。 */
  town: string;
}

const ENDPOINT = "https://zipcloud.ibsnet.co.jp/api/search";

/** ハイフン・空白等を除いた数字のみの7桁郵便番号を返す（それ以外は null）。 */
export function normalizePostalDigits(raw: string): string | null {
  const digits = raw.replace(/[^\d]/g, "");
  return digits.length === 7 ? digits : null;
}

export async function lookupPostalCode(
  zipcodeDigits: string,
  signal?: AbortSignal,
): Promise<PostalLookupResult | null> {
  try {
    const res = await fetch(`${ENDPOINT}?zipcode=${encodeURIComponent(zipcodeDigits)}`, {
      signal,
    });
    if (!res.ok) return null;
    const data = (await res.json()) as {
      status: number;
      results: { address1: string; address2: string; address3: string }[] | null;
    };
    const first = data.results?.[0];
    if (!first) return null;
    return { prefecture: first.address1, city: first.address2, town: first.address3 };
  } catch {
    // AbortError（入力し直し等での取消）・ネットワーク断・JSON不正のいずれも
    // 「自動補完できなかった」として黙って諦める（呼び出し側で手入力を妨げない）。
    return null;
  }
}
