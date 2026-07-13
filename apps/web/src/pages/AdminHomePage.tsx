import { useEffect, useState } from "react";
import {
  fetchAdminSession,
  loginAdmin,
} from "../api/client";
import { Button } from "../components/Button";

const adminModules = [
  {
    href: "/admin/accounts",
    title: "账号管理",
    description: "创建、编辑、启用或停用账号，绑定单店或多店门店权限，并重置账号密码。",
    meta: "账号与权限",
  },
  {
    href: "/admin/clue-allocation",
    title: "线索分配",
    description: "统一管理规则版本、试运行、分配记录和总部池。",
    meta: "规则与运营",
  },
  {
    href: "/admin/product-types",
    title: "商品口径控制",
    description: "限制线索中心和结算中心展示的商品类型，例如上线初期只开放精诚养车类数据。",
    meta: "展示口径",
  },
  {
    href: "/admin/feedback",
    title: "用户建议",
    description: "查看用户提交的体验反馈、数据问题和功能建议，并标记处理状态。",
    meta: "反馈处理",
  },
  {
    href: "/admin/rules",
    title: "商品分账规则",
    description: "按 SKU 配置商品类型和分账比例，保存后后台重建看板结果。",
    meta: "商品分账配置",
  },
  {
    href: "/admin/sync",
    title: "数据同步管理",
    description: "配置同步时间跨度、同步间隔，查看任务日志和手动补拉数据。",
    meta: "同步与任务",
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
          {loginError ? (
            <p className="admin-error" role="alert">
              {loginError}
            </p>
          ) : null}
          <Button type="submit" variant="primary">
            进入后台
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <h1>抖音经营中枢后台</h1>
          <p className="admin-muted">选择需要管理的配置模块。</p>
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
