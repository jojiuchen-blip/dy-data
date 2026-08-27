import type { AdminUser } from "../types/dashboard";

export function isClueDemoMode(
  env: Pick<ImportMetaEnv, "DEV" | "VITE_DEMO_MODE">,
): boolean {
  return env.DEV && env.VITE_DEMO_MODE === "true";
}

export const CLUE_DEMO_MODE =
  import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE === "true";

export function isClueDemoPathname(pathname: string): boolean {
  return pathname === "/clues"
    || pathname === "/clues/details"
    || pathname === "/admin/clue-allocation"
    || pathname.startsWith("/admin/clue-allocation/");
}

export const CLUE_DEMO_ADMIN_USER: AdminUser = {
  username: "demo_admin",
  user_id: "DEMO-USER-ADMIN",
  display_name: "演示最高管理员",
  role: "highest_admin",
  status: "active",
  is_initialized: true,
  store_ids: [],
  store_scope_mode: "all",
  page_keys: [
    "A01",
    "A02",
    "D05",
    "D06",
    "D07",
    "D08",
  ],
  is_highest_admin: true,
};
