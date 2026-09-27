/**
 * client-ip-relay.ts（利用者IPの署名付き中継ヘッダ）の回帰テスト。
 *
 * 実行（cwd は web）:
 *   node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON src/lib/client-ip-relay.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts と同じ（tsconfig の include に一致させず、型検査・ビルドの対象から
 * 外したまま実行できるようにするため）。
 *
 * 既知ベクトル（V1〜V3・否定2件）は backend 側の実装（backend/app/core/client_ip_relay.py）
 * のテストにも同じ値が入っている。web・backend のどちらかだけで正規化やHMACの実装が
 * ズレたら双方のテストが同時に落ちて検知できるよう、値は絶対に変えない。
 */
import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";

import {
  CLIENT_IP_RELAY_HEADER,
  CLIENT_IP_RELAY_MIN_SECRET_LENGTH,
  CLIENT_IP_RELAY_SIGNING_CONTEXT,
  _resetClientIpRelayLogStateForTests,
  buildClientIpRelayHeaders,
  canonicalRelayMessage,
  clientIpRelayHeaders,
  isKnownWeakRelaySecret,
  isRelayableClientIp,
  isValidRelaySecret,
  signClientIpRelay,
  type ClientIpRelaySkipReason,
  type HeaderReader,
} from "./client-ip-relay.ts";

/** 既知ベクトル用の鍵（本番の値ではない・テスト専用）。backend側テストと共通の値。 */
const KEY_A = "katazuke-relay-test-vector-A-0123456789abcdefghijklmnopqrstuvwxyz";
const KEY_B = "katazuke-relay-test-vector-B-0123456789abcdefghijklmnopqrstuvwxyz";

const BACKEND_LOGIN_URL = "https://sokuri-backend.onrender.com/api/v1/auth/login";

/** name→value の単純な Map から HeaderReader を作る。 */
function headersOf(values: Readonly<Record<string, string>>): HeaderReader {
  return {
    get(name: string): string | null {
      return Object.prototype.hasOwnProperty.call(values, name) ? values[name] : null;
    },
  };
}

/**
 * clientIpRelayHeaders（環境変数ラッパー）のテスト専用: 実運用鍵を模した、十分に
 * 長く高エントロピーなランダム英数字を生成する（isKnownWeakRelaySecret に該当
 * しないことを期待する値。KEY_A/KEY_B は既知の弱い鍵として拒否されるようになった
 * ため、ラッパーのテストでは本関数を使う。純関数 buildClientIpRelayHeaders の
 * 既知ベクトルテストでは引き続き KEY_A/KEY_B を使う）。
 */
function randomRelaySecret(): string {
  const CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = new Uint8Array(48);
  globalThis.crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += CHARS[bytes[i] % CHARS.length];
  }
  return out;
}

// 各テストケースの前にプロセス内グローバル状態（一度きりログのフラグ・スロットリング
// 状態）をリセットする。リセットしないと、あるテストケースで出したログが「既に出力
// 済み」として後続のテストケースの検証（ログが出ることの確認）を誤って失敗させる。
beforeEach(() => {
  _resetClientIpRelayLogStateForTests();
});

/** buildClientIpRelayHeaders のデフォルト入力（既知ベクトルV1相当）。テストごとに一部だけ上書きする。 */
function baseInput(
  overrides: Partial<Parameters<typeof buildClientIpRelayHeaders>[0]> = {},
): Parameters<typeof buildClientIpRelayHeaders>[0] {
  return {
    method: "POST",
    url: BACKEND_LOGIN_URL,
    incomingHeaders: headersOf({ "x-real-ip": "203.0.113.9" }),
    secret: KEY_A,
    onVercel: true,
    nowEpochSeconds: 1790000000,
    ...overrides,
  };
}

/** attached:false・headers:{}・指定した reason になることを確認する。 */
async function expectSkipped(
  input: Parameters<typeof buildClientIpRelayHeaders>[0],
  reason: ClientIpRelaySkipReason,
): Promise<void> {
  const result = await buildClientIpRelayHeaders(input);
  assert.equal(result.attached, false);
  assert.deepEqual(result.headers, {});
  if (result.attached) throw new Error("unreachable: attached が true になった");
  assert.equal(result.reason, reason);
}

describe("canonicalRelayMessage", () => {
  it("CLIENT_IP_RELAY_SIGNING_CONTEXT は固定文字列（バージョン識別のため）", () => {
    assert.equal(CLIENT_IP_RELAY_SIGNING_CONTEXT, "katazuke-client-ip-relay/v1");
  });

  it("V1: POST /api/v1/auth/login", () => {
    assert.equal(
      canonicalRelayMessage("POST", "/api/v1/auth/login", "1790000000", "203.0.113.9"),
      "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/login\n1790000000\n203.0.113.9",
    );
  });

  it("V2: POST /api/v1/auth/line/exchange（大文字IPv6はそのまま）", () => {
    assert.equal(
      canonicalRelayMessage(
        "POST",
        "/api/v1/auth/line/exchange",
        "1790000123",
        "2001:DB8:85A3::8A2E:370:7334",
      ),
      "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/line/exchange\n1790000123\n2001:DB8:85A3::8A2E:370:7334",
    );
  });

  it("V3: POST /api/v1/auth/operator/login（IPv4射影IPv6）", () => {
    assert.equal(
      canonicalRelayMessage(
        "POST",
        "/api/v1/auth/operator/login",
        "1790000059",
        "::ffff:198.51.100.7",
      ),
      "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/operator/login\n1790000059\n::ffff:198.51.100.7",
    );
  });

  it("methodが小文字'post'でもV1と同じ正規化メッセージになる（関数内で大文字化される）", () => {
    assert.equal(
      canonicalRelayMessage("post", "/api/v1/auth/login", "1790000000", "203.0.113.9"),
      "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/login\n1790000000\n203.0.113.9",
    );
  });

  it("methodが混在大文字小文字'PoSt'でもV1と同じ正規化メッセージになる", () => {
    assert.equal(
      canonicalRelayMessage("PoSt", "/api/v1/auth/login", "1790000000", "203.0.113.9"),
      "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/login\n1790000000\n203.0.113.9",
    );
  });
});

describe("signClientIpRelay（既知ベクトル）", () => {
  const V1_MESSAGE = "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/login\n1790000000\n203.0.113.9";
  const V2_MESSAGE =
    "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/line/exchange\n1790000123\n2001:DB8:85A3::8A2E:370:7334";
  const V3_MESSAGE =
    "katazuke-client-ip-relay/v1\nPOST\n/api/v1/auth/operator/login\n1790000059\n::ffff:198.51.100.7";

  it("V1: KEY_A で署名", async () => {
    assert.equal(
      await signClientIpRelay(KEY_A, V1_MESSAGE),
      "db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6",
    );
  });

  it("V2: KEY_B で署名", async () => {
    assert.equal(
      await signClientIpRelay(KEY_B, V2_MESSAGE),
      "965799a5a9624f69e0d6de412169154e433f308bed94c5e001faeacc12df34b0",
    );
  });

  it("V3: KEY_A で署名", async () => {
    assert.equal(
      await signClientIpRelay(KEY_A, V3_MESSAGE),
      "1f5c5681d5a2755ca5fce1f5c5441177ac956cfd0d9a9e547a9c28a9f8c07900",
    );
  });

  it("否定: V1のメッセージをKEY_Bで署名すると別の値になる（鍵の違いが署名に反映される）", async () => {
    assert.equal(
      await signClientIpRelay(KEY_B, V1_MESSAGE),
      "329be44aab4c5b91e92246585f15d4e8f7b000f6e6b6d37a3677f9d8d35dc305",
    );
  });

  it("否定: METHODをGETに変えると別の値になる（メッセージ構成要素の違いが署名に反映される）", async () => {
    const getMessage = canonicalRelayMessage("GET", "/api/v1/auth/login", "1790000000", "203.0.113.9");
    assert.equal(
      await signClientIpRelay(KEY_A, getMessage),
      "0216106b3f8b6cb4fcbd5403e633cdff4ef56bc000ba350e9d65dd3dbaca3a27",
    );
  });

  it("小文字16進数64桁で返す", async () => {
    const hex = await signClientIpRelay(KEY_A, V1_MESSAGE);
    assert.match(hex, /^[0-9a-f]{64}$/);
  });

  it("V1相当: methodを小文字'post'で組み立てても同じ署名になる（canonicalRelayMessage内で大文字化されるため）", async () => {
    const lowerMessage = canonicalRelayMessage("post", "/api/v1/auth/login", "1790000000", "203.0.113.9");
    assert.equal(lowerMessage, V1_MESSAGE);
    assert.equal(
      await signClientIpRelay(KEY_A, lowerMessage),
      "db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6",
    );
  });
});

describe("buildClientIpRelayHeaders（V1: ヘッダ値の完全一致）", () => {
  it("attached:true でヘッダ値が仕様通りに完全一致する", async () => {
    const result = await buildClientIpRelayHeaders(baseInput());
    assert.equal(result.attached, true);
    assert.deepEqual(result.headers, {
      [CLIENT_IP_RELAY_HEADER]:
        "v1;1790000000;203.0.113.9;db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6",
    });
  });
});

describe("buildClientIpRelayHeaders（無効化: onVercel・secret）", () => {
  it("onVercel=false → not_on_vercel", async () => {
    await expectSkipped(baseInput({ onVercel: false }), "not_on_vercel");
  });

  it("secret未指定(undefined) → no_secret", async () => {
    await expectSkipped(baseInput({ secret: undefined }), "no_secret");
  });

  it("secret空文字 → no_secret", async () => {
    await expectSkipped(baseInput({ secret: "" }), "no_secret");
  });

  it("secretが31文字（下限未満） → invalid_secret", async () => {
    const short = "a".repeat(CLIENT_IP_RELAY_MIN_SECRET_LENGTH - 1);
    assert.equal(short.length, 31);
    await expectSkipped(baseInput({ secret: short }), "invalid_secret");
  });

  it("secretに空白が混入 → invalid_secret", async () => {
    const withSpace = `${"a".repeat(31)} b`;
    await expectSkipped(baseInput({ secret: withSpace }), "invalid_secret");
  });

  it("secretにカンマが混入 → invalid_secret", async () => {
    const withComma = `${"a".repeat(31)},b`;
    await expectSkipped(baseInput({ secret: withComma }), "invalid_secret");
  });

  it("secretに非ASCII文字が混入 → invalid_secret", async () => {
    const withNonAscii = `${"a".repeat(31)}あ`;
    await expectSkipped(baseInput({ secret: withNonAscii }), "invalid_secret");
  });

  it("isValidRelaySecret 単体でも同じ判定になる", () => {
    assert.equal(isValidRelaySecret(KEY_A), true);
    assert.equal(isValidRelaySecret("a".repeat(31)), false);
    assert.equal(isValidRelaySecret(`${"a".repeat(31)} `), false);
    assert.equal(isValidRelaySecret(`${"a".repeat(31)},`), false);
  });
});

describe("buildClientIpRelayHeaders（無効化: x-real-ip）", () => {
  it("ヘッダが無い（get→null） → no_client_ip", async () => {
    await expectSkipped(baseInput({ incomingHeaders: headersOf({}) }), "no_client_ip");
  });

  it("incomingHeaders自体がnull → no_client_ip", async () => {
    await expectSkipped(baseInput({ incomingHeaders: null }), "no_client_ip");
  });

  it("incomingHeaders自体がundefined → no_client_ip", async () => {
    await expectSkipped(baseInput({ incomingHeaders: undefined }), "no_client_ip");
  });

  it('x-real-ipが空文字 → no_client_ip（invalid_client_ipではない）', async () => {
    await expectSkipped(baseInput({ incomingHeaders: headersOf({ "x-real-ip": "" }) }), "no_client_ip");
  });

  const INVALID_IPS: readonly string[] = [
    "1.2.3.4, 5.6.7.8",
    "1.2.3.4:443",
    "[2001:db8::1]",
    "fe80::1%eth0",
    "01.2.3.4",
    "256.1.1.1",
    "1.2.3",
    "1".repeat(46),
  ];
  for (const invalid of INVALID_IPS) {
    it(`x-real-ip=${JSON.stringify(invalid)} → invalid_client_ip`, async () => {
      await expectSkipped(
        baseInput({ incomingHeaders: headersOf({ "x-real-ip": invalid }) }),
        "invalid_client_ip",
      );
    });
  }

  const VALID_IPS: readonly string[] = [
    "203.0.113.9",
    "0.0.0.0",
    "255.255.255.255",
    "2001:db8::1",
    "2001:DB8:85A3::8A2E:370:7334",
    "::ffff:198.51.100.7",
    "::1",
    // ちょうど45文字（isRelayableClientIp が許容する上限）の境界値。
    "1234:5678:9abc:def0:1234:5678:255.255.255.255",
  ];
  for (const valid of VALID_IPS) {
    it(`x-real-ip=${JSON.stringify(valid)} は生のまま中継される`, async () => {
      const result = await buildClientIpRelayHeaders(
        baseInput({ incomingHeaders: headersOf({ "x-real-ip": valid }) }),
      );
      assert.equal(result.attached, true);
      if (!result.attached) return;
      assert.ok(result.headers[CLIENT_IP_RELAY_HEADER].includes(`;${valid};`));
    });
  }
});

describe("isRelayableClientIp（単体）", () => {
  const VALID: readonly string[] = [
    "203.0.113.9",
    "0.0.0.0",
    "255.255.255.255",
    "2001:db8::1",
    "2001:DB8:85A3::8A2E:370:7334",
    "::ffff:198.51.100.7",
    "::1",
    // ちょうど45文字（isRelayableClientIp が許容する上限）の境界値。
    "1234:5678:9abc:def0:1234:5678:255.255.255.255",
  ];
  for (const ip of VALID) {
    it(`${JSON.stringify(ip)} は有効`, () => {
      assert.equal(isRelayableClientIp(ip), true);
    });
  }

  const INVALID: readonly string[] = [
    "",
    "1.2.3.4, 5.6.7.8",
    "1.2.3.4:443",
    "[2001:db8::1]",
    "fe80::1%eth0",
    "01.2.3.4",
    "256.1.1.1",
    "1.2.3",
    "1".repeat(46),
  ];
  for (const ip of INVALID) {
    it(`${JSON.stringify(ip)} は無効`, () => {
      assert.equal(isRelayableClientIp(ip), false);
    });
  }
});

describe("isKnownWeakRelaySecret（単体）", () => {
  it("既知のテストベクトル鍵（KEY_A・KEY_B）は完全一致で弱い鍵と判定される", () => {
    assert.equal(isKnownWeakRelaySecret(KEY_A), true);
    assert.equal(isKnownWeakRelaySecret(KEY_B), true);
  });

  it('接頭辞 "katazuke-relay-test-" は弱い鍵と判定される（大文字小文字を区別しない）', () => {
    assert.equal(isKnownWeakRelaySecret(`katazuke-relay-test-${"x".repeat(40)}`), true);
    assert.equal(isKnownWeakRelaySecret(`KATAZUKE-RELAY-TEST-${"X".repeat(40)}`), true);
  });

  it('接頭辞 "http-relay-test-key-" は弱い鍵と判定される（大文字小文字を区別しない）', () => {
    assert.equal(isKnownWeakRelaySecret(`http-relay-test-key-${"x".repeat(40)}`), true);
    assert.equal(isKnownWeakRelaySecret(`HTTP-RELAY-TEST-KEY-${"X".repeat(40)}`), true);
  });

  it("使用文字種が10種類未満（単調な値）は弱い鍵と判定される", () => {
    assert.equal(isKnownWeakRelaySecret("a".repeat(40)), true);
    // "abcdefghi" の9種類の文字だけを繰り返す（32文字以上・接頭辞にも該当しない）。
    assert.equal(isKnownWeakRelaySecret("abcdefghi".repeat(5)), true);
  });

  it("使用文字種が10種類以上かつ既知の値・接頭辞に該当しなければ弱い鍵ではない", () => {
    // "abcdefghij" の10種類ちょうど（境界値）。
    assert.equal(isKnownWeakRelaySecret("abcdefghij".repeat(4)), false);
    assert.equal(isKnownWeakRelaySecret(randomRelaySecret()), false);
  });
});

describe("clientIpRelayHeaders（既知の弱い鍵は署名しない）", () => {
  let originalVercel: string | undefined;
  let originalVercelEnv: string | undefined;
  let originalSecret: string | undefined;

  beforeEach(() => {
    originalVercel = process.env.VERCEL;
    originalVercelEnv = process.env.VERCEL_ENV;
    originalSecret = process.env.CLIENT_IP_RELAY_SECRET;
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
  });

  afterEach(() => {
    if (originalVercel === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = originalVercel;
    if (originalVercelEnv === undefined) delete process.env.VERCEL_ENV;
    else process.env.VERCEL_ENV = originalVercelEnv;
    if (originalSecret === undefined) delete process.env.CLIENT_IP_RELAY_SECRET;
    else process.env.CLIENT_IP_RELAY_SECRET = originalSecret;
  });

  it("既知のテストベクトル鍵（KEY_A）ではヘッダを付けない（console.errorに鍵の値を出さない）", async (t) => {
    process.env.CLIENT_IP_RELAY_SECRET = KEY_A;
    const errorMock = t.mock.method(console, "error", () => undefined);
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
    assert.ok(errorMock.mock.calls.length >= 1);
    const args = errorMock.mock.calls.flatMap((call) => call.arguments.map((a) => String(a)));
    assert.ok(!args.some((a) => a.includes(KEY_A)));
  });

  it('接頭辞一致する弱い鍵（"http-relay-test-key-..."）ではヘッダを付けない', async () => {
    process.env.CLIENT_IP_RELAY_SECRET = `http-relay-test-key-${"x".repeat(40)}`;
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
  });

  it("十分に長くランダムな鍵ではヘッダを付ける", async () => {
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.ok(CLIENT_IP_RELAY_HEADER in headers);
  });
});

describe("buildClientIpRelayHeaders（無効化: method/url の正規化・字句検証）", () => {
  it("methodが小文字'post'でもV1と同じ署名になる（大文字に正規化される）", async () => {
    const result = await buildClientIpRelayHeaders(baseInput({ method: "post" }));
    assert.equal(result.attached, true);
    if (!result.attached) return;
    assert.equal(
      result.headers[CLIENT_IP_RELAY_HEADER],
      "v1;1790000000;203.0.113.9;db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6",
    );
  });

  it("クエリ付きURLでもV1と同じ署名になる（クエリは署名対象に含めない）", async () => {
    const result = await buildClientIpRelayHeaders(baseInput({ url: `${BACKEND_LOGIN_URL}?x=1` }));
    assert.equal(result.attached, true);
    if (!result.attached) return;
    assert.equal(
      result.headers[CLIENT_IP_RELAY_HEADER],
      "v1;1790000000;203.0.113.9;db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6",
    );
  });

  it("パスに許可外文字（%20）を含む → invalid_target", async () => {
    await expectSkipped(
      baseInput({ url: "https://sokuri-backend.onrender.com/api/v1/auth/log%20in" }),
      "invalid_target",
    );
  });

  it("パスに許可外文字（@）を含む → invalid_target", async () => {
    await expectSkipped(
      baseInput({ url: "https://sokuri-backend.onrender.com/api/v1/auth/@x" }),
      "invalid_target",
    );
  });

  it("不正なURL文字列（スキーム無し） → invalid_target", async () => {
    await expectSkipped(baseInput({ url: "not a valid url" }), "invalid_target");
  });

  it("宛先が http:// （https以外のスキーム） → invalid_target", async () => {
    await expectSkipped(
      baseInput({ url: "http://sokuri-backend.onrender.com/api/v1/auth/login" }),
      "invalid_target",
    );
  });

  it("methodが不正（数字を含む） → invalid_target", async () => {
    await expectSkipped(baseInput({ method: "PO5T" }), "invalid_target");
  });

  it("nowEpochSecondsが小数 → 秒に切り捨てたtsで署名される", async () => {
    const result = await buildClientIpRelayHeaders(baseInput({ nowEpochSeconds: 1790000000.9 }));
    assert.equal(result.attached, true);
    if (!result.attached) return;
    assert.ok(result.headers[CLIENT_IP_RELAY_HEADER].startsWith("v1;1790000000;"));
  });
});

describe("clientIpRelayHeaders（環境変数ラッパー）", () => {
  let originalVercel: string | undefined;
  let originalVercelEnv: string | undefined;
  let originalSecret: string | undefined;

  beforeEach(() => {
    originalVercel = process.env.VERCEL;
    originalVercelEnv = process.env.VERCEL_ENV;
    originalSecret = process.env.CLIENT_IP_RELAY_SECRET;
  });

  afterEach(() => {
    if (originalVercel === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = originalVercel;
    if (originalVercelEnv === undefined) delete process.env.VERCEL_ENV;
    else process.env.VERCEL_ENV = originalVercelEnv;
    if (originalSecret === undefined) delete process.env.CLIENT_IP_RELAY_SECRET;
    else process.env.CLIENT_IP_RELAY_SECRET = originalSecret;
  });

  it('VERCEL="1" かつ VERCEL_ENV="production" かつ有効なsecretならヘッダを1本返す', async () => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.match(headers[CLIENT_IP_RELAY_HEADER], /^v1;[0-9]{10};[0-9A-Fa-f:.]{2,45};[0-9a-f]{64}$/);
  });

  it("VERCELが無ければ空オブジェクトを返す", async () => {
    delete process.env.VERCEL;
    process.env.VERCEL_ENV = "production";
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
  });

  it('VERCEL="true"（"1"という文字列と厳密一致しない）では付かない', async () => {
    process.env.VERCEL = "true";
    process.env.VERCEL_ENV = "production";
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
  });

  const NON_PRODUCTION_VERCEL_ENVS: readonly (string | undefined)[] = ["preview", "development", undefined];
  for (const vercelEnv of NON_PRODUCTION_VERCEL_ENVS) {
    it(`VERCEL="1"でもVERCEL_ENV=${JSON.stringify(vercelEnv)}なら付かない`, async () => {
      process.env.VERCEL = "1";
      if (vercelEnv === undefined) delete process.env.VERCEL_ENV;
      else process.env.VERCEL_ENV = vercelEnv;
      process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
      const headers = await clientIpRelayHeaders(
        "POST",
        BACKEND_LOGIN_URL,
        headersOf({ "x-real-ip": "203.0.113.9" }),
      );
      assert.deepEqual(headers, {});
    });
  }

  it("URLが不正でも例外を投げずに{}を返し、console.warnでinvalid_targetを報告する", async (t) => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    const secret = randomRelaySecret();
    process.env.CLIENT_IP_RELAY_SECRET = secret;
    const warnMock = t.mock.method(console, "warn", () => undefined);
    const headers = await clientIpRelayHeaders(
      "POST",
      "not a valid url",
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
    assert.equal(warnMock.mock.calls.length, 1);
    const args = warnMock.mock.calls[0].arguments.map((a) => String(a));
    assert.ok(args.some((a) => a.includes("invalid_target")));
    // IPも鍵もログに出ないこと。
    assert.ok(!args.some((a) => a.includes("203.0.113.9")));
    assert.ok(!args.some((a) => a.includes(secret)));
  });

  it("無効なx-real-ipの場合もログにIPを出さない（invalid_client_ip）", async (t) => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
    const warnMock = t.mock.method(console, "warn", () => undefined);
    const suspiciousIp = "1.2.3.4:443";
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": suspiciousIp }),
    );
    assert.deepEqual(headers, {});
    assert.equal(warnMock.mock.calls.length, 1);
    const args = warnMock.mock.calls[0].arguments.map((a) => String(a));
    assert.ok(args.some((a) => a.includes("invalid_client_ip")));
    assert.ok(!args.some((a) => a.includes(suspiciousIp)));
  });

  it("secretが不正な場合、console.errorに鍵の値を出さない", async (t) => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    const badSecret = "short-secret-value-not-32-chars";
    assert.ok(badSecret.length < CLIENT_IP_RELAY_MIN_SECRET_LENGTH, "前提: 32文字未満のはず");
    process.env.CLIENT_IP_RELAY_SECRET = badSecret;
    const errorMock = t.mock.method(console, "error", () => undefined);
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
    assert.ok(errorMock.mock.calls.length >= 1);
    const args = errorMock.mock.calls.flatMap((call) => call.arguments.map((a) => String(a)));
    assert.ok(!args.some((a) => a.includes(badSecret)));
  });

  it("incomingHeaders.getが例外を投げても例外を外に出さず{}を返す", async () => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
    const throwingHeaders: HeaderReader = {
      get(): string | null {
        throw new Error("boom（想定外のHeaderReader実装からの例外）");
      },
    };
    const headers = await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, throwingHeaders);
    assert.deepEqual(headers, {});
  });
});

describe("clientIpRelayHeaders（no_secretの本番通知ログ）", () => {
  let originalVercel: string | undefined;
  let originalVercelEnv: string | undefined;
  let originalSecret: string | undefined;

  beforeEach(() => {
    originalVercel = process.env.VERCEL;
    originalVercelEnv = process.env.VERCEL_ENV;
    originalSecret = process.env.CLIENT_IP_RELAY_SECRET;
    // no_secret を再現するため、このdescribe内では明示的に鍵を未設定にする。
    delete process.env.CLIENT_IP_RELAY_SECRET;
  });

  afterEach(() => {
    if (originalVercel === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = originalVercel;
    if (originalVercelEnv === undefined) delete process.env.VERCEL_ENV;
    else process.env.VERCEL_ENV = originalVercelEnv;
    if (originalSecret === undefined) delete process.env.CLIENT_IP_RELAY_SECRET;
    else process.env.CLIENT_IP_RELAY_SECRET = originalSecret;
  });

  it("Vercel本番なのに鍵未設定なら1回だけconsole.errorで通知する（IPは出さない）", async (t) => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    const errorMock = t.mock.method(console, "error", () => undefined);
    const first = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    const second = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(first, {});
    assert.deepEqual(second, {});
    assert.equal(errorMock.mock.calls.length, 1);
    const args = errorMock.mock.calls[0].arguments.map((a) => String(a));
    assert.ok(args.some((a) => a.includes("CLIENT_IP_RELAY_SECRET")));
    assert.ok(args.some((a) => a.includes("Vercel")));
    assert.ok(!args.some((a) => a.includes("203.0.113.9")));
  });

  it("VERCEL_ENVが本番以外（preview）なら鍵未設定でもconsole.errorを出さない", async (t) => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "preview";
    const errorMock = t.mock.method(console, "error", () => undefined);
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
    assert.equal(errorMock.mock.calls.length, 0);
  });

  it("Vercel上ですらない場合は鍵未設定でもconsole.errorを出さない", async (t) => {
    delete process.env.VERCEL;
    process.env.VERCEL_ENV = "production";
    const errorMock = t.mock.method(console, "error", () => undefined);
    const headers = await clientIpRelayHeaders(
      "POST",
      BACKEND_LOGIN_URL,
      headersOf({ "x-real-ip": "203.0.113.9" }),
    );
    assert.deepEqual(headers, {});
    assert.equal(errorMock.mock.calls.length, 0);
  });

  it("_resetClientIpRelayLogStateForTestsを呼ぶとフラグが戻り、再度1回だけ通知される", async (t) => {
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    const errorMock = t.mock.method(console, "error", () => undefined);
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, headersOf({ "x-real-ip": "203.0.113.9" }));
    assert.equal(errorMock.mock.calls.length, 1);
    _resetClientIpRelayLogStateForTests();
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, headersOf({ "x-real-ip": "203.0.113.9" }));
    assert.equal(errorMock.mock.calls.length, 2);
  });
});

describe("clientIpRelayHeaders（console.warnのスロットリング）", () => {
  let originalVercel: string | undefined;
  let originalVercelEnv: string | undefined;
  let originalSecret: string | undefined;

  beforeEach(() => {
    originalVercel = process.env.VERCEL;
    originalVercelEnv = process.env.VERCEL_ENV;
    originalSecret = process.env.CLIENT_IP_RELAY_SECRET;
    process.env.VERCEL = "1";
    process.env.VERCEL_ENV = "production";
    process.env.CLIENT_IP_RELAY_SECRET = randomRelaySecret();
  });

  afterEach(() => {
    if (originalVercel === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = originalVercel;
    if (originalVercelEnv === undefined) delete process.env.VERCEL_ENV;
    else process.env.VERCEL_ENV = originalVercelEnv;
    if (originalSecret === undefined) delete process.env.CLIENT_IP_RELAY_SECRET;
    else process.env.CLIENT_IP_RELAY_SECRET = originalSecret;
  });

  it("同じreason・targetの警告は60秒以内では2回目が出ない", async (t) => {
    const warnMock = t.mock.method(console, "warn", () => undefined);
    const badHeaders = headersOf({ "x-real-ip": "1.2.3.4:443" }); // invalid_client_ip
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, badHeaders);
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, badHeaders);
    assert.equal(warnMock.mock.calls.length, 1);
  });

  it("60秒経過後は再度警告される", async (t) => {
    t.mock.timers.enable({ apis: ["Date"] });
    const warnMock = t.mock.method(console, "warn", () => undefined);
    const badHeaders = headersOf({ "x-real-ip": "1.2.3.4:443" });
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, badHeaders);
    t.mock.timers.tick(60_000);
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, badHeaders);
    assert.equal(warnMock.mock.calls.length, 2);
  });

  it("targetが異なれば別カウントとしてそれぞれ警告される", async (t) => {
    const warnMock = t.mock.method(console, "warn", () => undefined);
    const badHeaders = headersOf({ "x-real-ip": "1.2.3.4:443" });
    await clientIpRelayHeaders("POST", BACKEND_LOGIN_URL, badHeaders);
    await clientIpRelayHeaders(
      "POST",
      "https://sokuri-backend.onrender.com/api/v1/auth/operator/login",
      badHeaders,
    );
    assert.equal(warnMock.mock.calls.length, 2);
  });
});
