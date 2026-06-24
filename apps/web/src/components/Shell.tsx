import { useState, type ReactNode } from "react";
import { changeCurrentUserPassword } from "../api/client";
import type { AdminUser } from "../types/dashboard";
import { CommissionRulesButton } from "./CommissionRulesButton";
import { SolarIcon, type SolarIconName } from "./SolarIcon";

const settlementPaths = new Set(["/ranking", "/settlement", "/details"]);
const adminPaths = new Set([
  "/admin",
  "/admin/accounts",
  "/admin/rules",
  "/admin/sync",
  "/admin/clues/rules",
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
}

const moduleNavItems: ModuleNavItem[] = [
  {
    href: "/ranking",
    icon: "chart",
    label: "结算",
    section: "settlement",
    description: "订单分佣",
  },
  {
    href: "/clues",
    icon: "clues",
    label: "线索",
    section: "clues",
    description: "跟进分配",
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
  { href: "/clues", label: "线索中心", icon: "cluesLine" },
];

const adminNavItems: NavItem[] = [
  { href: "/admin", label: "后台首页", icon: "home" },
  { href: "/admin/accounts", label: "账号管理", icon: "accounts" },
  { href: "/admin/rules", label: "分佣规则", icon: "rules" },
  { href: "/admin/clues/rules", label: "线索规则", icon: "cluesLine" },
  { href: "/admin/sync", label: "数据同步", icon: "sync" },
];

const sectionLabels: Record<NavSection, string> = {
  settlement: "结算中心",
  clues: "线索中心",
  admin: "管理后台",
};

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
  if (currentPath === "/clues") {
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

function pageTitle(currentPath: string): string {
  const allItems = [...settlementNavItems, ...clueNavItems, ...adminNavItems];
  return (
    allItems.find((item) => item.href === currentPath)?.label ??
    (currentPath === "/rule-admin"
      ? "分佣规则"
      : currentPath === "/sync-admin"
        ? "数据同步"
        : "全国门店榜单")
  );
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
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [settingsMessage, setSettingsMessage] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const section = activeSection(currentPath);
  const sectionNavItems = secondaryNav(section);
  const visibleModuleItems = moduleNavItems.filter(
    (item) => item.section !== "admin" || currentUser?.role === "admin",
  );

  const handlePasswordChange = async (event: React.FormEvent<HTMLFormElement>) => {
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
                <small>{item.description}</small>
              </a>
            );
          })}
        </nav>
      </aside>

      <div className="workspace-shell">
        <header className="workspace-topbar">
          <div className="workspace-context">
            <div className="workspace-kicker">
              <span>{sectionLabels[section]}</span>
              <span>/</span>
              <strong>{pageTitle(currentPath)}</strong>
            </div>
            <div className="workspace-title">{pageTitle(currentPath)}</div>
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
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>

      {settingsOpen ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setSettingsOpen(false);
            }
          }}
          role="presentation"
        >
          <section
            aria-labelledby="personal-settings-title"
            aria-modal="true"
            className="personal-settings-modal"
            role="dialog"
          >
            <header className="clue-detail-modal__header">
              <div>
                <p className="eyebrow">Personal settings</p>
                <h2 id="personal-settings-title">个人设置</h2>
              </div>
              <button
                aria-label="关闭个人设置"
                className="modal-close"
                onClick={() => setSettingsOpen(false)}
                type="button"
              >
                <SolarIcon name="close" size={18} />
              </button>
            </header>
            <form className="auth-form personal-settings-form" onSubmit={handlePasswordChange}>
              <div>
                <h2>修改密码</h2>
                <p className="admin-muted">密码更新后，后续登录使用新密码。</p>
              </div>
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
              {settingsMessage ? <p className="admin-error">{settingsMessage}</p> : null}
              <button className="primary-button" disabled={savingPassword} type="submit">
                保存密码
              </button>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
