import { useEffect, useMemo, useState } from "react";
import { AppShell } from "./components/AppShell.jsx";
import { FinanceTimeline } from "./components/FinanceTimeline.jsx";
import { ScenarioSwitcher } from "./components/ScenarioSwitcher.jsx";
import { scenarioFixtures } from "./data/financeData.js";
import { StoreBillsPage } from "./pages/StoreBillsPage.jsx";
import { StoreHistoryPage } from "./pages/StoreHistoryPage.jsx";
import { StoreInvoicesPage } from "./pages/StoreInvoicesPage.jsx";
import { FinanceDisputesPage } from "./pages/FinanceDisputesPage.jsx";
import { FinanceImportsPage } from "./pages/FinanceImportsPage.jsx";
import { FinanceManagementPage } from "./pages/FinanceManagementPage.jsx";
import { FinancePromotionPage } from "./pages/FinancePromotionPage.jsx";
import { FinanceBaseInfoPage } from "./pages/FinanceBaseInfoPage.jsx";
import { FinanceOrdersPage } from "./pages/FinanceOrderDetailsPage.jsx";

const storePages = {
  "store-bills": { label: "单店分账", icon: "calendar", Component: StoreBillsPage },
  "store-invoices": { label: "推广服务费开票", icon: "document", Component: StoreInvoicesPage },
  "store-history": { label: "发票状态查看", icon: "history", Component: StoreHistoryPage },
};

const financePages = {
  "finance-promotion": { label: "推广服务费", icon: "wallet", Component: FinancePromotionPage },
  "finance-management": { label: "管理服务费", icon: "bill", Component: FinanceManagementPage },
  "finance-orders": { label: "订单明细", icon: "document", Component: FinanceOrdersPage },
  "finance-base-info": { label: "门店基础信息", icon: "shop", Component: FinanceBaseInfoPage },
  "finance-disputes": { label: "账单异议", icon: "danger", Component: FinanceDisputesPage },
  "finance-imports": { label: "导入记录", icon: "document", Component: FinanceImportsPage },
};

const pageRoutes = {
  "store-bills": "/settlement",
  "store-invoices": "/settlement/invoice",
  "store-history": "/settlement/invoice",
  "finance-promotion": "/finance/promotion",
  "finance-management": "/finance/management",
  "finance-orders": "/finance/orders/promotion",
  "finance-base-info": "/finance/stores",
  "finance-disputes": "/finance/disputes",
  "finance-imports": "/finance/imports",
};

function routeFromLocation() {
  const path = window.location.pathname;
  if (path === "/settlement/invoice") return { role: "store", page: "store-invoices" };
  if (path === "/settlement") return { role: "store", page: "store-bills" };
  if (path === "/finance/management") return { role: "finance", page: "finance-management" };
  if (path === "/finance/orders/management") return { role: "finance", page: "finance-orders", direction: "管理服务费" };
  if (path === "/finance/orders/promotion") return { role: "finance", page: "finance-orders", direction: "推广服务费" };
  if (path === "/finance/stores") return { role: "finance", page: "finance-base-info" };
  if (path === "/finance/disputes") return { role: "finance", page: "finance-disputes" };
  if (path === "/finance/imports") return { role: "finance", page: "finance-imports" };
  if (path.startsWith("/finance")) return { role: "finance", page: "finance-promotion" };
  return { role: "store", page: "store-bills" };
}

function routeForPage(page, direction) {
  if (page === "finance-orders") {
    return direction === "管理服务费" ? "/finance/orders/management" : "/finance/orders/promotion";
  }
  if (page === "store-history") return "/settlement/invoice?view=history";
  return pageRoutes[page] ?? "/settlement";
}

export function App({ initialRole, initialPage, initialScenario }) {
  const initialRoute = routeFromLocation();
  const resolvedRole = initialRole ?? initialRoute.role;
  const resolvedPage = initialPage ?? (initialRole ? (initialRole === "store" ? "store-bills" : "finance-promotion") : initialRoute.page);
  const [role, setRole] = useState(resolvedRole);
  const [page, setPage] = useState(resolvedPage);
  const [scenarioId, setScenarioId] = useState(initialScenario ?? (resolvedRole === "store" ? "F01" : "F05"));
  const [theme, setTheme] = useState("light");
  const [financeOrderDirection, setFinanceOrderDirection] = useState(initialPage || initialRole ? "推广服务费" : (initialRoute.direction ?? "推广服务费"));

  const pages = role === "store" ? storePages : financePages;
  const ActivePage = pages[page]?.Component ?? Object.values(pages)[0].Component;
  const scenario = scenarioFixtures[scenarioId];

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    function syncFromHistory() {
      const next = routeFromLocation();
      setRole(next.role);
      setPage(next.page);
      if (next.direction) setFinanceOrderDirection(next.direction);
    }
    window.addEventListener("popstate", syncFromHistory);
    return () => window.removeEventListener("popstate", syncFromHistory);
  }, []);

  const pageTitle = useMemo(() => pages[page]?.label ?? Object.values(pages)[0].label, [page, pages]);

  function applyScenario(nextScenario) {
    setRole(nextScenario.role);
    navigate(nextScenario.page);
  }

  function changeRole(nextRole) {
    setRole(nextRole);
    setScenarioId(nextRole === "store" ? "F01" : "F05");
    const nextPage = nextRole === "store" ? "store-bills" : "finance-promotion";
    setPage(nextPage);
    window.history.pushState({}, "", routeForPage(nextPage));
  }

  function navigate(nextPage, options = {}) {
    const nextDirection = nextPage === "finance-orders" ? (options.direction ?? financeOrderDirection) : financeOrderDirection;
    if (nextPage === "finance-orders") setFinanceOrderDirection(nextDirection);
    setPage(nextPage);
    window.history.pushState({}, "", routeForPage(nextPage, nextDirection));
  }

  return (
    <AppShell
      role={role}
      pages={pages}
      page={page}
      theme={theme}
      onRoleChange={changeRole}
      onPageChange={navigate}
      onThemeChange={setTheme}
    >
      <div className="workspace-topline">
        <span>{role === "store" ? "门店结算" : "财务管理"}</span>
        <i aria-hidden="true">/</i>
        <strong>{pageTitle}</strong>
        <span className="workspace-topline__version">DYDATA-19 · Mock</span>
      </div>
      <aside className="prototype-boundary" role="note" aria-label="原型边界">
        <strong>需求讨论原型</strong>
        <span>非生产能力 · 非权威契约 · 不会提交、审核、打款或修改业务状态</span>
      </aside>
      <FinanceTimeline scenario={scenario} />
      <ScenarioSwitcher
        value={scenarioId}
        role={role}
        onChange={setScenarioId}
        onApply={applyScenario}
      />
      <ActivePage
        scenario={scenario}
        onNavigate={navigate}
        direction={financeOrderDirection}
        onDirectionChange={setFinanceOrderDirection}
      />
    </AppShell>
  );
}

export { financePages, pageRoutes, storePages };
