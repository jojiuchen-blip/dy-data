import { useEffect, useMemo, useState } from "react";
import {
  createAccount,
  fetchAccounts,
  fetchFilterMeta,
  fetchUnactivatedAccountStores,
  resetManagedAccountPassword,
  updateAccount,
} from "../api/client";
import { Button } from "../components/Button";
import { StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { MultiSelectField, SelectField } from "../components/FormControls";
import type {
  AccountRow,
  AccountUpsertPayload,
  StoreOption,
  UnactivatedStoreAccountRow,
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

function idListLabel(values: string[]): string {
  return values.length ? values.join("、") : "-";
}

export function AdminAccountsPage() {
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [unactivatedStores, setUnactivatedStores] = useState<
    UnactivatedStoreAccountRow[]
  >([]);
  const [unactivatedQuery, setUnactivatedQuery] = useState("");
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [draft, setDraft] = useState<AccountUpsertPayload>(accountDraft());
  const [resetTarget, setResetTarget] = useState<AccountRow | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState("");
  const [loading, setLoading] = useState(true);
  const [unactivatedLoading, setUnactivatedLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [statusText, setStatusText] = useState("");

  const editingAccount = useMemo(
    () => accounts.find((account) => account.user_id === editingUserId) ?? null,
    [accounts, editingUserId],
  );

  const loadData = () => {
    setLoading(true);
    setUnactivatedLoading(true);
    setStatusText("");
    Promise.all([
      fetchAccounts(),
      fetchFilterMeta(),
      fetchUnactivatedAccountStores(),
    ])
      .then(([accountResponse, filterResponse, unactivatedResponse]) => {
        setAccounts(accountResponse.data.rows);
        setStores(filterResponse.data.stores);
        setUnactivatedStores(unactivatedResponse.data.rows);
      })
      .catch(() => {
        setStatusText("账号数据暂时无法读取，请确认当前账号具有管理员权限。");
      })
      .finally(() => {
        setLoading(false);
        setUnactivatedLoading(false);
      });
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

  const handleUnactivatedSearch = async (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    setUnactivatedLoading(true);
    setStatusText("");
    try {
      const response = await fetchUnactivatedAccountStores(
        unactivatedQuery.trim(),
      );
      setUnactivatedStores(response.data.rows);
    } catch {
      setStatusText("未激活门店暂时无法读取，请稍后重试。");
    } finally {
      setUnactivatedLoading(false);
    }
  };

  const resetUnactivatedSearch = async () => {
    setUnactivatedQuery("");
    setUnactivatedLoading(true);
    setStatusText("");
    try {
      const response = await fetchUnactivatedAccountStores();
      setUnactivatedStores(response.data.rows);
    } catch {
      setStatusText("未激活门店暂时无法读取，请稍后重试。");
    } finally {
      setUnactivatedLoading(false);
    }
  };

  const unactivatedStoreColumns: Column<UnactivatedStoreAccountRow>[] = [
    {
      key: "store",
      title: "门店",
      align: "left",
      render: (store) => (
        <>
          <strong>{store.store_name || store.store_id}</strong>
          <br />
          <span className="mono-cell">{store.store_id}</span>
        </>
      ),
    },
    {
      key: "subject",
      title: "认证主体",
      align: "left",
      render: (store) => store.certified_subject_name || "-",
    },
    {
      key: "account_ids",
      title: "所属账户ID",
      align: "left",
      render: (store) => (
        <span className="mono-cell">{idListLabel(store.account_ids)}</span>
      ),
    },
    {
      key: "poi_ids",
      title: "POI ID",
      align: "left",
      render: (store) => (
        <span className="mono-cell">{idListLabel(store.poi_ids)}</span>
      ),
    },
    {
      key: "poi_names",
      title: "POI 名称",
      align: "left",
      render: (store) => idListLabel(store.poi_names),
    },
  ];

  const accountColumns: Column<AccountRow>[] = [
    {
      key: "account",
      title: "账号名",
      align: "left",
      render: (account) => (
        <>
          <strong>{account.display_name || account.username}</strong>
          <br />
          <span className="mono-cell">{account.username}</span>
        </>
      ),
    },
    {
      key: "external",
      title: "所属账户ID",
      align: "left",
      render: (account) => (
        <span className="mono-cell">{account.external_account_id || "-"}</span>
      ),
    },
    { key: "role", title: "角色", render: (account) => roleLabel(account.role) },
    {
      key: "status",
      title: "状态",
      render: (account) => (
        <StatusChip tone={account.status === "active" ? "success" : "neutral"}>
          {account.status === "active" ? "启用" : "停用"}
        </StatusChip>
      ),
    },
    { key: "stores", title: "门店范围", align: "left", render: storesLabel },
    {
      key: "initialized",
      title: "激活状态",
      render: (account) => (account.is_initialized ? "已激活" : "未激活"),
    },
    {
      key: "updated",
      title: "更新时间",
      render: (account) => formatDateTime(account.updated_at),
    },
    {
      align: "center",
      key: "actions",
      title: "操作",
      render: (account) => (
        <div className="table-action-row">
          <Button
            onClick={() => startEdit(account)}
            type="button"
          >
            编辑
          </Button>
          <Button
            onClick={() => setResetTarget(account)}
            type="button"
          >
            重置密码
          </Button>
        </div>
      ),
    },
  ];

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
          <h1>账号管理</h1>
          <p className="admin-muted">
            管理登录账号、角色状态和门店数据范围。
          </p>
        </div>
        <div className="admin-header-actions">
          <Button onClick={startCreate} type="button" variant="primary">
            新建账号
          </Button>
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
          <DataTable
            columns={accountColumns}
            emptyText={loading ? "正在加载账号..." : "暂无账号"}
            rows={accounts}
            state={loading ? "loading" : "ready"}
            tableClassName="account-table"
          />
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
            <SelectField
              label="角色"
              onChange={(value) => setDraftField("role", value as UserRole)}
              options={[
                { value: "store", label: "门店账号" },
                { value: "viewer", label: "全局查看" },
                { value: "admin", label: "最高管理员" },
              ]}
              value={draft.role}
            />
            <SelectField
              label="状态"
              onChange={(value) => setDraftField("status", value as UserStatus)}
              options={[
                { value: "active", label: "启用" },
                { value: "disabled", label: "停用" },
              ]}
              value={draft.status}
            />
            <MultiSelectField
              disabled={draft.role !== "store"}
              emptyLabel={draft.role === "store" ? "未绑定门店" : "全部门店"}
              helperText={
                draft.role === "store"
                  ? "门店账号只能查看和操作已绑定门店。"
                  : "全局角色默认拥有全部门店范围。"
              }
              label="门店权限"
              onChange={(value) => setDraftField("store_ids", value)}
              options={stores.map((store) => ({
                label: `${store.store_name} (${store.store_id})`,
                value: store.store_id,
              }))}
              value={draft.role === "store" ? draft.store_ids : []}
            />
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
            <Button disabled={saving} type="submit" variant="primary">
              保存账号
            </Button>
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
                <Button
                  onClick={() => setResetTarget(null)}
                  type="button"
                >
                  取消
                </Button>
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
              <Button disabled={saving} type="submit" variant="primary">
                确认重置
              </Button>
            </form>
          ) : null}
        </aside>
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>未激活门店</h2>
            <p>
              共 {unactivatedStores.length} 个已准备但尚未激活账号的门店，可按所属账户ID/POI ID查询。
            </p>
          </div>
          {unactivatedLoading ? <span className="source-pill">加载中</span> : null}
        </div>
        <form
          className="filter-bar filter-bar--compact admin-tools"
          onSubmit={handleUnactivatedSearch}
        >
          <label className="filter-field">
            <span>所属账户ID/POI ID</span>
            <input
              onChange={(event) => setUnactivatedQuery(event.target.value)}
              placeholder="输入门店账户ID或POI ID"
              value={unactivatedQuery}
            />
          </label>
          <Button disabled={unactivatedLoading} type="submit" variant="primary">
            查询
          </Button>
          <Button
            disabled={unactivatedLoading}
            onClick={resetUnactivatedSearch}
            type="button"
          >
            重置
          </Button>
        </form>
        <DataTable
          columns={unactivatedStoreColumns}
          emptyText={unactivatedLoading ? "正在加载未激活门店..." : "暂无未激活门店"}
          rows={unactivatedStores}
          state={unactivatedLoading ? "loading" : "ready"}
          tableClassName="account-table"
        />
      </section>
    </div>
  );
}
