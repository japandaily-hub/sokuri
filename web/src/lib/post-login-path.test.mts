/**
 * post-login-path.ts（/login でログインした後の遷移先の決定）の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/post-login-path.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts と同じ（tsconfig の include に一致させず、型検査・ビルドの対象から
 * 外したまま実行できるようにするため）。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ADMIN_HOME_PATH,
  USER_HOME_PATH,
  defaultPostLoginPath,
  isAllowedPostLoginPath,
  resolvePostLoginPath,
} from "./post-login-path.ts";
import { safeInternalPath } from "./safe-path.ts";

/** セッションの role。依頼者は "user"、取得できなかった場合は undefined。 */
const ADMIN = "admin";
const USER = "user";

/**
 * app/login/page.tsx と同じ組み立て（クエリの callbackUrl → safeInternalPath で検証・正規化 →
 * 遷移先の決定）。検証に通らない値は空文字の fallback を経て null（＝指定なし）になる。
 */
function destinationFor(rawCallbackUrl: string | null, role: string | undefined): string {
  return resolvePostLoginPath(safeInternalPath(rawCallbackUrl, "") || null, role);
}

describe("defaultPostLoginPath", () => {
  it("運営は /admin", () => {
    assert.equal(defaultPostLoginPath(ADMIN), ADMIN_HOME_PATH);
  });

  for (const role of [USER, "operator", "", null, undefined]) {
    it(`${JSON.stringify(role)} は依頼者の /cases`, () => {
      assert.equal(defaultPostLoginPath(role), USER_HOME_PATH);
    });
  }
});

describe("isAllowedPostLoginPath", () => {
  for (const path of ["/cases", "/cases/abc?tab=bids#top", "/create", "/mypage/profile", "/chat/xyz"]) {
    it(`${path} は依頼者・運営・role 不明のいずれでも許可`, () => {
      assert.equal(isAllowedPostLoginPath(path, USER), true);
      assert.equal(isAllowedPostLoginPath(path, ADMIN), true);
      assert.equal(isAllowedPostLoginPath(path, undefined), true);
    });
  }

  // /operator/login も依頼者のセッションでは行き止まり（業者用の画面）。
  for (const path of ["/operator", "/operator/cases", "/operator/login", "/operators"]) {
    it(`${path} は依頼者・運営とも不可（業者専用）`, () => {
      assert.equal(isAllowedPostLoginPath(path, USER), false);
      assert.equal(isAllowedPostLoginPath(path, ADMIN), false);
    });
  }

  // ログイン画面そのものへ送っても、既定の遷移先へ読み込み直すだけの遠回りになる。
  for (const path of ["/login", "/login?callbackUrl=%2Fadmin", "/login#top"]) {
    it(`${path} は依頼者・運営とも不可（ログイン画面そのもの）`, () => {
      assert.equal(isAllowedPostLoginPath(path, USER), false);
      assert.equal(isAllowedPostLoginPath(path, ADMIN), false);
    });
  }

  for (const path of ["/admin", "/admin/users", "/admin/operator-applications?status=pending"]) {
    it(`${path} は運営だけが許可`, () => {
      assert.equal(isAllowedPostLoginPath(path, ADMIN), true);
      assert.equal(isAllowedPostLoginPath(path, USER), false);
      assert.equal(isAllowedPostLoginPath(path, undefined), false);
    });
  }
});

describe("resolvePostLoginPath", () => {
  it("callbackUrl の指定なし: 運営は /admin・依頼者は /cases・role 不明は /cases", () => {
    assert.equal(resolvePostLoginPath(null, ADMIN), ADMIN_HOME_PATH);
    assert.equal(resolvePostLoginPath(null, USER), USER_HOME_PATH);
    assert.equal(resolvePostLoginPath(null, undefined), USER_HOME_PATH);
  });

  it("許可できる callbackUrl はそのまま（検索・フラグメントも保つ）", () => {
    assert.equal(resolvePostLoginPath("/create", USER), "/create");
    assert.equal(resolvePostLoginPath("/create", ADMIN), "/create");
    assert.equal(resolvePostLoginPath("/cases/abc?tab=bids#top", USER), "/cases/abc?tab=bids#top");
    assert.equal(resolvePostLoginPath("/admin/users", ADMIN), "/admin/users");
  });

  it("許可できない callbackUrl はその role の既定へ戻す", () => {
    assert.equal(resolvePostLoginPath("/admin/users", USER), USER_HOME_PATH);
    assert.equal(resolvePostLoginPath("/admin/users", undefined), USER_HOME_PATH);
    assert.equal(resolvePostLoginPath("/operator/cases", USER), USER_HOME_PATH);
    assert.equal(resolvePostLoginPath("/operator/cases", ADMIN), ADMIN_HOME_PATH);
    assert.equal(resolvePostLoginPath("/login", ADMIN), ADMIN_HOME_PATH);
    assert.equal(resolvePostLoginPath("/login?callbackUrl=%2Fcreate", USER), USER_HOME_PATH);
  });
});

describe("クエリの callbackUrl からの組み立て（login/page.tsx と同じ）", () => {
  it("回帰: /login を直接開いた運営は /cases ではなく /admin に着く", () => {
    // 2026-09-15 の是正（c4942cc）は、既定の "/cases" が運営にも「到達できる」と判定されて
    // 着地先が /cases に上書きされていた。
    assert.equal(destinationFor(null, ADMIN), ADMIN_HOME_PATH);
    assert.equal(destinationFor(null, USER), USER_HOME_PATH);
  });

  it("空の callbackUrl は指定なしと同じ", () => {
    assert.equal(destinationFor("", ADMIN), ADMIN_HOME_PATH);
    assert.equal(destinationFor("", USER), USER_HOME_PATH);
  });

  // safeInternalPath が弾く値（外部サイト・スキーム相対 URL に解釈されうるもの）は指定なしと同じ扱い。
  // 運営の着地先が不正な callbackUrl で /cases へずれることもない。
  for (const raw of ["//evil.example", "/\t/evil.example", "https://evil.example/admin", "javascript:alert(1)", "/a/..//evil"]) {
    it(`${JSON.stringify(raw)} は既定へ（運営 /admin・依頼者 /cases）`, () => {
      assert.equal(destinationFor(raw, ADMIN), ADMIN_HOME_PATH);
      assert.equal(destinationFor(raw, USER), USER_HOME_PATH);
    });
  }

  it("ドットセグメントは解決後のパスで許可できるかを判定する", () => {
    assert.equal(destinationFor("/cases/../admin", ADMIN), "/admin");
    assert.equal(destinationFor("/cases/../admin", USER), USER_HOME_PATH);
    assert.equal(destinationFor("/cases/../operator/cases", ADMIN), ADMIN_HOME_PATH);
    assert.equal(destinationFor("/%2e%2e/operator", USER), USER_HOME_PATH);
    assert.equal(destinationFor("/cases/../login", ADMIN), ADMIN_HOME_PATH);
  });

  it("callbackUrl が /login（入れ子を含む）でも、読み込み直さずに既定へ", () => {
    assert.equal(destinationFor("/login", ADMIN), ADMIN_HOME_PATH);
    assert.equal(destinationFor("/login", USER), USER_HOME_PATH);
    assert.equal(destinationFor("/login?callbackUrl=%2Flogin", ADMIN), ADMIN_HOME_PATH);
    assert.equal(destinationFor("/login?callbackUrl=%2Fcreate", USER), USER_HOME_PATH);
  });

  it("許可できる callbackUrl は正規化した値へ", () => {
    assert.equal(destinationFor("/create?from=top", USER), "/create?from=top");
    assert.equal(destinationFor("/admin/users", ADMIN), "/admin/users");
  });

  it("どの入力・role でも、遷移先は /login 以外の同一 origin のサイト内パスになる", () => {
    const currentLocation = "https://katazuke.example/login?callbackUrl=x";
    const origin = new URL(currentLocation).origin;
    const inputs = [null, "", "//evil", "/\\evil", "/\u0000/evil", "/cases", "/admin", "/operator", "/cases/../admin", "/login"];
    for (const raw of inputs) {
      for (const role of [ADMIN, USER, undefined]) {
        const destination = destinationFor(raw, role);
        const label = `raw=${JSON.stringify(raw)} role=${role}`;
        assert.ok(destination.startsWith("/") && !destination.startsWith("//"), label);
        assert.equal(new URL(destination, currentLocation).origin, origin, label);
        assert.ok(!destination.startsWith("/login"), label);
      }
    }
  });
});
