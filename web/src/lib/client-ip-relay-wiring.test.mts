/**
 * client-ip-relay.ts（利用者IPの署名付き中継ヘッダ）の「組み込み配線」に対する静的検査。
 *
 * 目的はデグレの検知（配線が外れたら落ちる）であり、完全な構文解析ではない。
 * src 配下のソースをテキストとして読み、正規表現・文字列検索の簡易な検査で以下5点を
 * 確認する（詳細は各 describe 内のコメントを参照）:
 *   a. x-real-ip という文字列が現れるのは lib/client-ip-relay.ts と *.test.mts だけ。
 *   b. auth.ts / line-link.ts で serverBackendApiBase() を使う fetch には必ず
 *      redirect: "error" と clientIpRelayHeaders(...) の戻り値のスプレッドがある
 *      （切り出した関数本体に含まれる fetch(...) 呼び出しが1個であることも併せて
 *      検査する。2個以上あると「どちらの fetch を検査しているか」を区別できず、
 *      この簡易検査の前提が崩れるため）。LINE公式（LINE_TOKEN_URL）への fetch には
 *      中継ヘッダを付けていない。
 *   c. backend への fetch の headers に受信ヘッダそのもの（...request.headers 等）を
 *      丸ごと展開していない。
 *   d. Credentials の authorize が request?.headers を backendLogin に渡し、LINEの
 *      signIn が readIncomingRequestHeaders（try/catch付き headers()）を渡している。
 *   e. clientIpRelayHeaders を import しているのは許可リスト（auth.ts /
 *      lib/line-link.ts）だけ。新しい呼び出し元を追加する場合は、許可リストと
 *      b〜dの検査対象一覧の両方を増やす必要がある（アサート失敗メッセージで案内する）。
 *
 * a〜eの判定に使う正規表現ベースの関数（importsClientIpRelayHeaders・
 * countFetchCalls）自体の正しさは、末尾の自己テスト
 * （describe "自己テスト: 静的検査の判定ロジック自体の検査"）で陽性・陰性の両方の
 * 入力を使って別途確認する。
 *
 * コメント中の記述（この client-ip-relay.ts 自身の JSDoc が "redirect: \"error\"" 等の
 * 語句をそのまま説明文に含む等）に誤反応しないよう、行頭が "//"・"*"・"/*" の行
 * （コメント専用行）は検査対象から除外する。ただし逆に、コメント行しか除外しない
 * 簡易フィルタのため、コード行の末尾に付いたインラインコメント中の語句までは除去
 * できない（このリポジトリのスタイルではコメントは常に行頭に置かれるため実害は無い
 * 想定）。
 *
 * このファイルは client-ip-relay.ts 等の実装を import しない（node:fs でソースを
 * テキストとして読むだけ）。node: の組み込み（node:fs・node:path・node:test・
 * node:assert）だけを使う。
 *
 * 実行（cwd は web）:
 *   node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON src/lib/client-ip-relay-wiring.test.mts
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative, sep } from "node:path";
import { describe, it } from "node:test";

/** このファイル（src/lib/配下）から見た src ディレクトリの絶対パス。 */
const SRC_DIR = join(import.meta.dirname, "..");

/** 走査対象の拡張子。 */
const TARGET_EXTENSIONS = new Set([".ts", ".tsx", ".mts"]);

type SourceFile = {
  /** SRC_DIR からの相対パス。OSに依らず "/" 区切りに正規化済み（例: "lib/line-link.ts"）。 */
  relPath: string;
  /** コメント専用行（行頭が "//"・"*"・"/*"）を除いた行配列。 */
  lines: readonly string[];
};

/** 走査から除外するディレクトリ名かどうか（node_modules・隠しディレクトリ）。 */
function isExcludedDir(name: string): boolean {
  return name === "node_modules" || name.startsWith(".");
}

/** dir 配下を再帰的に走査し、対象拡張子のファイルの絶対パス一覧を返す。 */
function listSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (isExcludedDir(entry)) continue;
    const abs = join(dir, entry);
    if (statSync(abs).isDirectory()) {
      out.push(...listSourceFiles(abs));
    } else if (TARGET_EXTENSIONS.has(extname(entry))) {
      out.push(abs);
    }
  }
  return out;
}

/** ファイルを読み、コメント専用行（行頭が "//"・"*"・"/*"）を除いた行配列を返す。 */
function toCodeOnlyLines(absPath: string): string[] {
  const raw = readFileSync(absPath, "utf8");
  return raw.split(/\r?\n/).filter((line) => {
    const trimmed = line.trim();
    return !(trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*"));
  });
}

const ALL_SOURCE_FILES: readonly SourceFile[] = listSourceFiles(SRC_DIR).map((absPath) => ({
  relPath: relative(SRC_DIR, absPath).split(sep).join("/"),
  lines: toCodeOnlyLines(absPath),
}));

/** relPath（"auth.ts" 等、SRC_DIR からの "/" 区切り相対パス）でファイルを引く。見つからなければ即座に失敗させる。 */
function fileByRelPath(relPath: string): SourceFile {
  const found = ALL_SOURCE_FILES.find((f) => f.relPath === relPath);
  if (!found) {
    throw new Error(
      `前提: src/${relPath} が走査結果に見つかりません（SRC_DIRの取り違え、またはファイルの移動・` +
        "リネームの可能性があります）。",
    );
  }
  return found;
}

/** lines のうち literalSubstring を含む行のインデックス一覧を返す（部分一致・正規表現ではない）。 */
function findAnchorIndices(lines: readonly string[], literalSubstring: string): number[] {
  const indices: number[] = [];
  lines.forEach((line, i) => {
    if (line.includes(literalSubstring)) indices.push(i);
  });
  return indices;
}

/**
 * lines[anchorIndex] を含む「その関数の残り」を、次に現れる列0の "}"（トップレベル
 * 関数の閉じ括弧）までを1つの文字列にして返す。本リポジトリのフォーマット規約では
 * トップレベル関数の閉じ括弧は必ずインデント無しで書かれる（このファイルが検査する
 * auth.ts / line-link.ts の各関数で確認済み）ため、この単純な走査で関数本体を
 * 十分な精度で切り出せる。見つからない場合はフォーマット規約が崩れている可能性が
 * あるため、原因を特定しやすいメッセージで例外を投げる。
 */
function sliceFunctionBody(lines: readonly string[], anchorIndex: number, label: string): string {
  for (let i = anchorIndex + 1; i < lines.length; i++) {
    if (/^}\s*$/.test(lines[i])) {
      return lines.slice(anchorIndex, i + 1).join("\n");
    }
  }
  throw new Error(
    `${label}: anchor行（コメント除去後の配列index ${anchorIndex}）から関数末尾（列0の"}"）が` +
      "見つかりませんでした。トップレベル関数の閉じ括弧はインデント無しという前提が崩れていないか、" +
      "このテストの sliceFunctionBody を見直してください。",
  );
}

/**
 * text（コメント専用行を除いたソース全文。複数行可）に、clientIpRelayHeaders を
 * named import する import 文があるかどうかを判定する。
 * `import { ..., clientIpRelayHeaders, ... } from "..."` の形（`import type { ... }`・
 * 複数行にわたる import 文のいずれも対象）にマッチする。import 文以外での識別子への
 * 言及（呼び出し・コメント中の言及等）には反応しない。
 *
 * このファイル自身（e. のdescribe）が「許可リスト外からの import」を検知するために使う
 * 判定ロジック。正しさは末尾の自己テストで別途確認する。
 */
function importsClientIpRelayHeaders(text: string): boolean {
  return /import\s+(?:type\s+)?\{[^}]*\bclientIpRelayHeaders\b[^}]*\}\s*from\s*["'][^"']+["']/.test(
    text,
  );
}

/**
 * block（sliceFunctionBody が切り出した関数本体の文字列）に含まれる fetch(...) 呼び出しの
 * 個数を数える。
 *
 * b. の各 it は「関数内の fetch(...) 呼び出しは1個だけ」という前提のもとで、その1個が
 * redirect: "error" と中継ヘッダのスプレッドを持つかを検査している（どのfetchを見ているかを
 * 区別していない簡易検査のため）。2個以上あるとこの前提が崩れ、redirect: "error" が
 * 欠けている方の fetch を見逃しうる。正しさは末尾の自己テストで別途確認する。
 */
function countFetchCalls(block: string): number {
  return (block.match(/\bfetch\(/g) ?? []).length;
}

describe("前提: 走査対象パスの取り違え検知", () => {
  it("SRC_DIR配下で対象拡張子のソースファイルが一定数以上見つかる", () => {
    assert.ok(
      ALL_SOURCE_FILES.length > 10,
      `SRC_DIR(${SRC_DIR})配下の走査結果が${ALL_SOURCE_FILES.length}件しかありません。` +
        "パスの取り違えでほぼ何も検査できていない可能性があります。",
    );
  });

  it("検査対象の auth.ts / lib/line-link.ts / lib/client-ip-relay.ts が走査結果に含まれる", () => {
    assert.ok(ALL_SOURCE_FILES.some((f) => f.relPath === "auth.ts"));
    assert.ok(ALL_SOURCE_FILES.some((f) => f.relPath === "lib/line-link.ts"));
    assert.ok(ALL_SOURCE_FILES.some((f) => f.relPath === "lib/client-ip-relay.ts"));
  });
});

describe("a. x-real-ip の直接参照は lib/client-ip-relay.ts とテストファイルに限られる", () => {
  it("他のソースファイルに x-real-ip 文字列が現れない（大文字小文字を問わない）", () => {
    const offenders: string[] = [];
    for (const file of ALL_SOURCE_FILES) {
      if (file.relPath === "lib/client-ip-relay.ts") continue;
      if (file.relPath.endsWith(".test.mts")) continue;
      if (/x-real-ip/i.test(file.lines.join("\n"))) {
        offenders.push(file.relPath);
      }
    }
    assert.deepEqual(
      offenders,
      [],
      "x-real-ip は lib/client-ip-relay.ts（中継ヘッダの組み立て）だけが読むべき値です。" +
        "他の場所で直接参照すると、署名検証を経ないIPが混入する経路になりえます。",
    );
  });
});

describe('b. auth.ts / line-link.ts の backend fetch は redirect:"error" と中継ヘッダのスプレッドを持つ', () => {
  const BACKEND_FETCH_TARGETS: readonly { relPath: string; label: string }[] = [
    { relPath: "auth.ts", label: "auth.ts" },
    { relPath: "lib/line-link.ts", label: "line-link.ts" },
  ];

  for (const { relPath, label } of BACKEND_FETCH_TARGETS) {
    it(`${label}: serverBackendApiBase()を使う全fetch呼び出しに redirect:"error" と clientIpRelayHeaders(...)のスプレッドがある`, () => {
      const file = fileByRelPath(relPath);
      const anchors = findAnchorIndices(file.lines, "serverBackendApiBase()");
      assert.ok(
        anchors.length > 0,
        `前提: ${label} に serverBackendApiBase() の呼び出しが見つかりません` +
          "（識別子のリネーム等で検査対象を見失っている可能性があります）。",
      );
      for (const anchorIndex of anchors) {
        const block = sliceFunctionBody(file.lines, anchorIndex, label);
        const fetchCallCount = countFetchCalls(block);
        assert.ok(
          fetchCallCount < 2,
          `${label}: serverBackendApiBase()使用箇所（行index ${anchorIndex}）を含む関数内に` +
            ` fetch( の呼び出しが${fetchCallCount}個見つかりました。このテストは「関数内の` +
            'fetchは1個だけ」という前提で redirect:"error" 等を検査しているため、2個以上' +
            "あるとどちらのfetchを検査しているか区別できず見逃しが起きえます。関数を分割するか、" +
            "このテストの検査方法自体を見直してください。",
        );
        assert.match(
          block,
          /redirect:\s*"error"/,
          `${label}: serverBackendApiBase()使用箇所（行index ${anchorIndex}）を含む関数に` +
            ' redirect: "error" が指定されていません。',
        );
        const assigned = block.match(/const\s+(\w+)\s*=\s*await\s+clientIpRelayHeaders\(/);
        assert.ok(
          assigned,
          `${label}: serverBackendApiBase()使用箇所（行index ${anchorIndex}）を含む関数に` +
            " clientIpRelayHeaders(...) の呼び出しが見当たりません。",
        );
        const relayHeadersVarName = (assigned as RegExpMatchArray)[1];
        const spreadPattern = new RegExp(`\\.\\.\\.${relayHeadersVarName}\\b`);
        assert.match(
          block,
          spreadPattern,
          `${label}: clientIpRelayHeaders(...) の戻り値（変数 ${relayHeadersVarName}）が` +
            " fetch の headers にスプレッドされていません。",
        );
      }
    });
  }

  it("line-link.ts: LINE公式（LINE_TOKEN_URL）へのfetchには中継ヘッダを付けていない", () => {
    const file = fileByRelPath("lib/line-link.ts");
    const anchors = findAnchorIndices(file.lines, "fetch(LINE_TOKEN_URL");
    assert.equal(
      anchors.length,
      1,
      "前提: fetch(LINE_TOKEN_URL, ...) の呼び出しは1箇所のはずです（見つからない場合は" +
        "識別子のリネーム、複数箇所ある場合は検査ロジックの見直しが必要です）。",
    );
    const block = sliceFunctionBody(file.lines, anchors[0], "line-link.ts(LINE_TOKEN_URLへのfetch)");
    assert.ok(
      !block.includes("clientIpRelayHeaders"),
      "LINE公式のトークンエンドポイントへのfetchに中継ヘッダ（利用者IPの署名付きヘッダ）が" +
        "付いています。中継ヘッダはbackend宛てのfetchにのみ付けるべきで、LINE側には送るべき" +
        "ではありません。",
    );
  });
});

describe("c. backend への fetch に受信ヘッダそのものを丸ごと展開していない", () => {
  const TARGET_REL_PATHS: readonly string[] = ["auth.ts", "lib/line-link.ts"];

  /**
   * 受信ヘッダの丸ごと転送を疑わせるパターン。スプレッド構文（"..."）を伴う場合のみ
   * 検出する（"incomingHeaders" 等を通常の引数として渡すことは正当な用法であり、
   * スプレッドしている場合だけが「ヘッダをまるごと展開している」ことを意味するため）。
   */
  const FORBIDDEN_PATTERNS: readonly { label: string; pattern: RegExp }[] = [
    { label: '"...request.headers"（?.付き含む）のスプレッド', pattern: /\.\.\.\s*request\??\.headers\b/ },
    { label: '"...req.headers"（?.付き含む）のスプレッド', pattern: /\.\.\.\s*req\??\.headers\b/ },
    { label: '"...incomingHeaders" のスプレッド', pattern: /\.\.\.\s*incomingHeaders\b/ },
    { label: "headers() の戻り値のスプレッド", pattern: /\.\.\.\s*\(?\s*await\s+headers\(\)/ },
    { label: "Object.fromEntries( による丸ごとコピー", pattern: /Object\.fromEntries\(/ },
  ];

  for (const relPath of TARGET_REL_PATHS) {
    it(`${relPath} に受信ヘッダを丸ごと展開する既知パターンが無い`, () => {
      const file = fileByRelPath(relPath);
      const text = file.lines.join("\n");
      for (const { label, pattern } of FORBIDDEN_PATTERNS) {
        assert.ok(!pattern.test(text), `${relPath} に禁止パターンが見つかりました: ${label}`);
      }
    });
  }
});

describe("d. authorize / signIn が受信ヘッダを backend 呼び出しへ渡している", () => {
  it("auth.ts: Credentials の authorize が request?.headers を backendLogin に渡している（user/operator 両プロバイダ分）", () => {
    const file = fileByRelPath("auth.ts");
    const text = file.lines.join("\n");
    const matches = text.match(/request\?\.headers/g) ?? [];
    assert.equal(
      matches.length,
      2,
      "user-credentials・operator-credentials の両方の authorize で request?.headers が" +
        ` backendLogin に渡されているはずです（実際の出現数: ${matches.length}）。`,
    );
  });

  it("auth.ts: LINEのsignInコールバックがreadIncomingRequestHeaders()の戻り値をbackendLineExchangeに渡している", () => {
    const file = fileByRelPath("auth.ts");
    const text = file.lines.join("\n");
    assert.match(
      text,
      /backendLineExchange\(\s*lineAccessToken\s*,\s*await\s+readIncomingRequestHeaders\(\)\s*\)/,
      "signIn コールバックが readIncomingRequestHeaders() の戻り値を backendLineExchange の" +
        "第2引数に渡していません。",
    );
  });

  it("auth.ts: readIncomingRequestHeaders自体がtry/catch付きでheaders()を呼んでいる", () => {
    const file = fileByRelPath("auth.ts");
    const anchors = findAnchorIndices(file.lines, "async function readIncomingRequestHeaders(");
    assert.equal(
      anchors.length,
      1,
      "前提: readIncomingRequestHeaders の定義は1箇所のはずです。",
    );
    const block = sliceFunctionBody(file.lines, anchors[0], "auth.ts(readIncomingRequestHeaders)");
    assert.match(block, /try\s*{/, "readIncomingRequestHeaders に try { が見当たりません。");
    assert.match(block, /await\s+headers\(\)/, "readIncomingRequestHeaders に await headers() の呼び出しが見当たりません。");
    assert.match(block, /catch/, "readIncomingRequestHeaders に catch 節が見当たりません。");
  });
});

describe("e. clientIpRelayHeaders の import は許可リスト（auth.ts / lib/line-link.ts）に限られる", () => {
  /**
   * clientIpRelayHeaders を import してよい relPath の許可リスト。
   * b〜d の各 describe はこの許可リストのファイルだけを対象に redirect: "error" 等を
   * 検査しているため、許可リスト外から import する新しい呼び出し元が現れても b〜d は
   * 何も検知できない（検査対象に含まれないため）。この it が「許可リスト外からの
   * import」自体を検知することで、新しい呼び出し元が b〜d の検査から漏れたまま
   * 見過ごされることを防ぐ（セキュリティレビュー指摘 I-6 是正）。
   */
  const ALLOWED_CLIENT_IP_RELAY_HEADERS_IMPORTERS: readonly string[] = ["auth.ts", "lib/line-link.ts"];

  it("許可リスト外のソースファイルが clientIpRelayHeaders を import していない", () => {
    const offenders: string[] = [];
    for (const file of ALL_SOURCE_FILES) {
      if (file.relPath === "lib/client-ip-relay.ts") continue;
      if (file.relPath.endsWith(".test.mts")) continue;
      if (ALLOWED_CLIENT_IP_RELAY_HEADERS_IMPORTERS.includes(file.relPath)) continue;
      if (importsClientIpRelayHeaders(file.lines.join("\n"))) {
        offenders.push(file.relPath);
      }
    }
    assert.deepEqual(
      offenders,
      [],
      "clientIpRelayHeaders を import している新しい呼び出し元が見つかりました: " +
        `[${offenders.join(", ")}]。この静的検査（b〜dの各describe）は許可リスト` +
        "（auth.ts / lib/line-link.ts）だけを対象に redirect:\"error\" と中継ヘッダの" +
        "スプレッドを検査しているため、新しい呼び出し元を追加する場合は、このテストの" +
        "ALLOWED_CLIENT_IP_RELAY_HEADERS_IMPORTERS と、b〜dの各describe内の対象一覧" +
        "（BACKEND_FETCH_TARGETS・TARGET_REL_PATHS等）の両方に追加してください。",
    );
  });

  it("許可リストの各ファイルが走査結果に存在し、実際に clientIpRelayHeaders を import している（許可リストの空文字化・誤記の検知）", () => {
    for (const relPath of ALLOWED_CLIENT_IP_RELAY_HEADERS_IMPORTERS) {
      const file = fileByRelPath(relPath);
      assert.ok(
        importsClientIpRelayHeaders(file.lines.join("\n")),
        `前提: 許可リストの ${relPath} が実際には clientIpRelayHeaders を import して` +
          "いません。ファイルの移動・リネーム、または許可リスト自体の誤記の可能性が" +
          "あります。",
      );
    }
  });
});

describe("自己テスト: 静的検査の判定ロジック自体の検査", () => {
  describe("importsClientIpRelayHeaders", () => {
    it("通常の named import（他の識別子と同時 import）を陽性と判定する", () => {
      assert.equal(
        importsClientIpRelayHeaders(
          'import { clientIpRelayHeaders, type HeaderReader } from "@/lib/client-ip-relay";',
        ),
        true,
      );
    });

    it("import type { ... } の形でも陽性と判定する", () => {
      assert.equal(
        importsClientIpRelayHeaders('import type { clientIpRelayHeaders } from "@/lib/client-ip-relay";'),
        true,
      );
    });

    it("複数行にわたる import 文でも陽性と判定する", () => {
      const src = [
        "import {",
        "  clientIpRelayHeaders,",
        "  type HeaderReader,",
        '} from "./client-ip-relay";',
      ].join("\n");
      assert.equal(importsClientIpRelayHeaders(src), true);
    });

    it("別の識別子だけを import する文字列を陰性と判定する", () => {
      assert.equal(
        importsClientIpRelayHeaders('import { serverBackendApiBase } from "@/lib/backend-api-base";'),
        false,
      );
    });

    it("import文以外での識別子への言及（呼び出し・コメント）を陰性と判定する", () => {
      assert.equal(
        importsClientIpRelayHeaders('const relayHeaders = await clientIpRelayHeaders("POST", url, h);'),
        false,
      );
      assert.equal(
        importsClientIpRelayHeaders(
          "// clientIpRelayHeaders という語句への言及のみ（import文ではない）",
        ),
        false,
      );
    });
  });

  describe("countFetchCalls", () => {
    it("fetch(...) 呼び出しが1個の文字列で1を返す", () => {
      assert.equal(countFetchCalls('const res = await fetch(url, { method: "POST" });'), 1);
    });

    it("fetch(...) 呼び出しが2個の文字列で2を返す", () => {
      const src = ["const a = await fetch(url1, {});", "const b = await fetch(url2, {});"].join("\n");
      assert.equal(countFetchCalls(src), 2);
    });

    it("fetch(...) 呼び出しが0個の文字列で0を返す", () => {
      assert.equal(countFetchCalls("const x = 1;"), 0);
    });
  });
});
