/**
 * 利用者IPの署名付き中継ヘッダ — web(Vercel) → backend 呼び出し専用ヘルパー。
 *
 * 背景（是正対象の問題）:
 * backend は IP 単位でログイン試行回数を制限しているが、NextAuth の authorize()
 * （auth.ts の backendLogin）・LINEログインの signIn コールバック（auth.ts の
 * backendLineExchange）・LINE通知の後付け連携（line-link.ts の linkLineToCurrentUser）は
 * いずれも web のサーバー側（Vercel の実行環境）から backend へ fetch するため、backend
 * からは「Vercel の送信元IP」しか見えず、実際の利用者ではなく Vercel 側のIPで回数が
 * 数えられてしまっていた（同じ経路を通る全利用者が同じカウンタを共有してしまう）。
 *
 * 対策: web が Vercel から渡される x-real-ip（下記参照）を読み取り、HMAC-SHA256 で
 * 署名した1本のヘッダに包んで backend へ中継する。backend は署名が正しい場合のみ
 * ヘッダの値を「利用者IP」として採用し、正しくなければ従来通り接続元IPで数える
 * （fail-safe）。このファイルは中継ヘッダを「作る」側だけを担当する。実際に
 * auth.ts / line-link.ts の各呼び出し箇所へ組み込む作業と、backend 側の検証実装は
 * 別スコープ（後日・別セッションで対応）。
 *
 * x-real-ip を信頼できる根拠:
 * Vercel はエッジ層でリクエストの x-real-ip ヘッダを実際の接続元IPで必ず上書きする
 * （Vercel公式ドキュメント）。そのため送信者側がこのヘッダに任意の値を仕込んでも
 * Vercel を経由した時点で上書きされ、偽装できない。この前提が崩れるのは「Vercel を
 * 経由していないとき」だけなので、onVercel（環境変数 VERCEL === "1"）が true のとき
 * に限って x-real-ip を信頼する（ローカル開発・他ホスティングでは無視し、中継ヘッダを
 * 付けない）。
 *
 * 鍵（CLIENT_IP_RELAY_SECRET）の置き場所:
 * Vercel の Environment Variables に Production 環境専用（Preview/Development には
 * 設定しない）・Sensitive 属性で設定する。NEXT_PUBLIC_ を絶対に付けない（付けると
 * クライアントバンドルに焼き込まれ、利用者が任意のIPを名乗って署名を偽装できてしまう）。
 * backend 側は同じ値を保持する（正本は backend/app/core/client_ip_relay.py。鍵ローテー
 * ションのため backend 側は複数鍵の受理を想定しているが、web 側は常に1本の現行鍵で
 * 署名するだけでよい）。
 *
 * ヘッダ形式と署名対象:
 * ヘッダ名は CLIENT_IP_RELAY_HEADER、値は
 * "v1;<UNIX秒10桁>;<x-real-ipの生値>;<HMAC-SHA256の16進64桁・小文字>"。
 * 署名対象メッセージは canonicalRelayMessage が組み立てる
 * "[CLIENT_IP_RELAY_SIGNING_CONTEXT, METHOD, PATH, TS, IP].join(改行)"
 * （METHODは大文字に正規化・PATHはクエリを含まない・TSはUNIX秒10桁）。タイムスタンプを
 * 含めるのは、漏洩したヘッダ値を後から backend へ再送するリプレイ攻撃を、backend 側の
 * 許容時間幅チェックで防げるようにするため。
 *
 * node: を使わない理由:
 * web/src/middleware.ts が auth.ts を import しており、auth.ts は Vercel の Edge 実行
 * 環境にもバンドルされうる。Next.js 15.5 は Edge 向けバンドルに node:crypto / node:net
 * 等の node: プレフィックス付き import が混ざっていると警告を出しつつ置き換えを行う
 * （挙動が実行環境ごとに変わりうる）。Web Crypto（globalThis.crypto.subtle）は Node 24・
 * Vercel の Node runtime・Edge runtime のいずれでも同一APIで動くため、実行環境を問わず
 * 同じコードで完結させられる。
 *
 * 型除去（type stripping）だけで動かすための制約:
 * node --test はこのファイルを事前コンパイルせず、型注釈を消すだけで実行する
 * （理由の詳細は client-ip-relay.test.mts 冒頭・safe-path.test.mts 冒頭を参照）。その
 * ため enum・namespace・コンストラクタ引数プロパティ・satisfies 等、型注釈の削除だけ
 * では元の意味を保てない構文は使わない。process.env の参照は分割代入・動的キーを使わず
 * 必ずリテラルで書く。
 *
 * 組み込み予定（このファイル単体では未接続。別セッションで組み込まれる想定）:
 *   - auth.ts の backendLogin（/auth/login, /auth/operator/login）
 *   - auth.ts の backendLineExchange（/auth/line/exchange）
 *   - line-link.ts の linkLineToCurrentUser（/auth/line/exchange、Bearer付き）
 */

/** 中継ヘッダ名。 */
export const CLIENT_IP_RELAY_HEADER = "x-katazuke-client-ip-relay";

/**
 * 署名対象メッセージの先頭に必ず含める識別子。用途違いのHMAC値との取り違え防止と、
 * 将来ヘッダ形式を変える場合のバージョン識別を兼ねる（"v1" はヘッダ値側にも現れる）。
 */
export const CLIENT_IP_RELAY_SIGNING_CONTEXT = "katazuke-client-ip-relay/v1";

/** CLIENT_IP_RELAY_SECRET の最小文字数。HMAC-SHA256の鍵として十分な強度を確保する下限。 */
export const CLIENT_IP_RELAY_MIN_SECRET_LENGTH = 32;

/** Headers / ReadonlyHeaders（next/headers） / NextRequest.headers のいずれも満たす最小形。 */
export type HeaderReader = { get(name: string): string | null };

/** attached:false のときに headers が {} になる理由。値は検査順（buildClientIpRelayHeaders 参照）と対応する。 */
export type ClientIpRelaySkipReason =
  | "not_on_vercel"
  | "no_secret"
  | "invalid_secret"
  | "no_client_ip"
  | "invalid_client_ip"
  | "invalid_target"
  | "sign_failed";

export type ClientIpRelayResult =
  | { attached: true; headers: Record<string, string> }
  | { attached: false; headers: Record<string, string>; reason: ClientIpRelaySkipReason };

/**
 * CLIENT_IP_RELAY_SECRET として許容する文字種の検証用パターン。
 * 印字可能ASCII（0x21〜0x7E）のみを許可し、カンマ（0x2C）を除く
 * （0x21-0x2B と 0x2D-0x7E の2レンジで表現し、その間の 0x2C だけを弾く）。
 * 空白（0x20）はレンジ外のため自動的に禁止される。環境変数の設定ミス（改行混入・
 * 前後の空白・カンマ区切り値の誤結合等）を invalid_secret として早期検知するための
 * 字句検証であり、鍵としての強度は呼び出し側が32文字以上のランダム値を用意する運用で
 * 担保する。
 */
const RELAY_SECRET_PATTERN = /^[\x21-\x2b\x2d-\x7e]+$/;

/** x-real-ip に許可する文字種（IPv4/IPv6のいずれの表記もこの範囲に収まる）。 */
const RELAY_IP_CHARSET_PATTERN = /^[0-9A-Fa-f:.]+$/;

/** IPv4の各オクテット。先頭ゼロ（"01" 等）を許可しない厳格な表記のみ許可する。 */
const RELAY_IPV4_OCTET_SOURCE = "(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])";

/** ドット区切り4個のIPv4厳格パターン（先頭ゼロ不可）。 */
const RELAY_IPV4_PATTERN = new RegExp(`^${RELAY_IPV4_OCTET_SOURCE}(\\.${RELAY_IPV4_OCTET_SOURCE}){3}$`);

/**
 * 署名対象に使うパス（new URL(url).pathname）に許可する文字種。
 * 先頭は必ず "/"、以降は英数字・"/"・"_"・"."・"-" のみ、全体で最大256文字（先頭の
 * "/" を含む）。それ以外（%エンコードの残存・"@"・空白等）は invalid_target として
 * 拒否する（許可文字を絞ることで、署名対象メッセージの区切り文字である改行が別
 * フィールドの値と混同される余地を最初から無くす）。
 */
const RELAY_PATH_PATTERN = /^\/[A-Za-z0-9/_.-]{0,255}$/;

/** 署名対象に使うHTTPメソッド（大文字正規化後）に許可するパターン。英大文字のみ・最大16文字。 */
const RELAY_METHOD_PATTERN = /^[A-Z]{1,16}$/;

/** UNIX秒10桁（2001-09-09〜2286-11-20）のみ許可する。 */
const RELAY_TIMESTAMP_PATTERN = /^[0-9]{10}$/;

/** バイト列を小文字16進数文字列に変換する。node:buffer の Buffer に依存しないための自前実装。 */
function bytesToHex(bytes: Uint8Array): string {
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

/**
 * x-real-ip の値を中継してよい形式かどうかだけを判定する（プライベートIP・ループバック
 * 等を中継すべきでないというポリシー判断は行わない。それは backend 側だけの責務）。
 *
 * IPv6は自前で全構文を実装せず、WHATWG URL パーサの角括弧ホスト構文検証
 * （new URL("http://[" + raw + "]/") が例外を投げないか）に委譲する。ブラウザ・Node・
 * Edge runtime のいずれも同じ WHATWG URL Standard を実装しているため、実行環境を問わず
 * 判定結果が一致する。
 *
 * @param raw incomingHeaders.get("x-real-ip") で得た生の値
 */
export function isRelayableClientIp(raw: string): boolean {
  if (raw.length < 2 || raw.length > 45) return false;
  if (!RELAY_IP_CHARSET_PATTERN.test(raw)) return false;
  if (!raw.includes(":")) return RELAY_IPV4_PATTERN.test(raw);
  try {
    new URL(`http://[${raw}]/`);
    return true;
  } catch {
    return false;
  }
}

/**
 * CLIENT_IP_RELAY_SECRET が最小長・許容文字種を満たすかを検証する。
 * @param secret 環境変数から読んだ生の値
 */
export function isValidRelaySecret(secret: string): boolean {
  return secret.length >= CLIENT_IP_RELAY_MIN_SECRET_LENGTH && RELAY_SECRET_PATTERN.test(secret);
}

/**
 * 署名対象の正規化メッセージを組み立てる。
 * 各フィールドはあらかじめ字句検証済み（PATHは英数字と一部記号のみ・IPは16進数と
 * "."/":"のみ・METHODは英大文字のみ・TSは数字のみ）のため、いずれのフィールドにも
 * 区切り文字（改行）自体は現れず、フィールド混同（改行を挟んだ値がPATHとIPの境界を
 * 誤認させる等）は起きない。
 */
export function canonicalRelayMessage(
  method: string,
  path: string,
  timestamp: string,
  ip: string,
): string {
  return [CLIENT_IP_RELAY_SIGNING_CONTEXT, method, path, timestamp, ip].join("\n");
}

/**
 * HMAC-SHA256 で署名し、小文字16進数64桁の文字列を返す。
 * node:crypto ではなく Web Crypto（globalThis.crypto.subtle）を使う理由はファイル冒頭を
 * 参照。
 * @throws secret が Web Crypto の鍵インポートで拒否された場合など（呼び出し前に
 *   isValidRelaySecret で検証しておくこと）
 */
export async function signClientIpRelay(secret: string, message: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await globalThis.crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await globalThis.crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return bytesToHex(new Uint8Array(signature));
}

/**
 * 利用者IPの署名付き中継ヘッダを組み立てる（環境変数を読まない純関数）。
 * 環境依存（secret・onVercel・現在時刻）を全て引数化しているため、clientIpRelayHeaders
 * を介さずテストできる。
 *
 * 判定は次の順で行い、最初に該当した理由で { attached: false, headers: {}, reason } を
 * 返す。途中の判定を全て通過した場合のみ署名して attached: true を返す。
 *   1. onVercel が false                                     → not_on_vercel
 *   2. secret が undefined/空文字                             → no_secret
 *   3. secret が isValidRelaySecret を満たさない               → invalid_secret
 *   4. incomingHeaders?.get("x-real-ip") が null/空文字        → no_client_ip
 *   5. isRelayableClientIp を満たさない                        → invalid_client_ip
 *   6. url の pathname または method が字句検証を通らない       → invalid_target
 *   7. nowEpochSeconds から作ったタイムスタンプが10桁の数字でない → sign_failed
 *   8. 署名処理（Web Crypto）が例外を投げる                     → sign_failed
 */
export async function buildClientIpRelayHeaders(input: {
  method: string;
  url: string;
  incomingHeaders: HeaderReader | null | undefined;
  secret: string | undefined;
  onVercel: boolean;
  nowEpochSeconds: number;
}): Promise<ClientIpRelayResult> {
  const { method, url, incomingHeaders, secret, onVercel, nowEpochSeconds } = input;

  if (!onVercel) return { attached: false, headers: {}, reason: "not_on_vercel" };
  if (!secret) return { attached: false, headers: {}, reason: "no_secret" };
  if (!isValidRelaySecret(secret)) return { attached: false, headers: {}, reason: "invalid_secret" };

  const clientIp = incomingHeaders?.get("x-real-ip");
  if (!clientIp) return { attached: false, headers: {}, reason: "no_client_ip" };
  if (!isRelayableClientIp(clientIp)) {
    return { attached: false, headers: {}, reason: "invalid_client_ip" };
  }

  let pathname: string;
  try {
    pathname = new URL(url).pathname;
  } catch {
    return { attached: false, headers: {}, reason: "invalid_target" };
  }
  const normalizedMethod = method.toUpperCase();
  if (!RELAY_PATH_PATTERN.test(pathname) || !RELAY_METHOD_PATTERN.test(normalizedMethod)) {
    return { attached: false, headers: {}, reason: "invalid_target" };
  }

  const timestamp = String(Math.floor(nowEpochSeconds));
  if (!RELAY_TIMESTAMP_PATTERN.test(timestamp)) {
    return { attached: false, headers: {}, reason: "sign_failed" };
  }

  try {
    const message = canonicalRelayMessage(normalizedMethod, pathname, timestamp, clientIp);
    const signature = await signClientIpRelay(secret, message);
    return {
      attached: true,
      headers: { [CLIENT_IP_RELAY_HEADER]: `v1;${timestamp};${clientIp};${signature}` },
    };
  } catch {
    return { attached: false, headers: {}, reason: "sign_failed" };
  }
}

/** "付与した" ログを target(path) ごとに1回だけ出すための記録（プロセス内・コールドスタートでリセットされる）。 */
const loggedAttachedTargets = new Set<string>();

/** invalid_secret のログをプロセス内で1回だけ出すためのフラグ。 */
let loggedInvalidSecretOnce = false;

/**
 * 環境変数を読み、利用者IPの署名付き中継ヘッダを組み立てるラッパー。
 * 認証経路（auth.ts の backendLogin/backendLineExchange、line-link.ts の
 * linkLineToCurrentUser）から直接呼ばれる想定のため、いかなる入力・実行環境でも例外を
 * 投げない（失敗時は中継ヘッダなしで {} を返し、呼び出し元の fetch は中継ヘッダ無しで
 * 従来どおり進む＝fail-open。backend 側のIP単位レート制限が中継ヘッダ導入前の挙動に
 * 戻るだけで、ログイン機能自体は止めない）。
 *
 * 受信ヘッダを丸ごと転送することはせず、組み立てた1本のヘッダだけを返す。
 *
 * @param method fetch の method（大文字小文字は問わない）
 * @param url fetch 先の完全なURL
 * @param incomingHeaders 受信リクエストのヘッダ（Next.js の headers() の戻り値や
 *   NextRequest.headers）。x-real-ip の読み出しにのみ使う。
 * @returns 呼び出し先 fetch の headers にスプレッドできる Record。中継できない場合は
 *   空オブジェクト（呼び出し側は分岐せず常にスプレッドしてよい）。
 */
export async function clientIpRelayHeaders(
  method: string,
  url: string,
  incomingHeaders: HeaderReader | null | undefined,
): Promise<Record<string, string>> {
  // ログ表示用のtargetのみを先に確定する。urlが不正な場合はbuild側もinvalid_targetと
  // して扱うため、ログ上も安全な代替表記に留める（rawなurl文字列はログに出さない。
  // クエリに機微情報が含まれる可能性を考慮する）。
  let target = "-";
  try {
    target = new URL(url).pathname;
  } catch {
    /* target は "-" のまま。reason は下の build 呼び出しが invalid_target として確定する */
  }

  try {
    const result = await buildClientIpRelayHeaders({
      method,
      url,
      incomingHeaders,
      secret: process.env.CLIENT_IP_RELAY_SECRET,
      onVercel: process.env.VERCEL === "1",
      nowEpochSeconds: Date.now() / 1000,
    });

    if (result.attached) {
      if (!loggedAttachedTargets.has(target)) {
        loggedAttachedTargets.add(target);
        console.info("[client-ip-relay] 利用者IPの署名付き中継を付けて送信: target=%s", target);
      }
      return result.headers;
    }

    switch (result.reason) {
      case "not_on_vercel":
      case "no_secret":
        // ローカル開発・プレビュー環境では未設定が正常系のため無出力。
        break;
      case "invalid_secret":
        if (!loggedInvalidSecretOnce) {
          loggedInvalidSecretOnce = true;
          console.error(
            "[client-ip-relay] CLIENT_IP_RELAY_SECRET が不正です" +
              "（%d文字以上・印字可能ASCII・空白およびカンマ不可である必要があります）",
            CLIENT_IP_RELAY_MIN_SECRET_LENGTH,
          );
        }
        break;
      default:
        console.warn(
          "[client-ip-relay] 中継ヘッダを付けずに送信: reason=%s target=%s",
          result.reason,
          target,
        );
    }
    return {};
  } catch (e) {
    // 予期しない例外（incomingHeaders.get が想定外の実装で例外を投げる等）。例外名だけを
    // 出し、メッセージ本文（IPや鍵の値が混入し得る）は出さない。
    console.error("[client-ip-relay] 予期しない例外: %s", e instanceof Error ? e.name : "unknown");
    return {};
  }
}
