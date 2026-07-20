import { useMemo, useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { StatusChip } from "../components/Chips";
import { DataTable } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { SelectField } from "../components/FormControls";

type RoleKey = "highest" | "admin" | "store";
type PreviewTab = "accounts" | "roles";
type PermissionState = Record<RoleKey, Set<string>>;

interface PageDefinition {
  id: string;
  name: string;
  group: string;
}

interface PreviewAccount {
  id: string;
  name: string;
  username: string;
  externalId: string;
  role: RoleKey;
  scope: string;
  status: "启用" | "停用";
  activation: "已激活";
  updatedAt: string;
  permissionMode: "默认" | "已自定义";
}

interface PreviewAccountDraft {
  username: string;
  name: string;
  externalId: string;
  role: RoleKey;
  status: "启用" | "停用";
  storeNames: string[];
  password: string;
  passwordConfirm: string;
}

interface PreviewUnactivatedStore {
  id: string;
  name: string;
  subject: string;
  accountId: string;
  poiId: string;
  poiName: string;
}

interface PreviewAuditRow {
  action: string;
  actor: string;
  result: string;
  target: string;
  time: string;
}

const pages: PageDefinition[] = [
  { id: "A01", name: "线索看板", group: "线索中心" },
  { id: "A02", name: "线索明细", group: "线索中心" },
  { id: "B01", name: "全国门店榜单", group: "订单分佣" },
  { id: "B02", name: "单店结算", group: "订单分佣" },
  { id: "B03", name: "订单费用明细", group: "订单分佣" },
  { id: "C01", name: "核销表现", group: "核销表现" },
  { id: "D01", name: "后台首页", group: "管理后台" },
  { id: "D02", name: "账号管理", group: "管理后台" },
  { id: "D03", name: "分佣规则", group: "管理后台" },
  { id: "D04", name: "商品口径", group: "管理后台" },
  { id: "D05", name: "线索分配规则", group: "管理后台" },
  { id: "D06", name: "分配试运行", group: "管理后台" },
  { id: "D07", name: "分配记录", group: "管理后台" },
  { id: "D08", name: "总部线索池", group: "管理后台" },
  { id: "D09", name: "用户建议", group: "管理后台" },
  { id: "D10", name: "数据同步", group: "管理后台" },
];

const roles: Array<{ key: RoleKey; name: string; note: string }> = [
  { key: "highest", name: "最高管理员", note: "固定全部页面，不可修改" },
  { key: "admin", name: "管理员", note: "默认权限，可按账号例外调整" },
  { key: "store", name: "门店账号", note: "默认权限，可按账号例外调整" },
];

const accounts: PreviewAccount[] = [
  {
    id: "highest-current",
    name: "系统最高管理员",
    username: "system-admin",
    externalId: "-",
    role: "highest",
    scope: "全部门店",
    status: "启用",
    activation: "已激活",
    updatedAt: "2026-07-20 12:29",
    permissionMode: "默认",
  },
  {
    id: "highest-other",
    name: "业务最高管理员",
    username: "business-owner",
    externalId: "DY-HEADQUARTERS",
    role: "highest",
    scope: "全部门店",
    status: "启用",
    activation: "已激活",
    updatedAt: "2026-07-19 18:06",
    permissionMode: "默认",
  },
  {
    id: "admin-ops",
    name: "华东运营管理员",
    username: "east-ops",
    externalId: "DY-EAST-OPS",
    role: "admin",
    scope: "指定门店 · 12 家",
    status: "启用",
    activation: "已激活",
    updatedAt: "2026-07-19 10:18",
    permissionMode: "已自定义",
  },
  {
    id: "store-account",
    name: "上海徐汇门店",
    username: "store-310104",
    externalId: "DY-SH-310104",
    role: "store",
    scope: "指定门店 · 1 家",
    status: "启用",
    activation: "已激活",
    updatedAt: "2026-07-18 16:42",
    permissionMode: "默认",
  },
];

const unactivatedStores: PreviewUnactivatedStore[] = [
  {
    id: "unactivated-1",
    name: "上海浦东体验店",
    subject: "上海精诚汽车服务有限公司",
    accountId: "DY-SH-PD-001",
    poiId: "POI-310115-01",
    poiName: "精诚养车上海浦东体验店",
  },
  {
    id: "unactivated-2",
    name: "苏州工业园区店",
    subject: "苏州精诚汽车服务有限公司",
    accountId: "DY-SZ-IPS-003",
    poiId: "POI-320571-03",
    poiName: "精诚养车苏州工业园区店",
  },
];

const auditRows: PreviewAuditRow[] = [
  { time: "2026-07-20 14:32", actor: "system-admin", target: "管理员默认权限", action: "新增允许 D06；自定义账号保持不变", result: "成功" },
  { time: "2026-07-19 10:18", actor: "business-owner", target: "store-310104", action: "门店范围由 2 家调整为 1 家", result: "成功" },
  { time: "2026-07-18 09:06", actor: "system-admin", target: "business-owner", action: "重置密码（不记录密码内容）", result: "成功" },
];

const emptyAccountDraft: PreviewAccountDraft = {
  username: "",
  name: "",
  externalId: "",
  role: "store",
  status: "启用",
  storeNames: [],
  password: "",
  passwordConfirm: "",
};

const initialPermissions: PermissionState = {
  highest: new Set(pages.map((page) => page.id)),
  admin: new Set(pages.map((page) => page.id)),
  store: new Set(["B01", "B02", "B03", "C01"]),
};

const roleNames: Record<RoleKey, string> = {
  highest: "最高管理员",
  admin: "管理员",
  store: "门店账号",
};

function clonePermissions(source: PermissionState): PermissionState {
  return {
    highest: new Set(source.highest),
    admin: new Set(source.admin),
    store: new Set(source.store),
  };
}

function pageName(pageId: string): string {
  return pages.find((page) => page.id === pageId)?.name ?? pageId;
}

function accountDraft(account?: PreviewAccount): PreviewAccountDraft {
  if (!account) return { ...emptyAccountDraft, storeNames: [] };
  return {
    username: account.username,
    name: account.name,
    externalId: account.externalId === "-" ? "" : account.externalId,
    role: account.role,
    status: account.status,
    storeNames:
      account.role === "store"
        ? ["上海徐汇店"]
        : account.role === "admin" && account.scope.startsWith("指定门店")
          ? ["上海徐汇店", "上海静安店"]
          : [],
    password: "",
    passwordConfirm: "",
  };
}

export function AdminAccountsDydata32PreviewPage() {
  const [activeTab, setActiveTab] = useState<PreviewTab>("accounts");
  const [accountListView, setAccountListView] = useState<"activated" | "unactivated">("activated");
  const [permissions, setPermissions] = useState<PermissionState>(() =>
    clonePermissions(initialPermissions),
  );
  const [selectedAccountId, setSelectedAccountId] = useState("admin-ops");
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showRestoreDialog, setShowRestoreDialog] = useState(false);
  const [showAudit, setShowAudit] = useState(false);
  const [passwordResetTarget, setPasswordResetTarget] = useState<PreviewAccount | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState<PreviewAccountDraft>(() => accountDraft());
  const [unactivatedQuery, setUnactivatedQuery] = useState("");
  const [resetCustomized, setResetCustomized] = useState(false);
  const [scopeMode, setScopeMode] = useState<"all" | "specified">("specified");
  const [selectedStores, setSelectedStores] = useState(["上海徐汇店", "上海静安店"]);
  const [extraAllow, setExtraAllow] = useState(new Set(["D06"]));
  const [extraDeny, setExtraDeny] = useState(new Set(["D10"]));
  const [notice, setNotice] = useState("");
  const [accountConfigHint, setAccountConfigHint] = useState("当前展示华东运营管理员的页面权限与门店范围。");

  const selectedAccount =
    accounts.find((account) => account.id === selectedAccountId) ?? accounts[2];

  const filteredUnactivatedStores = useMemo(() => {
    const query = unactivatedQuery.trim().toLowerCase();
    if (!query) return unactivatedStores;
    return unactivatedStores.filter((store) =>
      [store.name, store.accountId, store.poiId, store.poiName]
        .some((value) => value.toLowerCase().includes(query)),
    );
  }, [unactivatedQuery]);

  const accountDefault = permissions[selectedAccount.role];
  const effectivePermissions = useMemo(() => {
    const result = new Set(accountDefault);
    extraAllow.forEach((pageId) => result.add(pageId));
    extraDeny.forEach((pageId) => result.delete(pageId));
    return result;
  }, [accountDefault, extraAllow, extraDeny]);

  const toggleRolePermission = (role: RoleKey, pageId: string) => {
    if (role === "highest") return;
    setPermissions((current) => {
      const next = clonePermissions(current);
      if (next[role].has(pageId)) next[role].delete(pageId);
      else next[role].add(pageId);
      return next;
    });
  };

  const toggleDelta = (kind: "allow" | "deny", pageId: string) => {
    const update = kind === "allow" ? setExtraAllow : setExtraDeny;
    const clearOther = kind === "allow" ? setExtraDeny : setExtraAllow;
    update((current) => {
      const next = new Set(current);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      return next;
    });
    clearOther((current) => {
      const next = new Set(current);
      next.delete(pageId);
      return next;
    });
  };

  const selectAccount = (account: PreviewAccount) => {
    setSelectedAccountId(account.id);
    setNotice("");
    setAccountConfigHint(`已从账号列表打开“${account.name}”的账号配置。`);
    if (account.role === "highest") {
      setScopeMode("all");
      setExtraAllow(new Set());
      setExtraDeny(new Set());
    } else if (account.role === "store") {
      setScopeMode("specified");
      setSelectedStores(["上海徐汇店"]);
      setExtraAllow(new Set());
      setExtraDeny(new Set());
    } else {
      setScopeMode("specified");
      setSelectedStores(["上海徐汇店", "上海静安店"]);
      setExtraAllow(new Set(["D06"]));
      setExtraDeny(new Set(["D10"]));
    }
    window.requestAnimationFrame(() => {
      const target = document.getElementById("dydata32-account-config");
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
      target?.focus({ preventScroll: true });
    });
  };

  const startCreateAccount = () => {
    setEditingAccountId(null);
    setAccountForm(accountDraft());
    setNotice("");
  };

  const startEditAccount = (account: PreviewAccount) => {
    setEditingAccountId(account.id);
    setAccountForm(accountDraft(account));
    selectAccount(account);
  };

  const setAccountFormField = <K extends keyof PreviewAccountDraft>(
    key: K,
    value: PreviewAccountDraft[K],
  ) => {
    setAccountForm((current) => ({ ...current, [key]: value }));
  };

  const saveAccountPreview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!accountForm.username.trim() || !accountForm.name.trim()) {
      setNotice("请先填写账号名和显示名称。真实数据未发生变化。");
      return;
    }
    if (accountForm.role === "store" && accountForm.storeNames.length === 0) {
      setNotice("新建门店账号必须至少选择 1 家门店；当前预览未保存。");
      return;
    }
    setNotice(
      `${editingAccountId ? "账号修改" : "新建账号"}已在预览中保存；真实数据未发生变化。`,
    );
  };

  const restoreDefault = () => {
    setExtraAllow(new Set());
    setExtraDeny(new Set());
    setShowRestoreDialog(false);
    setNotice("已在预览中恢复角色默认权限；真实数据未发生变化。 ");
  };

  return (
    <div className="page-stack dydata32-preview">
      <section className="dydata32-preview-banner" aria-label="预览说明">
        <div>
          <strong>DYDATA-32 账号与角色权限交互预览</strong>
          <p>本页使用演示数据，所有操作只在当前浏览器内生效，不会写入真实账号。</p>
        </div>
        <StatusChip tone="warning">第 1 轮回环</StatusChip>
      </section>

      <section className="admin-header">
        <div>
          <p className="eyebrow">管理后台 / 账号管理</p>
          <h1>账号与权限</h1>
          <p className="admin-muted">
            页面权限由角色默认值与单账号例外共同决定；门店数据范围按账号单独配置。
          </p>
        </div>
        <div className="admin-header-actions">
          <Button onClick={() => setShowAudit(true)} variant="secondary">
            查看变更记录
          </Button>
          <Button onClick={startCreateAccount} variant="primary">
            新建账号
          </Button>
        </div>
      </section>

      <nav className="dydata32-tabs" aria-label="账号与权限页签">
        <button
          aria-selected={activeTab === "accounts"}
          className={activeTab === "accounts" ? "is-active" : ""}
          onClick={() => setActiveTab("accounts")}
          role="tab"
          type="button"
        >
          账号列表
        </button>
        <button
          aria-selected={activeTab === "roles"}
          className={activeTab === "roles" ? "is-active" : ""}
          onClick={() => setActiveTab("roles")}
          role="tab"
          type="button"
        >
          角色权限
        </button>
      </nav>

      {notice ? <div className="dydata32-inline-notice">{notice}</div> : null}

      {activeTab === "accounts" ? (
        <>
          <div className="dydata32-account-workspace">
            <section className="content-section">
              <div className="dydata32-account-list-tabs" role="tablist" aria-label="账号激活状态">
                <button
                  aria-selected={accountListView === "activated"}
                  className={accountListView === "activated" ? "is-active" : ""}
                  onClick={() => setAccountListView("activated")}
                  role="tab"
                  type="button"
                >
                  已激活账号 <span>{accounts.length}</span>
                </button>
                <button
                  aria-selected={accountListView === "unactivated"}
                  className={accountListView === "unactivated" ? "is-active" : ""}
                  onClick={() => setAccountListView("unactivated")}
                  role="tab"
                  type="button"
                >
                  未激活门店 <span>{unactivatedStores.length}</span>
                </button>
              </div>

              {accountListView === "activated" ? (
                <>
              <div className="section-title">
                <div>
                  <p className="eyebrow">已激活账号</p>
                  <h2>账号列表</h2>
                  <p>共 {accounts.length} 个已激活账号；保留现有账号字段和操作。</p>
                </div>
                <div className="dydata32-filter-row">
                  <SelectField
                    label="角色"
                    onChange={() => undefined}
                    options={[
                      { label: "全部角色", value: "all" },
                      { label: "最高管理员", value: "highest" },
                      { label: "管理员", value: "admin" },
                      { label: "门店账号", value: "store" },
                    ]}
                    value="all"
                  />
                  <SelectField
                    label="状态"
                    onChange={() => undefined}
                    options={[
                      { label: "启用", value: "active" },
                      { label: "停用", value: "disabled" },
                    ]}
                    value="active"
                  />
                </div>
              </div>

              <DataTable
                columns={[
                  {
                    key: "account",
                    minWidth: 170,
                    render: (account: PreviewAccount) => (
                      <>
                        <strong>{account.name}</strong>
                        <small className="dydata32-cell-note">{account.username}</small>
                      </>
                    ),
                    title: "账号名",
                  },
                  { key: "externalId", minWidth: 150, render: (account: PreviewAccount) => <span className="mono-cell">{account.externalId}</span>, title: "所属账户编号" },
                  { key: "role", render: (account: PreviewAccount) => roleNames[account.role], title: "角色" },
                  { key: "status", render: (account: PreviewAccount) => <StatusChip tone="success">{account.status}</StatusChip>, title: "状态" },
                  { key: "scope", minWidth: 130, render: (account: PreviewAccount) => account.scope, title: "门店范围" },
                  { key: "activation", render: (account: PreviewAccount) => account.activation, title: "激活状态" },
                  {
                    key: "permissionMode",
                    render: (account: PreviewAccount) => (
                      <StatusChip tone={account.permissionMode === "默认" ? "neutral" : "info"}>
                        {account.permissionMode}
                      </StatusChip>
                    ),
                    title: "页面权限",
                  },
                  { key: "updatedAt", minWidth: 150, render: (account: PreviewAccount) => account.updatedAt, title: "更新时间" },
                  {
                    key: "actions",
                    minWidth: 280,
                    render: (account: PreviewAccount) => (
                      <div className="table-action-row">
                        <Button onClick={() => startEditAccount(account)} size="sm" variant="secondary">编辑</Button>
                        <Button onClick={() => selectAccount(account)} size="sm" variant="secondary">页面权限</Button>
                        <Button onClick={() => setPasswordResetTarget(account)} size="sm" variant="text">重置密码</Button>
                        {account.role === "highest" ? (
                          <Button
                            disabled={account.id === "highest-current"}
                            onClick={() => setNotice(`已进入 ${account.name} 的失效确认；无需第二人审批。`)}
                            size="sm"
                            title={account.id === "highest-current" ? "不能使当前登录账号失效" : undefined}
                            variant="danger"
                          >
                            设为失效
                          </Button>
                        ) : null}
                      </div>
                    ),
                    title: "操作",
                  },
                ]}
                mobileCard={false}
                rows={accounts}
                tableClassName="dydata32-account-table"
              />
              <p className="dydata32-footnote">
                最高管理员权限固定一致；可由任一最高管理员创建、重置密码或使其他最高管理员失效，不能使自己失效，也不提供直接降级。
              </p>
                </>
              ) : (
                <>
                  <div className="section-title">
                    <div>
                      <p className="eyebrow">未激活门店</p>
                      <h2>待激活门店列表</h2>
                      <p>
                        共 {filteredUnactivatedStores.length} 个尚未初始化门店账号的门店，可按所属账户编号或门店位置编号查询。
                      </p>
                    </div>
                  </div>

                  <div className="dydata32-unactivated-search">
                    <label>
                      所属账户编号或门店位置编号（POI ID）
                      <input
                        onChange={(event) => setUnactivatedQuery(event.target.value)}
                        placeholder="输入门店账户编号或位置编号"
                        value={unactivatedQuery}
                      />
                    </label>
                    <Button onClick={() => setNotice(`已按“${unactivatedQuery || "全部"}”查询未激活门店。`)} variant="secondary">
                      查询
                    </Button>
                    <Button onClick={() => setUnactivatedQuery("")} variant="text">重置</Button>
                  </div>

                  <DataTable
                    columns={[
                      { key: "name", render: (store: PreviewUnactivatedStore) => <strong>{store.name}</strong>, title: "门店" },
                      { key: "subject", render: (store: PreviewUnactivatedStore) => store.subject, title: "认证主体" },
                      { key: "accountId", render: (store: PreviewUnactivatedStore) => <span className="mono-cell">{store.accountId}</span>, title: "所属账户编号" },
                      { key: "poiId", render: (store: PreviewUnactivatedStore) => <span className="mono-cell">{store.poiId}</span>, title: "门店位置编号（POI ID）" },
                      { key: "poiName", render: (store: PreviewUnactivatedStore) => store.poiName, title: "POI 名称" },
                    ]}
                    emptyText="暂无匹配的未激活门店"
                    mobileCard={false}
                    rows={filteredUnactivatedStores}
                    tableClassName="dydata32-unactivated-table"
                  />

                  <div className="dydata32-activation-explainer">
                    <div>
                      <strong>自助激活与后台手工新建是两条独立路径</strong>
                      <p>未激活门店不代表系统已经预建了空范围账号。</p>
                    </div>
                    <div className="dydata32-activation-flow">
                      <strong>抖音来客账号 ID + POI ID 校验</strong>
                      <span>校验通过</span>
                      <strong>自动创建或绑定门店账号</strong>
                      <span>自动限定</span>
                      <strong>唯一对应门店</strong>
                    </div>
                    <p className="dydata32-help">
                      自助激活不受“后台新建门店账号必须手工选择门店”的表单校验影响；系统会从双 ID 校验结果自动确定唯一门店，不允许产生空范围账号。
                    </p>
                  </div>
                </>
              )}
            </section>

            <aside className="content-section dydata32-account-editor">
              <div className="section-title">
                <div>
                  <p className="eyebrow">{editingAccountId ? "编辑账号" : "新建账号"}</p>
                  <h2>{editingAccountId ? accountForm.name || "编辑账号" : "新建账号"}</h2>
                  <p>{editingAccountId ? "修改基础信息、角色和门店范围" : "创建后立即可登录"}</p>
                </div>
                {editingAccountId ? (
                  <Button onClick={startCreateAccount} size="sm" variant="text">取消编辑</Button>
                ) : null}
              </div>
              <form className="dydata32-account-form" onSubmit={saveAccountPreview}>
                <label>
                  账号名
                  <input
                    onChange={(event) => setAccountFormField("username", event.target.value)}
                    placeholder="请输入登录账号"
                    value={accountForm.username}
                  />
                </label>
                <label>
                  显示名称
                  <input
                    onChange={(event) => setAccountFormField("name", event.target.value)}
                    placeholder="请输入使用者或门店名称"
                    value={accountForm.name}
                  />
                </label>
                <label>
                  所属账户编号
                  <input
                    onChange={(event) => setAccountFormField("externalId", event.target.value)}
                    placeholder="选填"
                    value={accountForm.externalId}
                  />
                </label>
                <SelectField
                  label="角色"
                  onChange={(value) => {
                    const role = value as RoleKey;
                    setAccountForm((current) => ({
                      ...current,
                      role,
                      storeNames: role === "store" ? current.storeNames : [],
                    }));
                  }}
                  options={[
                    { label: "最高管理员", value: "highest" },
                    { label: "管理员", value: "admin" },
                    { label: "门店账号", value: "store" },
                  ]}
                  value={accountForm.role}
                />
                <SelectField
                  label="状态"
                  onChange={(value) => setAccountFormField("status", value as "启用" | "停用")}
                  options={[
                    { label: "启用", value: "启用" },
                    { label: "停用", value: "停用" },
                  ]}
                  value={accountForm.status}
                />

                <fieldset className="dydata32-form-fieldset">
                  <legend>门店权限</legend>
                  {accountForm.role === "highest" ? (
                    <p>最高管理员固定查看全部门店。</p>
                  ) : (
                    <>
                      {accountForm.role === "admin" ? (
                        <label className="dydata32-inline-choice">
                          <input
                            checked={accountForm.storeNames.length === 0}
                            onChange={() => setAccountFormField("storeNames", [])}
                            type="radio"
                          />
                          全部门店
                        </label>
                      ) : null}
                      <label className="dydata32-inline-choice">
                        <input
                          checked={accountForm.role === "store" || accountForm.storeNames.length > 0}
                          onChange={() => setAccountFormField("storeNames", ["上海徐汇店"])}
                          type="radio"
                        />
                        指定门店
                      </label>
                      {accountForm.role === "store" || accountForm.storeNames.length > 0 ? (
                        <div className="dydata32-store-picker">
                          {accountForm.storeNames.map((store) => <span key={store}>{store}</span>)}
                          <Button
                            onClick={() => setAccountFormField("storeNames", [...accountForm.storeNames, `演示门店 ${accountForm.storeNames.length + 1}`])}
                            size="sm"
                            variant="text"
                          >
                            选择门店
                          </Button>
                        </div>
                      ) : null}
                    </>
                  )}
                  <p>门店账号至少选择 1 家门店；空值不代表全部门店。</p>
                </fieldset>

                <label>
                  {editingAccountId ? "新密码（选填）" : "密码"}
                  <input
                    onChange={(event) => setAccountFormField("password", event.target.value)}
                    placeholder={editingAccountId ? "留空表示不修改" : "请输入初始密码"}
                    type="password"
                    value={accountForm.password}
                  />
                </label>
                <label>
                  确认密码
                  <input
                    onChange={(event) => setAccountFormField("passwordConfirm", event.target.value)}
                    placeholder="再次输入密码"
                    type="password"
                    value={accountForm.passwordConfirm}
                  />
                </label>
                <Button type="submit" variant="primary">
                  {editingAccountId ? "保存修改" : "保存账号"}
                </Button>
              </form>
            </aside>
          </div>

          <section
            className="content-section dydata32-account-detail"
            id="dydata32-account-config"
            tabIndex={-1}
          >
            <div className="section-title">
              <div>
                <p className="eyebrow">账号配置</p>
                <h2>{selectedAccount.name}</h2>
                <p>{roleNames[selectedAccount.role]} · {selectedAccount.username}</p>
              </div>
              <StatusChip tone={extraAllow.size || extraDeny.size ? "info" : "neutral"}>
                {extraAllow.size || extraDeny.size ? "已自定义" : "继承角色默认"}
              </StatusChip>
            </div>

            <div className="dydata32-config-guidance" role="status">
              <strong>已定位到账号配置</strong>
              <span>{accountConfigHint}</span>
            </div>

            <div className="dydata32-detail-grid">
              <div className="dydata32-config-block">
                <div className="dydata32-block-heading">
                  <div>
                    <h3>门店数据范围</h3>
                    <p>数据范围与页面权限分别计算。</p>
                  </div>
                </div>
                <div className="dydata32-scope-options">
                  <label>
                    <input
                      checked={scopeMode === "all"}
                      disabled={selectedAccount.role === "store"}
                      name="scope-mode"
                      onChange={() => setScopeMode("all")}
                      type="radio"
                    />
                    全部门店
                  </label>
                  <label>
                    <input
                      checked={scopeMode === "specified"}
                      disabled={selectedAccount.role === "highest"}
                      name="scope-mode"
                      onChange={() => setScopeMode("specified")}
                      type="radio"
                    />
                    指定门店
                  </label>
                </div>
                {scopeMode === "specified" ? (
                  <div className="dydata32-store-picker">
                    {selectedStores.map((store) => (
                      <span key={store}>{store}</span>
                    ))}
                    <Button
                      onClick={() => setSelectedStores((current) => [...current, `演示门店 ${current.length + 1}`])}
                      size="sm"
                      variant="text"
                    >
                      添加门店
                    </Button>
                  </div>
                ) : (
                  <p className="dydata32-scope-summary">可查看系统内全部门店数据</p>
                )}
                <p className="dydata32-help">
                  空门店范围表示无数据权限，不代表全部门店；新建门店账号必须至少选择 1 家门店。
                </p>
              </div>

              <div className="dydata32-config-block">
                <div className="dydata32-block-heading">
                  <div>
                    <h3>页面权限例外</h3>
                    <p>有效权限 = 角色默认 + 额外允许 − 额外禁止。</p>
                  </div>
                  {selectedAccount.role !== "highest" ? (
                    <Button onClick={() => setShowRestoreDialog(true)} size="sm" variant="text">
                      恢复角色默认
                    </Button>
                  ) : null}
                </div>
                <div className="dydata32-effective-summary">
                  <span>角色默认 <strong>{accountDefault.size}</strong></span>
                  <span>额外允许 <strong>{extraAllow.size}</strong></span>
                  <span>额外禁止 <strong>{extraDeny.size}</strong></span>
                  <span>最终可见 <strong>{effectivePermissions.size}</strong></span>
                </div>
                <div className="dydata32-delta-list">
                  {pages.map((page) => (
                    <div key={page.id}>
                      <span><small>{page.id}</small>{page.name}</span>
                      <label>
                        <input
                          checked={extraAllow.has(page.id)}
                          disabled={selectedAccount.role === "highest"}
                          onChange={() => toggleDelta("allow", page.id)}
                          type="checkbox"
                        />
                        额外允许
                      </label>
                      <label>
                        <input
                          checked={extraDeny.has(page.id)}
                          disabled={selectedAccount.role === "highest"}
                          onChange={() => toggleDelta("deny", page.id)}
                          type="checkbox"
                        />
                        额外禁止
                      </label>
                      <StatusChip tone={effectivePermissions.has(page.id) ? "success" : "neutral"}>
                        {effectivePermissions.has(page.id) ? "可见" : "不可见"}
                      </StatusChip>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="dydata32-save-row">
              <span>新增、编辑、删除、导出、审核等操作权限本期不进入配置矩阵。</span>
              <Button onClick={() => setNotice("账号权限与门店范围已在预览中保存；真实数据未发生变化。") } variant="primary">
                保存账号配置
              </Button>
            </div>
          </section>

        </>
      ) : (
        <section className="content-section dydata32-role-panel">
          <div className="section-title">
            <div>
              <p className="eyebrow">角色权限</p>
              <h2>角色 × 页面权限矩阵</h2>
              <p>角色纵向排列，当前系统页面横向排列；勾选表示该角色默认可见。</p>
            </div>
            <Button onClick={() => setShowSaveDialog(true)} variant="primary">
              保存默认权限
            </Button>
          </div>

          <div className="dydata32-matrix-wrap" tabIndex={0}>
            <DataTable
              columns={[
                {
                  key: "role",
                  minWidth: 180,
                  render: (role: (typeof roles)[number]) => (
                    <>
                      <strong>{role.name}</strong>
                      <small>{role.note}</small>
                    </>
                  ),
                  sticky: true,
                  title: "角色",
                },
                ...pages.map((page) => ({
                  key: page.id,
                  minWidth: 88,
                  render: (role: (typeof roles)[number]) => (
                    <input
                      aria-label={`${role.name}可见${page.name}`}
                      checked={permissions[role.key].has(page.id)}
                      disabled={role.key === "highest"}
                      onChange={() => toggleRolePermission(role.key, page.id)}
                      type="checkbox"
                    />
                  ),
                  title: (
                    <>
                      <small>{page.group}</small>
                      <span>{page.id} · {page.name}</span>
                    </>
                  ),
                })),
              ]}
              mobileCard={false}
              rows={roles}
              tableClassName="dydata32-permission-matrix"
            />
          </div>

          <div className="dydata32-rule-notes">
            <div>
              <strong>最高管理员</strong>
              <p>始终拥有全部页面，矩阵只读。</p>
            </div>
            <div>
              <strong>默认变更</strong>
              <p>继承默认的账号自动更新；自定义账号保持最终权限不变，并重新计算差异项。</p>
            </div>
            <div>
              <strong>后续新增页面</strong>
              <p>最高管理员默认允许；管理员和门店账号默认禁止，必须在此处明确勾选。</p>
            </div>
          </div>
        </section>
      )}

      <Dialog
        actions={(
          <>
            <Button onClick={() => setShowSaveDialog(false)} variant="secondary">取消</Button>
            <Button
              onClick={() => {
                setShowSaveDialog(false);
                setNotice(`角色默认权限已在预览中保存；${resetCustomized ? "自定义账号已选择重置" : "自定义账号保持不变"}。`);
              }}
              variant="primary"
            >
              确认变更
            </Button>
          </>
        )}
        description="7 个继承角色默认的账号将自动更新；2 个已自定义账号默认保持当前最终权限不变。"
        onClose={() => setShowSaveDialog(false)}
        open={showSaveDialog}
        panelClassName="dydata32-dialog"
        title="本次变更会影响 9 个账号"
      >
        <div className="dydata32-impact-grid">
          <span><strong>7</strong>继承默认</span>
          <span><strong>2</strong>已自定义</span>
          <span><strong>0</strong>权限丢失</span>
        </div>
        <label className="dydata32-reset-option">
          <input checked={resetCustomized} onChange={(event) => setResetCustomized(event.target.checked)} type="checkbox" />
          同时将 2 个自定义账号重置为新的角色默认权限
        </label>
        <p className="dydata32-help">该选项默认不勾选。确认后会写入权限变更记录。</p>
      </Dialog>

      <Dialog
        actions={(
          <>
            <Button onClick={() => setShowRestoreDialog(false)} variant="secondary">取消</Button>
            <Button onClick={restoreDefault} variant="primary">确认恢复</Button>
          </>
        )}
        description={`将移除 ${extraAllow.size} 项额外允许和 ${extraDeny.size} 项额外禁止，最终权限重新继承角色默认值。`}
        onClose={() => setShowRestoreDialog(false)}
        open={showRestoreDialog}
        panelClassName="dydata32-dialog"
        title={`清除 ${selectedAccount.name} 的全部例外设置？`}
      >
        <p className="dydata32-help">确认后会写入权限变更记录。</p>
      </Dialog>

      <Dialog
        actions={(
          <>
            <Button onClick={() => setPasswordResetTarget(null)} variant="secondary">取消</Button>
            <Button
              onClick={() => {
                setPasswordResetTarget(null);
                setNotice("密码已在预览中重置；真实数据未发生变化。");
              }}
              variant="primary"
            >
              确认重置
            </Button>
          </>
        )}
        description="保留现有密码重置窗口；操作记录只记重置动作，不记录密码内容。"
        onClose={() => setPasswordResetTarget(null)}
        open={passwordResetTarget !== null}
        panelClassName="dydata32-dialog"
        title={passwordResetTarget?.name ?? "重置密码"}
      >
        <div className="dydata32-account-form">
          <label>新密码<input placeholder="请输入新密码" type="password" /></label>
          <label>确认密码<input placeholder="再次输入新密码" type="password" /></label>
        </div>
      </Dialog>

      <Dialog
        description="只记录账号、角色、页面权限、门店范围和最高管理员治理操作，不记录密码内容。"
        onClose={() => setShowAudit(false)}
        open={showAudit}
        panelClassName="dydata32-dialog dydata32-dialog--wide"
        title="账号与权限变更记录"
      >
        <div className="dydata32-filter-row">
          <SelectField label="操作人" onChange={() => undefined} options={[{ label: "全部", value: "all" }, { label: "system-admin", value: "system-admin" }]} value="all" />
          <SelectField label="操作类型" onChange={() => undefined} options={[{ label: "全部类型", value: "all" }, { label: "权限变更", value: "permission" }, { label: "账号失效", value: "disabled" }]} value="all" />
          <SelectField label="时间范围" onChange={() => undefined} options={[{ label: "近 30 天", value: "30" }, { label: "近 7 天", value: "7" }]} value="30" />
        </div>
        <DataTable
          columns={[
            { key: "time", render: (row: PreviewAuditRow) => row.time, title: "时间" },
            { key: "actor", render: (row: PreviewAuditRow) => row.actor, title: "操作人" },
            { key: "target", render: (row: PreviewAuditRow) => row.target, title: "对象" },
            { key: "action", minWidth: 280, render: (row: PreviewAuditRow) => row.action, title: "操作" },
            { key: "result", render: (row: PreviewAuditRow) => <StatusChip tone="success">{row.result}</StatusChip>, title: "结果" },
          ]}
          mobileCard={false}
          rows={auditRows}
        />
        <p className="dydata32-help">本期提供查看与筛选，不提供导出。</p>
      </Dialog>
    </div>
  );
}
