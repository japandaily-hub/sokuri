"use client";

/** 管理画面: 招待コード発行 / 業者承認（role=admin のみ。ミドルウェアで保護）。 */

import { useCallback, useEffect, useState } from "react";
import { Spinner } from "@/components/Icon";
import {
  Card,
  Notice,
  PageShell,
  StatusBadge,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import {
  KdzApiError,
  adminCreateInvite,
  adminListInvites,
  adminListOperators,
  adminVerifyOperator,
  type InviteOut,
  type OperatorOut,
} from "@/lib/katadzuke-api";

export default function AdminPage() {
  const { token, loading } = useToken();
  const [invites, setInvites] = useState<InviteOut[] | null>(null);
  const [operators, setOperators] = useState<OperatorOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      const [inv, ops] = await Promise.all([
        adminListInvites(token),
        adminListOperators(token),
      ]);
      setInvites(inv);
      setOperators(ops);
    } catch (e) {
      setError(e instanceof KdzApiError ? e.message : "取得に失敗しました");
    }
  }, [token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function issueInvite() {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await adminCreateInvite(inviteEmail.trim() || null, token);
      setInviteEmail("");
      await reload();
    } catch (e) {
      setError(e instanceof KdzApiError ? e.message : "発行に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  async function toggleVerify(op: OperatorOut) {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await adminVerifyOperator(op.id, op.verified_at == null, token);
      await reload();
    } catch (e) {
      setError(e instanceof KdzApiError ? e.message : "更新に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  function copyCode(code: string) {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(code);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  if (loading || (!invites && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  return (
    <PageShell title="管理画面" description="業者招待コードの発行とアカウント承認を行います。">
      {error ? (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ===== 招待コード ===== */}
        <Card>
          <h2 className="font-bold text-slate-900">業者招待コード</h2>
          <div className="mt-3 flex gap-2">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className={inputBase}
              placeholder="送付先メール（任意・メモ用）"
            />
            <button
              type="button"
              onClick={issueInvite}
              disabled={busy}
              className={`${btnPrimary} shrink-0`}
            >
              発行
            </button>
          </div>
          <ul className="mt-4 divide-y divide-slate-100">
            {invites?.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between gap-2 py-2.5">
                <div>
                  <p className="font-mono text-sm font-bold text-slate-900">{inv.code}</p>
                  <p className="text-xs text-slate-400">
                    {inv.email ?? "宛先未指定"} ・{" "}
                    {new Date(inv.created_at).toLocaleDateString("ja-JP")}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {inv.used_at ? (
                    <StatusBadge value="rejected" label="使用済み" />
                  ) : (
                    <>
                      <StatusBadge value="open" label="未使用" />
                      <button
                        type="button"
                        onClick={() => copyCode(inv.code)}
                        className={btnSecondary}
                      >
                        {copied === inv.code ? "コピー済" : "コピー"}
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
            {invites && invites.length === 0 ? (
              <li className="py-3 text-sm text-slate-500">まだ発行されていません。</li>
            ) : null}
          </ul>
        </Card>

        {/* ===== 業者承認 ===== */}
        <Card>
          <h2 className="font-bold text-slate-900">業者アカウント</h2>
          <ul className="mt-4 divide-y divide-slate-100">
            {operators?.map((op) => (
              <li key={op.id} className="flex items-center justify-between gap-2 py-2.5">
                <div>
                  <p className="text-sm font-bold text-slate-900">{op.company_name}</p>
                  <p className="text-xs text-slate-400">
                    {op.contact_email}
                    {op.license_number ? ` ・ ${op.license_number}` : ""}
                  </p>
                  <div className="mt-1 flex gap-1.5">
                    {op.verified_at ? (
                      <StatusBadge value="completed" label="承認済み" />
                    ) : (
                      <StatusBadge value="pending" label="承認待ち" />
                    )}
                    {op.is_suspended ? <StatusBadge value="cancelled" label="停止中" /> : null}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => toggleVerify(op)}
                  disabled={busy}
                  className={op.verified_at ? btnSecondary : btnPrimary}
                >
                  {op.verified_at ? "承認を取消" : "承認する"}
                </button>
              </li>
            ))}
            {operators && operators.length === 0 ? (
              <li className="py-3 text-sm text-slate-500">登録業者はまだいません。</li>
            ) : null}
          </ul>
        </Card>
      </div>
    </PageShell>
  );
}
