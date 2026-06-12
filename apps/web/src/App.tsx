import { FormEvent, useEffect, useMemo, useState } from "react";
import { fetchCurrentUser, login, logout, type CurrentUser } from "./api/client";
import { Shell } from "./components/Shell";
import { OrderDetailsPage } from "./pages/OrderDetailsPage";
import { StoreRankingPage } from "./pages/StoreRankingPage";
import { StoreSettlementPage } from "./pages/StoreSettlementPage";

function readLocation() {
  return {
    pathname: window.location.pathname === "/" ? "/ranking" : window.location.pathname,
    search: window.location.search,
  };
}

export function App() {
  const [location, setLocation] = useState(readLocation);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    const syncLocation = () => setLocation(readLocation());

    const handleClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey) {
        return;
      }

      const target = event.target as Element | null;
      const anchor = target?.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor) {
        return;
      }

      const url = new URL(anchor.href);
      if (url.origin !== window.location.origin) {
        return;
      }

      event.preventDefault();
      window.history.pushState(null, "", `${url.pathname}${url.search}${url.hash}`);
      syncLocation();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    window.addEventListener("popstate", syncLocation);
    document.addEventListener("click", handleClick);
    return () => {
      window.removeEventListener("popstate", syncLocation);
      document.removeEventListener("click", handleClick);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetchCurrentUser()
      .then((user) => {
        if (!cancelled) {
          setCurrentUser(user);
          setAuthError("");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCurrentUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAuthLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );

  const page =
    location.pathname === "/settlement" ? (
      <StoreSettlementPage searchParams={searchParams} />
    ) : location.pathname === "/details" ? (
      <OrderDetailsPage searchParams={searchParams} />
    ) : (
      <StoreRankingPage searchParams={searchParams} />
    );

  const handleLogin = async (username: string, password: string) => {
    setAuthError("");
    try {
      setCurrentUser(await login(username, password));
    } catch {
      setAuthError("账号或密码不正确");
    }
  };

  const handleLogout = async () => {
    await logout();
    setCurrentUser(null);
  };

  if (authLoading) {
    return (
      <div className="login-screen">
        <div className="login-panel">
          <p className="eyebrow">登录</p>
          <h1>正在验证登录状态</h1>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return <LoginPanel error={authError} onSubmit={handleLogin} />;
  }

  return (
    <Shell
      currentPath={location.pathname}
      onLogout={handleLogout}
      username={currentUser.username}
    >
      {page}
    </Shell>
  );
}

interface LoginPanelProps {
  error: string;
  onSubmit: (username: string, password: string) => Promise<void>;
}

function LoginPanel({ error, onSubmit }: LoginPanelProps) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(username, password);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-screen">
      <form className="login-panel" onSubmit={handleSubmit}>
        <p className="eyebrow">登录</p>
        <h1>抖音订单分账数据看板</h1>
        <label>
          <span>账号</span>
          <input
            autoComplete="username"
            onChange={(event) => setUsername(event.target.value)}
            value={username}
          />
        </label>
        <label>
          <span>密码</span>
          <input
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            value={password}
          />
        </label>
        {error ? <p className="login-error">{error}</p> : null}
        <button disabled={submitting} type="submit">
          {submitting ? "登录中" : "登录"}
        </button>
      </form>
    </div>
  );
}
