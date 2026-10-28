// Production page rendered with synthetic API fixtures supplied by browser QA.
import { createRoot } from "react-dom/client";
import { ClueCenterPage } from "../src/pages/ClueCenterPage";
import { DashboardPublicationProvider } from "../src/hooks/PublicationContext";
import type { AdminUser } from "../src/types/dashboard";
import "../src/styles.css";
const user: AdminUser = { username: "synthetic-qa", role: "admin", status: "active",
  is_initialized: true, store_ids: [], store_scope_mode: "all", page_keys: [],
  can_manage_accounts: true, can_manage_global_settings: true };
createRoot(document.getElementById("root")!).render(<DashboardPublicationProvider>
  <ClueCenterPage currentUser={user} searchParams={new URLSearchParams()} view="details" />
</DashboardPublicationProvider>);
