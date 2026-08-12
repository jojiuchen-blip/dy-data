import { SolarIcon } from "./SolarIcon.jsx";

export function AppShell({
  role,
  pages,
  page,
  theme,
  children,
  onRoleChange,
  onPageChange,
  onThemeChange,
}) {
  function changeRole(nextRole) {
    onRoleChange(nextRole);
    onPageChange(nextRole === "store" ? "store-bills" : "finance-promotion");
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <header className="app-header">
        <div className="brand-lockup" aria-label="抖音经营引擎">
          <span className="brand-mark" aria-hidden="true">
            <i />
            <b />
          </span>
          <div>
            <strong>抖音经营引擎</strong>
            <small>月度财务协同</small>
          </div>
        </div>
        <div className="role-switcher" aria-label="演示角色">
          <button
            type="button"
            className={role === "store" ? "is-active" : ""}
            aria-pressed={role === "store"}
            onClick={() => changeRole("store")}
          >
            门店端
          </button>
          <button
            type="button"
            className={role === "finance" ? "is-active" : ""}
            aria-pressed={role === "finance"}
            onClick={() => changeRole("finance")}
          >
            财务端
          </button>
        </div>
        <div className="app-header__actions">
          <span className="account-context">
            <SolarIcon name={role === "store" ? "shop" : "user"} />
            {role === "store" ? "深圳龙岗比亚迪王朝店" : "财务（管理员角色）"}
          </span>
          <button
            type="button"
            className="icon-button"
            aria-label={theme === "light" ? "切换到深色主题" : "切换到浅色主题"}
            onClick={() => onThemeChange(theme === "light" ? "dark" : "light")}
          >
            <SolarIcon name={theme === "light" ? "moon" : "sun"} />
          </button>
        </div>
      </header>

      <aside className="primary-rail">
        <div className="primary-rail__intro">
          <span>{role === "store" ? "门店结算" : "财务管理"}</span>
          <strong>{role === "store" ? "2026年7月账期" : "全量门店"}</strong>
        </div>
        <nav aria-label={role === "store" ? "门店财务页面" : "财务管理页面"}>
          {Object.entries(pages).filter(([, item]) => item.nav !== false).map(([id, item]) => (
            <button
              type="button"
              key={id}
              className={page === id ? "is-active" : ""}
              aria-current={page === id ? "page" : undefined}
              onClick={() => onPageChange(id)}
            >
              <SolarIcon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="primary-rail__footnote">
          <SolarIcon name="info" />
          <span>演示数据仅用于流程确认，不写入真实账单。</span>
        </div>
      </aside>

      <main id="main-content" className="app-main">
        {children}
      </main>
    </div>
  );
}
