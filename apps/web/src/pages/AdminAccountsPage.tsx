import { useEffect, useMemo, useState } from "react";
import {
  createAccount,
  fetchAccounts,
  fetchFilterMeta,
  resetManagedAccountPassword,
  updateAccount,
} from "../api/client";
import type {
  AccountRow,
  AccountUpsertPayload,
  StoreOption,
  UserRole,
  UserStatus,
} from "../types/dashboard";
import { formatDateTime } from "../utils/format";

const emptyDraft: AccountUpsertPayload = {
  username: "",
  display_name: "",
  role: "store",
  status: "active",
  external_account_id: "",
  store_ids: [],
  password: "",
  password_confirm: "",
};

function accountDraft(account?: AccountRow | null): AccountUpsertPayload {
  if (!account) {
    return { ...emptyDraft, store_ids: [] };
  }
  return {
    username: account.username,
    display_name: account.display_name,
    role: account.role,
    status: account.status,
    external_account_id: account.external_account_id ?? "",
    store_ids: account.stores.map((store) => store.store_id),
    password: "",
    password_confirm: "",
  };
}

function compactPayload(
  draft: AccountUpsertPayload,
  includePassword: boolean,
): AccountUpsertPayload {
  const password = draft.password?.trim() ?? "";
  const passwordConfirm = draft.password_confirm?.trim() ?? "";
  return {
    username: draft.username.trim(),
    display_name: draft.display_name.trim(),
    role: draft.role,
    status: draft.status,
    external_account_id: draft.external_account_id?.trim() || null,
    store_ids: draft.role === "store" ? draft.store_ids : [],
    password: includePassword || password || passwordConfirm ? password : null,
    password_confirm:
      includePassword || password || passwordConfirm ? passwordConfirm : null,
  };
}

function roleLabel(role: UserRole): string {
  if (role === "admin") {
    return "最高管理员";
  }
  if (role === "viewer") {
    return "全局查看";
  }
  return "门店账号";
}

function storesLabel(account: AccountRow): string {
  if (account.role !== "store") {
    return "全部门店";
  }
  if (!account.stores.length) {
    return "未绑定";
  }
  return account.stores
    .map((store) => `${store.store_name || store.store_id}(${store.store_id})`)
    .join("、");
}

export function AdminAccountsPage() {
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [draft, setDraft] = useState<AccountUpsertPayload>(accountDraft());
  const [resetTarget, setResetTarget] = useState<AccountRow | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [statusText, setStatusText] = useState("");

  const editingAccount = useMemo(
    () => accounts.find((account) => account.user_id === editingUserId) ?? null,
    [accounts, editingUserId],
  );

  const loadData = () => {
    setLoading(true);
    setStatusText("");
    Promise.all([fetchAccounts(), fetchFilterMeta()])
      .then(([accountResponse, filterResponse]) => {
        setAccounts(accountResponse.data.rows);
        setStores(filterResponse.data.stores);
      })
      .catch(() => {
        setStatusText("账号数据暂时无法读取，请确认当前账号具有管理员权限。");
      })
      .finally(() => setLoading(false));
  };

  useEffect(loadData, []);

  const setDraftField = <K extends keyof AccountUpsertPayload>(
    field: K,
    value: AccountUpsertPayload[K],
  ) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const startCreate = () => {
    setEditingUserId(null);
    setDraft(accountDraft());
    setStatusText("");
  };

  const startEdit = (account: AccountRow) => {
    setEditingUserId(account.user_id);
    setDraft(accountDraft(account));
    setStatusText("");
  };

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setStatusText("");
    try {
      const payload = compactPayload(draft, editingUserId === null);
      const result =
        editingUserId === null
          ? await createAccount(payload)
          : await updateAccount(editingUserId, payload);
      setAccounts((current) => {
        const withoutSaved = current.filter(
          (account) => account.user_id !== result.data.user_id,
        );
        return [...withoutSaved, result.data].sort((a, b) =>
          a.username.localeCompare(b.username),
        );
      });
      setEditingUserId(result.data.user_id);
      setDraft(accountDraft(result.data));
      setStatusText("账号已保存。");
    } catch {
      setStatusText("保存失败，请检查账号名、所属账户ID、密码确认和门店绑定。");
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!resetTarget) {
      return;
    }
    setSaving(true);
    setStatusText("");
    try {
      const result = await resetManagedAccountPassword(resetTarget.user_id, {
        password: resetPassword,
        password_confirm: resetPasswordConfirm,
      });
      setAccounts((current) =>
        current.map((account) =>
          account.user_id === result.data.user_id ? result.data : account,
        ),
      );
      setResetTarget(null);
      setResetPassword("");
      setResetPasswordConfirm("");
      setStatusText("密码已重置。");
    } catch {
      setStatusText("密码重置失败，请检查两次输入是否一致。");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <p className="source-pill">账号体系</p>
          <h1>账号管理</h1>
          <p className="admin-muted">
            管理登录账号、角色状态和门店数据范围。
          </p>
        </div>
        <div className="admin-header-actions">
          <a className="ghost-button admin-link-button" href="/admin">
            返回后台首页
          </a>
          <button className="primary-button" onClick={startCreate} type="button">
            新建账号
          </button>
        </div>
      </section>

      {statusText ? (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="resource-notice"
          role="status"
        >
          {statusText}
        </div>
      ) : null}

      <section className="content-section account-admin-layout">
        <div className="account-admin-main">
          <div className="section-title">
            <div>
              <h2>账号列表</h2>
              <p>共 {accounts.length} 个本地账号。</p>
            </div>
            {loading ? <span className="source-pill">加载中</span> : null}
          </div>
          <div className="table-wrap">
            <table className="data-table account-table">
              <thead>
                <tr>
                  <th>账号名</th>
                  <th>所属账户ID</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>门店范围</th>
                  <th>激活状态</th>
                  <th>更新时间</th>
                  <th className="is-center">操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.length === 0 ? (
                  <tr>
                    <td className="empty-cell" colSpan={8}>
                      暂无账号
                    </td>
                  </tr>
                ) : (
                  accounts.map((account) => (
                    <tr key={account.user_id}>
                      <td>
                        <strong>{account.display_name || account.username}</strong>
                        <br />
                        <span className="mono-cell">{account.username}</span>
                      </td>
                      <td className="mono-cell">{account.external_account_id || "-"}</td>
                      <td>{roleLabel(account.role)}</td>
                      <td>
                        <span className="status-chip">
                          {account.status === "active" ? "启用" : "停用"}
                        </span>
                      </td>
                      <td>{storesLabel(account)}</td>
                      <td>{account.is_initialized ? "已激活" : "未激活"}</td>
                      <td>{formatDateTime(account.updated_at)}</td>
                      <td className="is-center">
                        <div className="table-action-row">
                          <button
                            className="ghost-button"
                            onClick={() => startEdit(account)}
                            type="button"
                          >
                            编辑
                          </button>
                          <button
                            className="ghost-button"
                            onClick={() => setResetTarget(account)}
                            type="button"
                          >
                            重置密码
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <aside className="account-editor">
          <form className="content-section account-form" onSubmit={handleSave}>
            <div className="section-title">
              <div>
                <h2>{editingAccount ? "编辑账号" : "新建账号"}</h2>
                <p>{editingAccount ? editingAccount.user_id : "创建后立即可登录"}</p>
              </div>
            </div>
            <label className="filter-field">
              <span>账号名</span>
              <input
                onChange={(event) => setDraftField("username", event.target.value)}
                value={draft.username}
              />
            </label>
            <label className="filter-field">
              <span>显示名称</span>
              <input
                onChange={(event) =>
                  setDraftField("display_name", event.target.value)
                }
                value={draft.display_name}
              />
            </label>
            <label className="filter-field">
              <span>所属账户ID</span>
              <input
                onChange={(event) =>
                  setDraftField("external_account_id", event.target.value)
                }
                value={draft.external_account_id ?? ""}
              />
            </label>
            <label className="filter-field">
              <span>角色</span>
              <select
                onChange={(event) =>
                  setDraftField("role", event.target.value as UserRole)
                }
                value={draft.role}
              >
                <option value="store">门店账号</option>
                <option value="viewer">全局查看</option>
                <option value="admin">最高管理员</option>
              </select>
            </label>
            <label className="filter-field">
              <span>状态</span>
              <select
                onChange={(event) =>
                  setDraftField("status", event.target.value as UserStatus)
                }
                value={draft.status}
              >
                <option value="active">启用</option>
                <option value="disabled">停用</option>
              </select>
            </label>
            <label className="filter-field">
              <span>门店权限</span>
              <select
                disabled={draft.role !== "store"}
                multiple
                onChange={(event) =>
                  setDraftField(
                    "store_ids",
                    Array.from(event.currentTarget.selectedOptions).map(
                      (option) => option.value,
                    ),
                  )
                }
                size={Math.min(10, Math.max(4, stores.length))}
                value={draft.store_ids}
              >
                {stores.map((store) => (
                  <option key={store.store_id} value={store.store_id}>
                    {store.store_name} ({store.store_id})
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span>{editingAccount ? "新密码（可选）" : "密码"}</span>
              <input
                autoComplete="new-password"
                onChange={(event) => setDraftField("password", event.target.value)}
                type="password"
                value={draft.password ?? ""}
              />
            </label>
            <label className="filter-field">
              <span>确认密码</span>
              <input
                autoComplete="new-password"
                onChange={(event) =>
                  setDraftField("password_confirm", event.target.value)
                }
                type="password"
                value={draft.password_confirm ?? ""}
              />
            </label>
            <button className="primary-button" disabled={saving} type="submit">
              保存账号
            </button>
          </form>

          {resetTarget ? (
            <form
              className="content-section account-form"
              onSubmit={handleResetPassword}
            >
              <div className="section-title">
                <div>
                  <h2>重置密码</h2>
                  <p>{resetTarget.username}</p>
                </div>
                <button
                  className="ghost-button"
                  onClick={() => setResetTarget(null)}
                  type="button"
                >
                  取消
                </button>
              </div>
              <label className="filter-field">
                <span>新密码</span>
                <input
                  autoComplete="new-password"
                  onChange={(event) => setResetPassword(event.target.value)}
                  type="password"
                  value={resetPassword}
                />
              </label>
              <label className="filter-field">
                <span>确认密码</span>
                <input
                  autoComplete="new-password"
                  onChange={(event) => setResetPasswordConfirm(event.target.value)}
                  type="password"
                  value={resetPasswordConfirm}
                />
              </label>
              <button className="primary-button" disabled={saving} type="submit">
                确认重置
              </button>
            </form>
          ) : null}
        </aside>
      </section>
    </div>
  );
}
