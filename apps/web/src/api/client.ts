import {
  defaultMonth,
  defaultStore,
  clueCenterResponses,
  monthlySummaryResponse,
  orderDetails,
  page1Definitions,
  page2Definitions,
  skuProductRulesResponse,
  storeRankingResponse,
} from "../data/mockData";
import {
  CLUE_DEMO_ADMIN_USER,
  CLUE_DEMO_MODE,
} from "../demo/clueDemoMode";
import {
  ClueDemoRepositoryError,
  clueDemoRepository,
} from "../demo/clueDemoRepository";
import type {
  ApiResponse,
  AccountActivationCheckData,
  AccountActivationCheckPayload,
  AccountActivationPayload,
  AccountListData,
  AccountPagePermissionPayload,
  AccountPermissionAuditListData,
  AccountPasswordResetPayload,
  AccountPasswordPayload,
  AccountRow,
  AccountUpsertPayload,
  AccessControlData,
  AdminUser,
  ClueAssignmentRoundData,
  ClueCenterMaterializationResult,
  ClueAllocationAuditLogData,
  ClueAllocationCycleData,
  ClueAllocationCycleExecution,
  ClueAllocationCyclePreview,
  ClueAllocationCyclePreviewRequest,
  ClueAllocationCycleRequest,
  ClueAllocationCycleRebuildRequest,
  ClueAllocationDecisionData,
  ClueAllocationEligibleLeadData,
  ClueAllocationRule,
  ClueAllocationRuleCreate,
  ClueAllocationRuleDetailData,
  ClueAllocationRuleListData,
  ClueAllocationRuleVersion,
  ClueAllocationRuleVersionWrite,
  ClueFilterMetadata,
  ClueFollowUpPayload,
  ClueFollowUpRecord,
  ClueOrderDetail,
  ClueOverviewFilters,
  ClueOverviewMetrics,
  CluePhoneReveal,
  ClueHeadquartersPoolData,
  CommissionRulesSummaryData,
  DetailFilters,
  FeedbackCategory,
  FeedbackListData,
  FeedbackRow,
  FeedbackSubmissionPayload,
  FeedbackSubmissionReceipt,
  FeedbackStatus,
  FilterMetaData,
  MonthlySettlementData,
  NonCommissionOwnerAccountListData,
  NonCommissionOwnerAccountUpdateResult,
  OrderDetailsData,
  ProductTypeVisibilityData,
  ProductTypeVisibilityUpdate,
  RolePermissionImpactData,
  SelectOption,
  SalesDashboardData,
  SettlementViewData,
  ManualSyncResult,
  ManualSyncTarget,
  SkuProductCommissionRule,
  SkuRuleListData,
  SkuRuleLookupData,
  SkuRuleUpdateResult,
  SyncAdminData,
  SyncConfigUpdate,
  StoreRankingData,
  StoreScoreSnapshotData,
  UnactivatedStoreAccountListData,
} from "../types/dashboard";
import {
  buildSalesDashboardView,
  filterOrderDetails,
  getProductOptions,
  getRankingRows,
  getRankingTotals,
  getSaleMonthOptions,
  getSettlementView,
  getStoreOptions,
  getVerifyMonthOptions,
} from "../utils/settlement";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const USE_MOCKS =
  CLUE_DEMO_MODE || import.meta.env.VITE_USE_MOCKS === "true";
const DEFAULT_DETAIL_PAGE_SIZE = 50;
const ALL_MONTHS = "all";
const mockFollowUpRecordsByOrder: Record<string, ClueFollowUpRecord[]> = {};

type QueryParamValue =
  | string
  | number
  | boolean
  | Array<string | number | boolean>
  | null
  | undefined;
type QueryParams = Record<string, QueryParamValue>;

export interface ApiLoadResult<T> extends ApiResponse<T> {
  usingMock: boolean;
  fallbackReason?: string;
}

interface DetailQuery {
  filters: DetailFilters;
  page: number;
  pageSize: number;
}

interface SalesDashboardQuery {
  store: { store_id: string; store_name: string };
  month: string;
  productScope: string;
  productType: string;
  trendMonths?: string[];
}

interface ClueRoundQuery {
  filters: ClueOverviewFilters;
  page: number;
  pageSize: number;
}

export class ApiRequestError extends Error {
  status: number;

  constructor(status: number, message?: string) {
    super(message ?? `API ${status}`);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

function demoLoad<T>(factory: () => ApiResponse<T>): Promise<ApiLoadResult<T>> {
  try {
    return Promise.resolve({
      ...factory(),
      usingMock: true,
      fallbackReason: "当前展示合成演示数据。",
    });
  } catch (error) {
    if (error instanceof ClueDemoRepositoryError) {
      return Promise.reject(new ApiRequestError(error.status, error.message));
    }
    return Promise.reject(error);
  }
}

function blockDemoNetwork(): void {
  if (CLUE_DEMO_MODE) {
    throw new ApiRequestError(
      503,
      "演示模式未提供该接口，已阻止真实网络请求。",
    );
  }
}

function generatedAt(): string {
  return new Date().toISOString();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "未知错误";
}

function apiUrl(path: string, params: QueryParams = {}): string {
  const base = API_BASE_URL.startsWith("http")
    ? API_BASE_URL
    : new URL(API_BASE_URL, window.location.origin).toString();
  const url = new URL(`${base.replace(/\/$/, "")}${path}`);

  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        url.searchParams.append(key, String(item));
      });
      return;
    }
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });

  return url.toString();
}

function isAuthError(error: unknown): boolean {
  return error instanceof ApiRequestError && [401, 403].includes(error.status);
}

async function requestJson<T>(
  path: string,
  params?: QueryParams,
): Promise<ApiResponse<T>> {
  blockDemoNetwork();
  const response = await fetch(apiUrl(path, params), {
    credentials: "include",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new ApiRequestError(response.status);
  }

  return response.json() as Promise<ApiResponse<T>>;
}

function filenameFromContentDisposition(disposition: string | null): string | null {
  if (!disposition) {
    return null;
  }
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
  return asciiMatch?.[1] ?? null;
}

async function requestDownload(
  path: string,
  params?: QueryParams,
): Promise<void> {
  blockDemoNetwork();
  const response = await fetch(apiUrl(path, params), {
    credentials: "include",
    headers: { Accept: "text/csv" },
  });

  if (!response.ok) {
    throw new ApiRequestError(response.status);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download =
    filenameFromContentDisposition(response.headers.get("Content-Disposition")) ??
    "export.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

async function sendJson<T>(
  path: string,
  {
    body,
    method = "POST",
    params,
  }: {
    body?: unknown;
    method?: "DELETE" | "POST" | "PUT";
    params?: QueryParams;
  } = {},
): Promise<ApiResponse<T>> {
  blockDemoNetwork();
  const response = await fetch(apiUrl(path, params), {
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    method,
  });

  if (!response.ok) {
    throw new ApiRequestError(response.status);
  }

  return response.json() as Promise<ApiResponse<T>>;
}

async function withMockFallback<T>(
  request: () => Promise<ApiResponse<T>>,
  fallback: () => ApiResponse<T>,
  options: { fallbackOnError?: boolean } = {},
): Promise<ApiLoadResult<T>> {
  if (USE_MOCKS) {
    return {
      ...fallback(),
      usingMock: true,
      fallbackReason: "当前展示演示数据。",
    };
  }

  try {
    return { ...(await request()), usingMock: false };
  } catch (error) {
    if (isAuthError(error) || options.fallbackOnError === false) {
      throw error;
    }
    return {
      ...fallback(),
      usingMock: true,
      fallbackReason: "服务暂不可用，当前展示演示数据。",
    };
  }
}

function optionValues(options: SelectOption[]): string[] {
  return options.map((option) => option.value);
}

function mockMetaResponse(): ApiResponse<FilterMetaData> {
  const productTypes = optionValues(getProductOptions());
  const scopedProductTypes = productTypes.filter((value) => value !== ALL_MONTHS);
  return {
    data: {
      stores: getStoreOptions().map((option) => ({
        store_id: option.value,
        store_name: option.label,
      })),
      product_scopes: ["all", "精诚养车"],
      product_scope_type_map: {
        精诚养车: scopedProductTypes,
      },
      product_types: productTypes,
      default_product_type: "all",
      sale_months: optionValues(getSaleMonthOptions()),
      verify_months: optionValues(getVerifyMonthOptions()),
    },
    meta: {
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockCommissionRulesSummaryResponse(): ApiResponse<CommissionRulesSummaryData> {
  return {
    data: {
      non_commission_owner_accounts: [],
      commission_skus: skuProductRulesResponse.data.rows
        .filter(
          (rule) =>
            (rule.is_service_product ?? true) && (rule.commission_rate ?? 0) > 0,
        )
        .map((rule) => ({
          commission_rate: rule.commission_rate ?? 0,
          product_name: rule.product_name ?? "",
          sku_id: rule.sku_id,
        })),
    },
    meta: { generated_at: generatedAt(), source: "contract-mock" },
  };
}

function mockStoreRankingResponse(
  month: string,
  productScope: string,
  productType: string,
  limit: number,
): ApiResponse<StoreRankingData> {
  const allowedProductTypes =
    productScope && productScope !== "all"
      ? (mockMetaResponse().data.product_scope_type_map?.[productScope] ?? [])
      : undefined;
  const rows = getRankingRows(month, productType, allowedProductTypes).slice(0, limit);
  return {
    data: {
      month,
      product_scope: productScope,
      product_type: productType,
      limit,
      totals: getRankingTotals(month, productType, allowedProductTypes),
      rows,
    },
    definitions: page1Definitions,
    meta: {
      ...storeRankingResponse.meta,
      source: "mock",
    },
  };
}

function mockSettlementResponse(
  storeId: string,
  month: string,
  productScope: string,
  productType: string,
): ApiResponse<SettlementViewData> {
  const allowedProductTypes =
    productScope && productScope !== "all"
      ? (mockMetaResponse().data.product_scope_type_map?.[productScope] ?? [])
      : undefined;
  const view = getSettlementView(
    storeId,
    month,
    productType,
    productScope,
    allowedProductTypes,
  );
  return {
    data: view,
    definitions: page2Definitions,
    meta: {
      ...monthlySummaryResponse.meta,
      source: `mock:${view.source}`,
    },
  };
}

const SALES_DASHBOARD_DEFINITIONS = [
  {
    key: "total_sales_order_count",
    label: "总销售订单量",
    description:
      "销售归属门店在所选期间卖出的有效订单数，按订单编号去重，退款订单不计入。",
  },
  {
    key: "self_verify_order_count",
    label: "自店核销数",
    description:
      "销售归属门店和实际核销门店都是当前门店的订单数，按订单编号去重，退款订单不计入。",
  },
  {
    key: "self_verify_rate",
    label: "自店核销率",
    description: "自店核销数 / 总销售订单量；总销售订单量为 0 时显示 0。",
  },
  {
    key: "total_verify_order_count",
    label: "实际核销总数",
    description:
      "不管销售归属门店，只要在当前门店于所选期间完成核销即计入，按订单编号去重；一单核销多券也只算一单。",
  },
  {
    key: "actual_verify_amount_cent",
    label: "实际核销金额",
    description:
      "当前门店产生核销后的实收金额合计，退款订单不计入。",
  },
  {
    key: "avg_verify_cycle_days",
    label: "平均核销周期",
    description:
      "当前门店已核销订单从销售时间到核销时间的平均天数，按订单编号去重。",
  },
  {
    key: "cycle_distribution",
    label: "核销周期分布",
    description:
      "按商品类型展示当前门店核销订单从销售时间到核销时间的周期，箱线图展示四分位，散点展示订单样本。",
  },
];

function salesTrendMonths(month: string, trendMonths: string[] = []): string[] {
  const months = [
    ...new Set([month, ...trendMonths].filter((value) => value && value !== ALL_MONTHS)),
  ];
  return months.length > 0 ? months : [month];
}

function mockSalesDashboardResponse({
  store,
  month,
  productScope,
  productType,
  trendMonths = [],
}: SalesDashboardQuery): ApiResponse<SalesDashboardData> {
  const scopeProductTypes =
    mockMetaResponse().data.product_scope_type_map?.[productScope] ?? [];
  const scopedRows =
    productScope && productScope !== "all" && scopeProductTypes.length > 0
      ? orderDetails.filter((row) => scopeProductTypes.includes(row.product_type))
      : orderDetails;
  return {
    data: buildSalesDashboardView({
      rows: scopedRows,
      store,
      month,
      productScope,
      productType,
      trendMonths: salesTrendMonths(month, trendMonths),
    }),
    definitions: SALES_DASHBOARD_DEFINITIONS,
    meta: {
      generated_at: generatedAt(),
      source: "mock:order-details",
    },
  };
}

function mockOrderDetailsResponse({
  filters,
  page,
  pageSize,
}: DetailQuery): ApiResponse<OrderDetailsData> {
  const productScope = filters.product_scope ?? "all";
  const allowedProductTypes =
    productScope && productScope !== "all"
      ? (mockMetaResponse().data.product_scope_type_map?.[productScope] ?? [])
      : undefined;
  const filteredRows = filterOrderDetails(orderDetails, filters, allowedProductTypes);
  const safePageSize =
    Number.isFinite(pageSize) && pageSize > 0
      ? Math.min(Math.floor(pageSize), 500)
      : DEFAULT_DETAIL_PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / safePageSize));
  const safePage =
    Number.isFinite(page) && page > 0
      ? Math.min(Math.floor(page), totalPages)
      : 1;
  const startIndex = (safePage - 1) * safePageSize;

  return {
    data: {
      rows: filteredRows.slice(startIndex, startIndex + safePageSize),
      pagination: {
        page: safePage,
        page_size: safePageSize,
        total: filteredRows.length,
        total_pages: totalPages,
      },
    },
    meta: {
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

async function requestSalesDashboard({
  store,
  month,
  productScope,
  productType,
  trendMonths = [],
}: SalesDashboardQuery): Promise<ApiResponse<SalesDashboardData>> {
  return requestJson<SalesDashboardData>("/dashboard/sales", {
    store_id: store.store_id,
    month,
    product_scope: productScope,
    product_type: productType,
    trend_months: salesTrendMonths(month, trendMonths),
  });
}

function mockClueFiltersResponse(): ApiResponse<ClueFilterMetadata> {
  return {
    data: {
      ...clueCenterResponses.filters.data,
      default_product_type: "all",
    },
    definitions: clueCenterResponses.filters.definitions,
    meta: {
      ...clueCenterResponses.filters.meta,
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockStoreDisplayStatus(row: ClueAssignmentRoundData["rows"][number]): string {
  if (row.store_display_status) {
    return row.store_display_status;
  }
  if (row.lead_status === "converted") {
    return "已核销";
  }
  if (row.lead_status === "refunded" || row.order_current_status === "refunded") {
    return "已退款";
  }
  if (row.round_status === "expired_pending_reassign") {
    return "超期失效";
  }
  if (
    row.round_status === "failed_pending_reassign" ||
    row.follow_result === "lost" ||
    row.follow_result === "failed"
  ) {
    return "主动战败";
  }
  if (row.lead_status === "active" && row.round_status === "active_followed") {
    return "已跟进";
  }
  if (row.lead_status === "active" && row.round_status === "active_unfollowed") {
    return "待跟进";
  }
  return "不可跟进";
}

function mockFilterClueRounds(
  filters: ClueOverviewFilters,
): ClueAssignmentRoundData["rows"] {
  return clueCenterResponses.assignment_rounds.data.rows.filter((row) => {
    if (
      filters.store_display_status &&
      mockStoreDisplayStatus(row) !== filters.store_display_status
    ) {
      return false;
    }
    return true;
  });
}

function mockClueOverviewResponse(
  filters: ClueOverviewFilters = {},
): ApiResponse<ClueOverviewMetrics> {
  const rows = mockFilterClueRounds(filters);
  const total = rows.length;
  const followed = rows.filter((row) => row.followed_at).length;
  const successful = rows.filter((row) => row.follow_result === "success").length;
  const verified = rows.filter((row) => row.is_self_store_verified).length;

  return {
    data: {
      total_clues: total,
      active_clues: rows.filter(
        (row) =>
          row.is_current_round &&
          ["active_unfollowed", "active_followed"].includes(row.round_status),
      ).length,
      follow_rate: total ? followed / total : 0,
      follow_success_rate: total ? successful / total : 0,
      verified_count: verified,
      self_store_verify_rate: total ? verified / total : 0,
      pending_reassign_count: rows.filter((row) =>
        ["failed_pending_reassign", "expired_pending_reassign"].includes(
          row.round_status,
        ),
      ).length,
    },
    meta: {
      ...clueCenterResponses.overview.meta,
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockClueAssignmentRoundsResponse({
  filters,
  page,
  pageSize,
}: ClueRoundQuery): ApiResponse<ClueAssignmentRoundData> {
  const rows = mockFilterClueRounds(filters);
  const safePageSize =
    Number.isFinite(pageSize) && pageSize > 0
      ? Math.min(Math.floor(pageSize), 100)
      : 20;
  const totalPages = Math.max(1, Math.ceil(rows.length / safePageSize));
  const safePage =
    Number.isFinite(page) && page > 0
      ? Math.min(Math.floor(page), totalPages)
      : 1;
  const startIndex = (safePage - 1) * safePageSize;

  return {
    data: {
      rows: rows.slice(startIndex, startIndex + safePageSize),
      pagination: {
        page: safePage,
        page_size: safePageSize,
        total: rows.length,
        total_pages: totalPages,
      },
    },
    meta: {
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockClueOrderDetailResponse(
  orderId: string,
): ApiResponse<ClueOrderDetail> {
  const stored = clueCenterResponses.order_details?.[orderId];
  const extraRecords = mockFollowUpRecordsByOrder[orderId] ?? [];
  if (stored) {
    return {
      data: {
        ...stored.data,
        follow_up_records: [
          ...(stored.data.follow_up_records ?? []),
          ...extraRecords,
        ],
      },
      meta: {
        ...stored.meta,
        generated_at: generatedAt(),
        source: "mock",
      },
    };
  }

  const rounds = clueCenterResponses.assignment_rounds.data.rows.filter(
    (row) => row.order_id === orderId,
  );
  const firstRound = rounds[0];

  return {
    data: {
      order_id: orderId,
      canonical_clue_id: null,
      lead_status: firstRound?.lead_status ?? "active",
      phone_masked: firstRound?.phone_masked ?? "",
      product_id: null,
      product_name: firstRound?.product_name ?? null,
      product_type: firstRound?.product_type ?? null,
      author_nickname: firstRound?.author_nickname ?? null,
      assigned_city: null,
      assigned_province: null,
      rounds,
      follow_up_records: extraRecords,
    },
    meta: {
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockClueFollowUpResponse(
  orderId: string,
  payload: ClueFollowUpPayload,
): ApiResponse<ClueFollowUpRecord> {
  const createdAt = generatedAt();
  const row = clueCenterResponses.assignment_rounds.data.rows.find(
    (candidate) =>
      candidate.order_id === orderId &&
      candidate.assignment_round_id === payload.assignment_round_id,
  );
  const record: ClueFollowUpRecord = {
    follow_up_record_id: `mock-follow-up-${orderId}-${Date.now()}`,
    order_id: orderId,
    assignment_round_id: payload.assignment_round_id,
    round_no: row?.round_no ?? 1,
    assigned_store_id: row?.assigned_store_id ?? null,
    assigned_store_name: row?.assigned_store_name ?? null,
    follow_result: payload.follow_result,
    note: payload.note,
    timing_state:
      payload.follow_result === "appointment" ? "protected" : "active",
    operator_user_id: "mock-store-user",
    operator_username: "本店账号",
    created_at: createdAt,
  };

  mockFollowUpRecordsByOrder[orderId] = [
    ...(mockFollowUpRecordsByOrder[orderId] ?? []),
    record,
  ];

  if (row) {
    row.followed_at = createdAt;
    row.follow_result = payload.follow_result;
    row.round_status =
      payload.follow_result === "lost" ||
      payload.follow_result === "request_store_change"
        ? "failed_pending_reassign"
        : "active_followed";
    if (
      payload.follow_result === "lost" ||
      payload.follow_result === "request_store_change"
    ) {
      row.lead_status = "pending_reassign";
      row.expires_at = createdAt;
      row.remaining_reassign_seconds = 0;
      row.reassign_reason =
        payload.follow_result === "request_store_change"
          ? "request_store_change"
          : "follow_lost";
      row.can_operate_current_round = false;
    }
  }

  return {
    data: record,
    meta: {
      generated_at: createdAt,
      source: "mock",
    },
  };
}

function mockDeleteClueFollowUpRecordResponse(
  followUpRecordId: string,
): ApiResponse<ClueFollowUpRecord> {
  for (const records of Object.values(mockFollowUpRecordsByOrder)) {
    const index = records.findIndex(
      (record) => record.follow_up_record_id === followUpRecordId,
    );
    if (index >= 0) {
      const record = records[index];
      record.is_deleted = true;
      record.deleted_at = generatedAt();
      record.deleted_by_username = "最高管理员";
      record.deletion_reason = "reversed_by_highest_admin";
      return {
        data: record,
        meta: {
          generated_at: generatedAt(),
          source: "mock",
        },
      };
    }
  }

  for (const detail of Object.values(clueCenterResponses.order_details ?? {})) {
    const records = detail.data.follow_up_records ?? [];
    const index = records.findIndex(
      (record) => record.follow_up_record_id === followUpRecordId,
    );
    if (index >= 0) {
      const record = records[index];
      record.is_deleted = true;
      record.deleted_at = generatedAt();
      record.deleted_by_username = "最高管理员";
      record.deletion_reason = "reversed_by_highest_admin";
      return {
        data: record,
        meta: {
          generated_at: generatedAt(),
          source: "mock",
        },
      };
    }
  }

  throw new ApiRequestError(404);
}

function mockClueOrderPhoneResponse(orderId: string): ApiResponse<CluePhoneReveal> {
  const stored = clueCenterResponses.order_details?.[orderId];
  const phoneMasked =
    stored?.data.phone_masked ??
    clueCenterResponses.assignment_rounds.data.rows.find(
      (row) => row.order_id === orderId,
    )?.phone_masked ??
    "";
  const phone = phoneMasked ? "MOCK_PHONE_REDACTED" : "";
  return {
    data: {
      order_id: orderId,
      phone,
      phone_masked: phoneMasked,
    },
    meta: {
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

export function fetchFilterMeta(): Promise<ApiLoadResult<FilterMetaData>> {
  return withMockFallback(
    () => requestJson<FilterMetaData>("/meta/filters"),
    mockMetaResponse,
  );
}

export function fetchStoreRanking({
  month,
  productScope,
  productType,
  limit = 20,
}: {
  month: string;
  productScope: string;
  productType: string;
  limit?: number;
}): Promise<ApiLoadResult<StoreRankingData>> {
  return withMockFallback(
    () =>
      requestJson<StoreRankingData>("/dashboard/store-ranking", {
        month,
        product_scope: productScope,
        product_type: productType,
        limit,
      }),
    () => mockStoreRankingResponse(month, productScope, productType, limit),
  );
}

export function fetchMonthlySettlement({
  storeId,
  month,
  productScope,
  productType,
}: {
  storeId: string;
  month: string;
  productScope: string;
  productType: string;
}): Promise<ApiLoadResult<MonthlySettlementData>> {
  return withMockFallback(
    () =>
      requestJson<MonthlySettlementData>(
        `/stores/${encodeURIComponent(storeId)}/monthly-settlement`,
        {
          month,
          product_scope: productScope,
          product_type: productType,
        },
      ),
    () => mockSettlementResponse(storeId, month, productScope, productType),
  );
}

export function fetchOrderDetails(
  query: DetailQuery,
): Promise<ApiLoadResult<OrderDetailsData>> {
  return withMockFallback(
    () =>
      requestJson<OrderDetailsData>("/order-details", {
        ...query.filters,
        page: query.page,
        page_size: query.pageSize,
      }),
    () => mockOrderDetailsResponse(query),
  );
}

export function fetchSalesDashboard(
  query: SalesDashboardQuery,
): Promise<ApiLoadResult<SalesDashboardData>> {
  return withMockFallback(
    () => requestSalesDashboard(query),
    () => mockSalesDashboardResponse(query),
  );
}

export function fetchClueFilters(): Promise<ApiLoadResult<ClueFilterMetadata>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getFilters());
  }
  return withMockFallback(
    () => requestJson<ClueFilterMetadata>("/clues/filters"),
    mockClueFiltersResponse,
  );
}

export function fetchClueOverview(
  filters: ClueOverviewFilters,
): Promise<ApiLoadResult<ClueOverviewMetrics>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getOverview(filters));
  }
  return withMockFallback(
    () => requestJson<ClueOverviewMetrics>("/clues/overview", { ...filters }),
    () => mockClueOverviewResponse(filters),
  );
}

export function exportOrderDetails(filters: DetailFilters): Promise<void> {
  return requestDownload("/order-details/export", { ...filters });
}

export function fetchClueAssignmentRounds(
  query: ClueRoundQuery,
): Promise<ApiLoadResult<ClueAssignmentRoundData>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getAssignmentRounds(query));
  }
  return withMockFallback(
    () =>
      requestJson<ClueAssignmentRoundData>("/clues/assignment-rounds", {
        ...query.filters,
        page: query.page,
        page_size: query.pageSize,
      }),
    () => mockClueAssignmentRoundsResponse(query),
  );
}

export function fetchClueOrderDetail(
  orderId: string,
): Promise<ApiLoadResult<ClueOrderDetail>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getOrderDetail(orderId));
  }
  return withMockFallback(
    () =>
      requestJson<ClueOrderDetail>(
        `/clues/orders/${encodeURIComponent(orderId)}`,
      ),
    () => mockClueOrderDetailResponse(orderId),
  );
}

export function exportClueAssignmentRounds(
  filters: ClueOverviewFilters,
): Promise<void> {
  if (CLUE_DEMO_MODE) {
    const file = clueDemoRepository.exportAssignmentRounds(filters);
    const blob = new Blob([file.content], { type: file.mimeType });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = file.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
    return Promise.resolve();
  }
  return requestDownload("/clues/assignment-rounds/export", { ...filters });
}

export function fetchClueOrderPhone(
  orderId: string,
): Promise<ApiLoadResult<CluePhoneReveal>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getOrderPhone(orderId));
  }
  return withMockFallback(
    () =>
      requestJson<CluePhoneReveal>(
        `/clues/orders/${encodeURIComponent(orderId)}/phone`,
      ),
    () => mockClueOrderPhoneResponse(orderId),
    { fallbackOnError: false },
  );
}

export function saveClueFollowUp(
  orderId: string,
  payload: ClueFollowUpPayload,
): Promise<ApiLoadResult<ClueFollowUpRecord>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.saveFollowUp(orderId, payload));
  }
  return withMockFallback(
    () =>
      sendJson<ClueFollowUpRecord>(
        `/clues/orders/${encodeURIComponent(orderId)}/follow-up`,
        {
          body: payload,
          method: "POST",
        },
      ),
    () => mockClueFollowUpResponse(orderId, payload),
    { fallbackOnError: false },
  );
}

export function deleteClueFollowUpRecord(
  followUpRecordId: string,
): Promise<ApiLoadResult<ClueFollowUpRecord>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() =>
      clueDemoRepository.deleteFollowUpRecord(followUpRecordId),
    );
  }
  return withMockFallback(
    () =>
      sendJson<ClueFollowUpRecord>(
        `/clues/follow-up-records/${encodeURIComponent(followUpRecordId)}`,
        { method: "DELETE" },
      ),
    () => mockDeleteClueFollowUpRecordResponse(followUpRecordId),
    { fallbackOnError: false },
  );
}

export async function loginAdmin(
  usernameOrPassword: string,
  password?: string,
): Promise<ApiLoadResult<AdminUser>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => ({
      data: CLUE_DEMO_ADMIN_USER,
      meta: { generated_at: generatedAt(), source: "demo" },
    }));
  }
  const username = password === undefined ? "admin" : usernameOrPassword;
  const resolvedPassword = password === undefined ? usernameOrPassword : password;
  return {
    ...(await sendJson<AdminUser>("/auth/login", {
      body: { username, password: resolvedPassword },
    })),
    usingMock: false,
  };
}

export async function fetchAdminSession(): Promise<ApiLoadResult<AdminUser>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => ({
      data: CLUE_DEMO_ADMIN_USER,
      meta: { generated_at: generatedAt(), source: "demo" },
    }));
  }
  return { ...(await requestJson<AdminUser>("/auth/me")), usingMock: false };
}

export async function logoutAdmin(): Promise<ApiLoadResult<AdminUser>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => ({
      data: CLUE_DEMO_ADMIN_USER,
      meta: { generated_at: generatedAt(), source: "demo" },
    }));
  }
  return {
    ...(await sendJson<AdminUser>("/auth/logout", { method: "POST" })),
    usingMock: false,
  };
}

export async function initializeAccount(
  payload: AccountActivationPayload,
): Promise<ApiLoadResult<AdminUser>> {
  return {
    ...(await sendJson<AdminUser>("/auth/initialize", { body: payload })),
    usingMock: false,
  };
}

export async function checkAccountActivationStatus(
  payload: AccountActivationCheckPayload,
): Promise<ApiLoadResult<AccountActivationCheckData>> {
  return {
    ...(await sendJson<AccountActivationCheckData>("/auth/activation-status", {
      body: payload,
    })),
    usingMock: false,
  };
}

export async function resetAccountPassword(
  payload: AccountPasswordResetPayload,
): Promise<ApiLoadResult<AdminUser>> {
  return {
    ...(await sendJson<AdminUser>("/auth/reset-password", { body: payload })),
    usingMock: false,
  };
}

export async function changeCurrentUserPassword(
  payload: AccountPasswordPayload,
): Promise<ApiLoadResult<AdminUser>> {
  return {
    ...(await sendJson<AdminUser>("/auth/change-password", { body: payload })),
    usingMock: false,
  };
}

export async function submitFeedback(
  payload: FeedbackSubmissionPayload,
): Promise<ApiLoadResult<FeedbackSubmissionReceipt>> {
  return {
    ...(await sendJson<FeedbackSubmissionReceipt>("/feedback", { body: payload })),
    usingMock: false,
  };
}

export async function fetchFeedback({
  category,
  page,
  pageSize,
  q,
  status,
}: {
  category?: FeedbackCategory | "";
  page: number;
  pageSize: number;
  q?: string;
  status?: FeedbackStatus | "";
}): Promise<ApiLoadResult<FeedbackListData>> {
  return {
    ...(await requestJson<FeedbackListData>("/admin/feedback", {
      category,
      page,
      page_size: pageSize,
      q,
      status,
    })),
    usingMock: false,
  };
}

export async function updateFeedbackStatus(
  feedbackId: string,
  status: FeedbackStatus,
): Promise<ApiLoadResult<FeedbackRow>> {
  return {
    ...(await sendJson<FeedbackRow>(
      `/admin/feedback/${encodeURIComponent(feedbackId)}/status`,
      {
        body: { status },
        method: "PUT",
      },
    )),
    usingMock: false,
  };
}

export async function fetchAccounts(): Promise<ApiLoadResult<AccountListData>> {
  return {
    ...(await requestJson<AccountListData>("/admin/accounts")),
    usingMock: false,
  };
}

export async function fetchUnactivatedAccountStores(
  q?: string,
): Promise<ApiLoadResult<UnactivatedStoreAccountListData>> {
  return {
    ...(await requestJson<UnactivatedStoreAccountListData>(
      "/admin/accounts/unactivated-stores",
      { q },
    )),
    usingMock: false,
  };
}

export async function createAccount(
  payload: AccountUpsertPayload,
): Promise<ApiLoadResult<AccountRow>> {
  return {
    ...(await sendJson<AccountRow>("/admin/accounts", { body: payload })),
    usingMock: false,
  };
}

export async function updateAccount(
  userId: string,
  payload: AccountUpsertPayload,
): Promise<ApiLoadResult<AccountRow>> {
  return {
    ...(await sendJson<AccountRow>(`/admin/accounts/${encodeURIComponent(userId)}`, {
      body: payload,
      method: "PUT",
    })),
    usingMock: false,
  };
}

export async function resetManagedAccountPassword(
  userId: string,
  payload: AccountPasswordPayload,
): Promise<ApiLoadResult<AccountRow>> {
  return {
    ...(await sendJson<AccountRow>(
      `/admin/accounts/${encodeURIComponent(userId)}/reset-password`,
      { body: payload },
    )),
    usingMock: false,
  };
}

export async function fetchAccessControl(): Promise<ApiLoadResult<AccessControlData>> {
  return {
    ...(await requestJson<AccessControlData>("/admin/access-control")),
    usingMock: false,
  };
}

export async function updateAccountPagePermissions(
  userId: string,
  payload: AccountPagePermissionPayload,
): Promise<ApiLoadResult<AccountRow>> {
  return {
    ...(await sendJson<AccountRow>(
      `/admin/accounts/${encodeURIComponent(userId)}/page-permissions`,
      { body: payload, method: "PUT" },
    )),
    usingMock: false,
  };
}

export async function restoreAccountPagePermissions(
  userId: string,
): Promise<ApiLoadResult<AccountRow>> {
  return {
    ...(await sendJson<AccountRow>(
      `/admin/accounts/${encodeURIComponent(userId)}/page-permissions/restore`,
      { method: "POST" },
    )),
    usingMock: false,
  };
}

export async function previewRolePagePermissions(
  role: "admin" | "store",
  pageKeys: string[],
): Promise<ApiLoadResult<RolePermissionImpactData>> {
  return {
    ...(await sendJson<RolePermissionImpactData>(
      `/admin/access-control/roles/${role}/preview`,
      { body: { page_keys: pageKeys, confirmed: false } },
    )),
    usingMock: false,
  };
}

export async function updateRolePagePermissions(
  role: "admin" | "store",
  pageKeys: string[],
): Promise<ApiLoadResult<RolePermissionImpactData>> {
  return {
    ...(await sendJson<RolePermissionImpactData>(
      `/admin/access-control/roles/${role}`,
      { body: { page_keys: pageKeys, confirmed: true }, method: "PUT" },
    )),
    usingMock: false,
  };
}

export async function fetchAccountPermissionAuditLogs(
  filters: {
    targetUserId?: string;
    action?: string;
    actorUsername?: string;
    createdFrom?: string;
    createdTo?: string;
  } = {},
): Promise<ApiLoadResult<AccountPermissionAuditListData>> {
  return {
    ...(await requestJson<AccountPermissionAuditListData>(
      "/admin/access-control/audit-logs",
      {
        target_user_id: filters.targetUserId,
        action: filters.action,
        actor_username: filters.actorUsername,
        created_from: filters.createdFrom,
        created_to: filters.createdTo,
      },
    )),
    usingMock: false,
  };
}

export async function fetchSkuRules({
  page,
  pageSize,
  productScope,
  q,
}: {
  page: number;
  pageSize: number;
  productScope?: string;
  q?: string;
}): Promise<ApiLoadResult<SkuRuleListData>> {
  return {
    ...(await requestJson<SkuRuleListData>("/admin/sku-rules", {
      page,
      page_size: pageSize,
      product_scope: productScope,
      q,
    })),
    usingMock: false,
  };
}

export async function lookupSkuRules(
  skuIds: string[],
): Promise<ApiLoadResult<SkuRuleLookupData>> {
  return {
    ...(await sendJson<SkuRuleLookupData>("/admin/sku-rules/lookup", {
      body: { sku_ids: skuIds },
      method: "POST",
    })),
    usingMock: false,
  };
}

export async function saveSkuRules(
  rules: SkuProductCommissionRule[],
): Promise<ApiLoadResult<SkuRuleUpdateResult>> {
  return {
    ...(await sendJson<SkuRuleUpdateResult>("/admin/sku-rules", {
      body: { rules },
      method: "PUT",
    })),
    usingMock: false,
  };
}

export async function fetchNonCommissionOwnerAccounts(): Promise<
  ApiLoadResult<NonCommissionOwnerAccountListData>
> {
  return {
    ...(await requestJson<NonCommissionOwnerAccountListData>(
      "/admin/non-commission-owner-accounts",
    )),
    usingMock: false,
  };
}

export async function saveNonCommissionOwnerAccounts(
  ownerAccountNames: string[],
): Promise<ApiLoadResult<NonCommissionOwnerAccountUpdateResult>> {
  return {
    ...(await sendJson<NonCommissionOwnerAccountUpdateResult>(
      "/admin/non-commission-owner-accounts",
      {
        body: {
          accounts: ownerAccountNames.map((owner_account_name) => ({
            owner_account_name,
          })),
        },
        method: "PUT",
      },
    )),
    usingMock: false,
  };
}

export async function fetchCommissionRulesSummary(): Promise<
  ApiLoadResult<CommissionRulesSummaryData>
> {
  return withMockFallback(
    () => requestJson<CommissionRulesSummaryData>("/commission-rules/summary"),
    mockCommissionRulesSummaryResponse,
  );
}

export async function fetchSyncAdmin(): Promise<ApiLoadResult<SyncAdminData>> {
  return {
    ...(await requestJson<SyncAdminData>("/admin/sync")),
    usingMock: false,
  };
}

export async function saveSyncConfig(
  config: SyncConfigUpdate,
): Promise<ApiLoadResult<SyncAdminData>> {
  return {
    ...(await sendJson<SyncAdminData>("/admin/sync/config", {
      body: config,
      method: "PUT",
    })),
    usingMock: false,
  };
}

export async function runManualSync({
  target,
  days,
}: {
  target: ManualSyncTarget;
  days?: number;
}): Promise<ApiLoadResult<ManualSyncResult>> {
  return {
    ...(await sendJson<ManualSyncResult>("/admin/sync/run", {
      body: { target, days },
      method: "POST",
    })),
    usingMock: false,
  };
}

export async function rebuildClueCenterMaterialization(): Promise<
  ApiLoadResult<ClueCenterMaterializationResult>
> {
  return {
    ...(await sendJson<ClueCenterMaterializationResult>("/admin/sync/clue-center/rebuild", {
      method: "POST",
    })),
    usingMock: false,
  };
}

export async function fetchClueAllocationEligibleLeads(): Promise<
  ApiLoadResult<ClueAllocationEligibleLeadData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getEligibleLeads());
  }
  return {
    ...(await requestJson<ClueAllocationEligibleLeadData>(
      "/admin/clue-allocation/eligible-leads",
    )),
    usingMock: false,
  };
}

export interface ClueHeadquartersPoolFilters extends QueryParams {
  pool_status?: string;
  reason?: string;
  entered_date_start?: string;
  entered_date_end?: string;
  order_status?: string;
  order_id?: string;
  page?: number;
  page_size?: number;
}

export async function fetchClueHeadquartersPool(
  filters: ClueHeadquartersPoolFilters = {},
): Promise<
  ApiLoadResult<ClueHeadquartersPoolData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getHeadquartersPool(filters));
  }
  return {
    ...(await requestJson<ClueHeadquartersPoolData>(
      "/admin/clue-allocation/headquarters-pool",
      filters,
    )),
    usingMock: false,
  };
}

export async function fetchClueAllocationCycles(): Promise<
  ApiLoadResult<ClueAllocationCycleData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getCycles());
  }
  return {
    ...(await requestJson<ClueAllocationCycleData>(
      "/admin/clue-allocation/cycles",
    )),
    usingMock: false,
  };
}

export async function fetchClueAllocationAuditLogs(): Promise<
  ApiLoadResult<ClueAllocationAuditLogData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getAuditLogs());
  }
  return {
    ...(await requestJson<ClueAllocationAuditLogData>(
      "/admin/clue-allocation/audit-logs",
    )),
    usingMock: false,
  };
}

export async function previewClueAllocationCycle(
  payload: ClueAllocationCyclePreviewRequest,
): Promise<ApiLoadResult<ClueAllocationCyclePreview>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.previewCycle(payload));
  }
  return {
    ...(await sendJson<ClueAllocationCyclePreview>(
      "/admin/clue-allocation/cycles/preview",
      { body: payload, method: "POST" },
    )),
    usingMock: false,
  };
}

export async function runClueAllocationTrial(
  payload: ClueAllocationCycleRequest,
): Promise<ApiLoadResult<ClueAllocationCycleExecution>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.runTrial(payload));
  }
  return {
    ...(await sendJson<ClueAllocationCycleExecution>(
      "/admin/clue-allocation/cycles/trial",
      { body: payload, method: "POST" },
    )),
    usingMock: false,
  };
}

export async function rebuildClueAllocationTrial(
  payload: ClueAllocationCycleRebuildRequest,
): Promise<ApiLoadResult<ClueAllocationCycleExecution>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.rebuildTrial(payload));
  }
  return {
    ...(await sendJson<ClueAllocationCycleExecution>(
      "/admin/clue-allocation/cycles/rebuild",
      { body: payload, method: "POST" },
    )),
    usingMock: false,
  };
}

export async function fetchClueAllocationRules(): Promise<
  ApiLoadResult<ClueAllocationRuleListData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getRules());
  }
  return {
    ...(await requestJson<ClueAllocationRuleListData>("/admin/clue-allocation/rules")),
    usingMock: false,
  };
}

export async function fetchClueAllocationRuleDetail(
  ruleId: string,
): Promise<ApiLoadResult<ClueAllocationRuleDetailData>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getRuleDetail(ruleId));
  }
  return {
    ...(await requestJson<ClueAllocationRuleDetailData>(
      `/admin/clue-allocation/rules/${encodeURIComponent(ruleId)}`,
    )),
    usingMock: false,
  };
}

export async function fetchClueAllocationDecisions(): Promise<
  ApiLoadResult<ClueAllocationDecisionData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getDecisions());
  }
  return {
    ...(await requestJson<ClueAllocationDecisionData>("/admin/clue-allocation/decisions")),
    usingMock: false,
  };
}

export async function fetchClueAllocationStoreScores(): Promise<
  ApiLoadResult<StoreScoreSnapshotData>
> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getStoreScores());
  }
  return {
    ...(await requestJson<StoreScoreSnapshotData>("/admin/clue-allocation/store-scores")),
    usingMock: false,
  };
}

export async function createClueAllocationRule(
  payload: ClueAllocationRuleCreate,
): Promise<ApiLoadResult<ClueAllocationRule>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.createRule(payload));
  }
  return {
    ...(await sendJson<ClueAllocationRule>("/admin/clue-allocation/rules", {
      body: payload,
      method: "POST",
    })),
    usingMock: false,
  };
}

export async function createClueAllocationRuleVersion(
  ruleId: string,
  payload: ClueAllocationRuleVersionWrite,
): Promise<ApiLoadResult<ClueAllocationRuleVersion>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() =>
      clueDemoRepository.createRuleVersion(ruleId, payload),
    );
  }
  return {
    ...(await sendJson<ClueAllocationRuleVersion>(
      `/admin/clue-allocation/rules/${encodeURIComponent(ruleId)}/versions`,
      { body: payload, method: "POST" },
    )),
    usingMock: false,
  };
}

export async function publishClueAllocationRuleVersion(
  ruleVersionId: string,
): Promise<ApiLoadResult<ClueAllocationRuleVersion>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() =>
      clueDemoRepository.publishRuleVersion(ruleVersionId),
    );
  }
  return {
    ...(await sendJson<ClueAllocationRuleVersion>(
      `/admin/clue-allocation/rule-versions/${encodeURIComponent(ruleVersionId)}/publish`,
      { method: "POST" },
    )),
    usingMock: false,
  };
}

export async function retireClueAllocationRuleVersion(
  ruleVersionId: string,
): Promise<ApiLoadResult<ClueAllocationRuleVersion>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() =>
      clueDemoRepository.retireRuleVersion(ruleVersionId),
    );
  }
  return {
    ...(await sendJson<ClueAllocationRuleVersion>(
      `/admin/clue-allocation/rule-versions/${encodeURIComponent(ruleVersionId)}/retire`,
      { method: "POST" },
    )),
    usingMock: false,
  };
}

export async function fetchProductTypeVisibility(): Promise<
  ApiLoadResult<ProductTypeVisibilityData>
> {
  return {
    ...(await requestJson<ProductTypeVisibilityData>("/admin/product-type-visibility")),
    usingMock: false,
  };
}

export async function saveProductTypeVisibility(
  payload: ProductTypeVisibilityUpdate,
): Promise<ApiLoadResult<ProductTypeVisibilityData>> {
  return {
    ...(await sendJson<ProductTypeVisibilityData>("/admin/product-type-visibility", {
      body: payload,
      method: "PUT",
    })),
    usingMock: false,
  };
}

export { defaultMonth, defaultStore, DEFAULT_DETAIL_PAGE_SIZE };
