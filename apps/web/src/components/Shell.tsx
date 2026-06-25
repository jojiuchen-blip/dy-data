import { useState, type FormEvent, type ReactNode } from "react";
import { changeCurrentUserPassword, submitFeedback } from "../api/client";
import type { AdminUser, FeedbackCategory } from "../types/dashboard";
import { CommissionRulesButton } from "./CommissionRulesButton";
import { Dialog } from "./Dialog";
import { SelectField } from "./FormControls";
import { SolarIcon, type SolarIconName } from "./SolarIcon";

const settlementPaths = new Set(["/ranking", "/settlement", "/details"]);
const adminPaths = new Set([
  "/admin",
  "/admin/accounts",
  "/admin/rules",
  "/admin/sync",
  "/admin/clues/rules",
  "/admin/feedback",
  "/rule-admin",
  "/sync-admin",
]);

type NavSection = "settlement" | "clues" | "admin";

interface NavItem {
  href: string;
  icon?: SolarIconName;
  label: string;
}

interface ModuleNavItem extends NavItem {
  section: NavSection;
  description: string;
  badge?: string;
}

const moduleNavItems: ModuleNavItem[] = [
  {
    href: "/clues",
    icon: "clues",
    label: "线索中心",
    section: "clues",
    description: "经营线索",
  },
  {
    href: "/ranking",
    icon: "chart",
    label: "订单分佣",
    section: "settlement",
    description: "BETA",
    badge: "BETA",
  },
  {
    href: "/admin",
    icon: "admin",
    label: "后台",
    section: "admin",
    description: "系统管理",
  },
];

const settlementNavItems: NavItem[] = [
  { href: "/ranking", label: "全国门店榜单", icon: "ranking" },
  { href: "/settlement", label: "单店结算", icon: "settlement" },
  { href: "/details", label: "订单明细", icon: "details" },
];

const clueNavItems: NavItem[] = [
  { href: "/clues", label: "线索看板", icon: "chart" },
  { href: "/clues/details", label: "线索明细", icon: "details" },
];

const adminNavItems: NavItem[] = [
  { href: "/admin", label: "后台首页", icon: "home" },
  { href: "/admin/accounts", label: "账号管理", icon: "accounts" },
  { href: "/admin/rules", label: "分佣规则", icon: "rules" },
  { href: "/admin/clues/rules", label: "线索规则", icon: "cluesLine" },
  { href: "/admin/feedback", label: "用户建议", icon: "feedback" },
  { href: "/admin/sync", label: "数据同步", icon: "sync" },
];

const sectionLabels: Record<NavSection, string> = {
  settlement: "订单分佣结算中心",
  clues: "线索中心",
  admin: "管理后台",
};

const feedbackCategories: Array<{ label: string; value: FeedbackCategory }> = [
  { label: "使用体验", value: "experience" },
  { label: "数据问题", value: "data" },
  { label: "功能建议", value: "feature" },
  { label: "其他", value: "other" },
];

interface ShellProps {
  currentPath: string;
  currentUser?: AdminUser | null;
  onLogout?: () => void;
  children: ReactNode;
}

function activeSection(currentPath: string): NavSection {
  if (adminPaths.has(currentPath)) {
    return "admin";
  }
  if (currentPath === "/clues" || currentPath.startsWith("/clues/")) {
    return "clues";
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
  return settlementNavItems;
}

function roleLabel(role: AdminUser["role"]): string {
  if (role === "admin") {
    return "最高管理员";
  }
  if (role === "viewer") {
    return "全局查看";
  }
  return "门店账号";
}

export function Shell({ currentPath, currentUser, onLogout, children }: ShellProps) {
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
  const sectionNavItems = secondaryNav(section);
  const visibleModuleItems = moduleNavItems.filter(
    (item) => item.section !== "admin" || currentUser?.role === "admin",
  );

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
    <div className="app-shell app-shell--rail">
      <aside className="app-rail" aria-label="主模块导航">
        <a className="rail-brand" href="/">
          <SolarIcon className="rail-brand__mark" name="brand" size={42} />
          <span>经营引擎</span>
        </a>
        <nav className="rail-nav">
          {visibleModuleItems.map((item) => {
            const active = item.section === section;
            return (
              <a
                aria-current={active ? "page" : undefined}
                className="rail-nav__item"
                href={item.href}
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
          <div className="workspace-context">
            <div className="workspace-kicker">
              <span>{sectionLabels[section]}</span>
              {section === "settlement" ? <em>BETA</em> : null}
            </div>
          </div>

          <div className="workspace-actions">
            {section === "settlement" ? <CommissionRulesButton /> : null}
            {currentUser ? (
              <div className="account-cluster">
                <div className="account-cluster__identity">
                  <SolarIcon name="accounts" size={18} />
                  <span>{currentUser.display_name || currentUser.username}</span>
                  <em>{roleLabel(currentUser.role)}</em>
                </div>
                <button
                  className="ghost-button utility-button"
                  onClick={() => setSettingsOpen(true)}
                  type="button"
                >
                  <SolarIcon name="key" size={15} />
                  个人设置
                </button>
                {onLogout ? (
                  <button
                    className="ghost-button utility-button"
                    onClick={onLogout}
                    type="button"
                  >
                    <SolarIcon name="logout" size={15} />
                    退出
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </header>

        <nav className="workspace-subnav" aria-label={`${sectionLabels[section]}导航`}>
          {sectionNavItems.map((item) => {
            const active =
              currentPath === item.href ||
              (item.href === "/admin/rules" && currentPath === "/rule-admin") ||
              (item.href === "/admin/sync" && currentPath === "/sync-admin");
            return (
              <a
                aria-current={active ? "page" : undefined}
                href={item.href}
                key={item.href}
              >
                {item.icon ? <SolarIcon name={item.icon} size={15} /> : null}
                {item.label}
              </a>
            );
          })}
        </nav>

        <main className="page-frame">{children}</main>
      </div>

      <nav className="mobile-bottom-nav" aria-label="一级导航">
        {visibleModuleItems.map((item) => {
          const active = item.section === section;
          return (
            <a
              aria-current={active ? "page" : undefined}
              href={item.href}
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
              <dd>{roleLabel(currentUser.role)}</dd>
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
            <button
              className="ghost-button mine-panel__action"
              onClick={openSettingsFromMine}
              type="button"
            >
              <SolarIcon name="key" size={18} />
              <span>修改密码</span>
            </button>
            <button
              className="ghost-button mine-panel__action"
              onClick={openFeedbackFromMine}
              type="button"
            >
              <SolarIcon name="feedback" size={18} />
              <span>提交建议</span>
            </button>
            {onLogout ? (
              <button
                className="ghost-button mine-panel__action mine-panel__action--danger"
                onClick={handleMineLogout}
                type="button"
              >
                <SolarIcon name="logout" size={18} />
                <span>退出登录</span>
              </button>
            ) : null}
          </div>
        </Dialog>
      ) : null}

      {feedbackOpen ? (
        <Dialog
          bodyClassName="ui-dialog__body--flush"
          closeDisabled={submittingFeedback}
          closeLabel="关闭提交建议"
          description="反馈体验问题、数据问题或希望补充的能力。"
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
              <button
                className="ghost-button"
                disabled={submittingFeedback}
                onClick={() => setFeedbackOpen(false)}
                type="button"
              >
                取消
              </button>
              <button
                className="primary-button"
                disabled={submittingFeedback || !feedbackContent.trim()}
                type="submit"
              >
                {submittingFeedback ? "提交中..." : "提交建议"}
              </button>
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
            <button className="primary-button" disabled={savingPassword} type="submit">
              保存密码
            </button>
          </form>
        </Dialog>
      ) : null}
    </div>
  );
}
