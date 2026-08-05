import { useEffect, useMemo, useState } from "react";
import { AppShell } from "./components/AppShell.jsx";
import { FinanceTimeline } from "./components/FinanceTimeline.jsx";
import { ScenarioSwitcher } from "./components/ScenarioSwitcher.jsx";
import { scenarioFixtures } from "./data/financeData.js";
import { StoreBillsPage } from "./pages/StoreBillsPage.jsx";
import { StoreHistoryPage } from "./pages/StoreHistoryPage.jsx";
import { StoreInvoicesPage } from "./pages/StoreInvoicesPage.jsx";
import { FinanceDisputesPage } from "./pages/FinanceDisputesPage.jsx";
import { FinanceHomePage } from "./pages/FinanceHomePage.jsx";
import { FinanceImportsPage } from "./pages/FinanceImportsPage.jsx";
import { FinanceManagementPage } from "./pages/FinanceManagementPage.jsx";
import { FinancePromotionPage } from "./pages/FinancePromotionPage.jsx";

const storePages = {
  "store-bills": { label: "月度账单", icon: "calendar", Component: StoreBillsPage },
  "store-invoices": { label: "推广服务费开票", icon: "document", Component: StoreInvoicesPage },
  "store-history": { label: "发票与调整记录", icon: "history", Component: StoreHistoryPage },
};

const financePages = {
  "finance-home": { label: "财务", icon: "home", Component: FinanceHomePage },
  "finance-promotion": { label: "推广服务费", icon: "wallet", Component: FinancePromotionPage },
  "finance-management": { label: "管理服务费", icon: "bill", Component: FinanceManagementPage },
  "finance-disputes": { label: "账单异议", icon: "danger", Component: FinanceDisputesPage },
  "finance-imports": { label: "导入记录", icon: "document", Component: FinanceImportsPage },
};

export function App({ initialRole = "store", initialPage }) {
  const [role, setRole] = useState(initialRole);
  const [page, setPage] = useState(initialPage ?? (initialRole === "store" ? "store-bills" : "finance-home"));
  const [scenarioId, setScenarioId] = useState(initialRole === "store" ? "F01" : "F05");
  const [theme, setTheme] = useState("light");

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

  return (
    <AppShell
      role={role}
      pages={pages}
      page={page}
      theme={theme}
      onRoleChange={setRole}
      onPageChange={setPage}
      onThemeChange={setTheme}
    >
      <div className="workspace-topline">
        <span>{role === "store" ? "门店结算" : "财务管理"}</span>
        <i aria-hidden="true">/</i>
        <strong>{pageTitle}</strong>
        <span className="workspace-topline__version">DYDATA-19 · Mock V1</span>
      </div>
      <FinanceTimeline scenario={scenario} />
      <ScenarioSwitcher
        value={scenarioId}
        onChange={setScenarioId}
        onApply={applyScenario}
      />
      <ActivePage scenario={scenario} onNavigate={setPage} />
    </AppShell>
  );
}

export { financePages, storePages };
