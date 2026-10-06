import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  LINE_CONSENT_REQUIRED_HINT,
  LINE_TERMS_CONSENT_COOKIE,
  LINE_TERMS_CONSENT_MAX_AGE_SECONDS,
  LINE_TERMS_REQUIRED_MESSAGE,
  LINE_TERMS_REQUIRED_REASON,
  TERMS_AGREEMENT_REQUIRED_CODE,
  TERMS_VERSION_OUTDATED_CODE,
  TERMS_VERSION_OUTDATED_MESSAGE,
  USER_TERMS_VERSION,
  buildLineTermsConsentCookie,
  canStartLineAuth,
  clearLineTermsConsentCookie,
  isSecureRequest,
  lineConsentHint,
  lineExchangeConsentFields,
  lineTermsConsentCookieName,
  lineTermsConsentCookiePath,
} from "./line-consent.ts";

describe("canStartLineAuth（N-2・N-9: LINE ボタンは明示の同意後だけ押せる）", () => {
  it("同意済み・遷移中でない → 押せる", () => {
    assert.equal(canStartLineAuth({ agreed: true, busy: false }), true);
  });
  it("未同意 → 押せない", () => {
    assert.equal(canStartLineAuth({ agreed: false, busy: false }), false);
  });
  it("同意済みでも遷移中 → 押せない（二重押し防止）", () => {
    assert.equal(canStartLineAuth({ agreed: true, busy: true }), false);
  });
  it("未同意かつ遷移中 → 押せない", () => {
    assert.equal(canStartLineAuth({ agreed: false, busy: true }), false);
  });
  it("boolean の true 以外は同意とみなさない（取り違え防止）", () => {
    for (const v of ["true", 1, null, undefined, {}] as unknown[]) {
      assert.equal(canStartLineAuth({ agreed: v as boolean, busy: false }), false, String(v));
    }
  });
});

describe("lineConsentHint", () => {
  it("未同意のときだけ理由を出す", () => {
    assert.equal(lineConsentHint({ agreed: false, busy: false }), LINE_CONSENT_REQUIRED_HINT);
    assert.equal(lineConsentHint({ agreed: true, busy: false }), null);
  });
  it("遷移中は出さない", () => {
    assert.equal(lineConsentHint({ agreed: false, busy: true }), null);
    assert.equal(lineConsentHint({ agreed: true, busy: true }), null);
  });
  it("理由の文言は規約とポリシーの両方に触れる", () => {
    assert.match(LINE_CONSENT_REQUIRED_HINT, /利用規約/);
    assert.match(LINE_CONSENT_REQUIRED_HINT, /プライバシーポリシー/);
  });
});

describe("配線: /login・/signup の LINE ボタンは同意つきの部品を使い、みなし同意を残さない", () => {
  const APP = join(process.cwd(), "src", "app");
  for (const file of ["login/page.tsx", "signup/page.tsx"]) {
    const src = readFileSync(join(APP, file), "utf8");
    it(`${file}: LineConsentAuth を使う`, () => {
      assert.match(src, /<LineConsentAuth\b/);
    });
    it(`${file}: 同意なしの LineAuthButton を直接置かない`, () => {
      assert.doesNotMatch(src, /<LineAuthButton\b/);
    });
    it(`${file}: みなし同意の文言がない`, () => {
      assert.doesNotMatch(src, /同意したものとみなします/);
    });
  }
});

describe("同意の Cookie（3周目の法務監査: 同意を LINE 交換のリクエストへ運ぶ）", () => {
  it("版数・Path=/api/auth・Max-Age・SameSite=Lax を持ち、https のときだけ Secure", () => {
    const secure = buildLineTermsConsentCookie(true);
    assert.equal(
      secure,
      `__Host-${LINE_TERMS_CONSENT_COOKIE}=${USER_TERMS_VERSION}; Path=/; Max-Age=${LINE_TERMS_CONSENT_MAX_AGE_SECONDS}; SameSite=Lax; Secure`,
    );
    assert.equal(
      buildLineTermsConsentCookie(false),
      `${LINE_TERMS_CONSENT_COOKIE}=${USER_TERMS_VERSION}; Path=/api/auth; Max-Age=${LINE_TERMS_CONSENT_MAX_AGE_SECONDS}; SameSite=Lax`,
    );
    assert.doesNotMatch(buildLineTermsConsentCookie(false), /Secure/);
    assert.ok(LINE_TERMS_CONSENT_MAX_AGE_SECONDS > 0 && LINE_TERMS_CONSENT_MAX_AGE_SECONDS <= 3600);
  });
  it("消すときは同じ Path で Max-Age=0", () => {
    assert.equal(clearLineTermsConsentCookie(), `${LINE_TERMS_CONSENT_COOKIE}=; Path=/api/auth; Max-Age=0; SameSite=Lax`);
    assert.equal(clearLineTermsConsentCookie(true), `__Host-${LINE_TERMS_CONSENT_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax; Secure`);
  });
  it("名前と Path は https で __Host-・Path=/、http で従来名・/api/auth", () => {
    assert.equal(lineTermsConsentCookieName(true), "__Host-kdz_line_terms");
    assert.equal(lineTermsConsentCookieName(false), "kdz_line_terms");
    assert.equal(lineTermsConsentCookiePath(true), "/");
    assert.equal(lineTermsConsentCookiePath(false), "/api/auth");
  });
  it("isSecureRequest: x-forwarded-proto を優先し、無ければ AUTH_URL で決める", () => {
    assert.equal(isSecureRequest("https", undefined), true);
    assert.equal(isSecureRequest("https,http", "http://localhost:3000"), true);
    assert.equal(isSecureRequest("http", "https://example.com"), false);
    assert.equal(isSecureRequest(null, "https://example.com"), true);
    assert.equal(isSecureRequest(undefined, "http://localhost:3000"), false);
    assert.equal(isSecureRequest(undefined, undefined), false);
  });
});

describe("lineExchangeConsentFields", () => {
  it("YYYY-MM-DD の版数なら agreed_terms: true と版数を返す", () => {
    assert.deepEqual(lineExchangeConsentFields(USER_TERMS_VERSION), {
      agreed_terms: true,
      terms_version: USER_TERMS_VERSION,
    });
  });
  it("未設定・空・形式違い・文字列以外は同意を送らない（空）", () => {
    for (const v of [undefined, null, "", "1", "true", "2026-1-6", "2026-10-06x", " 2026-10-06", 20261006, {}] as unknown[]) {
      assert.deepEqual(lineExchangeConsentFields(v), {}, String(v));
    }
  });
});

describe("版数・コードの食い違い防止", () => {
  const ROOT = process.cwd();
  it("USER_TERMS_VERSION は backend の CURRENT_USER_TERMS_VERSION と同じ", () => {
    const py = readFileSync(join(ROOT, "..", "backend", "app", "schemas_katadzuke.py"), "utf8");
    const m = py.match(/^CURRENT_USER_TERMS_VERSION = "([^"]+)"/m);
    assert.ok(m, "backend に CURRENT_USER_TERMS_VERSION が無い");
    assert.equal(m[1], USER_TERMS_VERSION);
  });
  it("TERMS_AGREEMENT_REQUIRED_CODE は backend の auth.py と同じ", () => {
    const py = readFileSync(join(ROOT, "..", "backend", "app", "api", "v1", "endpoints", "auth.py"), "utf8");
    assert.match(py, new RegExp(`^TERMS_AGREEMENT_REQUIRED_CODE = "${TERMS_AGREEMENT_REQUIRED_CODE}"`, "m"));
  });
  it("USER_TERMS_VERSION は /terms の「最終改定」の日付と同じ（規約を改定したら版数も上げる）", () => {
    const src = readFileSync(join(ROOT, "src", "app", "terms", "page.tsx"), "utf8");
    const m = src.match(/最終改定：(\d{4})年(\d{1,2})月(\d{1,2})日/);
    assert.ok(m, "/terms に最終改定の日付が無い");
    const date = `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
    assert.equal(date, USER_TERMS_VERSION);
  });
  it("案内の文言は同意のチェックに触れる", () => {
    assert.match(LINE_TERMS_REQUIRED_MESSAGE, /利用規約/);
    assert.match(LINE_TERMS_REQUIRED_MESSAGE, /チェック/);
    assert.equal(LINE_TERMS_REQUIRED_REASON, "terms_required");
  });
});

describe("配線: 同意をサーバーへ送る", () => {
  const SRC = join(process.cwd(), "src");
  const authTs = readFileSync(join(SRC, "auth.ts"), "utf8");
  const authTsx = readFileSync(join(SRC, "components", "kdz", "auth.tsx"), "utf8");
  const signup = readFileSync(join(SRC, "app", "signup", "page.tsx"), "utf8");
  const login = readFileSync(join(SRC, "app", "login", "page.tsx"), "utf8");
  it("auth.ts: LINE 交換の本文に同意の項目を載せ、Cookie から読む", () => {
    assert.match(authTs, /line_access_token: lineAccessToken, \.\.\.consent/);
    assert.match(authTs, /const consent = await readLineTermsConsent\(\);/);
    assert.match(authTs, /lineExchangeConsentFields\(store\.get\(cookieName\)\?\.value\)/);
    assert.match(authTs, /lineTermsConsentCookieName\(secure\)/);
  });
  it("auth.ts: 同意なしの新規作成の拒否は /login?reason=terms_required へ戻す", () => {
    assert.match(authTs, /result\.code === TERMS_AGREEMENT_REQUIRED_CODE \|\| result\.code === TERMS_VERSION_OUTDATED_CODE\) return `\/login\?reason=\$\{LINE_TERMS_REQUIRED_REASON\}`/);
  });
  it("LineConsentAuth: 同意の判定を通った後でだけ Cookie を置いて signIn する", () => {
    const i = authTsx.indexOf("if (!canStartLineAuth({ agreed, busy })) return;");
    const j = authTsx.indexOf("document.cookie = buildLineTermsConsentCookie(");
    const k = authTsx.indexOf('void signIn("line", { callbackUrl });', j);
    assert.ok(i >= 0 && j > i && k > j, "判定 → Cookie → signIn の順でない");
  });
  it("signup: メール登録は agreed_terms: true と版数を送る", () => {
    assert.match(signup, /agreed_terms: true,\s*terms_version: USER_TERMS_VERSION/);
  });
  it("signup: 登録済みメールはパスワード再設定へ案内し、問い合わせへは誘導しない・文を重ねない", () => {
    assert.match(signup, /<Link href="\/password-reset"/);
    assert.doesNotMatch(signup, /忘れた場合は<Link href="\/contact"/);
    assert.match(signup, /errs\.email && !emailTaken &&/);
  });
  it("login: reason=terms_required の案内を出す", () => {
    assert.match(login, /params\.get\("reason"\) === LINE_TERMS_REQUIRED_REASON/);
    assert.match(login, /\{LINE_TERMS_REQUIRED_MESSAGE\}/);
  });
});

describe("規約の版数が古いときの 409（登録済みメールの 409 と取り違えない）", () => {
  it("backend の code と文言", () => {
    assert.equal(TERMS_VERSION_OUTDATED_CODE, "terms_version_outdated");
    assert.match(TERMS_VERSION_OUTDATED_MESSAGE, /再読み込み/);
  });

  it("signup: 版数の食い違いの 409 は登録済みメールの案内にしない（コードで先に分岐）", () => {
    const src = readFileSync(new URL("../app/signup/page.tsx", import.meta.url), "utf8");
    const iOutdated = src.indexOf("TERMS_VERSION_OUTDATED_CODE)");
    const iTaken = src.indexOf("err.status === 409");
    assert.ok(iOutdated > 0 && iTaken > 0 && iOutdated < iTaken);
  });

  it("auth.ts: LINE 交換の版数の食い違いも /login?reason=terms_required へ戻す", () => {
    const src = readFileSync(new URL("../auth.ts", import.meta.url), "utf8");
    assert.match(src, /TERMS_VERSION_OUTDATED_CODE/);
  });
});
