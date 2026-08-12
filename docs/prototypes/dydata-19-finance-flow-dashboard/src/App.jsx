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

export function App({ initialRole = "store", initialPage, initialScenario }) {
  const [role, setRole] = useState(initialRole);
  const [page, setPage] = useState(initialPage ?? (initialRole === "store" ? "store-bills" : "finance-promotion"));
  const [scenarioId, setScenarioId] = useState(initialScenario ?? (initialRole === "store" ? "F01" : "F05"));
  const [theme, setTheme] = useState("light");
  const [financeOrderDirection, setFinanceOrderDirection] = useState("推广服务费");

  const pages = role === "store" ? storePages : financePages;
  const ActivePage = pages[page]?.Component ?? Object.values(pages)[0].Component;
  const scenario = scenarioFixtures[scenarioId];

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const pageTitle = useMemo(() => pages[page]?.label ?? Object.values(pages)[0].label, [page, pages]);

  function applyScenario(nextScenario) {
    setRole(nextScenario.role);
    setPage(nextScenario.page);
  }

  function changeRole(nextRole) {
    setRole(nextRole);
    setScenarioId(nextRole === "store" ? "F01" : "F05");
  }

  function navigate(nextPage, options = {}) {
    if (nextPage === "finance-orders" && options.direction) {
      setFinanceOrderDirection(options.direction);
    }
    setPage(nextPage);
  }

  return (
    <AppShell
      role={role}
      pages={pages}
      page={page}
      theme={theme}
      onRoleChange={changeRole}
      onPageChange={setPage}
      onThemeChange={setTheme}
    >
      <div className="workspace-topline">
        <span>{role === "store" ? "门店结算" : "财务管理"}</span>
        <i aria-hidden="true">/</i>
        <strong>{pageTitle}</strong>
        <span className="workspace-topline__version">DYDATA-19 · Mock</span>
      </div>
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

export { financePages, storePages };
