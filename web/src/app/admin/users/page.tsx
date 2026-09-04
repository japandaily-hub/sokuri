"use client";

/**
 * 管理画面: 依頼者アカウントの一覧・停止／解除（role=admin のみ）。
 * 依頼者側に停止手段が無かった問題（r3-verify-operator ADD-2）への対応。
 * 既存の業者停止（admin/page.tsx toggleSuspend）と同じ確認フローだが、
 * window.confirm ではなく ConfirmModal（自前ダイアログ）を使う。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Card, Notice, PageShell, StatusBadge, btnDanger, btnPrimary, btnSecondary, inputBase, useToken } from "@/components/kdz/Ui";
import { AdminPagination } from "../_components/AdminPagination";
import { ConfirmModal } from "../_components/ConfirmModal";
import { CopyableId } from "../_components/CopyableId";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  adminListUsers,
  adminSuspendUser,
  adminPromoteUser,
  adminDemoteUser,
  toDisplayMessage,
  type AdminUserListItem,
  type AdminUserListResponse,
} from "@/lib/katadzuke-api";

/** 昇格／降格の確認モーダル対象。 */
type RoleActionTarget = { user: AdminUserListItem; action: "promote" | "demote" };

export default function AdminUsersPage() {
  const { token, loading } = useToken();
  // 自分自身の行には昇格／降格ボタンを出さない。session に user.id は無いため email 一致で判定する
  // （/auth/me 相当の専用エンドポイントは無い。r3 再レビュー3回目 指示どおり email フォールバック）。
  const { data: session } = useSession();
  const myEmail = session?.user?.email ?? null;
  const [data, setData] = useState<AdminUserListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // r3 再レビュー R-M5 是正: 停止操作時点の進行中案件数（backend が返す open_case_count）を
  // 運営に提示する。0件なら表示しない（不要な注意喚起を避ける）。
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);

  const [suspendTarget, setSuspendTarget] = useState<AdminUserListItem | null>(null);
  const [roleTarget, setRoleTarget] = useState<RoleActionTarget | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    try {
      const res = await adminListUsers({ q, limit: ADMIN_LIST_DEFAULT_LIMIT, offset }, token);
      setData(res);
      setError(null);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    } finally {
      setBusy(false);
    }
  }, [token, q, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function runSearch() {
    setOffset(0);
    setQ(qInput.trim());
  }

  async function confirmSuspend(reason: string | null) {
    if (!suspendTarget || !token || busy) return;
    const next = !suspendTarget.is_suspended;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await adminSuspendUser(suspendTarget.id, next, reason, token);
      setSuspendTarget(null);
      if (next && result.open_case_count > 0) {
        setNotice(
          `停止しました（進行中の案件が${result.open_case_count}件あります。必要に応じて案件一覧から確認してください）`,
        );
      }
      await reload();
    } catch (e) {
      // r4-fix-frontend2 M2 波及是正: 失敗時も対象をクリアしてモーダルを閉じ、
      // 隠れずに見える Notice でエラーを出す（admin/page.tsx・operator-applications/page.tsx と同型）。
      setSuspendTarget(null);
      setError(toDisplayMessage(e, "更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRoleChange() {
    if (!roleTarget || !token || busy) return;
    const { user: target, action } = roleTarget;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (action === "promote") {
        await adminPromoteUser(target.id, token);
      } else {
        await adminDemoteUser(target.id, token);
      }
      setRoleTarget(null);
      await reload();
    } catch (e) {
      setRoleTarget(null);
      setError(
        toDisplayMessage(
          e,
          action === "promote" ? "管理者への昇格に失敗しました" : "管理者権限の解除に失敗しました",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!data && !error)) {
    return (
      <div className="admin-page">
        <AppHeader showBell={false} />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AppHeader showBell={false} />
      <PageShell
        title="依頼者一覧"
        description="依頼者アカウントを検索・閲覧し、必要に応じて停止／解除できます。"
        actions={
          <Link href="/admin" className={btnSecondary}>
            管理画面トップへ
          </Link>
        }
      >
        {error ? (
          <div className="mb-4">
            <Notice tone="error">{error}</Notice>
          </div>
        ) : null}
        {notice ? (
          <div className="mb-4">
            <Notice tone="warn">{notice}</Notice>
          </div>
        ) : null}

        <Card>
          <div className="flex gap-2">
            <input
              type="text"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") runSearch();
              }}
              className={inputBase}
              placeholder="メール／表示名（部分一致）またはユーザーIDで検索"
            />
            <button type="button" onClick={runSearch} className={`${btnPrimary} shrink-0`}>
              検索
            </button>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">ID</th>
                  <th className="pb-2 pr-4">メール</th>
                  <th className="pb-2 pr-4">表示名</th>
                  <th className="pb-2 pr-4">登録日時</th>
                  <th className="pb-2 pr-4 text-right">案件数</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((u) => (
                  <tr key={u.id}>
                    <td className="py-2 pr-4">
                      <CopyableId id={u.id} />
                    </td>
                    <td className="py-2 pr-4 text-slate-700">{u.email}</td>
                    <td className="py-2 pr-4 text-slate-700">{u.display_name ?? "—"}</td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {new Date(u.created_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4 text-right">{u.case_count}</td>
                    <td className="py-2 pr-4">
                      {u.role === "admin" ? (
                        <StatusBadge value="approved" label="admin" />
                      ) : u.is_suspended ? (
                        <StatusBadge value="cancelled" label="停止中" />
                      ) : (
                        <StatusBadge value="completed" label="有効" />
                      )}
                    </td>
                    <td className="py-2 text-right">
                      <div className="flex justify-end gap-2">
                        {u.email !== myEmail && u.role === "user" && !u.is_suspended ? (
                          <button
                            type="button"
                            onClick={() => setRoleTarget({ user: u, action: "promote" })}
                            disabled={busy}
                            className={btnSecondary}
                          >
                            管理者にする
                          </button>
                        ) : null}
                        {u.email !== myEmail && u.role === "admin" ? (
                          <button
                            type="button"
                            onClick={() => setRoleTarget({ user: u, action: "demote" })}
                            disabled={busy}
                            className={btnSecondary}
                          >
                            管理者を解除
                          </button>
                        ) : null}
                        {u.role === "admin" ? null : (
                          <button
                            type="button"
                            onClick={() => setSuspendTarget(u)}
                            disabled={busy}
                            className={u.is_suspended ? btnPrimary : btnDanger}
                          >
                            {u.is_suspended ? "停止を解除" : "停止する"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && data.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当する依頼者はいません。</p>
            ) : null}
            {busy && !suspendTarget ? (
              <div className="flex items-center gap-2 py-3 text-sm text-slate-400">
                <Spinner className="h-4 w-4" /> 読み込み中…
              </div>
            ) : null}
          </div>

          {data ? (
            <AdminPagination
              total={data.total}
              limit={ADMIN_LIST_DEFAULT_LIMIT}
              offset={offset}
              itemCount={data.items.length}
              onPrev={() => setOffset(Math.max(0, offset - ADMIN_LIST_DEFAULT_LIMIT))}
              onNext={() => setOffset(offset + ADMIN_LIST_DEFAULT_LIMIT)}
            />
          ) : null}
        </Card>
      </PageShell>

      {suspendTarget ? (
        <ConfirmModal
          title={
            suspendTarget.is_suspended
              ? `${suspendTarget.email} の停止を解除します`
              : `${suspendTarget.email} を停止します`
          }
          message={
            suspendTarget.is_suspended
              ? "停止を解除すると、依頼者は再びログイン・案件作成ができるようになります。よろしいですか？"
              : "停止すると、依頼者の既存トークンは失効しログインができなくなります。よろしいですか？"
          }
          confirmLabel={suspendTarget.is_suspended ? "停止を解除する" : "停止する"}
          danger={!suspendTarget.is_suspended}
          withReason
          reasonLabel="理由（任意・社内記録用）"
          busy={busy}
          onCancel={() => setSuspendTarget(null)}
          onConfirm={(reason) => void confirmSuspend(reason)}
        />
      ) : null}

      {roleTarget ? (
        <ConfirmModal
          title={
            roleTarget.action === "promote"
              ? `${roleTarget.user.email} を管理者にします`
              : `${roleTarget.user.email} の管理者権限を解除します`
          }
          message={
            roleTarget.action === "promote"
              ? "管理者にすると、このユーザーは依頼者・業者アカウントの停止／解除や管理者権限の付与ができるようになります。よろしいですか？"
              : "管理者権限を解除すると、このユーザーは一般の依頼者アカウントに戻ります。よろしいですか？"
          }
          confirmLabel={roleTarget.action === "promote" ? "管理者にする" : "解除する"}
          danger={roleTarget.action === "demote"}
          busy={busy}
          onCancel={() => setRoleTarget(null)}
          onConfirm={() => void confirmRoleChange()}
        />
      ) : null}
    </div>
  );
}
