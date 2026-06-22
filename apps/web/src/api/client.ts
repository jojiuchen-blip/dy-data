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
  AccountListData,
  AccountPasswordPayload,
  AccountRow,
  AccountSelfServicePayload,
  AccountUpsertPayload,
  AdminUser,
  ClueAssignmentRoundData,
  ClueFilterMetadata,
  ClueOrderDetail,
  ClueOverviewFilters,
  ClueOverviewMetrics,
  CluePhoneReveal,
  ClueReassignRuleData,
  ClueReassignRuleUpdate,
  ClueRebuildResult,
  CommissionRulesSummaryData,
  DetailFilters,
  FilterMetaData,
  MonthlySettlementData,
  NonCommissionOwnerAccountListData,
  NonCommissionOwnerAccountUpdateResult,
  OrderDetailsData,
  SelectOption,
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
} from "../types/dashboard";
import {
  filterOrderDetails,
  getMonthOptions,
  getProductOptions,
  getRankingRows,
  getRankingTotals,
  getSettlementView,
  getStoreOptions,
} from "../utils/settlement";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";
const DEFAULT_DETAIL_PAGE_SIZE = 50;

type QueryParams = Record<
  string,
  string | number | boolean | null | undefined
>;

export interface ApiLoadResult<T> extends ApiResponse<T> {
  usingMock: boolean;
  fallbackReason?: string;
}

interface DetailQuery {
  filters: DetailFilters;
  page: number;
  pageSize: number;
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
    throw new ApiRequestError(response.status);
  }

  return response.json() as Promise<ApiResponse<T>>;
}

async function sendJson<T>(
  path: string,
  {
    body,
    method = "POST",
    params,
  }: {
    body?: unknown;
    method?: "POST" | "PUT";
    params?: QueryParams;
  } = {},
): Promise<ApiResponse<T>> {
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
): Promise<ApiLoadResult<T>> {
  if (USE_MOCKS) {
    return {
      ...fallback(),
      usingMock: true,
      fallbackReason: "VITE_USE_MOCKS=true，已使用本地 mock 数据。",
    };
  }

  try {
    return { ...(await request()), usingMock: false };
  } catch (error) {
    if (isAuthError(error)) {
      throw error;
    }
    return {
      ...fallback(),
      usingMock: true,
      fallbackReason: `API 不可用，已使用本地 mock 数据。${errorMessage(error)}`,
    };
  }
}

function optionValues(options: SelectOption[]): string[] {
  return options.map((option) => option.value);
}

function mockMetaResponse(): ApiResponse<FilterMetaData> {
  const months = optionValues(getMonthOptions());
  return {
    data: {
      stores: getStoreOptions().map((option) => ({
        store_id: option.value,
        store_name: option.label,
      })),
      product_types: optionValues(getProductOptions()),
      sale_months: months,
      verify_months: months,
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
  productType: string,
  limit: number,
): ApiResponse<StoreRankingData> {
  const rows = getRankingRows(month, productType).slice(0, limit);
  return {
    data: {
      month,
      product_type: productType,
      limit,
      totals: getRankingTotals(month, productType),
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
  productType: string,
): ApiResponse<SettlementViewData> {
  const view = getSettlementView(storeId, month, productType);
  return {
    data: view,
    definitions: page2Definitions,
    meta: {
      ...monthlySummaryResponse.meta,
      source: `mock:${view.source}`,
    },
  };
}

function mockOrderDetailsResponse({
  filters,
  page,
  pageSize,
}: DetailQuery): ApiResponse<OrderDetailsData> {
  const filteredRows = filterOrderDetails(orderDetails, filters);
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

function mockClueFiltersResponse(): ApiResponse<ClueFilterMetadata> {
  return {
    ...clueCenterResponses.filters,
    meta: {
      ...clueCenterResponses.filters.meta,
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockClueOverviewResponse(): ApiResponse<ClueOverviewMetrics> {
  return {
    ...clueCenterResponses.overview,
    meta: {
      ...clueCenterResponses.overview.meta,
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockClueAssignmentRoundsResponse({
  page,
  pageSize,
}: ClueRoundQuery): ApiResponse<ClueAssignmentRoundData> {
  const rows = clueCenterResponses.assignment_rounds.data.rows;
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
  if (stored) {
    return {
      ...stored,
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
      product_name: null,
      product_type: firstRound?.product_type ?? null,
      author_nickname: firstRound?.author_nickname ?? null,
      assigned_city: null,
      assigned_province: null,
      rounds,
    },
    meta: {
      generated_at: generatedAt(),
      source: "mock",
    },
  };
}

function mockClueOrderPhoneResponse(orderId: string): ApiResponse<CluePhoneReveal> {
  const stored = clueCenterResponses.order_details?.[orderId];
  const phoneMasked =
    stored?.data.phone_masked ??
    clueCenterResponses.assignment_rounds.data.rows.find(
      (row) => row.order_id === orderId,
    )?.phone_masked ??
    "";
  const phone = phoneMasked.replace("****", "0000") || "";
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

function mockClueRuleResponse(
  override?: ClueReassignRuleUpdate,
): ApiResponse<ClueReassignRuleData> {
  return {
    data: {
      ...clueCenterResponses.rule.data,
      reassign_sla_hours:
        override?.reassign_sla_hours ??
        clueCenterResponses.rule.data.reassign_sla_hours,
      updated_at: generatedAt(),
    },
    meta: {
      ...clueCenterResponses.rule.meta,
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
  productType,
  limit = 20,
}: {
  month: string;
  productType: string;
  limit?: number;
}): Promise<ApiLoadResult<StoreRankingData>> {
  return withMockFallback(
    () =>
      requestJson<StoreRankingData>("/dashboard/store-ranking", {
        month,
        product_type: productType,
        limit,
      }),
    () => mockStoreRankingResponse(month, productType, limit),
  );
}

export function fetchMonthlySettlement({
  storeId,
  month,
  productType,
}: {
  storeId: string;
  month: string;
  productType: string;
}): Promise<ApiLoadResult<MonthlySettlementData>> {
  return withMockFallback(
    () =>
      requestJson<MonthlySettlementData>(
        `/stores/${encodeURIComponent(storeId)}/monthly-settlement`,
        {
          month,
          product_type: productType,
        },
      ),
    () => mockSettlementResponse(storeId, month, productType),
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
    mockClueOverviewResponse,
  );
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

export function fetchClueOrderPhone(
  orderId: string,
): Promise<ApiLoadResult<CluePhoneReveal>> {
  return withMockFallback(
    () =>
      requestJson<CluePhoneReveal>(
        `/clues/orders/${encodeURIComponent(orderId)}/phone`,
      ),
    () => mockClueOrderPhoneResponse(orderId),
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
  payload: AccountSelfServicePayload,
): Promise<ApiLoadResult<AdminUser>> {
  return {
    ...(await sendJson<AdminUser>("/auth/initialize", { body: payload })),
    usingMock: false,
  };
}

export async function resetAccountPassword(
  payload: AccountSelfServicePayload,
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

export async function fetchAccounts(): Promise<ApiLoadResult<AccountListData>> {
  return {
    ...(await requestJson<AccountListData>("/admin/accounts")),
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

export async function fetchSkuRules({
  page,
  pageSize,
  q,
}: {
  page: number;
  pageSize: number;
  q?: string;
}): Promise<ApiLoadResult<SkuRuleListData>> {
  return {
    ...(await requestJson<SkuRuleListData>("/admin/sku-rules", {
      page,
      page_size: pageSize,
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

export function fetchClueReassignRule(): Promise<ApiLoadResult<ClueReassignRuleData>> {
  return withMockFallback(
    () => requestJson<ClueReassignRuleData>("/admin/clue-reassign-rule"),
    () => mockClueRuleResponse(),
  );
}

export function saveClueReassignRule(
  payload: ClueReassignRuleUpdate,
): Promise<ApiLoadResult<ClueReassignRuleData>> {
  return withMockFallback(
    () =>
      sendJson<ClueReassignRuleData>("/admin/clue-reassign-rule", {
        body: payload,
        method: "PUT",
      }),
    () => mockClueRuleResponse(payload),
  );
}

export function rebuildClues(): Promise<ApiLoadResult<ClueRebuildResult>> {
  return withMockFallback(
    () => sendJson<ClueRebuildResult>("/admin/clues/rebuild", { method: "POST" }),
    () => ({
      ...clueCenterResponses.rebuild,
      meta: {
        ...clueCenterResponses.rebuild.meta,
        generated_at: generatedAt(),
        source: "mock",
      },
    }),
  );
}

export { defaultMonth, defaultStore, DEFAULT_DETAIL_PAGE_SIZE };
