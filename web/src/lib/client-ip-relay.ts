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
 * （fail-safe）。このファイルは中継ヘッダを「作る」側（署名の組み立て・環境変数の
 * 読み取り）を担当する。auth.ts / line-link.ts の各呼び出し箇所への組み込みは完了
 * 済み（呼び出し箇所の一覧・守るべき不変条件は本ファイル末尾「組み込み状況」を
 * 参照）。backend 側の検証実装は別ファイル（backend/app/core/client_ip_relay.py・
 * 実装済み）。
 *
 * x-real-ip を信頼できる根拠:
 * Vercel はエッジ層でリクエストの x-real-ip ヘッダを実際の接続元IPで必ず上書きする
 * （Vercel公式ドキュメント）。そのため送信者側がこのヘッダに任意の値を仕込んでも
 * Vercel を経由した時点で上書きされ、偽装できない。この前提が崩れるのは「Vercel を
 * 経由していないとき」だけなので、Vercel の本番デプロイ（環境変数 VERCEL === "1" かつ
 * VERCEL_ENV === "production"）のときに限って x-real-ip を信頼する（ローカル開発・
 * Preview・他ホスティングでは無視し、中継ヘッダを付けない）。
 *
 * VERCEL_ENV も条件に含める理由（VERCEL === "1" だけでは不十分な理由）:
 * `vercel env pull` を引数なしで実行すると Development 環境変数を含む .env.local が
 * 手元に生成され、そこには VERCEL="1" は含まれるが VERCEL_ENV は "development"
 * になる（明示的に設定されなければ未定義のこともある）。この .env.local を使って
 * `next dev` を起動し、それを誤って LAN 等へ公開してしまうと、`next dev` は Vercel の
 * x-real-ip 上書きを経由しない（＝任意の第三者が x-real-ip ヘッダを自由に名乗れる）
 * にもかかわらず、VERCEL === "1" の判定だけを見ていると本番向けの正当な署名済み
 * ヘッダを誰でも作らせられてしまう。VERCEL_ENV === "production" も併せて要求する
 * ことでこの穴を塞ぐ。
 *
 * `vercel env pull --environment=production` を指定した場合の扱い（前提が崩れる
 * ケース）:
 * このオプション付きで実行すると Production 環境変数が対象になり、プロジェクト設定で
 * System Environment Variables の自動公開が有効な場合は .env.local に
 * VERCEL_ENV="production" が書き出されうる（上記の「development になる」という
 * 前提はこのケースでは成り立たない）。しかしこの場合でも、CLIENT_IP_RELAY_SECRET は
 * Vercel の Environment Variables に Sensitive 属性で設定する運用のため（下記「鍵の
 * 置き場所」参照）、Vercel は Sensitive な値を作成後に一切再表示しない仕様であり
 * `vercel env pull` の応答にも実際の値は含まれない。そのため
 * `--environment=production` で生成した .env.local を使って `next dev` を起動しても
 * CLIENT_IP_RELAY_SECRET は手元に存在せず、clientIpRelayHeaders は no_secret として
 * 中継を拒否する（fail-open。偽装された署名付きヘッダは作れない）。この no_secret は
 * 「Vercel の本番デプロイ自体で鍵の設定を忘れている」状態と字面上区別できないため、
 * 後者を見逃さないよう clientIpRelayHeaders は console.error で1回だけ通知する
 * （詳細は同関数の実装・JSDoc参照）。
 *
 * 鍵（CLIENT_IP_RELAY_SECRET）の置き場所:
 * Vercel の Environment Variables に Production 環境専用で設定する（Environment の
 * チェックボックスは Production のみを残し、Preview・Development のチェックを外す。
 * VERCEL_ENV !== "production" のデプロイでは本ヘルパー自体が中継しないため実害は
 * 無いが、値の漏洩経路を減らすため Preview/Development には値を入れない運用とする）。
 * Type は Sensitive 属性で設定する（ダッシュボード上で値を再表示不可にする）。
 * NEXT_PUBLIC_ を絶対に付けない（付けるとクライアントバンドルに焼き込まれ、利用者が
 * 任意のIPを名乗って署名を偽装できてしまう）。
 * backend 側は同じ値を保持する（正本は backend/app/core/client_ip_relay.py。鍵ローテー
 * ションのため backend 側は複数鍵の受理を想定しているが、web 側は常に1本の現行鍵で
 * 署名するだけでよい）。既知のテストベクトル鍵・パターン化された弱い鍵は
 * isKnownWeakRelaySecret が拒否する（詳細は同関数の JSDoc を参照）。
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
 * 組み込み状況（実装済み。以下3箇所から呼ばれている）:
 *   - web/src/auth.ts の backendLogin（/auth/login, /auth/operator/login）。
 *     呼び出し元は Credentials プロバイダの authorize（user-credentials /
 *     operator-credentials 共通・第2引数 request のヘッダを渡す）。
 *   - web/src/auth.ts の backendLineExchange（/auth/line/exchange）。
 *     呼び出し元は LINE プロバイダの signIn コールバック（readIncomingRequestHeaders
 *     経由で next/headers の headers() を渡す）。
 *   - web/src/lib/line-link.ts の linkLineToCurrentUser（/auth/line/exchange、
 *     Bearer付き）。呼び出し元は web/src/app/api/line/link/callback/route.ts
 *     （NextRequest.headers をそのまま渡す）。
 *
 * 上記いずれの呼び出し箇所でも次の3点を「守るべき不変条件」として維持すること
 * （どれか1つでも崩れると中継ヘッダ導入の意図が損なわれる。実装を変更する際は
 * 必ず維持されているか確認する。client-ip-relay-wiring.test.mts がこの一部を
 * 静的検査で自動検知する）:
 *   - fetch のオプションに redirect: "error" を指定する。既定の "follow" のままだと
 *     backend からの 3xx 応答に暗黙に追従してしまい、署名済み中継ヘッダとログイン用
 *     パスワードがリダイレクト先の任意のオリジンへそのまま送られる経路ができてしまう。
 *   - 受信リクエストのヘッダを丸ごと backend へ転送しない。clientIpRelayHeaders の
 *     戻り値（中継ヘッダ1本だけを含む Record）だけを fetch の headers にスプレッド
 *     する。
 *   - LINEログインの signIn コールバック（auth.ts の backendLineExchange）で
 *     incomingHeaders を得るために呼ぶ next/headers の headers() は、呼び出し文脈に
 *     よっては例外を投げうるため await headers() を try/catch で包み、失敗時は
 *     clientIpRelayHeaders の incomingHeaders 引数に null を渡す（null は
 *     no_client_ip として扱われ、中継ヘッダなしで fail-open する。本関数自体が
 *     incomingHeaders?.get の例外を最終的に捕捉するため二重の安全網にはなるが、
 *     signIn コールバック側で早期に捕捉した方が例外の発生箇所を特定しやすい）。
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

/**
 * attached:false のときに headers が {} になる理由。"not_production" 以外の値は
 * 検査順（buildClientIpRelayHeaders 参照）と対応する。"not_production" は
 * buildClientIpRelayHeaders（純関数。onVercel は boolean のまま）では発生せず、
 * ラッパー（clientIpRelayHeaders）が VERCEL="1" だが VERCEL_ENV !== "production" の
 * ときに独自に判定して返す（Vercel 上ではあるが本番デプロイではない状態を、
 * Vercel を経由していない not_on_vercel とは区別するため）。
 */
export type ClientIpRelaySkipReason =
  | "not_on_vercel"
  | "not_production"
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

/** isKnownWeakRelaySecret が完全一致で拒否する既知のテストベクトル鍵。backend側テストと共通の値。 */
const KNOWN_WEAK_RELAY_SECRET_EXACT_VALUES: readonly string[] = [
  "katazuke-relay-test-vector-A-0123456789abcdefghijklmnopqrstuvwxyz",
  "katazuke-relay-test-vector-B-0123456789abcdefghijklmnopqrstuvwxyz",
];

/** isKnownWeakRelaySecret が拒否する既知のテストベクトル鍵の接頭辞（大文字小文字を区別しない）。 */
const KNOWN_WEAK_RELAY_SECRET_PREFIXES: readonly string[] = ["katazuke-relay-test-", "http-relay-test-key-"];

/** isKnownWeakRelaySecret が「弱い」とみなす、使用文字種数の下限（この数未満なら弱いとみなす）。 */
const WEAK_RELAY_SECRET_MIN_UNIQUE_CHARS = 10;

/**
 * secret が既知のテストベクトル鍵、またはパターン化された弱い鍵かどうかを判定する。
 * isValidRelaySecret（長さ・許容文字種の字句検証）とは独立の追加検査であり、
 * 「字句としては有効だが実運用鍵として使うべきでない既知の値」を拒否する
 * （backend 側も同じ規則で鍵を拒否する。値・接頭辞・文字種数の下限を変更する場合は
 * backend 側の対応する検査も揃えて更新すること）。
 *
 * 判定規則（いずれか1つでも該当すれば true）:
 *   (a) このリポジトリのテストベクトルで使われている既知の鍵と完全一致する。
 *   (b) "katazuke-relay-test-" または "http-relay-test-key-" で始まる
 *       （大文字小文字を区別しない）。
 *   (c) 使われている文字の種類（Set化した文字数）が
 *       WEAK_RELAY_SECRET_MIN_UNIQUE_CHARS（10）種類未満
 *       （"aaaa...a" のような単調な値・低エントロピーな値を弾く）。
 *
 * buildClientIpRelayHeaders（純関数）はこの検査を行わない。既知ベクトルのテスト
 * （signClientIpRelay・buildClientIpRelayHeaders 自体のテスト）が意図的に KEY_A/
 * KEY_B を使い続けるため。この検査は環境変数から読んだ実運用鍵だけを対象にする
 * ラッパー（clientIpRelayHeaders）側で、isValidRelaySecret の後に使う。
 *
 * @param secret 環境変数から読んだ生の値（isValidRelaySecret を満たす前提。
 *   満たさない値を渡しても例外は投げないが、呼び出し側は isValidRelaySecret を
 *   先に確認してから呼ぶ想定）
 */
export function isKnownWeakRelaySecret(secret: string): boolean {
  if (KNOWN_WEAK_RELAY_SECRET_EXACT_VALUES.includes(secret)) return true;
  const lowered = secret.toLowerCase();
  if (KNOWN_WEAK_RELAY_SECRET_PREFIXES.some((prefix) => lowered.startsWith(prefix))) return true;
  return new Set(secret).size < WEAK_RELAY_SECRET_MIN_UNIQUE_CHARS;
}

/**
 * 署名対象の正規化メッセージを組み立てる。
 * method はこの関数の中で必ず大文字化する（署名生成・検証のいずれもこの関数を必ず
 * 経由するため、呼び出し側の大文字小文字表記に関わらず一貫した署名対象が得られる。
 * backend 側の canonical_relay_message と対称な設計。buildClientIpRelayHeaders は
 * 既に大文字化した値をここへ渡すが、String.prototype.toUpperCase は冪等なので
 * 二重適用しても結果は変わらない）。
 * path・timestamp・ip はあらかじめ字句検証済み（PATHは英数字と一部記号のみ・IPは
 * 16進数と "."/":"のみ・TSは数字のみ）のため、いずれのフィールドにも区切り文字
 * （改行）自体は現れず、フィールド混同（改行を挟んだ値がPATHとIPの境界を誤認させる
 * 等）は起きない。
 */
export function canonicalRelayMessage(
  method: string,
  path: string,
  timestamp: string,
  ip: string,
): string {
  return [CLIENT_IP_RELAY_SIGNING_CONTEXT, method.toUpperCase(), path, timestamp, ip].join("\n");
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
 *   6. url が https 以外のスキーム、または pathname/method が字句検証を通らない
 *                                                              → invalid_target
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
    const parsedUrl = new URL(url);
    // https 以外（http:・その他スキーム）には送らない。平文経路や想定外の宛先へ
    // 署名済み中継ヘッダ（利用者IPそのもの）を送出してしまう事故を防ぐ
    // （backend は常に https で運用しているため、実運用上の制約にはならない）。
    if (parsedUrl.protocol !== "https:") {
      return { attached: false, headers: {}, reason: "invalid_target" };
    }
    pathname = parsedUrl.pathname;
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
 * no_secret（VERCEL="1" かつ VERCEL_ENV="production" なのに CLIENT_IP_RELAY_SECRET が
 * 未設定）のログをプロセス内で1回だけ出すためのフラグ。invalid_secret と別フラグに
 * する理由: 原因（鍵が無い／鍵はあるが不正）が異なり、運用者が取るべき対応も異なる
 * （前者は鍵をまだ設定していない、後者は設定値が壊れている）ため、それぞれ独立に
 * 1回ずつ通知できるようにする。
 */
let loggedNoSecretInProductionOnce = false;

/**
 * (reason, target) の組み合わせごとに直近 console.warn を出した時刻（ミリ秒・
 * Date.now()）を記録する。スロットリング用（backend の ThrottledLogger と同じ
 * 「直近の発火から一定秒数未満は抑制し、それ以降は再び出す」方針。
 * app/core/log_throttle.py 参照）。キーは reason・target とも字句検証済みの
 * 文字種のみを想定するが、invalid_target 時の target は URL パース失敗により
 * "-" にもなるため、区切り文字混同を避けて JSON.stringify でタプル化して使う。
 */
const warnedAtMsByReasonAndTarget = new Map<string, number>();

/** console.warn のスロットリング間隔（ミリ秒）。backend の ThrottledLogger の既定値（60秒）と同じ。 */
const WARN_THROTTLE_INTERVAL_MS = 60_000;

/**
 * (reason, target) について、直近 WARN_THROTTLE_INTERVAL_MS 以内に既に警告済みで
 * なければ記録を更新して true（＝今回は警告してよい）を返す。既に警告済みなら
 * 記録を更新せず false を返す。
 */
function shouldWarnNow(reason: string, target: string): boolean {
  const key = JSON.stringify([reason, target]);
  const now = Date.now();
  const last = warnedAtMsByReasonAndTarget.get(key);
  if (last !== undefined && now - last < WARN_THROTTLE_INTERVAL_MS) {
    return false;
  }
  warnedAtMsByReasonAndTarget.set(key, now);
  return true;
}

/**
 * テスト専用: プロセス内グローバル状態（付与ログ済み target 集合・invalid_secret
 * 済みフラグ・no_secret（Vercel本番なのに鍵未設定）済みフラグ・console.warn の
 * スロットリング状態）を初期化する。このモジュールは複数のテストケースから同一
 * プロセス内で繰り返し呼ばれるため、各テストケースの実行前に呼ばないと「前の
 * テストケースで既にログ済み」という状態を引きずり、後続のテストが誤って
 * 「ログされなかった」と判定してしまう。
 */
export function _resetClientIpRelayLogStateForTests(): void {
  loggedAttachedTargets.clear();
  loggedInvalidSecretOnce = false;
  loggedNoSecretInProductionOnce = false;
  warnedAtMsByReasonAndTarget.clear();
}

/**
 * VERCEL / VERCEL_ENV 環境変数から、中継ヘッダの組み立てを試みてよい状態かどうかを
 * 判定する。"ok" 以外はいずれも buildClientIpRelayHeaders を呼ばずに確定させる
 * （本番デプロイでなければ secret・x-real-ip・URL の妥当性に関わらず中継しない
 * ため、それらの検証コスト自体が無駄になる）。VERCEL_ENV も条件に含める理由は
 * ファイル冒頭の JSDoc を参照（`vercel env pull` で取得した .env.local を使った
 * next dev を誤って公開してしまうケースへの対策）。
 */
function checkVercelProductionEnv(): "ok" | "not_on_vercel" | "not_production" {
  if (process.env.VERCEL !== "1") return "not_on_vercel";
  if (process.env.VERCEL_ENV !== "production") return "not_production";
  return "ok";
}

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
 * ログ出力ポリシー（no_secret）: VERCEL="1" かつ VERCEL_ENV="production"
 * （＝Vercelの本番デプロイ）であるにもかかわらず CLIENT_IP_RELAY_SECRET が未設定
 * だった場合は、プロセスごとに1回だけ console.error で通知する（鍵の値はそもそも
 * 読めていないため出しようがなく、IPも出さない）。本番デプロイの全面展開前（まだ
 * Vercel に鍵を投入していない移行期間）もこの条件に該当し、その間は呼び出しの都度
 * この分岐を通過する（1回だけログを出した後は無出力）。これは「中継ヘッダが効いて
 * おらず、backend が Vercel の送信元IPで回数制限している」実態を正しく示しているため
 * 想定どおりの挙動であり、鍵を投入すれば自然に発生しなくなる。
 *
 * buildClientIpRelayHeaders を呼ぶ前に、このラッパー固有の追加判定を行う
 * （いずれも該当すれば buildClientIpRelayHeaders を呼ばずに確定させる）:
 *   - checkVercelProductionEnv() が "ok" 以外 → その reason（not_on_vercel /
 *     not_production）で確定。
 *   - secret が isValidRelaySecret を満たし、かつ isKnownWeakRelaySecret も
 *     真（既知のテストベクトル鍵・パターン化された弱い鍵）→ invalid_secret で
 *     確定（backend も同じ規則で鍵を拒否するため対称）。
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
    const vercelCheck = checkVercelProductionEnv();
    const secret = process.env.CLIENT_IP_RELAY_SECRET;

    let result: ClientIpRelayResult;
    if (vercelCheck !== "ok") {
      result = { attached: false, headers: {}, reason: vercelCheck };
    } else if (secret && isValidRelaySecret(secret) && isKnownWeakRelaySecret(secret)) {
      result = { attached: false, headers: {}, reason: "invalid_secret" };
    } else {
      result = await buildClientIpRelayHeaders({
        method,
        url,
        incomingHeaders,
        secret,
        // vercelCheck === "ok" のときのみこの分岐に来るため、Vercel の本番デプロイ
        // であることは確定している。
        onVercel: true,
        nowEpochSeconds: Date.now() / 1000,
      });
    }

    if (result.attached) {
      if (!loggedAttachedTargets.has(target)) {
        loggedAttachedTargets.add(target);
        console.info("[client-ip-relay] 利用者IPの署名付き中継を付けて送信: target=%s", target);
      }
      return result.headers;
    }

    switch (result.reason) {
      case "not_on_vercel":
      case "not_production":
        // ローカル開発・Preview・本番以外のVercelデプロイでは中継しないのが
        // 正常系のため無出力。
        break;
      case "no_secret":
        // no_secretはvercelCheck==="ok"（Vercel本番デプロイ）の分岐でしか発生しない
        // （直前のif/else-ifを参照。vercelCheckが"ok"以外ならbuildClientIpRelayHeaders
        // 自体を呼ばずreasonを確定させているため）。本番デプロイなのに鍵が未設定という
        // 運用上見逃せない状態（全面展開前で鍵をまだ投入していない移行期間を含む）を
        // 一度だけ通知する。vercelCheckを併せて確認するのは、reasonの値だけに依存せず
        // 呼び出し元の条件を自己文書化するため（鍵の値はそもそも読めていないため出せない）。
        if (vercelCheck === "ok" && !loggedNoSecretInProductionOnce) {
          loggedNoSecretInProductionOnce = true;
          console.error(
            "[client-ip-relay] Vercel の本番なのに CLIENT_IP_RELAY_SECRET が未設定です。" +
              "ログイン・LINE の回数制限が Vercel の送信元 IP で数えられる状態（I8 以前）" +
              "に戻っています。",
          );
        }
        break;
      case "invalid_secret":
        if (!loggedInvalidSecretOnce) {
          loggedInvalidSecretOnce = true;
          console.error(
            "[client-ip-relay] CLIENT_IP_RELAY_SECRET が不正です" +
              "（%d文字以上・印字可能ASCII・空白およびカンマ不可、かつ既知のテスト用" +
              "鍵・低エントロピーな値ではない必要があります）",
            CLIENT_IP_RELAY_MIN_SECRET_LENGTH,
          );
        }
        break;
      default:
        if (shouldWarnNow(result.reason, target)) {
          console.warn(
            "[client-ip-relay] 中継ヘッダを付けずに送信: reason=%s target=%s",
            result.reason,
            target,
          );
        }
    }
    return {};
  } catch (e) {
    // 予期しない例外（incomingHeaders.get が想定外の実装で例外を投げる等）。例外名だけを
    // 出し、メッセージ本文（IPや鍵の値が混入し得る）は出さない。
    console.error("[client-ip-relay] 予期しない例外: %s", e instanceof Error ? e.name : "unknown");
    return {};
  }
}
