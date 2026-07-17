import { useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchAdminSession, logoutAdmin } from "./api/client";
import { CLUE_DEMO_MODE } from "./demo/clueDemoMode";
import type { AdminUser } from "./types/dashboard";
import { AdminHomePage } from "./pages/AdminHomePage";
import {
  AdminClueAllocationPage,
  type AllocationSubview,
} from "./pages/AdminClueAllocationPage";
import { AdminFeedbackPage } from "./pages/AdminFeedbackPage";
import { AdminProductTypeVisibilityPage } from "./pages/AdminProductTypeVisibilityPage";
import { AdminAccountsPage } from "./pages/AdminAccountsPage";
import { AuthPage, type AuthMode } from "./pages/AuthPage";
import { Shell } from "./components/Shell";
import { AdminSkuRulesPage } from "./pages/AdminSkuRulesPage";
import { AdminSyncPage } from "./pages/AdminSyncPage";
import { ClueCenterPage } from "./pages/ClueCenterPage";
import { HomePage } from "./pages/HomePage";
import { OrderDetailsPage } from "./pages/OrderDetailsPage";
import { SalesDashboardPage } from "./pages/SalesDashboardPage";
import { StoreRankingPage } from "./pages/StoreRankingPage";
import { StoreSettlementPage } from "./pages/StoreSettlementPage";

function readLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

interface AuthGateProps {
  children: (props: { user: AdminUser; onLogout: () => void }) => ReactNode;
  pathname: string;
}

function authModeFromPath(pathname: string): AuthMode {
  if (pathname === "/auth/reset-password") {
    return "reset";
  }
  if (pathname === "/auth/activate") {
    return "activate";
  }
  return "login";
}

function clueAllocationSubviewFromPath(pathname: string): AllocationSubview | null {
  if (pathname === "/admin/clue-allocation" || pathname === "/admin/clue-allocation/rules") {
    return "rules";
  }
  if (pathname === "/admin/clue-allocation/trial") {
    return "trial";
  }
  if (pathname === "/admin/clue-allocation/records") {
    return "records";
  }
  if (pathname === "/admin/clue-allocation/headquarters") {
    return "headquarters";
  }
  return null;
}

function AuthGate({ children, pathname }: AuthGateProps) {
  const [checking, setChecking] = useState(true);
  const [user, setUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAdminSession()
      .then((result) => {
        if (!cancelled) {
          setUser(result.data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setChecking(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = () => {
    logoutAdmin().catch(() => undefined);
    setUser(null);
  };

  const handleAuthenticated = (nextUser: AdminUser) => {
    setUser(nextUser);
    if (pathname === "/login" || pathname.startsWith("/auth/")) {
      window.history.pushState(null, "", "/ranking");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  };

  if (checking) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">正在检查登录状态...</section>
      </main>
    );
  }

  if (!user) {
    return (
      <AuthPage
        initialMode={authModeFromPath(pathname)}
        onAuthenticated={handleAuthenticated}
      />
    );
  }

  return <>{children({ user, onLogout: handleLogout })}</>;
}

function AdminForbiddenPage() {
  return (
    <div className="page-stack">
      <section className="content-section">
        <div className="section-title">
          <div>
            <p className="eyebrow">无权访问</p>
            <h1>当前账号没有最高管理员权限</h1>
            <p>请使用最高管理员账号登录后进入系统后台，不能通过地址直接进入。</p>
          </div>
        </div>
      </section>
    </div>
  );
}

export function App() {
  const [location, setLocation] = useState(readLocation);

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

      if (
        anchor.hasAttribute("download") ||
        anchor.target ||
        anchor.href.startsWith("blob:")
      ) {
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

  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );

  return (
    <AuthGate pathname={location.pathname}>
      {({ user, onLogout }) => {
        const clueAllocationSubview = clueAllocationSubviewFromPath(location.pathname);
        const adminPage =
          location.pathname === "/admin" ? (
            <AdminHomePage />
          ) : location.pathname === "/admin/accounts" ? (
            <AdminAccountsPage />
          ) : location.pathname === "/rule-admin" ||
            location.pathname === "/admin/rules" ? (
            <AdminSkuRulesPage />
          ) : location.pathname === "/sync-admin" ||
            location.pathname === "/admin/sync" ? (
            <AdminSyncPage isHighestAdmin={user.is_highest_admin === true} />
          ) : clueAllocationSubview ? (
            <AdminClueAllocationPage
              activeSubview={clueAllocationSubview}
              isHighestAdmin={user.is_highest_admin === true}
            />
          ) : location.pathname === "/admin/feedback" ? (
            <AdminFeedbackPage />
          ) : location.pathname === "/admin/product-types" ? (
            <AdminProductTypeVisibilityPage />
          ) : null;

        if (adminPage) {
          return (
            <Shell
              currentPath={location.pathname}
              currentUser={user}
              isDemoMode={CLUE_DEMO_MODE}
              onLogout={CLUE_DEMO_MODE ? undefined : onLogout}
            >
              {user.role === "admin" ? (
                adminPage
              ) : (
                <AdminForbiddenPage />
              )}
            </Shell>
          );
        }

        if (location.pathname === "/" || location.pathname === "/login") {
          return <HomePage />;
        }

        const page =
          location.pathname === "/settlement" ? (
            <StoreSettlementPage searchParams={searchParams} />
          ) : location.pathname === "/clues" ? (
            <ClueCenterPage
              currentUser={user}
              searchParams={searchParams}
              view="dashboard"
            />
          ) : location.pathname === "/clues/details" ? (
            <ClueCenterPage
              currentUser={user}
              searchParams={searchParams}
              view="details"
            />
          ) : location.pathname === "/details" ? (
            <OrderDetailsPage searchParams={searchParams} />
          ) : location.pathname === "/sales" ? (
            <SalesDashboardPage currentUser={user} searchParams={searchParams} />
          ) : (
            <StoreRankingPage searchParams={searchParams} />
          );

        return (
          <Shell
            currentPath={location.pathname}
            currentUser={user}
            isDemoMode={CLUE_DEMO_MODE}
            onLogout={CLUE_DEMO_MODE ? undefined : onLogout}
          >
            {page}
          </Shell>
        );
      }}
    </AuthGate>
  );
}
