import type { AdminUser } from "../types/dashboard";

export function isClueDemoMode(
  env: Pick<ImportMetaEnv, "DEV" | "VITE_DEMO_MODE">,
): boolean {
  return env.DEV && env.VITE_DEMO_MODE === "true";
}

export const CLUE_DEMO_MODE =
  import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE === "true";

export const CLUE_DEMO_ADMIN_USER: AdminUser = {
  username: "demo_admin",
  user_id: "DEMO-USER-ADMIN",
  display_name: "演示最高管理员",
  role: "admin",
  status: "active",
  is_initialized: true,
  store_ids: [],
  is_highest_admin: true,
};
