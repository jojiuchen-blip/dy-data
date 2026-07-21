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
import type {
  ApiResponse,
  AccountActivationCheckData,
  AccountActivationCheckPayload,
  AccountActivationPayload,
  AccountListData,
  AccountPasswordResetPayload,
  AccountPasswordPayload,
  AccountRow,
  AccountUpsertPayload,
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
  FeeDirection,
  MonthlySettlementData,
  OrderFeeDetailsData,
  PeriodType,
  RankingSortBy,
  SortOrder,
  NonCommissionOwnerAccountListData,
  NonCommissionOwnerAccountUpdateResult,
  OrderDetailsData,
  ProductTypeVisibilityData,
  ProductTypeVisibilityUpdate,
  SelectOption,
  SalesDashboardData,
  SettlementViewData,
  ManualSyncResult,
  ManualSyncTarget,
  ImportBatchCommitData,
  ImportBatchDetailData,
  ImportBatchListData,
  ImportBatchUploadData,
  ProductSyncMode,
  ProductSyncRunDetailData,
  ProductSyncRunListData,
  ProductSyncTriggerData,
  SkuFeeRuleCreate,
  SkuFeeRuleItem,
  SkuFeeRuleListData,
  SkuProductItem,
  SkuProductListData,
  SkuProductManualUpdate,
  SkuSyncHistoryListData,
  SkuProductCommissionRule,
  SkuRuleListData,
  SkuRuleLookupData,
  SkuRuleUpdateResult,
  SyncAdminData,
  SyncConfigUpdate,
  StoreRankingData,
  SettlementFilterMetaData,
  SettlementMonthlyData,
  SettlementStoreRankingData,
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
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";
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
  code?: string;
  requestId?: string;
  fieldErrors?: unknown;
  returnPath?: string;

  constructor(status: number, message?: string, detail?: Record<string, unknown>) {
    super(message ?? `API ${status}`);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = typeof detail?.code === "string" ? detail.code : undefined;
    this.requestId = typeof detail?.requestId === "string" ? detail.requestId : undefined;
    this.fieldErrors = detail?.fieldErrors ?? detail?.errors;
    this.returnPath = typeof detail?.returnPath === "string" ? detail.returnPath : undefined;
  }
}

async function apiRequestError(response: Response): Promise<ApiRequestError> {
  let payload: unknown;
  try {
    payload = await response.clone().json();
  } catch {
    payload = undefined;
  }
  const envelope = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : undefined;
  const detailValue = envelope?.detail ?? envelope?.error ?? envelope;
  const detail = detailValue && typeof detailValue === "object"
    ? detailValue as Record<string, unknown>
    : undefined;
  const message = typeof detailValue === "string"
    ? detailValue
    : typeof detail?.message === "string"
      ? detail.message
      : undefined;
  return new ApiRequestError(response.status, message, detail);
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
  const response = await fetch(apiUrl(path, params), {
    credentials: "include",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw await apiRequestError(response);
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
  const response = await fetch(apiUrl(path, params), {
    credentials: "include",
    headers: { Accept: "text/csv" },
  });

  if (!response.ok) {
    throw await apiRequestError(response);
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
    headers,
    method = "POST",
    params,
  }: {
    body?: unknown;
    headers?: Record<string, string>;
    method?: "DELETE" | "POST" | "PUT";
    params?: QueryParams;
  } = {},
): Promise<ApiResponse<T>> {
  const response = await fetch(apiUrl(path, params), {
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...headers,
    },
    method,
  });

  if (!response.ok) {
    throw await apiRequestError(response);
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
    async () => {
      const response = await requestJson<SettlementFilterMetaData>("/meta/filters");
      return {
        ...response,
        data: {
          stores: response.data.stores.map((store) => ({
            store_id: store.storeId,
            store_name: store.storeName,
          })),
          product_scopes: response.data.productScopes,
          product_scope_type_map: response.data.productScopeTypeMap,
          product_types: response.data.productTypes,
          default_product_type: response.data.defaultProductType,
          sale_months: response.data.saleMonths,
          verify_months: response.data.verifyMonths,
        },
      };
    },
    mockMetaResponse,
  );
}

async function sendForm<T>(path: string, body: FormData): Promise<ApiResponse<T>> {
  const response = await fetch(apiUrl(path), {
    body,
    credentials: "include",
    headers: { Accept: "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw await apiRequestError(response);
  }
  return response.json() as Promise<ApiResponse<T>>;
}

function mockSettlementFilterMetaResponse(): ApiResponse<SettlementFilterMetaData> {
  const legacy = mockMetaResponse().data;
  const targetDemoStore = {
    storeId: "ST-SH-001",
    storeName: "上海浦东体验中心",
  };
  return {
    data: {
      stores: [
        targetDemoStore,
        ...legacy.stores
          .filter(
            (store) =>
              Boolean(store.store_id) && store.store_id !== targetDemoStore.storeId,
          )
          .map((store) => ({
            storeId: store.store_id,
            storeName: store.store_name,
          })),
      ],
      productScopes: legacy.product_scopes ?? ["all"],
      productScopeTypeMap: legacy.product_scope_type_map ?? {},
      productTypes: legacy.product_types,
      defaultProductType: legacy.default_product_type,
      saleMonths: legacy.sale_months,
      verifyMonths: legacy.verify_months,
      statementMonths: legacy.verify_months,
      periodTypes: ["MONTHLY", "CUMULATIVE"],
      feeDirections: ["PROMOTION", "MANAGEMENT"],
      formalPeriodStartMonth: "2026-08",
      timezone: "Asia/Shanghai",
    },
    meta: { generated_at: generatedAt(), source: "mock" },
  };
}

export function fetchSettlementFilterMeta(): Promise<
  ApiLoadResult<SettlementFilterMetaData>
> {
  return withMockFallback(
    () => requestJson<SettlementFilterMetaData>("/meta/filters"),
    mockSettlementFilterMetaResponse,
    { fallbackOnError: false },
  );
}

export function fetchSettlementStoreRanking({
  periodType,
  periodKey,
  productScope,
  productType,
  q,
  sortBy,
  sortOrder,
  page,
  pageSize,
}: {
  periodType: PeriodType;
  periodKey: string;
  productScope: string;
  productType: string;
  q?: string;
  sortBy?: RankingSortBy;
  sortOrder?: SortOrder;
  page: number;
  pageSize: number;
}): Promise<ApiLoadResult<SettlementStoreRankingData>> {
  return withMockFallback(
    () =>
      requestJson<SettlementStoreRankingData>("/dashboard/store-ranking", {
        periodType,
        periodKey,
        productScope,
        productType,
        q,
        sortBy,
        sortOrder,
        page,
        pageSize,
      }),
    () => ({
      data: {
        periodType,
        periodKey,
        productScope,
        productType,
        scopeMode: "AUTHORIZED",
        totals: {
          salesOrderCount: 36,
          salesAmountCent: 428600,
          verifiedOrderCount: 31,
          verifiedAmountCent: 368000,
          promotionNetFeeCent: 28640,
          managementNetFeeCent: 12480,
          netSettlementReferenceCent: 16160,
        },
        list: [{
          rank: 1,
          storeId: "ST-SH-001",
          storeName: "上海浦东体验中心",
          salesOrderCount: 36,
          salesAmountCent: 428600,
          verifiedOrderCount: 31,
          verifiedAmountCent: 368000,
          promotionNetFeeCent: 28640,
          managementNetFeeCent: 12480,
          netSettlementReferenceCent: 16160,
        }],
        total: 1,
        page,
        pageSize,
      },
      meta: { generated_at: generatedAt(), source: "mock" },
    }),
    { fallbackOnError: false },
  );
}

export function fetchSettlementMonthly({
  storeId,
  month,
  productScope,
  productType,
}: {
  storeId: string;
  month: string;
  productScope: string;
  productType: string;
}): Promise<ApiLoadResult<SettlementMonthlyData>> {
  return withMockFallback(
    () =>
      requestJson<SettlementMonthlyData>(
        `/stores/${encodeURIComponent(storeId)}/monthly-settlement`,
        { month, productScope, productType },
      ),
    () => ({
      data: {
        store: { storeId, storeName: "上海浦东体验中心" },
        month,
        productScope,
        productType,
        isFormalPeriod: month >= "2026-08",
        statement: null,
        metrics: {
          salesOrderCount: 36,
          salesAmountCent: 428600,
          verifiedOrderCount: 31,
          verifiedAmountCent: 368000,
          promotionBaseCent: 358000,
          promotionOriginalFeeCent: 28640,
          promotionAdjustmentFeeCent: -800,
          promotionNetFeeCent: 27840,
          managementBaseCent: 312000,
          managementOriginalFeeCent: 12480,
          managementAdjustmentFeeCent: 0,
          managementNetFeeCent: 12480,
          netSettlementReferenceCent: 15360,
        },
        lines: [
          { statementLineId: null, feeDirection: "PROMOTION", productScope, productType, originalEntryCount: 28, adjustmentEntryCount: 1, originalBaseCent: 368000, adjustmentBaseCent: -10000, netBaseCent: 358000, originalFeeCent: 28640, adjustmentFeeCent: -800, netFeeCent: 27840, minFeeRate: "0.080000", maxFeeRate: "0.080000", ruleVersionCount: 1, feeRates: ["0.080000"], ruleVersions: ["V2026.08.1"] },
          { statementLineId: null, feeDirection: "MANAGEMENT", productScope, productType, originalEntryCount: 24, adjustmentEntryCount: 0, originalBaseCent: 312000, adjustmentBaseCent: 0, netBaseCent: 312000, originalFeeCent: 12480, adjustmentFeeCent: 0, netFeeCent: 12480, minFeeRate: "0.040000", maxFeeRate: "0.040000", ruleVersionCount: 1, feeRates: ["0.040000"], ruleVersions: ["V2026.08.1"] },
        ],
      },
      meta: { generated_at: generatedAt(), source: "mock" },
    }),
    { fallbackOnError: false },
  );
}

export interface OrderFeeDetailsQuery {
  statementId?: string;
  statementLineId?: string;
  storeId?: string;
  month?: string;
  saleMonth?: string;
  verifyMonth?: string;
  feeDirection: FeeDirection;
  productScope?: string;
  productType?: string;
  feeRates?: string[];
  ruleVersions?: string[];
  dataStatus?: string;
  q?: string;
  page: number;
  pageSize: number;
}

export function fetchOrderFeeDetails(
  query: OrderFeeDetailsQuery,
): Promise<ApiLoadResult<OrderFeeDetailsData>> {
  return withMockFallback(
    () => requestJson<OrderFeeDetailsData>("/order-fee-details", { ...query }),
    () => ({
      data: {
        context: {
          ...query,
          productScope: query.productScope ?? "all",
          productType: query.productType ?? "all",
          feeRates: query.feeRates ?? [],
          ruleVersions: query.ruleVersions ?? [],
        },
        list: [{
          feeResultId: "fee-demo-1",
          orderId: "ORDER-DEMO-001",
          couponId: "COUPON-DEMO-001",
          feeDirection: query.feeDirection,
          originalBusinessMonth: query.month ?? "2026-08",
          saleMonth: "2026-08",
          verifyMonth: "2026-08",
          saleTime: "2026-08-12T10:00:00+08:00",
          verifyTime: "2026-08-18T15:30:00+08:00",
          saleStoreId: query.storeId ?? "ST-SH-001",
          saleStoreName: "上海浦东体验中心",
          verifyStoreId: "ST-SH-002",
          verifyStoreName: "上海虹桥服务中心",
          skuId: "SKU-DEMO-001",
          productName: "精诚养车基础保养服务",
          productScope: query.productScope ?? "all",
          productType: query.productType ?? "all",
          saleChannel: "LIVE",
          sourceAmountCent: 12800,
          refundedAmountCent: 0,
          originalBaseCent: 12800,
          feeRate: query.feeDirection === "PROMOTION" ? "0.080000" : "0.040000",
          originalFeeCent: query.feeDirection === "PROMOTION" ? 1024 : 512,
          adjustmentBaseCent: 0,
          adjustmentFeeCent: 0,
          adjustedNetBaseCent: 12800,
          adjustedNetFeeCent: query.feeDirection === "PROMOTION" ? 1024 : 512,
          ruleVersion: "V2026.08.1",
          resultStatus: "VALID",
          dataStatus: "VALID",
          adjustments: [],
        }],
        total: 1,
        page: query.page,
        pageSize: query.pageSize,
      },
      meta: { generated_at: generatedAt(), source: "mock" },
    }),
    { fallbackOnError: false },
  );
}

export function exportOrderFeeDetails(query: OrderFeeDetailsQuery): Promise<void> {
  const { page: _page, pageSize: _pageSize, ...exportQuery } = query;
  return requestDownload("/order-fee-details/export", exportQuery);
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
  return withMockFallback(
    () => requestJson<ClueFilterMetadata>("/clues/filters"),
    mockClueFiltersResponse,
  );
}

export function fetchClueOverview(
  filters: ClueOverviewFilters,
): Promise<ApiLoadResult<ClueOverviewMetrics>> {
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
  return requestDownload("/clues/assignment-rounds/export", { ...filters });
}

export function fetchClueOrderPhone(
  orderId: string,
): Promise<ApiLoadResult<CluePhoneReveal>> {
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
  return { ...(await requestJson<AdminUser>("/auth/me")), usingMock: false };
}

export async function logoutAdmin(): Promise<ApiLoadResult<AdminUser>> {
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

export function createIdempotencyKey(prefix: string): string {
  const suffix = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

export async function fetchSkuProducts(params: {
  page?: number;
  pageSize?: number;
  q?: string;
  productScope?: string;
  productType?: string;
  productStatus?: string;
} = {}): Promise<ApiLoadResult<SkuProductListData>> {
  return {
    ...(await requestJson<SkuProductListData>("/admin/sku-products", params)),
    usingMock: false,
  };
}

export async function updateSkuProduct(
  skuId: string,
  payload: SkuProductManualUpdate,
): Promise<ApiLoadResult<SkuProductItem>> {
  return {
    ...(await sendJson<SkuProductItem>(
      `/admin/sku-products/${encodeURIComponent(skuId)}`,
      { body: payload, method: "PUT" },
    )),
    usingMock: false,
  };
}

export async function fetchSkuFeeRules(params: {
  page?: number;
  pageSize?: number;
  q?: string;
  skuId?: string;
  ruleStatus?: string;
  asOfDate?: string;
} = {}): Promise<ApiLoadResult<SkuFeeRuleListData>> {
  return {
    ...(await requestJson<SkuFeeRuleListData>("/admin/sku-fee-rules", params)),
    usingMock: false,
  };
}

export async function publishSkuFeeRule(
  payload: SkuFeeRuleCreate,
  idempotencyKey: string,
): Promise<ApiLoadResult<SkuFeeRuleItem>> {
  return {
    ...(await sendJson<SkuFeeRuleItem>("/admin/sku-fee-rules", {
      body: payload,
      headers: { "Idempotency-Key": idempotencyKey },
    })),
    usingMock: false,
  };
}

export async function fetchSkuFeeRuleImports(params: {
  page?: number;
  pageSize?: number;
  batchStatus?: string;
} = {}): Promise<ApiLoadResult<ImportBatchListData>> {
  return {
    ...(await requestJson<ImportBatchListData>("/admin/sku-fee-rule-imports", params)),
    usingMock: false,
  };
}

export async function uploadSkuFeeRuleImport(
  file: File,
  effectiveDate: string,
): Promise<ApiLoadResult<ImportBatchUploadData>> {
  const form = new FormData();
  form.append("file", file);
  form.append("effectiveDate", effectiveDate);
  return {
    ...(await sendForm<ImportBatchUploadData>("/admin/sku-fee-rule-imports", form)),
    usingMock: false,
  };
}

export async function fetchSkuFeeRuleImportDetail(
  batchId: string,
): Promise<ApiLoadResult<ImportBatchDetailData>> {
  return {
    ...(await requestJson<ImportBatchDetailData>(
      `/admin/sku-fee-rule-imports/${encodeURIComponent(batchId)}`,
      { page: 1, pageSize: 200 },
    )),
    usingMock: false,
  };
}

export async function commitSkuFeeRuleImport(
  batchId: string,
  changeReason: string,
  idempotencyKey: string,
): Promise<ApiLoadResult<ImportBatchCommitData>> {
  return {
    ...(await sendJson<ImportBatchCommitData>(
      `/admin/sku-fee-rule-imports/${encodeURIComponent(batchId)}/commit`,
      {
        body: { changeReason },
        headers: { "Idempotency-Key": idempotencyKey },
      },
    )),
    usingMock: false,
  };
}

export function downloadSkuFeeRuleImportTemplate(): Promise<void> {
  return requestDownload("/admin/sku-fee-rule-imports/template");
}

export function downloadSkuFeeRuleImportResult(batchId: string): Promise<void> {
  return requestDownload(
    `/admin/sku-fee-rule-imports/${encodeURIComponent(batchId)}/result-file`,
  );
}

export async function fetchProductSyncRuns(params: {
  page?: number;
  pageSize?: number;
  status?: string;
  mode?: ProductSyncMode | "";
} = {}): Promise<ApiLoadResult<ProductSyncRunListData>> {
  return {
    ...(await requestJson<ProductSyncRunListData>("/admin/product-sync-runs", params)),
    usingMock: false,
  };
}

export async function triggerProductSync(
  mode: ProductSyncMode,
  reason: string,
  idempotencyKey: string,
): Promise<ApiLoadResult<ProductSyncTriggerData>> {
  return {
    ...(await sendJson<ProductSyncTriggerData>("/admin/product-sync-runs", {
      body: { mode, reason },
      headers: { "Idempotency-Key": idempotencyKey },
    })),
    usingMock: false,
  };
}

export async function fetchProductSyncRunDetail(
  syncRunId: string,
): Promise<ApiLoadResult<ProductSyncRunDetailData>> {
  return {
    ...(await requestJson<ProductSyncRunDetailData>(
      `/admin/product-sync-runs/${encodeURIComponent(syncRunId)}`,
    )),
    usingMock: false,
  };
}

export async function fetchSkuSyncHistory(
  skuId: string,
): Promise<ApiLoadResult<SkuSyncHistoryListData>> {
  return {
    ...(await requestJson<SkuSyncHistoryListData>(
      `/admin/sku-products/${encodeURIComponent(skuId)}/sync-history`,
      { page: 1, pageSize: 50 },
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
  return {
    ...(await requestJson<ClueAllocationEligibleLeadData>(
      "/admin/clue-allocation/eligible-leads",
    )),
    usingMock: false,
  };
}

export async function fetchClueHeadquartersPool(): Promise<
  ApiLoadResult<ClueHeadquartersPoolData>
> {
  return {
    ...(await requestJson<ClueHeadquartersPoolData>(
      "/admin/clue-allocation/headquarters-pool",
    )),
    usingMock: false,
  };
}

export async function fetchClueAllocationCycles(): Promise<
  ApiLoadResult<ClueAllocationCycleData>
> {
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
  return {
    ...(await requestJson<ClueAllocationRuleListData>("/admin/clue-allocation/rules")),
    usingMock: false,
  };
}

export async function fetchClueAllocationRuleDetail(
  ruleId: string,
): Promise<ApiLoadResult<ClueAllocationRuleDetailData>> {
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
  return {
    ...(await requestJson<ClueAllocationDecisionData>("/admin/clue-allocation/decisions")),
    usingMock: false,
  };
}

export async function fetchClueAllocationStoreScores(): Promise<
  ApiLoadResult<StoreScoreSnapshotData>
> {
  return {
    ...(await requestJson<StoreScoreSnapshotData>("/admin/clue-allocation/store-scores")),
    usingMock: false,
  };
}

export async function createClueAllocationRule(
  payload: ClueAllocationRuleCreate,
): Promise<ApiLoadResult<ClueAllocationRule>> {
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
