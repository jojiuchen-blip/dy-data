// Render the production components against the isolated real API, including the
// legacy governance panel which has no current top-level application route.
import { createRoot } from "react-dom/client";
import { fetchSkuFeeRuleImports } from "../src/api/client";
import { AdminSkuGovernancePanel } from "../src/components/AdminSkuGovernancePanel";
import { AdminSkuRuleImportDrawer } from "../src/components/AdminSkuRuleImportDrawer";
import { DashboardPublicationProvider } from "../src/hooks/PublicationContext";
import { AdminProductTypeVisibilityPage } from "../src/pages/AdminProductTypeVisibilityPage";
import { StoreSettlementPage } from "../src/pages/StoreSettlementPage";
import type { AdminUser } from "../src/types/dashboard";
import "../src/styles.css";

const params = new URLSearchParams(location.search);
const user: AdminUser = { username: "ui104", role: "admin", status: "active",
  is_initialized: true, store_ids: [], store_scope_mode: "all", page_keys: [] };
const surface = params.get("surface");
const batches = surface === "drawer" ? (await fetchSkuFeeRuleImports({ pageSize: 10 })).data.list : [];
const content = surface === "drawer"
  ? <AdminSkuRuleImportDrawer open batches={batches} initialBatch={batches[0] ?? null} onChanged={async () => {}} onClose={() => {}} />
  : surface === "governance" ? <AdminSkuGovernancePanel />
  : surface === "product" ? <AdminProductTypeVisibilityPage />
  : <DashboardPublicationProvider><StoreSettlementPage currentUser={user} searchParams={params} /></DashboardPublicationProvider>;
createRoot(document.getElementById("root")!).render(content);
