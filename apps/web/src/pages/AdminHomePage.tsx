import { useEffect, useState } from "react";
import {
  fetchAdminSession,
  loginAdmin,
  logoutAdmin,
} from "../api/client";

const adminModules = [
  {
    href: "/admin/accounts",
    title: "账号管理",
    description: "创建、编辑、启用或停用账号，绑定单店或多店门店权限，并重置账号密码。",
    meta: "账号体系 v1",
  },
  {
    href: "/admin/clues/rules",
    title: "线索再分配规则",
    description: "配置线索中心全局 SLA，支持留空关闭自动超时待再分配，并触发线索中心重建。",
    meta: "线索中心 MVP",
  },
  {
    href: "/admin/rules",
    title: "商品分账规则",
    description: "按 SKU 配置商品类型和分账比例，保存后后台重建看板结果。",
    meta: "对应旧入口 /rule-admin",
  },
  {
    href: "/admin/sync",
    title: "数据同步管理",
    description: "配置同步时间跨度、同步间隔，查看任务日志和手动补拉数据。",
    meta: "对应旧入口 /sync-admin",
  },
];

export function AdminHomePage() {
  const [checkingSession, setCheckingSession] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchAdminSession()
      .then(() => {
        if (!cancelled) {
          setAuthenticated(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuthenticated(false);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingSession(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginError("");
    try {
      await loginAdmin(password);
      setPassword("");
      setAuthenticated(true);
    } catch {
      setLoginError("密码不正确，或后端未配置管理密码。");
    }
  };

  const handleLogout = async () => {
    await logoutAdmin().catch(() => undefined);
    setAuthenticated(false);
  };

  if (checkingSession) {
    return (
      <div className="admin-page">
        <section className="admin-login-panel">正在检查管理权限...</section>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="admin-page admin-page--centered">
        <form className="admin-login-panel" onSubmit={handleLogin}>
          <div>
            <p className="source-pill">系统管理后台</p>
            <h1>抖音经营中枢后台</h1>
            <p className="admin-muted">输入管理密码后进入配置页面。</p>
          </div>
          <label className="filter-field">
            <span>管理密码</span>
            <input
              autoFocus
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入管理密码"
              type="password"
              value={password}
            />
          </label>
          {loginError ? <p className="admin-error">{loginError}</p> : null}
          <button className="primary-button" type="submit">
            进入后台
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <p className="source-pill">系统管理后台</p>
          <h1>抖音经营中枢后台</h1>
          <p className="admin-muted">选择需要管理的配置模块。</p>
        </div>
        <div className="admin-header-actions">
          <a className="ghost-button admin-link-button" href="/">
            返回看板主页
          </a>
          <button className="ghost-button" onClick={handleLogout} type="button">
            退出
          </button>
        </div>
      </section>

      <section className="admin-module-grid">
        {adminModules.map((item) => (
          <a className="admin-module-card" href={item.href} key={item.href}>
            <div>
              <h2>{item.title}</h2>
              <p>{item.description}</p>
            </div>
            <span>{item.meta}</span>
          </a>
        ))}
      </section>
    </div>
  );
}
