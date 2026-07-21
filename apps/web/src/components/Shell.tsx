import { useState, type FormEvent, type ReactNode } from "react";
import { changeCurrentUserPassword, submitFeedback } from "../api/client";
import type { AdminUser, FeedbackCategory } from "../types/dashboard";
import { CommissionRulesButton } from "./CommissionRulesButton";
import { Dialog } from "./Dialog";
import { SelectField } from "./FormControls";
import { Button } from "./Button";
import { SolarIcon, type SolarIconName } from "./SolarIcon";

const settlementPaths = new Set(["/ranking", "/settlement", "/details"]);
const verificationPaths = new Set(["/sales"]);
const dataWorkspacePaths = new Set(["/clues/details", "/details"]);
const adminPaths = new Set([
  "/admin",
  "/admin/accounts",
  "/admin/rules",
  "/admin/sync",
  "/admin/clue-allocation",
  "/admin/feedback",
  "/admin/product-types",
  "/rule-admin",
  "/sync-admin",
]);

type NavSection = "settlement" | "verification" | "clues" | "admin";

interface NavItem {
  href: string;
  label: string;
  pageKey?: string;
}

interface ModuleNavItem extends NavItem {
  icon?: SolarIconName;
  section: NavSection;
  description: string;
  badge?: string;
  pageKeys: string[];
}

const moduleNavItems: ModuleNavItem[] = [
  {
    href: "/clues",
    pageKey: "A01",
    pageKeys: ["A01", "A02"],
    icon: "clues",
    label: "线索中心",
    section: "clues",
    description: "经营线索",
  },
  {
    href: "/sales",
    pageKey: "C01",
    pageKeys: ["C01"],
    icon: "chart",
    label: "核销表现",
    section: "verification",
    description: "核销分析",
  },
  {
    href: "/ranking",
    pageKey: "B01",
    pageKeys: ["B01", "B02", "B03"],
    icon: "chart",
    label: "订单分佣",
    section: "settlement",
    description: "试运行",
    badge: "试运行",
  },
  {
    href: "/admin",
    pageKey: "D01",
    pageKeys: ["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10"],
    icon: "admin",
    label: "后台",
    section: "admin",
    description: "系统管理",
  },
];

const settlementNavItems: NavItem[] = [
  { href: "/ranking", label: "全国门店榜单", pageKey: "B01" },
  { href: "/settlement", label: "单店结算", pageKey: "B02" },
  { href: "/details", label: "订单明细", pageKey: "B03" },
];

const clueNavItems: NavItem[] = [
  { href: "/clues", label: "线索看板", pageKey: "A01" },
  { href: "/clues/details", label: "线索明细", pageKey: "A02" },
];

const adminNavItems: NavItem[] = [
  { href: "/admin", label: "后台首页", pageKey: "D01" },
  { href: "/admin/accounts", label: "账号管理", pageKey: "D02" },
  { href: "/admin/rules", label: "分佣规则", pageKey: "D03" },
  { href: "/admin/product-types", label: "商品口径", pageKey: "D04" },
  { href: "/admin/clue-allocation", label: "线索分配规则", pageKey: "D05" },
  { href: "/admin/clue-allocation/trial", label: "分配试运行", pageKey: "D06" },
  { href: "/admin/clue-allocation/records", label: "分配记录", pageKey: "D07" },
  { href: "/admin/clue-allocation/headquarters", label: "总部线索池", pageKey: "D08" },
  { href: "/admin/feedback", label: "用户建议", pageKey: "D09" },
  { href: "/admin/sync", label: "数据同步", pageKey: "D10" },
];

const secondaryNavPathAliases: Record<string, string> = {
  "/rule-admin": "/admin/rules",
  "/sync-admin": "/admin/sync",
};

const sectionLabels: Record<NavSection, string> = {
  settlement: "订单分佣结算中心",
  verification: "核销表现",
  clues: "线索中心",
  admin: "管理后台",
};

const settlementTrialNotice =
  "提示：预计分佣比例、金额仅为试运行参考，不代表最终规则或最终到账金额。";

const feedbackCategories: Array<{ label: string; value: FeedbackCategory }> = [
  { label: "使用体验", value: "experience" },
  { label: "数据问题", value: "data" },
  { label: "功能建议", value: "feature" },
  { label: "其他", value: "other" },
];

interface ShellProps {
  currentPath: string;
  currentUser?: AdminUser | null;
  isDemoMode?: boolean;
  onLogout?: () => void;
  children: ReactNode;
}

function activeSection(currentPath: string): NavSection {
  if (
    adminPaths.has(currentPath) ||
    Array.from(adminPaths).some(
      (path) => path !== "/admin" && currentPath.startsWith(`${path}/`),
    )
  ) {
    return "admin";
  }
  if (verificationPaths.has(currentPath)) {
    return "verification";
  }
  if (currentPath === "/clues" || currentPath.startsWith("/clues/")) {
    return "clues";
  }
  if (settlementPaths.has(currentPath)) {
    return "settlement";
  }
  return "settlement";
}

function secondaryNav(section: NavSection): NavItem[] {
  if (section === "admin") {
    return adminNavItems;
  }
  if (section === "clues") {
    return clueNavItems;
  }
  if (section === "verification") {
    return [];
  }
  return settlementNavItems;
}

const pageKeyByNavHref: Record<string, string> = {
  "/clues": "A01",
  "/clues/details": "A02",
  "/ranking": "B01",
  "/settlement": "B02",
  "/details": "B03",
  "/sales": "C01",
  "/admin": "D01",
  "/admin/accounts": "D02",
  "/admin/rules": "D03",
  "/admin/product-types": "D04",
  "/admin/clue-allocation": "D05",
  "/admin/feedback": "D09",
  "/admin/sync": "D10",
};

const defaultHrefByPageKey: Record<string, string> = Object.fromEntries(
  Object.entries(pageKeyByNavHref).map(([href, pageKey]) => [pageKey, href]),
);

function accessibleModuleHref(item: ModuleNavItem, user?: AdminUser | null): string {
  const pageKey = item.pageKeys.find((key) => user?.page_keys.includes(key));
  return (pageKey && defaultHrefByPageKey[pageKey]) || item.href;
}

function activeSecondaryNavHref(
  items: NavItem[],
  currentPath: string,
): string | undefined {
  const normalizedPath = secondaryNavPathAliases[currentPath] ?? currentPath;
  return [...items]
    .sort((left, right) => right.href.length - left.href.length)
    .find(
      (item) =>
        normalizedPath === item.href ||
        normalizedPath.startsWith(`${item.href}/`),
    )?.href;
}

function roleLabel(user: AdminUser): string {
  if (user.role === "highest_admin") {
    return "最高管理员";
  }
  if (user.role === "admin") {
    return user.is_highest_admin ? "最高管理员" : "管理员";
  }
  return "门店账号";
}

export function Shell({
  currentPath,
  currentUser,
  isDemoMode = false,
  onLogout,
  children,
}: ShellProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mineOpen, setMineOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [settingsMessage, setSettingsMessage] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackCategory, setFeedbackCategory] =
    useState<FeedbackCategory>("experience");
  const [feedbackContent, setFeedbackContent] = useState("");
  const [feedbackContact, setFeedbackContact] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [feedbackMessageType, setFeedbackMessageType] = useState<
    "error" | "success" | null
  >(null);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const section = activeSection(currentPath);
  const sectionNavItems = secondaryNav(section).filter((item) => {
    const pageKey = item.pageKey ?? pageKeyByNavHref[item.href];
    return pageKey ? currentUser?.page_keys.includes(pageKey) : false;
  });
  const activeSecondaryHref = activeSecondaryNavHref(
    sectionNavItems,
    currentPath,
  );
  const pageFrameClassName = [
    "page-frame",
    dataWorkspacePaths.has(currentPath) ? "page-frame--data-workspace" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const visibleModuleItems = moduleNavItems.filter((item) =>
    item.pageKeys.some((pageKey) => currentUser?.page_keys.includes(pageKey)),
  );
  const shellClassName = isDemoMode
    ? "app-shell app-shell--rail app-shell--demo"
    : "app-shell app-shell--rail";

  const openFeedback = () => {
    setFeedbackOpen(true);
    setFeedbackMessage("");
    setFeedbackMessageType(null);
  };

  const openFeedbackFromMine = () => {
    setMineOpen(false);
    openFeedback();
  };

  const openSettingsFromMine = () => {
    setMineOpen(false);
    setSettingsOpen(true);
  };

  const handleMineLogout = () => {
    setMineOpen(false);
    onLogout?.();
  };

  const storeScopeLabel =
    currentUser && currentUser.store_ids.length > 0
      ? `${currentUser.store_ids.length} 个门店`
      : currentUser?.role === "store"
        ? "未绑定门店"
        : "全部数据";

  const renderSecondaryNav = (className: string) => (
    sectionNavItems.length > 0 ? (
      <nav
        className={`workspace-subnav ${className}`}
        aria-label={`${sectionLabels[section]}导航`}
      >
        {sectionNavItems.map((item) => {
          const active = item.href === activeSecondaryHref;
          return (
            <a
              aria-current={active ? "page" : undefined}
              href={item.href}
              key={item.href}
            >
              {item.label}
            </a>
          );
        })}
      </nav>
    ) : null
  );

  const handleFeedbackSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const content = feedbackContent.trim();
    const contact = feedbackContact.trim();
    if (!content) {
      setFeedbackMessage("请先写下你的建议。");
      setFeedbackMessageType("error");
      return;
    }

    setSubmittingFeedback(true);
    setFeedbackMessage("");
    setFeedbackMessageType(null);
    try {
      await submitFeedback({
        category: feedbackCategory,
        contact: contact || null,
        content,
        page_path: currentPath,
      });
      setFeedbackContent("");
      setFeedbackContact("");
      setFeedbackMessage("建议已提交，感谢反馈。");
      setFeedbackMessageType("success");
    } catch {
      setFeedbackMessage("提交失败，请稍后重试。");
      setFeedbackMessageType("error");
    } finally {
      setSubmittingFeedback(false);
    }
  };

  const handlePasswordChange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSettingsMessage("");
    setSavingPassword(true);
    try {
      await changeCurrentUserPassword({
        password,
        password_confirm: passwordConfirm,
      });
      setPassword("");
      setPasswordConfirm("");
      setSettingsMessage("密码已更新。");
    } catch {
      setSettingsMessage("密码更新失败，请确认两次输入一致。");
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <div className={shellClassName}>
      <aside className="app-rail" aria-label="主模块导航">
        <a className="rail-brand" href="/">
          <SolarIcon className="rail-brand__mark" name="brand" size={42} />
          <span>经营引擎</span>
        </a>
        <nav className="rail-nav">
          {visibleModuleItems.map((item) => {
            const active = item.section === section;
            const href = accessibleModuleHref(item, currentUser);
            return (
              <a
                aria-current={active ? "page" : undefined}
                className="rail-nav__item"
                href={href}
                key={item.href}
              >
                {item.icon ? <SolarIcon name={item.icon} size={19} /> : null}
                <span>{item.label}</span>
                <small>
                  {item.badge ? <em>{item.badge}</em> : item.description}
                </small>
              </a>
            );
          })}
        </nav>
        <button
          aria-label="提交使用体验建议"
          className="rail-feedback-button"
          onClick={openFeedback}
          type="button"
        >
          <SolarIcon name="feedback" size={20} />
          <span>建议</span>
          <small>提交体验</small>
        </button>
      </aside>

      <div className="workspace-shell">
        <header className="workspace-topbar">
          {renderSecondaryNav("workspace-subnav--desktop")}
          {section === "settlement" ? (
            <div
              aria-label={settlementTrialNotice}
              className="settlement-trial-notice"
              role="note"
            >
              {settlementTrialNotice}
            </div>
          ) : null}
          <div className="workspace-actions">
            {section === "settlement" ? <CommissionRulesButton /> : null}
            {currentUser ? (
              <div className="account-cluster">
                <div className="account-cluster__identity">
                  <SolarIcon name="accounts" size={18} />
                  <span>{currentUser.display_name || currentUser.username}</span>
                  <em>{roleLabel(currentUser)}</em>
                </div>
                <Button
                  className="utility-button"
                  icon="key"
                  onClick={() => setSettingsOpen(true)}
                  type="button"
                  variant="secondary"
                >
                  个人设置
                </Button>
                {onLogout ? (
                  <Button
                    className="utility-button"
                    icon="logout"
                    onClick={onLogout}
                    type="button"
                    variant="secondary"
                  >
                    退出
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        </header>

        {renderSecondaryNav("workspace-subnav--mobile")}
        {section === "settlement" ? (
          <div className="settlement-trial-notice settlement-trial-notice--mobile">
            {settlementTrialNotice}
          </div>
        ) : null}

        {isDemoMode ? (
          <div className="demo-mode-notice" role="note">
            <SolarIcon name="question" size={16} />
            <span>演示数据 · 全部为合成数据 · 不写入数据库</span>
            <small>操作仅在当前浏览器会话生效，刷新后重置</small>
          </div>
        ) : null}

        <main className={pageFrameClassName}>{children}</main>
      </div>

      <nav className="mobile-bottom-nav" aria-label="一级导航">
          {visibleModuleItems.map((item) => {
            const active = item.section === section;
            const href = accessibleModuleHref(item, currentUser);
            return (
            <a
              aria-current={active ? "page" : undefined}
                href={href}
              key={item.href}
            >
              {item.icon ? <SolarIcon name={item.icon} size={21} /> : null}
              <span>
                {item.label}
                {item.badge ? <em>{item.badge}</em> : null}
              </span>
            </a>
          );
        })}
        <button
          aria-label="我的账号"
          aria-expanded={mineOpen}
          className="mobile-bottom-nav__mine"
          onClick={() => setMineOpen(true)}
          type="button"
        >
          <SolarIcon name="accounts" size={21} />
          <span>我的</span>
        </button>
      </nav>

      {mineOpen && currentUser ? (
        <Dialog
          backdropClassName="modal-backdrop--mine"
          bodyClassName="ui-dialog__body--flush"
          onClose={() => setMineOpen(false)}
          open={mineOpen}
          panelClassName="mine-panel"
          title="我的"
        >
          <div className="mine-panel__identity">
            <SolarIcon name="accounts" size={30} />
            <div>
              <strong>{currentUser.display_name || currentUser.username}</strong>
              <span>{currentUser.username}</span>
            </div>
          </div>
          <dl className="mine-panel__meta">
            <div>
              <dt>角色</dt>
              <dd>{roleLabel(currentUser)}</dd>
            </div>
            <div>
              <dt>账号状态</dt>
              <dd>{currentUser.status === "active" ? "正常" : "已停用"}</dd>
            </div>
            <div>
              <dt>可见范围</dt>
              <dd>{storeScopeLabel}</dd>
            </div>
            <div>
              <dt>激活状态</dt>
              <dd>{currentUser.is_initialized ? "已激活" : "未激活"}</dd>
            </div>
          </dl>
          <div className="mine-panel__actions" aria-label="我的操作">
            <Button
              className="mine-panel__action"
              icon="key"
              onClick={openSettingsFromMine}
              type="button"
              variant="secondary"
            >
              修改密码
            </Button>
            <Button
              className="mine-panel__action"
              icon="feedback"
              onClick={openFeedbackFromMine}
              type="button"
              variant="secondary"
            >
              提交建议
            </Button>
            {onLogout ? (
              <Button
                className="mine-panel__action"
                icon="logout"
                onClick={handleMineLogout}
                type="button"
                variant="danger"
              >
                退出登录
              </Button>
            ) : null}
          </div>
        </Dialog>
      ) : null}

      {feedbackOpen ? (
        <Dialog
          bodyClassName="ui-dialog__body--flush"
          closeDisabled={submittingFeedback}
          closeLabel="关闭提交建议"
          description="我们会采取星评加分等激励措施，期待您一起构建更好的数据经营平台。"
          onClose={() => setFeedbackOpen(false)}
          open={feedbackOpen}
          panelClassName="feedback-modal"
          title="提交建议"
        >
          <form className="feedback-form" onSubmit={handleFeedbackSubmit}>
            <SelectField
              label="建议类型"
              onChange={(value) => setFeedbackCategory(value as FeedbackCategory)}
              options={feedbackCategories}
              value={feedbackCategory}
            />
            <label className="filter-field">
              <span>你的建议</span>
              <textarea
                maxLength={2000}
                onChange={(event) => setFeedbackContent(event.target.value)}
                placeholder="写下哪里不好用、缺什么能力，或数据哪里不符合预期。"
                required
                value={feedbackContent}
              />
            </label>
            <label className="filter-field">
              <span>联系方式（选填）</span>
              <input
                maxLength={120}
                onChange={(event) => setFeedbackContact(event.target.value)}
                placeholder="方便回访时填写姓名、门店或手机号"
                value={feedbackContact}
              />
            </label>
            {feedbackMessage ? (
              <p
                aria-live={feedbackMessageType === "error" ? "assertive" : "polite"}
                className={`feedback-form__message feedback-form__message--${feedbackMessageType}`}
                role={feedbackMessageType === "error" ? "alert" : "status"}
              >
                {feedbackMessage}
              </p>
            ) : null}
            <div className="feedback-form__actions">
              <Button
                disabled={submittingFeedback}
                onClick={() => setFeedbackOpen(false)}
                type="button"
                variant="secondary"
              >
                取消
              </Button>
              <Button
                disabled={!feedbackContent.trim()}
                loading={submittingFeedback}
                type="submit"
                variant="primary"
              >
                {submittingFeedback ? "提交中..." : "提交建议"}
              </Button>
            </div>
          </form>
        </Dialog>
      ) : null}

      {settingsOpen ? (
        <Dialog
          bodyClassName="ui-dialog__body--flush"
          closeLabel="关闭个人设置"
          description="修改当前账号的登录密码。"
          onClose={() => setSettingsOpen(false)}
          open={settingsOpen}
          panelClassName="personal-settings-modal"
          title="个人设置"
        >
          <form className="auth-form personal-settings-form" onSubmit={handlePasswordChange}>
            <label className="filter-field">
              <span>新密码</span>
              <input
                autoComplete="new-password"
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                value={password}
              />
            </label>
            <label className="filter-field">
              <span>确认密码</span>
              <input
                autoComplete="new-password"
                onChange={(event) => setPasswordConfirm(event.target.value)}
                type="password"
                value={passwordConfirm}
              />
            </label>
            {settingsMessage ? (
              <p aria-live="polite" className="admin-error" role="status">
                {settingsMessage}
              </p>
            ) : null}
            <Button loading={savingPassword} type="submit" variant="primary">
              保存密码
            </Button>
          </form>
        </Dialog>
      ) : null}
    </div>
  );
}
