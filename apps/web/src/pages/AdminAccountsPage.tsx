import { useEffect, useMemo, useState } from "react";
import {
  createAccount,
  fetchAccessControl,
  fetchAccountPermissionAuditLogs,
  fetchAccounts,
  fetchFilterMeta,
  fetchUnactivatedAccountStores,
  resetManagedAccountPassword,
  previewRolePagePermissions,
  restoreAccountPagePermissions,
  updateAccountPagePermissions,
  updateAccount,
  updateRolePagePermissions,
} from "../api/client";
import { Button } from "../components/Button";
import { StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { MultiSelectField, SelectField } from "../components/FormControls";
import type {
  AccountRow,
  AccessControlData,
  AccountPermissionAuditRow,
  AdminUser,
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
  store_scope_mode: "specified",
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
    store_scope_mode: account.store_scope_mode,
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
    store_scope_mode:
      draft.role === "highest_admin" ? "all" : draft.store_scope_mode,
    external_account_id: draft.external_account_id?.trim() || null,
    store_ids: draft.store_scope_mode === "specified" ? draft.store_ids : [],
    password: includePassword || password || passwordConfirm ? password : null,
    password_confirm:
      includePassword || password || passwordConfirm ? passwordConfirm : null,
  };
}

function roleLabel(role: UserRole): string {
  if (role === "highest_admin") {
    return "最高管理员";
  }
  if (role === "admin") {
    return "管理员";
  }
  return "门店账号";
}

function storesLabel(account: AccountRow): string {
  if (account.store_scope_mode === "all") {
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

const auditActionOptions = [
  { value: "", label: "全部操作类型" },
  { value: "account.created", label: "创建账号" },
  { value: "account.updated", label: "修改账号" },
  { value: "account.activated", label: "激活账号" },
  { value: "account.password_reset", label: "管理员重置密码" },
  { value: "account.password_changed", label: "个人修改密码" },
  { value: "account.password_reset_by_identity", label: "身份核验重置密码" },
  { value: "account.page_permissions.updated", label: "修改账号页面权限" },
  { value: "role.page_permissions.updated", label: "修改角色默认权限" },
];

function auditActionLabel(action: string): string {
  return auditActionOptions.find((option) => option.value === action)?.label ?? action;
}

interface AdminAccountsPageProps {
  currentUser: AdminUser;
}

export function AdminAccountsPage({ currentUser }: AdminAccountsPageProps) {
  const [activeTab, setActiveTab] = useState<"accounts" | "roles">("accounts");
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [accessControl, setAccessControl] = useState<AccessControlData | null>(null);
  const [auditRows, setAuditRows] = useState<AccountPermissionAuditRow[]>([]);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditFilters, setAuditFilters] = useState({
    targetUserId: "",
    actorUsername: "",
    action: "",
    createdFrom: "",
    createdTo: "",
  });
  const [roleDrafts, setRoleDrafts] = useState<Record<"admin" | "store", Set<string>>>(
    { admin: new Set(), store: new Set() },
  );
  const [extraAllow, setExtraAllow] = useState<Set<string>>(new Set());
  const [extraDeny, setExtraDeny] = useState<Set<string>>(new Set());
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

  const queryAuditRows = async (filters = auditFilters) => {
    setAuditLoading(true);
    try {
      const response = await fetchAccountPermissionAuditLogs({
        targetUserId: filters.targetUserId || undefined,
        actorUsername: filters.actorUsername.trim() || undefined,
        action: filters.action || undefined,
        createdFrom: filters.createdFrom
          ? `${filters.createdFrom}T00:00:00+08:00`
          : undefined,
        createdTo: filters.createdTo
          ? `${filters.createdTo}T23:59:59+08:00`
          : undefined,
      });
      setAuditRows(response.data.rows);
    } catch {
      setStatusText("变更记录读取失败，请稍后重试。");
    } finally {
      setAuditLoading(false);
    }
  };

  const handleAuditSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void queryAuditRows();
  };

  const resetAuditSearch = () => {
    const emptyFilters = {
      targetUserId: "",
      actorUsername: "",
      action: "",
      createdFrom: "",
      createdTo: "",
    };
    setAuditFilters(emptyFilters);
    void queryAuditRows(emptyFilters);
  };

  const loadData = () => {
    setLoading(true);
    setUnactivatedLoading(true);
    setStatusText("");
    Promise.all([
      fetchAccounts(),
      fetchFilterMeta(),
      fetchUnactivatedAccountStores(),
      fetchAccessControl(),
      fetchAccountPermissionAuditLogs(),
    ])
      .then(([accountResponse, filterResponse, unactivatedResponse, accessResponse, auditResponse]) => {
        setAccounts(accountResponse.data.rows);
        setStores(filterResponse.data.stores);
        setUnactivatedStores(unactivatedResponse.data.rows);
        setAccessControl(accessResponse.data);
        setAuditRows(auditResponse.data.rows);
        setRoleDrafts({
          admin: new Set(accessResponse.data.role_permissions.admin ?? []),
          store: new Set(accessResponse.data.role_permissions.store ?? []),
        });
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
    setExtraAllow(new Set());
    setExtraDeny(new Set());
  };

  const startEdit = (account: AccountRow) => {
    setEditingUserId(account.user_id);
    setDraft(accountDraft(account));
    setExtraAllow(new Set(account.extra_allow));
    setExtraDeny(new Set(account.extra_deny));
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
      title: "所属账户编号",
      align: "left",
      render: (store) => (
        <span className="mono-cell">{idListLabel(store.account_ids)}</span>
      ),
    },
    {
      key: "poi_ids",
      title: "门店位置编号（POI ID）",
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
      title: "所属账户编号",
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
      setStatusText("保存失败，请检查账号名、所属账户编号、密码确认和门店绑定。");
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

  const toggleAccountPermission = (
    pageKey: string,
    effect: "allow" | "deny",
  ) => {
    const update = effect === "allow" ? setExtraAllow : setExtraDeny;
    const clearOther = effect === "allow" ? setExtraDeny : setExtraAllow;
    update((current) => {
      const next = new Set(current);
      next.has(pageKey) ? next.delete(pageKey) : next.add(pageKey);
      return next;
    });
    clearOther((current) => {
      const next = new Set(current);
      next.delete(pageKey);
      return next;
    });
  };

  const saveAccountPermissions = async () => {
    if (!editingAccount) return;
    setSaving(true);
    setStatusText("");
    try {
      const result = await updateAccountPagePermissions(editingAccount.user_id, {
        extra_allow: Array.from(extraAllow),
        extra_deny: Array.from(extraDeny),
      });
      setAccounts((current) =>
        current.map((account) =>
          account.user_id === result.data.user_id ? result.data : account,
        ),
      );
      setStatusText("账号页面权限已保存并立即生效。");
      const auditResponse = await fetchAccountPermissionAuditLogs();
      setAuditRows(auditResponse.data.rows);
    } catch {
      setStatusText("页面权限保存失败，请检查权限项后重试。");
    } finally {
      setSaving(false);
    }
  };

  const restoreAccountPermissions = async () => {
    if (!editingAccount) return;
    setSaving(true);
    try {
      const result = await restoreAccountPagePermissions(editingAccount.user_id);
      setAccounts((current) =>
        current.map((account) =>
          account.user_id === result.data.user_id ? result.data : account,
        ),
      );
      setExtraAllow(new Set());
      setExtraDeny(new Set());
      setStatusText("已恢复角色默认权限。");
    } catch {
      setStatusText("恢复角色默认权限失败。");
    } finally {
      setSaving(false);
    }
  };

  const toggleRolePermission = (role: "admin" | "store", pageKey: string) => {
    setRoleDrafts((current) => {
      const next = new Set(current[role]);
      next.has(pageKey) ? next.delete(pageKey) : next.add(pageKey);
      return { ...current, [role]: next };
    });
  };

  const saveRolePermissions = async (role: "admin" | "store") => {
    const pageKeys = Array.from(roleDrafts[role]);
    setSaving(true);
    try {
      const preview = await previewRolePagePermissions(role, pageKeys);
      const accepted = window.confirm(
        `本次修改将影响 ${preview.data.inheriting_user_count} 个继承账号；` +
          `${preview.data.customized_user_count} 个自定义账号将保持当前有效权限。确认保存吗？`,
      );
      if (!accepted) return;
      await updateRolePagePermissions(role, pageKeys);
      const [accessResponse, accountResponse, auditResponse] = await Promise.all([
        fetchAccessControl(),
        fetchAccounts(),
        fetchAccountPermissionAuditLogs(),
      ]);
      setAccessControl(accessResponse.data);
      setAccounts(accountResponse.data.rows);
      setAuditRows(auditResponse.data.rows);
      setStatusText("角色默认权限已保存并立即生效。");
    } catch {
      setStatusText("角色默认权限保存失败。");
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
          <Button
            onClick={() => {
              setAuditOpen((current) => !current);
            }}
            type="button"
          >
            变更记录
          </Button>
          <Button onClick={startCreate} type="button" variant="primary">
            新建账号
          </Button>
        </div>
      </section>

      <div className="segmented-control" role="tablist" aria-label="账号权限管理视图">
        <button
          aria-selected={activeTab === "accounts"}
          onClick={() => setActiveTab("accounts")}
          role="tab"
          type="button"
        >
          账号列表
        </button>
        <button
          aria-selected={activeTab === "roles"}
          onClick={() => setActiveTab("roles")}
          role="tab"
          type="button"
        >
          角色权限
        </button>
      </div>

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

      {auditOpen ? (
        <section className="content-section account-audit-panel">
          <div className="section-title">
            <div>
              <h2>账号与权限变更记录</h2>
              <p>记录账号和权限变更及执行结果，不记录密码内容。</p>
            </div>
            {auditLoading ? <span className="source-pill">加载中</span> : null}
          </div>
          <form className="filter-bar filter-bar--compact audit-filter-bar" onSubmit={handleAuditSearch}>
            <SelectField
              label="账号"
              onChange={(value) =>
                setAuditFilters((current) => ({ ...current, targetUserId: value }))
              }
              options={[
                { value: "", label: "全部账号" },
                ...accounts.map((account) => ({
                  value: account.user_id,
                  label: account.display_name || account.username,
                })),
              ]}
              value={auditFilters.targetUserId}
            />
            <label className="filter-field">
              <span>操作者</span>
              <input
                onChange={(event) =>
                  setAuditFilters((current) => ({
                    ...current,
                    actorUsername: event.target.value,
                  }))
                }
                placeholder="输入账号名"
                value={auditFilters.actorUsername}
              />
            </label>
            <SelectField
              label="操作类型"
              onChange={(value) =>
                setAuditFilters((current) => ({ ...current, action: value }))
              }
              options={auditActionOptions}
              value={auditFilters.action}
            />
            <label className="filter-field">
              <span>开始日期</span>
              <input
                onChange={(event) =>
                  setAuditFilters((current) => ({ ...current, createdFrom: event.target.value }))
                }
                type="date"
                value={auditFilters.createdFrom}
              />
            </label>
            <label className="filter-field">
              <span>结束日期</span>
              <input
                onChange={(event) =>
                  setAuditFilters((current) => ({ ...current, createdTo: event.target.value }))
                }
                type="date"
                value={auditFilters.createdTo}
              />
            </label>
            <Button disabled={auditLoading} type="submit" variant="primary">查询</Button>
            <Button disabled={auditLoading} onClick={resetAuditSearch} type="button">重置</Button>
          </form>
          <div className="audit-list">
            <div className="audit-list__row audit-list__header">
              <strong>时间</strong>
              <strong>操作者</strong>
              <strong>操作类型</strong>
              <strong>对象</strong>
              <strong>结果</strong>
            </div>
            {auditRows.slice(0, 500).map((row) => (
              <div className="audit-list__row" key={row.audit_id}>
                <span>{formatDateTime(row.created_at)}</span>
                <strong>{row.actor_username}</strong>
                <span>{auditActionLabel(row.action)}</span>
                <span>{row.target_username ?? "角色默认权限"}</span>
                <StatusChip tone={row.result === "success" ? "success" : "danger"}>
                  {row.result === "success" ? "成功" : "失败"}
                </StatusChip>
              </div>
            ))}
            {!auditRows.length && !auditLoading ? <p className="audit-list__empty">暂无符合条件的记录</p> : null}
          </div>
        </section>
      ) : null}

      <section className="content-section account-admin-layout" hidden={activeTab !== "accounts"}>
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
              <span>所属账户编号</span>
              <input
                onChange={(event) =>
                  setDraftField("external_account_id", event.target.value)
                }
                value={draft.external_account_id ?? ""}
              />
            </label>
            <SelectField
              label="角色"
              onChange={(value) => {
                const role = value as UserRole;
                setDraftField("role", role);
                setDraftField(
                  "store_scope_mode",
                  role === "highest_admin" || role === "admin" ? "all" : "specified",
                );
              }}
              options={
                currentUser.is_highest_admin
                  ? [
                      { value: "store", label: "门店账号" },
                      { value: "admin", label: "管理员" },
                      { value: "highest_admin", label: "最高管理员" },
                    ]
                  : [{ value: "store", label: "门店账号" }]
              }
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
            <SelectField
              label="门店范围模式"
              onChange={(value) =>
                setDraftField(
                  "store_scope_mode",
                  value as AccountUpsertPayload["store_scope_mode"],
                )
              }
              options={
                draft.role === "highest_admin"
                  ? [{ value: "all", label: "全部门店" }]
                  : draft.role === "admin"
                    ? [
                        { value: "all", label: "全部门店" },
                        { value: "specified", label: "指定门店" },
                      ]
                    : [{ value: "specified", label: "指定门店" }]
              }
              value={draft.store_scope_mode}
            />
            <MultiSelectField
              disabled={draft.store_scope_mode !== "specified"}
              emptyLabel={draft.store_scope_mode === "specified" ? "未绑定门店" : "全部门店"}
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
              value={draft.store_scope_mode === "specified" ? draft.store_ids : []}
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

          {editingAccount && editingAccount.role !== "highest_admin" && accessControl ? (
            <section className="content-section account-form permission-editor">
              <div className="section-title">
                <div>
                  <h2>账号页面权限</h2>
                  <p>有效权限 = 角色默认 + 额外允许 - 额外禁止</p>
                </div>
              </div>
              <div className="permission-list">
                {accessControl.pages.map((page) => (
                  <div className="permission-list__row" key={page.page_key}>
                    <span><strong>{page.page_key}</strong> {page.page_name}</span>
                    <label>
                      <input
                        checked={extraAllow.has(page.page_key)}
                        onChange={() => toggleAccountPermission(page.page_key, "allow")}
                        type="checkbox"
                      />
                      额外允许
                    </label>
                    <label>
                      <input
                        checked={extraDeny.has(page.page_key)}
                        onChange={() => toggleAccountPermission(page.page_key, "deny")}
                        type="checkbox"
                      />
                      额外禁止
                    </label>
                  </div>
                ))}
              </div>
              <div className="table-action-row">
                <Button disabled={saving} onClick={saveAccountPermissions} type="button" variant="primary">
                  保存页面权限
                </Button>
                <Button disabled={saving} onClick={restoreAccountPermissions} type="button">
                  恢复角色默认
                </Button>
              </div>
            </section>
          ) : null}

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

      <section className="content-section" hidden={activeTab !== "roles"}>
        <div className="section-title">
          <div>
            <h2>角色默认页面权限</h2>
            <p>最高管理员固定拥有全部页面；已自定义账号在角色默认值变化后保持当前有效权限。</p>
          </div>
        </div>
        {accessControl ? (
          <div className="role-permission-table" role="table" aria-label="角色页面权限矩阵">
            <div className="role-permission-table__header" role="row">
              <strong>页面</strong>
              <strong>最高管理员</strong>
              <strong>管理员</strong>
              <strong>门店账号</strong>
            </div>
            {accessControl.pages.map((page) => (
              <div className="role-permission-table__row" key={page.page_key} role="row">
                <span><strong>{page.page_key}</strong> {page.page_name}</span>
                <input aria-label={`${page.page_name} 最高管理员`} checked disabled readOnly type="checkbox" />
                <input
                  aria-label={`${page.page_name} 管理员`}
                  checked={roleDrafts.admin.has(page.page_key)}
                  disabled={!currentUser.is_highest_admin}
                  onChange={() => toggleRolePermission("admin", page.page_key)}
                  type="checkbox"
                />
                <input
                  aria-label={`${page.page_name} 门店账号`}
                  checked={roleDrafts.store.has(page.page_key)}
                  onChange={() => toggleRolePermission("store", page.page_key)}
                  type="checkbox"
                />
              </div>
            ))}
            <div className="table-action-row role-permission-table__actions">
              {currentUser.is_highest_admin ? (
                <Button disabled={saving} onClick={() => saveRolePermissions("admin")} type="button">
                  保存管理员默认权限
                </Button>
              ) : null}
              <Button disabled={saving} onClick={() => saveRolePermissions("store")} type="button" variant="primary">
                保存门店账号默认权限
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="content-section" hidden={activeTab !== "accounts"}>
        <div className="section-title">
          <div>
            <h2>未激活门店</h2>
            <p>
              共 {unactivatedStores.length} 个已准备但尚未激活账号的门店，可按所属账户编号或门店位置编号查询。
            </p>
          </div>
          {unactivatedLoading ? <span className="source-pill">加载中</span> : null}
        </div>
        <form
          className="filter-bar filter-bar--compact admin-tools"
          onSubmit={handleUnactivatedSearch}
        >
          <label className="filter-field">
            <span>所属账户编号或门店位置编号（POI ID）</span>
            <input
              onChange={(event) => setUnactivatedQuery(event.target.value)}
              placeholder="输入门店账户编号或位置编号"
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
