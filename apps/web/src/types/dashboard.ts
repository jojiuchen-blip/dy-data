export interface ApiDefinition {
  key: string;
  label: string;
  description: string;
}

export interface ApiMeta {
  generated_at: string;
  source: string;
}

export interface ApiResponse<T> {
  data: T;
  definitions?: ApiDefinition[];
  meta: ApiMeta;
}

export type UserRole = "admin" | "viewer" | "store";
export type UserStatus = "active" | "disabled";

export interface AdminUser {
  username: string;
  user_id?: string | null;
  display_name?: string | null;
  role: UserRole;
  status: UserStatus;
  is_initialized: boolean;
  store_ids: string[];
}

export interface AccountStoreScope {
  store_id: string;
  store_name: string;
}

export interface AccountRow {
  user_id: string;
  username: string;
  external_account_id: string | null;
  display_name: string;
  role: UserRole;
  status: UserStatus;
  is_initialized: boolean;
  stores: AccountStoreScope[];
  created_at: string | null;
  updated_at: string | null;
}

export interface AccountListData {
  rows: AccountRow[];
}

export interface AccountUpsertPayload {
  username: string;
  display_name: string;
  role: UserRole;
  status: UserStatus;
  external_account_id?: string | null;
  store_ids: string[];
  password?: string | null;
  password_confirm?: string | null;
}

export interface AccountPasswordPayload {
  password: string;
  password_confirm: string;
}

export interface AccountSelfServicePayload {
  external_account_id: string;
  certified_subject_name: string;
  username: string;
  password: string;
  password_confirm: string;
  display_name?: string | null;
}

export interface JobRun {
  job_id: string;
  job_name: string;
  status: "running" | "success" | "failed" | "queued";
  started_at: string | null;
  finished_at: string | null;
  success_count: number;
  failed_count: number;
  error_message: string | null;
  metadata_json?: {
    source_window?: SyncWindow;
    phases?: Record<
      string,
      {
        name: string;
        fetched?: number;
        upserted?: number;
        skipped?: number;
        failed?: number;
      }
    >;
  };
}

export interface SyncWindow {
  start: string;
  end: string;
  timezone: string;
}

export interface SyncConfigData {
  history_start: string;
  history_end: string;
  history_chunk_days: number;
  rolling_days: number;
  interval_seconds: number;
  auto_sync_enabled: boolean;
  backfill_skip_completed: boolean;
}

export interface SyncProgressData {
  total_windows: number;
  completed_windows: number;
  running_jobs: number;
  failed_jobs: number;
  latest_completed_window: SyncWindow | null;
}

export interface SyncAdminData {
  config: SyncConfigData;
  progress: SyncProgressData;
  schedule: SyncScheduleData;
  jobs: JobRun[];
}

export interface SyncConfigUpdate {
  history_start?: string;
  history_end?: string;
  history_chunk_days?: number;
  rolling_days?: number;
  interval_seconds?: number;
  auto_sync_enabled?: boolean;
  backfill_skip_completed?: boolean;
}

export interface SyncScheduleData {
  auto_sync_enabled: boolean;
  latest_successful_sync_at: string | null;
  next_scheduled_sync_at: string | null;
}

export type ManualSyncTarget =
  | "all"
  | "orders"
  | "verify_records"
  | "shop_pois"
  | "aweme_bindings"
  | "backend_aweme_export"
  | "settlement";

export interface ManualSyncResult {
  job_id: string;
  target: ManualSyncTarget;
  window: SyncWindow;
}

export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface StoreOption {
  store_id: string;
  store_name: string;
}

export interface SelectOption {
  value: string;
  label: string;
}

export interface FilterMetaData {
  stores: StoreOption[];
  product_types: string[];
  sale_months: string[];
  verify_months: string[];
}

export interface StoreRankingRow {
  rank: number;
  store_id: string;
  store_name: string;
  sales_order_count: number;
  self_sold_self_verified_count: number;
  self_sold_other_verified_count: number;
  other_sold_self_verified_count: number;
  self_verify_income_cent: number;
  effective_commission_income_cent: number;
}

export interface StoreRankingTotals {
  sales_order_count: number;
  self_verify_income_cent: number;
  effective_commission_income_cent: number;
}

export interface StoreRankingData {
  month: string;
  product_type: string;
  limit: number;
  totals: StoreRankingTotals;
  rows: StoreRankingRow[];
}

export interface MonthlySummaryData {
  store: StoreOption;
  month: string;
  product_type: string;
  metrics: {
    estimated_receivable_commission_cent: number;
    commissionable_total_cent: number;
    estimated_payable_commission_cent: number;
  };
}

export interface ReceivableCommissionRow {
  product_type: string;
  verified_coupon_count: number;
  paid_amount_cent: number;
  commission_rate: number;
  commissionable_total_cent: number;
  estimated_receivable_commission_cent: number;
}

export interface PayableCommissionRow {
  product_type: string;
  verified_coupon_count: number;
  paid_amount_cent: number;
  commission_rate: number;
  payable_commission_cent: number;
}

export interface NonCommissionOrderRow {
  product_type: string;
  verified_coupon_count: number;
  paid_amount_cent: number;
}

export interface CommissionTablesData {
  store: StoreOption;
  month: string;
  product_type: string;
  tables: {
    receivable_commissions: ReceivableCommissionRow[];
    payable_commissions: PayableCommissionRow[];
    non_commission_orders: NonCommissionOrderRow[];
  };
}

export interface MonthlySettlementData extends MonthlySummaryData {
  tables: CommissionTablesData["tables"];
  source?: "contract-mock" | "detail-derived";
}

export interface OrderDetail {
  order_id: string;
  coupon_id: string;
  sku_id: string;
  owner_account_id: string;
  owner_account_name: string;
  product_type: string;
  sale_store_id: string;
  sale_store_name: string;
  sale_store_subject_name: string;
  sale_month: string;
  sale_time: string;
  is_verified: boolean;
  verify_store_id: string;
  verify_store_name: string;
  verify_store_subject_name: string;
  verify_month: string;
  verify_time: string;
  relation_type: "same_store" | "cross_store" | "unverified" | "unknown" | "";
  is_commissionable: boolean | null;
  paid_amount_cent: number;
  commission_rate: number;
  receivable_commission_cent: number;
  payable_commission_cent: number;
}

export interface DetailFilters {
  product_type?: string;
  sale_store_id?: string;
  exclude_sale_store_id?: string;
  sale_month?: string;
  is_verified?: string;
  verify_store_id?: string;
  exclude_verify_store_id?: string;
  verify_month?: string;
  relation_type?: string;
  is_commissionable?: string;
  q?: string;
}

export interface SkuProductCommissionRule {
  sku_id: string;
  product_name?: string;
  product_type: string;
  commission_rate: number;
  is_service_product?: boolean;
  order_count?: number;
  verified_coupon_count?: number;
}

export interface SkuRuleListData {
  rows: SkuProductCommissionRule[];
  pagination: Pagination;
}

export interface SkuRuleLookupData {
  rows: SkuProductCommissionRule[];
  missing_sku_ids: string[];
  duplicate_sku_ids: string[];
}

export interface SkuRuleUpdateResult {
  updated_count: number;
  job_id: string;
  rebuild_status: "queued" | "running" | "success" | "failed";
  settlement_detail_count?: number | null;
  settlement_monthly_count?: number | null;
}

export interface NonCommissionOwnerAccount {
  owner_account_name: string;
  normalized_owner_account_name: string;
  is_active: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
}

export interface NonCommissionOwnerAccountListData {
  rows: NonCommissionOwnerAccount[];
}

export interface NonCommissionOwnerAccountUpdateResult {
  rows: NonCommissionOwnerAccount[];
  updated_count: number;
  job_id: string;
  rebuild_status: "queued" | "running" | "success" | "failed";
}

export interface CommissionRuleSkuSummary {
  sku_id: string;
  product_name: string;
  commission_rate: number;
}

export interface CommissionRulesSummaryData {
  non_commission_owner_accounts: string[];
  commission_skus: CommissionRuleSkuSummary[];
}

export interface SettlementViewData extends MonthlySettlementData {
  source: "contract-mock" | "detail-derived";
}

export interface OrderDetailsData {
  rows: OrderDetail[];
  pagination: Pagination;
}

export interface ClueOverviewFilters {
  assigned_store_id?: string;
  assigned_date_start?: string;
  assigned_date_end?: string;
  lead_status?: string;
  round_status?: string;
  product_type?: string;
  city?: string;
}

export interface ClueFilterMetadata {
  assigned_stores: StoreOption[];
  assigned_cities: string[];
  product_types: string[];
  lead_statuses: string[];
  round_statuses: string[];
}

export interface ClueOverviewMetrics {
  total_clues: number;
  active_clues: number;
  follow_rate: number;
  follow_success_rate: number;
  self_store_verify_rate: number;
  pending_reassign_count: number;
}

export interface ClueAssignmentRound {
  assignment_round_id: string;
  order_id: string;
  round_no: number;
  lead_status: string;
  order_current_status: string;
  current_assignment_round_id: string | null;
  current_round_no: number;
  current_round_status: string;
  current_assigned_store_id: string | null;
  current_assigned_store_name: string | null;
  is_current_round: boolean;
  round_effective_status: "active" | "inactive";
  round_status: string;
  assigned_at: string | null;
  expires_at: string | null;
  remaining_reassign_seconds: number | null;
  assigned_store_id: string | null;
  assigned_store_name: string | null;
  phone_masked: string;
  product_type: string | null;
  author_nickname: string | null;
  followed_at: string | null;
  follow_result: string;
  reassign_reason: string | null;
  reassigned_at: string | null;
  verified_store_id: string | null;
  verified_store_name: string | null;
  verified_at: string | null;
  is_self_store_verified: boolean;
}

export interface ClueAssignmentRoundData {
  rows: ClueAssignmentRound[];
  pagination: Pagination;
}

export interface ClueOrderDetail {
  order_id: string;
  canonical_clue_id: string | null;
  lead_status: string;
  phone_masked: string;
  product_id: string | null;
  product_name: string | null;
  product_type: string | null;
  author_nickname: string | null;
  assigned_city: string | null;
  assigned_province: string | null;
  rounds: ClueAssignmentRound[];
}

export interface CluePhoneReveal {
  order_id: string;
  phone: string;
  phone_masked: string;
}

export interface ClueReassignRuleData {
  reassign_sla_hours: number | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface ClueReassignRuleUpdate {
  reassign_sla_hours: number | null;
}

export interface ClueRebuildResult {
  job_id?: string | null;
  status?: "queued" | "running" | "success" | "failed";
  rebuilt_order_count?: number | null;
  rebuilt_round_count?: number | null;
}
