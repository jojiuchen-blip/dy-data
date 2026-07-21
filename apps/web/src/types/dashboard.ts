export interface ApiDefinition {
  key: string;
  label: string;
  description: string;
}

export interface ApiMeta {
  generated_at?: string;
  generatedAt?: string;
  requestId?: string;
  source?: string;
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
  is_highest_admin?: boolean;
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

export interface UnactivatedStoreAccountRow {
  store_id: string;
  store_name: string;
  certified_subject_name: string;
  account_ids: string[];
  poi_ids: string[];
  poi_names: string[];
}

export interface UnactivatedStoreAccountListData {
  rows: UnactivatedStoreAccountRow[];
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

export type FeedbackCategory = "experience" | "data" | "feature" | "other";

export interface FeedbackSubmissionPayload {
  category: FeedbackCategory;
  content: string;
  contact?: string | null;
  page_path?: string | null;
}

export interface FeedbackSubmissionReceipt {
  feedback_id: string;
  category: FeedbackCategory;
  status: "new";
  created_at: string;
}

export type FeedbackStatus = "new" | "reviewed" | "resolved" | "ignored";

export interface FeedbackRow {
  feedback_id: string;
  category: FeedbackCategory;
  content: string;
  contact: string | null;
  page_path: string | null;
  user_id: string | null;
  username: string | null;
  user_role: string | null;
  status: FeedbackStatus;
  created_at: string;
}

export interface FeedbackListData {
  rows: FeedbackRow[];
  pagination: Pagination;
  status_counts: Record<string, number>;
}

export interface AccountSelfServicePayload {
  external_account_id: string;
  certified_subject_name: string;
  username: string;
  password: string;
  password_confirm: string;
  display_name?: string | null;
}

export interface AccountActivationCheckPayload {
  external_account_id: string;
  poi_id: string;
}

export type AccountActivationStatus = "invalid" | "activated" | "ready";

export interface AccountActivationCheckData {
  status: AccountActivationStatus;
}

export interface AccountActivationPayload extends AccountActivationCheckPayload {
  username: string;
  password: string;
  password_confirm: string;
}

export interface AccountPasswordResetPayload
  extends AccountActivationCheckPayload {
  password: string;
  password_confirm: string;
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
  worker_status: SyncWorkerStatusData;
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

export interface SyncWorkerStatusData {
  mode: string;
  auto_sync_enabled: boolean;
  interval_seconds: number;
  rolling_days: number;
  history_chunk_days: number;
  run_on_start: boolean;
  run_once: boolean;
  chunk_max_attempts: number;
  disabled_poll_seconds: number;
  active_job: JobRun | null;
  latest_success: JobRun | null;
  latest_failure: JobRun | null;
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
  product_scopes?: string[];
  product_scope_type_map?: Record<string, string[]>;
  product_types: string[];
  default_product_type: string;
  sale_months: string[];
  verify_months: string[];
}

export type FeeDirection = "PROMOTION" | "MANAGEMENT";
export type PeriodType = "MONTHLY" | "CUMULATIVE";
export type RankingSortBy =
  | "SALES_AMOUNT"
  | "VERIFIED_AMOUNT"
  | "PROMOTION_FEE"
  | "MANAGEMENT_FEE"
  | "NET_SETTLEMENT_REFERENCE";
export type SortOrder = "ASC" | "DESC";

export interface SettlementFilterMetaData {
  stores: Array<{ storeId: string; storeName: string }>;
  productScopes: string[];
  productScopeTypeMap: Record<string, string[]>;
  productTypes: string[];
  defaultProductType: string;
  saleMonths: string[];
  verifyMonths: string[];
  statementMonths: string[];
  periodTypes: PeriodType[];
  feeDirections: FeeDirection[];
  formalPeriodStartMonth: string;
  timezone: string;
}

export interface SettlementStoreRankingRow {
  rank: number;
  storeId: string;
  storeName: string;
  salesOrderCount: number;
  salesAmountCent: number;
  verifiedOrderCount: number;
  verifiedAmountCent: number;
  promotionNetFeeCent: number;
  managementNetFeeCent: number;
  netSettlementReferenceCent: number;
}

export interface SettlementStoreRankingData {
  periodType: PeriodType;
  periodKey: string;
  productScope: string;
  productType: string;
  scopeMode: "AUTHORIZED" | "GLOBAL_TOP_20_EXCEPTION";
  totals: Omit<SettlementStoreRankingRow, "rank" | "storeId" | "storeName">;
  list: SettlementStoreRankingRow[];
  total: number;
  page: number;
  pageSize: number;
}

export interface SettlementStatementSummary {
  statementId: string;
  statementStatus: "GENERATING" | "PENDING_CONFIRMATION" | "CONFIRMED" | "LOCKED";
  confirmedAt?: string | null;
  lockedAt?: string | null;
  lockVersion?: string | null;
}

export interface SettlementStatementLine {
  statementLineId?: string | null;
  feeDirection: FeeDirection;
  productScope: string;
  productType: string;
  originalEntryCount: number;
  adjustmentEntryCount: number;
  originalBaseCent: number;
  adjustmentBaseCent: number;
  netBaseCent: number;
  originalFeeCent: number;
  adjustmentFeeCent: number;
  netFeeCent: number;
  minFeeRate?: string | null;
  maxFeeRate?: string | null;
  ruleVersionCount: number;
  feeRates: string[];
  ruleVersions: string[];
}

export interface SettlementMonthlyData {
  store: { storeId: string; storeName: string };
  month: string;
  productScope: string;
  productType: string;
  isFormalPeriod: boolean;
  statement?: SettlementStatementSummary | null;
  metrics: {
    salesOrderCount: number;
    salesAmountCent: number;
    verifiedOrderCount: number;
    verifiedAmountCent: number;
    promotionBaseCent: number;
    promotionOriginalFeeCent: number;
    promotionAdjustmentFeeCent: number;
    promotionNetFeeCent: number;
    managementBaseCent: number;
    managementOriginalFeeCent: number;
    managementAdjustmentFeeCent: number;
    managementNetFeeCent: number;
    netSettlementReferenceCent: number;
  };
  lines: SettlementStatementLine[];
}

export interface OrderFeeAdjustment {
  adjustmentId: string;
  adjustmentPostingMonth: string;
  adjustmentType: string;
  adjustmentBaseCent: number;
  adjustmentFeeCent: number;
  ruleVersion: string;
  adjustmentReason: string;
  occurredAt: string;
}

export interface OrderFeeDetailRow {
  feeResultId: string;
  statementEntryId?: string | null;
  orderId: string;
  couponId: string;
  orderStatus?: string | null;
  couponStatus?: string | null;
  feeDirection: FeeDirection;
  originalBusinessMonth: string;
  saleMonth?: string | null;
  verifyMonth?: string | null;
  ruleMatchDate?: string | null;
  saleTime?: string | null;
  verifyTime?: string | null;
  saleStoreId?: string | null;
  saleStoreName?: string | null;
  verifyStoreId?: string | null;
  verifyStoreName?: string | null;
  skuId: string;
  skuName?: string | null;
  productName?: string | null;
  productScope: string;
  productType: string;
  saleChannel: string;
  sourceAmountCent: number;
  refundedAmountCent: number;
  originalBaseCent: number;
  feeRate: string;
  originalFeeCent: number;
  adjustmentBaseCent: number;
  adjustmentFeeCent: number;
  adjustedNetBaseCent: number;
  adjustedNetFeeCent: number;
  ruleVersion: string;
  resultStatus: string;
  statementId?: string | null;
  statementLineId?: string | null;
  statementStatus?: string | null;
  dataStatus?: string;
  adjustments: OrderFeeAdjustment[];
}

export interface OrderFeeDetailsData {
  context: {
    statementId?: string | null;
    statementLineId?: string | null;
    storeId?: string | null;
    month?: string | null;
    saleMonth?: string | null;
    verifyMonth?: string | null;
    feeDirection: FeeDirection;
    productScope: string;
    productType: string;
    feeRates: string[];
    ruleVersions: string[];
    dataStatus?: string | null;
    q?: string | null;
    statementStatus?: string | null;
  };
  list: OrderFeeDetailRow[];
  total: number;
  page: number;
  pageSize: number;
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
  product_scope?: string;
  product_type: string;
  limit: number;
  totals: StoreRankingTotals;
  rows: StoreRankingRow[];
}

export interface MonthlySummaryData {
  store: StoreOption;
  month: string;
  product_scope?: string;
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
  product_scope?: string;
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
  product_name: string;
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
  is_refund_excluded: boolean;
  paid_amount_cent: number;
  commission_rate: number;
  receivable_commission_cent: number;
  payable_commission_cent: number;
}

export interface SalesDashboardMetrics {
  total_sales_order_count: number;
  self_verify_order_count: number;
  self_verify_rate: number;
  total_verify_order_count: number;
  actual_verify_amount_cent: number;
  avg_verify_cycle_days: number | null;
}

export interface SalesMetricRow extends SalesDashboardMetrics {
  product_type: string;
}

export interface SalesTrendRow {
  month: string;
  order_count: number;
  verify_order_count: number;
}

export interface SalesCyclePoint {
  order_id: string;
  cycle_days: number;
  sale_time: string;
  verify_time: string;
}

export interface SalesCycleDistributionRow {
  product_type: string;
  count: number;
  min_days: number | null;
  q1_days: number | null;
  median_days: number | null;
  q3_days: number | null;
  max_days: number | null;
  avg_days: number | null;
  sample_points: SalesCyclePoint[];
}

export interface SalesDashboardData {
  store: StoreOption;
  month: string;
  product_scope?: string;
  product_type: string;
  metrics: SalesDashboardMetrics;
  product_rows: SalesMetricRow[];
  trend_rows: SalesTrendRow[];
  cycle_rows: SalesCycleDistributionRow[];
  source_row_count: number;
}

export interface DetailFilters {
  product_scope?: string;
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
  product_scope?: string;
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

export interface CamelPagination {
  page: number;
  pageSize: number;
  total: number;
  totalPages?: number;
}

export type ProductStatus = "ACTIVE" | "INACTIVE" | "DELETED" | "UNKNOWN";

export interface SkuProductItem {
  skuId: string;
  skuName: string | null;
  productId: string | null;
  productName: string | null;
  spuId: string | null;
  productScope: string;
  productType: string;
  isServiceProduct: boolean;
  creatorAccountId: string | null;
  creatorAccountName: string | null;
  ownerAccountId: string | null;
  ownerAccountName: string | null;
  productStatus: ProductStatus | null;
  isActiveProduct: boolean;
  lastSyncedAt: string | null;
  manualModifiedAt: string | null;
}

export interface SkuProductListData extends CamelPagination {
  list: SkuProductItem[];
}

export interface SkuProductManualUpdate {
  productScope: string;
  productType: string;
  isServiceProduct: boolean;
}

export type FeeRuleStatus = "ACTIVE" | "INACTIVE";

export interface SkuFeeRuleItem {
  ruleVersion: string;
  skuId: string;
  skuName: string | null;
  productScope: string;
  productType: string;
  promotionServiceFeeRate: string;
  managementServiceFeeRate: string;
  effectiveDate: string;
  effectiveAt: string;
  ruleStatus: FeeRuleStatus;
  previousRuleVersion: string | null;
  createdBy: string;
  changeReason: string;
  publishedAt: string;
  isMatchedVersion?: boolean;
}

export interface SkuFeeRuleListData extends CamelPagination {
  list: SkuFeeRuleItem[];
}

export interface SkuFeeRuleCreate {
  skuId: string;
  promotionServiceFeeRate: string;
  managementServiceFeeRate: string;
  effectiveDate: string;
  ruleStatus: FeeRuleStatus;
  changeReason: string;
}

export type ImportBatchStatus =
  | "UPLOADED"
  | "VALIDATION_FAILED"
  | "PENDING_COMMIT"
  | "COMMITTING"
  | "COMPLETED"
  | "FAILED";

export type ImportRowStatus =
  | "PENDING"
  | "VALID"
  | "INVALID"
  | "COMMITTED"
  | "COMMIT_FAILED";

export interface ImportBatchItem {
  batchId: string;
  fileName: string;
  batchStatus: ImportBatchStatus;
  commitMode: "ATOMIC";
  effectiveDate: string;
  totalCount: number;
  validCount: number;
  successCount: number;
  failedCount: number;
  uploadedBy: string;
  validatedAt: string | null;
  committedAt: string | null;
  hasResultFile: boolean;
}

export interface ImportRowError {
  field: string;
  code: string;
  message: string;
}

export interface ImportRowItem {
  rowNumber: number;
  skuName: string | null;
  skuId: string | null;
  promotionServiceFeeRate: string | null;
  managementServiceFeeRate: string | null;
  validationStatus: ImportRowStatus;
  errors: ImportRowError[];
  createdRuleVersion: string | null;
}

export interface ImportBatchUploadData {
  batch: ImportBatchItem;
  errorPreview: ImportRowItem[];
  hasMoreErrors: boolean;
}

export interface ImportBatchListData extends CamelPagination {
  list: ImportBatchItem[];
}

export interface ImportBatchDetailData {
  batch: ImportBatchItem;
  rows: CamelPagination & { list: ImportRowItem[] };
}

export interface ImportBatchCommitData {
  batch: ImportBatchItem;
  createdRuleVersions: string[];
}

export type ProductSyncStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCESS"
  | "FAILED"
  | "PARTIAL";
export type ProductSyncMode = "INCREMENTAL" | "FULL";

export interface ProductSyncRunItem {
  syncRunId: string;
  mode: ProductSyncMode;
  status: ProductSyncStatus;
  startedAt: string | null;
  finishedAt: string | null;
  observedCount: number;
  insertedCount: number;
  updatedCount: number;
  unchangedCount: number;
  failedCount: number;
  latestSuccessfulSyncedAt: string | null;
  nextCursorMasked: string | null;
  errorCode: string | null;
  errorMessage: string | null;
}

export interface ProductSyncRunListData extends CamelPagination {
  list: ProductSyncRunItem[];
}

export interface ProductSyncRunDetailData {
  run: ProductSyncRunItem;
  phaseCounts: Record<string, number>;
  affectedSkuSample: string[];
  dataQualityIssueCount: number;
  retryable: boolean;
}

export interface ProductSyncTriggerData {
  syncRunId: string;
  mode: ProductSyncMode;
  status: "QUEUED";
}

export interface SkuSyncHistoryItem {
  snapshotId: string;
  syncRunId: string;
  skuId: string;
  productId: string | null;
  spuId: string | null;
  skuName: string | null;
  productName: string | null;
  creatorAccountId: string | null;
  creatorAccountName: string | null;
  ownerAccountId: string | null;
  ownerAccountName: string | null;
  productStatusRaw: string | null;
  productStatus: ProductStatus | null;
  payloadSha256: string;
  observedAt: string;
}

export interface SkuSyncHistoryListData extends CamelPagination {
  list: SkuSyncHistoryItem[];
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
  store_display_status?: string;
  round_status?: string;
  product_type?: string;
  province?: string;
  city?: string;
}

export interface ClueFilterMetadata {
  assigned_stores: StoreOption[];
  assigned_provinces: string[];
  assigned_cities: string[];
  product_types: string[];
  default_product_type: string;
  lead_statuses: string[];
  round_statuses: string[];
  verification_statuses: string[];
}

export interface ClueOverviewMetrics {
  total_clues: number;
  active_clues: number;
  follow_rate: number;
  follow_success_rate: number;
  verified_count: number;
  self_store_verify_rate: number;
  pending_reassign_count: number;
}

export interface ClueAssignmentRound {
  assignment_round_id: string;
  order_id: string;
  round_no: number;
  store_display_status?: string | null;
  lead_status: string;
  order_current_status: string;
  current_assignment_round_id: string | null;
  current_round_no: number;
  current_round_status: string;
  current_assigned_store_id: string | null;
  current_assigned_store_name: string | null;
  is_current_round: boolean;
  round_effective_status: "active" | "inactive";
  can_operate_current_round?: boolean;
  timing_state?: string | null;
  status_reason?: string | null;
  round_status: string;
  assigned_at: string | null;
  expires_at: string | null;
  remaining_reassign_seconds: number | null;
  assigned_store_id: string | null;
  assigned_store_name: string | null;
  phone_masked: string;
  product_name?: string | null;
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

export type ClueFollowUpAction =
  | "appointment"
  | "further_follow_up"
  | "lost"
  | "unreachable"
  | "request_store_change";

export type ClueFollowUpLegacyResult =
  | "success"
  | "failed"
  | "continue_following";

export type ClueFollowUpResult =
  | ClueFollowUpAction
  | ClueFollowUpLegacyResult;

export interface ClueFollowUpRecord {
  follow_up_record_id: string;
  order_id: string;
  assignment_round_id: string;
  round_no: number;
  assigned_store_id: string | null;
  assigned_store_name?: string | null;
  follow_result: ClueFollowUpResult;
  note: string | null;
  timing_state?: string | null;
  status_reason?: string | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  deleted_by_user_id?: string | null;
  deleted_by_username?: string | null;
  deletion_reason?: string | null;
  operator_user_id: string | null;
  operator_username: string | null;
  created_at: string;
}

export interface ClueFollowUpPayload {
  assignment_round_id: string;
  follow_result: ClueFollowUpAction;
  note: string | null;
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
  follow_up_records: ClueFollowUpRecord[];
}

export interface CluePhoneReveal {
  order_id: string;
  phone: string;
  phone_masked: string;
}

export interface ClueAllocationEligibleLead {
  lead_key: string;
  canonical_clue_id: string | null;
  order_id: string | null;
  allocation_state: string;
  pool_location: string | null;
  anchor_store_id: string | null;
  anchor_city: string | null;
  anchor_city_code: string | null;
  updated_at: string;
}

export interface ClueAllocationEligibleLeadData {
  rows: ClueAllocationEligibleLead[];
  pagination: Pagination;
}

export interface ClueHeadquartersPoolEntry {
  headquarters_pool_entry_id: string;
  lead_key: string;
  canonical_clue_id: string | null;
  order_id: string | null;
  status: string;
  reason: string;
  entered_at: string;
  closed_at: string | null;
  close_reason: string | null;
  anchor_store_id: string | null;
  anchor_city: string | null;
  anchor_city_code: string | null;
  source_assignment_round_id: string | null;
  source_decision_id: string | null;
  source_rule_version_id: string | null;
  allocation_cycle_id: string | null;
}

export interface ClueHeadquartersPoolData {
  rows: ClueHeadquartersPoolEntry[];
  pagination: Pagination;
}

export interface ClueAllocationCycle {
  allocation_cycle_id: string;
  cycle_type: string;
  execution_mode: string;
  status: string;
  parent_cycle_id: string | null;
  selected_lead_keys: string[];
  requested_lead_count: number;
  active_lead_count: number;
  planned_impact: Record<string, unknown>;
  actual_impact: Record<string, unknown>;
  actor: string | null;
  privileged_confirmation: boolean;
  created_at: string;
  executed_at: string | null;
  completed_at: string | null;
}

export interface ClueAllocationCycleData {
  rows: ClueAllocationCycle[];
  pagination: Pagination;
}

export interface ClueAllocationAuditLog {
  audit_log_id: string;
  event_type: string;
  allocation_cycle_id: string | null;
  actor: string | null;
  privileged_confirmation: boolean;
  before_snapshot: Record<string, unknown>;
  after_snapshot: Record<string, unknown>;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ClueAllocationAuditLogData {
  rows: ClueAllocationAuditLog[];
  pagination: Pagination;
}

export interface ClueAllocationCycleRequest {
  lead_keys: string[];
  preview_token?: string;
  confirm?: boolean;
  privileged_confirmation?: boolean;
}

export interface ClueAllocationCyclePreviewRequest {
  operation?: "trial" | "rebuild";
  lead_keys?: string[];
  source_cycle_id?: string;
  privileged_confirmation?: boolean;
}

export interface ClueAllocationCycleRebuildRequest {
  source_cycle_id: string;
  preview_token: string;
  confirm?: boolean;
  privileged_confirmation?: boolean;
}

export interface ClueAllocationCyclePreview {
  requested_lead_count: number;
  active_lead_count: number;
  lead_keys: string[];
  summary: Record<string, number>;
  operation: string;
  source_cycle_id: string | null;
  preview_token: string;
  preview_expires_at: string;
}

export interface ClueAllocationCycleExecution {
  allocation_cycle_id: string;
  cycle_type: string;
  execution_mode: string;
  status: string;
  requested_lead_count: number;
  active_lead_count: number;
  privileged_confirmation: boolean;
  parent_cycle_id: string | null;
  summary: Record<string, number>;
}

export type ClueAllocationScopeType =
  | "global"
  | "city"
  | "store_group"
  | "anchor_store";

export interface ClueAllocationRuleScope {
  scope_type: ClueAllocationScopeType;
  city_code: string | null;
  store_group_id: string | null;
  anchor_store_id: string | null;
}

export interface ClueAllocationStrategyConfig {
  strategy_type:
    | "sales_store_priority"
    | "nearby_city_optimization"
    | "city_fallback";
  enabled: boolean;
  execution_order: number;
  params: Record<string, unknown>;
}

export interface ClueAllocationRuleVersion {
  rule_version_id: string;
  rule_id: string;
  version_no: number;
  status: "draft" | "published" | "retired";
  auto_expiry_enabled: boolean | null;
  first_follow_up_sla_hours: number | null;
  protection_days: number | null;
  conversion_weight: number | null;
  follow_24h_weight: number | null;
  lookback_days: number | null;
  min_samples: number | null;
  strategy_configs: ClueAllocationStrategyConfig[];
  created_at: string;
  updated_at: string;
  published_at: string | null;
  retired_at: string | null;
}

export interface ClueAllocationRule {
  rule_id: string;
  name: string;
  scope: ClueAllocationRuleScope;
  created_at: string;
  updated_at: string;
}

export interface ClueAllocationRuleListData {
  rows: ClueAllocationRule[];
  pagination: Pagination;
}

export interface ClueAllocationRuleDetailData {
  rule: ClueAllocationRule;
  versions: ClueAllocationRuleVersion[];
}

export interface ClueAllocationRuleCreate {
  name: string;
  scope: ClueAllocationRuleScope;
}

export interface ClueAllocationRuleVersionWrite {
  auto_expiry_enabled: boolean;
  first_follow_up_sla_hours: number;
  protection_days: number;
  conversion_weight: number;
  follow_24h_weight: number;
  lookback_days: number;
  min_samples: number;
  strategy_configs: ClueAllocationStrategyConfig[];
}

export interface ClueAllocationDecision {
  decision_id: string;
  lead_key: string;
  order_id: string | null;
  rule_id: string | null;
  rule_version_id: string | null;
  scope_type: string | null;
  scope_key: string | null;
  strategy_type: string;
  execution_order: number | null;
  allocation_cycle_id: string | null;
  execution_mode: string;
  assignment_round_id: string | null;
  round_no: number | null;
  selected_store_id: string | null;
  selected_store_name: string | null;
  decision_status: string;
  reason: string | null;
  payload: Record<string, unknown>;
  actor: string | null;
  executed_at: string;
}

export interface ClueAllocationDecisionData {
  rows: ClueAllocationDecision[];
  pagination: Pagination;
}

export interface StoreScoreSnapshotRun {
  snapshot_run_id: string;
  snapshot_date: string;
  run_mode: string;
  window_start: string;
  window_end: string;
  candidate_store_count: number;
  snapshot_count: number;
  triggered_by: string | null;
  computed_at: string;
}

export interface StoreScoreSnapshot {
  store_id: string;
  city_code: string | null;
  conversion_numerator: number;
  conversion_denominator: number;
  conversion_rate: number;
  conversion_value_source: string;
  follow_24h_numerator: number;
  follow_24h_denominator: number;
  follow_24h_rate: number;
  follow_24h_value_source: string;
  store_weight: number;
  composite_score: number;
}

export interface StoreScoreSnapshotData {
  run: StoreScoreSnapshotRun | null;
  rows: StoreScoreSnapshot[];
  pagination: Pagination;
}

export interface ClueCenterMaterializationResult {
  job_id?: string | null;
  status?: "queued" | "running" | "success" | "failed";
  rebuilt_order_count?: number | null;
  rebuilt_round_count?: number | null;
}

export interface ProductTypeVisibilityData {
  enabled: boolean;
  visible_product_scopes: string[];
  visible_product_types: string[];
  default_product_type: string;
  available_product_scopes: string[];
  available_product_types: string[];
  product_scope_type_map: Record<string, string[]>;
  updated_at: string | null;
  updated_by: string | null;
}

export interface ProductTypeVisibilityUpdate {
  enabled: boolean;
  visible_product_scopes: string[];
  visible_product_types: string[];
  default_product_type: string;
}
