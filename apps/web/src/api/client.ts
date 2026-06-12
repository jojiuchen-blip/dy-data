import {
  defaultMonth,
  defaultStore,
  monthlySummaryResponse,
  orderDetails,
  page1Definitions,
  page2Definitions,
  storeRankingResponse,
} from "../data/mockData";
import type {
  ApiResponse,
  DetailFilters,
  FilterMetaData,
  MonthlySettlementData,
  OrderDetailsData,
  SelectOption,
  SettlementViewData,
  StoreRankingData,
} from "../types/dashboard";
import {
  filterOrderDetails,
  getMonthOptions,
  getProductOptions,
  getRankingRows,
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

export { defaultMonth, defaultStore, DEFAULT_DETAIL_PAGE_SIZE };
