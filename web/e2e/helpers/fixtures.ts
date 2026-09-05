/**
 * シード済み DB から前提データを「引き当てる」ヘルパー。
 *
 * 案件の新規作成は AI 解析を伴い時間あたり上限（既定 10件/時・IP軸/アカウント軸）が
 * あるため、**既存の案件・取引を再利用できる場合は必ず再利用し、作成は最後の手段**に
 * している。この方針を崩すと desktop/mobile の2プロジェクトぶんを流した時点で
 * 429 に当たってスイート全体が落ちる。
 */
import { Api, CaseDetail, OperatorSession, TransactionSummary } from "./api";

/** 入札待ちで、指定業者の入札が載っている案件を1件用意する。 */
export async function ensureOpenCaseWithBid(
  api: Api,
  sellerToken: string,
  vendor: OperatorSession,
): Promise<{ caseId: string; bidId: string }> {
  const cases = await api.listCases(sellerToken);
  const openCases = cases.filter((c) => c.status === "open" || c.status === "bidding");

  // 1) 既に業者の入札が載っている open 案件があればそれを使う。
  for (const c of openCases) {
    const detail: CaseDetail = await api.getCase(c.id, sellerToken);
    const bid = detail.bids?.find((b) => b.status === "pending" && b.operator?.id === vendor.operatorId);
    if (bid) return { caseId: c.id, bidId: bid.id };
  }

  // 2) 入札の無い open 案件があれば、そこへ業者として入札する。
  for (const c of openCases) {
    const detail = await api.getCase(c.id, sellerToken);
    const already = detail.bids?.some((b) => b.operator?.id === vendor.operatorId);
    if (already) continue;
    try {
      const bid = await api.createBid(c.id, 32000, "E2E: まとめて引き取ります。", vendor.token);
      return { caseId: c.id, bidId: bid.id };
    } catch (err) {
      // 409（既に入札済み）は入札一覧の形が想定と違った場合の保険。次の案件へ。
      if (String(err).includes("409")) continue;
      throw err;
    }
  }

  // 3) 最後の手段: 案件を新規作成する。
  const created = await api.createCase(sellerToken);
  const bid = await api.createBid(created.id, 32000, "E2E: まとめて引き取ります。", vendor.token);
  return { caseId: created.id, bidId: bid.id };
}

/** 進行中（pending / visiting）の取引を1件用意する。無ければ入札→選定で作る。 */
export async function ensureLiveTransaction(
  api: Api,
  sellerToken: string,
  vendor: OperatorSession,
  opts: { withoutPendingReduction?: boolean } = {},
): Promise<TransactionSummary> {
  const live = (await api.listTransactions(sellerToken)).filter(
    (t) => t.status === "pending" || t.status === "visiting",
  );
  for (const t of live) {
    if (!opts.withoutPendingReduction) return t;
    const detail = await api.getTransaction(t.id, sellerToken);
    if (!detail.reductions?.some((r) => r.status === "pending")) return t;
  }

  const { caseId, bidId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  return api.selectBid(caseId, bidId, sellerToken);
}

/** 訪問日程が未確定（pending かつ visit_date null）の取引を1件用意する。 */
export async function ensureUnscheduledTransaction(
  api: Api,
  sellerToken: string,
  vendor: OperatorSession,
): Promise<TransactionSummary> {
  const candidates = (await api.listTransactions(sellerToken)).filter(
    (t) => t.status === "pending" && t.visit_date == null,
  );
  for (const t of candidates) {
    const detail = await api.getTransaction(t.id, sellerToken);
    if (!detail.reductions?.some((r) => r.status === "pending")) return t;
  }
  const { caseId, bidId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  return api.selectBid(caseId, bidId, sellerToken);
}
