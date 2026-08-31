import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { fetchAdminSession, logoutAdmin } from "./api/client";
import { CLUE_DEMO_MODE, isClueDemoPathname } from "./demo/clueDemoMode";
import type { AdminUser } from "./types/dashboard";
import type { AllocationSubview } from "./pages/AdminClueAllocationPage";
import { AuthPage, type AuthMode } from "./pages/AuthPage";
import { Shell } from "./components/Shell";
import { CliAuthorizePage } from "./pages/CliAuthorizePage";
import { McpAuthorizePage } from "./pages/McpAuthorizePage";
import { HomePage } from "./pages/HomePage";

const AdminHomePage = lazy(() =>
  import("./pages/AdminHomePage").then((module) => ({
    default: module.AdminHomePage,
  })),
);
const AdminClueAllocationPage = lazy(() =>
  import("./pages/AdminClueAllocationPage").then((module) => ({
    default: module.AdminClueAllocationPage,
  })),
);
const AdminFeedbackPage = lazy(() =>
  import("./pages/AdminFeedbackPage").then((module) => ({
    default: module.AdminFeedbackPage,
  })),
);
const AdminProductTypeVisibilityPage = lazy(() =>
  import("./pages/AdminProductTypeVisibilityPage").then((module) => ({
    default: module.AdminProductTypeVisibilityPage,
  })),
);
const AdminAccountsPage = lazy(() =>
  import("./pages/AdminAccountsPage").then((module) => ({
    default: module.AdminAccountsPage,
  })),
);
const AdminSkuRulesPage = lazy(() =>
  import("./pages/AdminSkuRulesPage").then((module) => ({
    default: module.AdminSkuRulesPage,
  })),
);
const AdminSyncPage = lazy(() =>
  import("./pages/AdminSyncPage").then((module) => ({
    default: module.AdminSyncPage,
  })),
);
const ClueCenterPage = lazy(() =>
  import("./pages/ClueCenterPage").then((module) => ({
    default: module.ClueCenterPage,
  })),
);
const FinanceDisputesPage = lazy(() =>
  import("./pages/FinanceDisputesPage").then((module) => ({
    default: module.FinanceDisputesPage,
  })),
);
const FinanceFeePage = lazy(() =>
  import("./pages/FinanceFeePage").then((module) => ({
    default: module.FinanceFeePage,
  })),
);
const FinanceImportsPage = lazy(() =>
  import("./pages/FinanceImportsPage").then((module) => ({
    default: module.FinanceImportsPage,
  })),
);
const FinanceOrderDetailsPage = lazy(() =>
  import("./pages/FinanceOrderDetailsPage").then((module) => ({
    default: module.FinanceOrderDetailsPage,
  })),
);
const FinanceStoresPage = lazy(() =>
  import("./pages/FinanceStoresPage").then((module) => ({
    default: module.FinanceStoresPage,
  })),
);
const OrderDetailsPage = lazy(() =>
  import("./pages/OrderDetailsPage").then((module) => ({
    default: module.OrderDetailsPage,
  })),
);
const SalesDashboardPage = lazy(() =>
  import("./pages/SalesDashboardPage").then((module) => ({
    default: module.SalesDashboardPage,
  })),
);
const StoreRankingPage = lazy(() =>
  import("./pages/StoreRankingPage").then((module) => ({
    default: module.StoreRankingPage,
  })),
);
const StoreSettlementPage = lazy(() =>
  import("./pages/StoreSettlementPage").then((module) => ({
    default: module.StoreSettlementPage,
  })),
);
const StoreInvoicePage = lazy(() =>
  import("./pages/StoreInvoicePage").then((module) => ({
    default: module.StoreInvoicePage,
  })),
);
const StoreInvoiceStatusPage = lazy(() =>
  import("./pages/StoreInvoiceStatusPage").then((module) => ({
    default: module.StoreInvoiceStatusPage,
  })),
);

function readLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

interface AuthGateProps {
  children: (props: { user: AdminUser; onLogout: () => void }) => ReactNode;
  isDemoMode: boolean;
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

const pageKeyByPath: Array<[string, string]> = [
  ["/admin/clue-allocation/headquarters", "D08"],
  ["/admin/clue-allocation/records", "D07"],
  ["/admin/clue-allocation/trial", "D06"],
  ["/admin/clue-allocation/rules", "D05"],
  ["/admin/clue-allocation", "D05"],
  ["/admin/product-types", "D04"],
  ["/admin/feedback", "D09"],
  ["/admin/accounts", "D02"],
  ["/admin/rules", "D03"],
  ["/rule-admin", "D03"],
  ["/admin/sync", "D10"],
  ["/sync-admin", "D10"],
  ["/admin", "D01"],
  ["/finance/promotion", "D01"],
  ["/finance/management", "D01"],
  ["/finance/orders/promotion", "D01"],
  ["/finance/orders/management", "D01"],
  ["/finance/stores", "D01"],
  ["/finance/disputes", "D01"],
  ["/finance/imports", "D01"],
  ["/clues/details", "A02"],
  ["/clues", "A01"],
  ["/ranking", "B01"],
  ["/settlement", "B02"],
  ["/settlement/invoice/status", "B02"],
  ["/settlement/invoice", "B02"],
  ["/details", "B03"],
  ["/invoice", "B02"],
  ["/sales", "C01"],
];

function firstAccessiblePath(user: AdminUser): string {
  const preferred = ["/ranking", "/clues", "/settlement", "/details", "/sales", "/admin"];
  return preferred.find((path) => hasPageAccess(user, path)) ?? "/login";
}

export function hasPageAccess(user: AdminUser, pathname: string): boolean {
  const match = pageKeyByPath.find(
    ([path]) => pathname === path,
  );
  return match
    ? user.page_keys.includes(match[1])
    : pathname === "/" || pathname === "/login";
}

function AuthGate({ children, isDemoMode, pathname }: AuthGateProps) {
  const [checking, setChecking] = useState(true);
  const [user, setUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    setChecking(true);
    setUser(null);
    fetchAdminSession({ allowDemoIdentity: isDemoMode })
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
  }, [isDemoMode]);

  const handleLogout = () => {
    logoutAdmin().catch(() => undefined);
    setUser(null);
  };

  const handleAuthenticated = (nextUser: AdminUser) => {
    setUser(nextUser);
    if (
      (pathname === "/login" || pathname.startsWith("/auth/")) &&
      pathname !== "/auth/cli/authorize" &&
      pathname !== "/auth/mcp/authorize"
    ) {
      window.history.pushState(null, "", firstAccessiblePath(nextUser));
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

function PageForbiddenPage() {
  return (
    <div className="page-stack">
      <section className="content-section">
        <div className="section-title">
          <div>
            <p className="eyebrow">无权访问</p>
            <h1>当前账号没有此页面权限</h1>
            <p>页面菜单、直接地址和接口使用同一套权限结果，请联系管理员调整。</p>
          </div>
        </div>
      </section>
    </div>
  );
}

function PageLoadingFallback() {
  return (
    <main className="page-stack">
      <section aria-live="polite" className="content-section" role="status">
        正在加载页面...
      </section>
    </main>
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

  useEffect(() => {
    if (location.pathname === "/invoice") {
      window.history.replaceState(null, "", "/settlement/invoice");
      setLocation(readLocation());
      return;
    }
    if (location.pathname === "/finance") {
      window.history.replaceState(null, "", "/finance/promotion");
      setLocation(readLocation());
    }
  }, [location.pathname]);

  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const isDemoMode = CLUE_DEMO_MODE && isClueDemoPathname(location.pathname);

  return (
    <Suspense fallback={<PageLoadingFallback />}>
      <AuthGate
        isDemoMode={isDemoMode}
        key={isDemoMode ? "clue-demo" : "live"}
        pathname={location.pathname}
      >
        {({ user, onLogout }) => {
        if (location.pathname === "/auth/cli/authorize") {
          return <CliAuthorizePage currentUser={user} search={location.search} />;
        }
        if (location.pathname === "/auth/mcp/authorize") {
          return <McpAuthorizePage currentUser={user} search={location.search} />;
        }

        const clueAllocationSubview = clueAllocationSubviewFromPath(location.pathname);
        const adminPage =
          location.pathname === "/admin" ? (
            <AdminHomePage />
          ) : location.pathname === "/admin/accounts" ? (
            <AdminAccountsPage currentUser={user} />
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
              isDemoMode={isDemoMode}
              onLogout={isDemoMode ? undefined : onLogout}
            >
              {hasPageAccess(user, location.pathname) ? (
                adminPage
              ) : (
                <PageForbiddenPage />
              )}
            </Shell>
          );
        }

        if (location.pathname === "/" || location.pathname === "/login") {
          return <HomePage />;
        }

        const page =
          location.pathname === "/settlement" ? (
            <StoreSettlementPage currentUser={user} searchParams={searchParams} />
          ) : location.pathname === "/settlement/invoice/status" ? (
            <StoreInvoiceStatusPage currentUser={user} searchParams={searchParams} />
          ) : location.pathname === "/settlement/invoice" ? (
            <StoreInvoicePage currentUser={user} searchParams={searchParams} />
          ) : location.pathname === "/finance/promotion" ? (
            <FinanceFeePage feeDirection="PROMOTION" searchParams={searchParams} />
          ) : location.pathname === "/finance/management" ? (
            <FinanceFeePage feeDirection="MANAGEMENT" searchParams={searchParams} />
          ) : location.pathname === "/finance/orders/promotion" ? (
            <FinanceOrderDetailsPage feeDirection="PROMOTION" searchParams={searchParams} />
          ) : location.pathname === "/finance/orders/management" ? (
            <FinanceOrderDetailsPage feeDirection="MANAGEMENT" searchParams={searchParams} />
          ) : location.pathname === "/finance/stores" ? (
            <FinanceStoresPage currentUser={user} searchParams={searchParams} />
          ) : location.pathname === "/finance/disputes" ? (
            <FinanceDisputesPage searchParams={searchParams} />
          ) : location.pathname === "/finance/imports" ? (
            <FinanceImportsPage searchParams={searchParams} />
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
            isDemoMode={isDemoMode}
            onLogout={isDemoMode ? undefined : onLogout}
          >
            {hasPageAccess(user, location.pathname) ? page : <PageForbiddenPage />}
          </Shell>
        );
        }}
      </AuthGate>
    </Suspense>
  );
}
