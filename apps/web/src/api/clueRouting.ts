import { ApiRequestError, clearRequestJsonCache } from "./client";
import { userFacingError } from "../utils/userFacingError";

export type ClueRoutingProductScope = "all" | "jingcheng" | "byd";
export type ClueRoutingAction = "publish_list" | "publish_rule" | "enable" | "disable" | "request_auto_list" | "restore_manual_list";
export type ClueRoutingStoreListSource = "manual" | "auto_pending" | "douyin";
export type DouyinStoreScopeStatus = "valid" | "source_error" | "missing_product" | "missing_or_invalid_pois" | "poi_mapping_incomplete" | "no_active_stores";
export type ClueRoutingExpiryAction = "next" | "close";

export interface ClueRoutingPolicy {
  appointment_hours: number;
  further_follow_up_hours: number;
  unreachable_hours: number;
  pending_action: ClueRoutingExpiryAction;
  appointment_action: ClueRoutingExpiryAction;
  further_follow_up_action: ClueRoutingExpiryAction;
  unreachable_action: ClueRoutingExpiryAction;
}

export interface ClueRoutingRuleWrite extends Partial<ClueRoutingPolicy> {
  first_follow_up_sla_hours?: number;
}

export interface ClueRoutingRuleSnapshot {
  rule_version_id: string | null;
  first_follow_up_sla_hours: number;
  follow_up_policy: Partial<ClueRoutingPolicy>;
  can_manage: boolean;
}

export interface ClueRoutingProduct extends ClueRoutingRuleSnapshot {
  product_id: string;
  product_name: string;
  product_scope: Exclude<ClueRoutingProductScope, "all">;
  routing_enabled: boolean;
  store_ids: string[];
  list_version: number | string | null;
  store_list_source?: ClueRoutingStoreListSource;
  douyin_store_scope?: DouyinStoreScopeSummary | null;
}

export interface DouyinStoreScopeSummary {
  status: DouyinStoreScopeStatus;
  checked_at: string;
  last_success_at: string | null;
  store_count: number | null;
}

export interface DouyinStoreScopeDetail {
  product_id: string;
  douyin_store_scope: DouyinStoreScopeSummary | null;
  store_ids: string[];
}

export interface ClueRoutingFilters {
  q: string;
  product_scope: ClueRoutingProductScope;
}

export interface ClueRoutingProductList {
  rows: ClueRoutingProduct[];
  total: number;
  page: number;
  page_size: number;
  can_manage_grants: boolean;
  can_manage_shared_rule?: boolean;
}

export interface ClueRoutingProductListWrite {
  product_id: string;
  store_ids: string[];
}

export interface ClueRoutingBatchWrite {
  product_ids: string[];
  all_matching: boolean;
  filters: ClueRoutingFilters;
  action: ClueRoutingAction;
  store_ids?: string[];
  lists?: ClueRoutingProductListWrite[];
  rules?: ClueRoutingRuleWrite;
  authorization_note?: string;
  expected_list_versions?: Record<string, string | number | null>;
  expected_douyin_scope_checks?: Record<string, string>;
  preview: boolean;
}

export interface ClueRoutingFailure {
  code: string;
  message?: string;
}

export interface ClueRoutingResult {
  product_id: string;
  status: "preview" | "success" | "failed";
  error?: ClueRoutingFailure | null;
  before: Partial<ClueRoutingProduct>;
  after: Partial<ClueRoutingProduct> & { proposed_change?: boolean };
}

export interface ClueRoutingBatchResult {
  results: ClueRoutingResult[];
  total: number;
  succeeded: number;
  failed: number;
}

export interface ClueRoutingGrantSet {
  user_ids: string[];
  users: Array<{ user_id: string; username: string; display_name: string | null }>;
}

export interface ClueRoutingGrants extends ClueRoutingGrantSet {
  product_id: string;
}

export interface SharedClueRoutingRuleResult {
  before: ClueRoutingRuleSnapshot;
  after: ClueRoutingRuleSnapshot;
  status: "preview" | "success";
}

export interface HeadquartersResumeResult {
  status: string;
  selected_store_id: string | null;
  assignment_round_id: string | null;
  reason: string | null;
}

const failureLabels: Record<string, string> = {
  PRODUCT_FORBIDDEN: "该商品不存在或没有管理权限。",
  STORE_IDS_REQUIRED: "请提供商品适用门店名单。",
  UNKNOWN_STORE_IDS: "名单包含无法识别的门店编码，请核对后重试。",
  PUBLISHED_LIST_REQUIRED: "请先发布并确认该商品的有效门店名单。",
  AUTHORIZATION_REQUIRED: "正式开启前须填写业务负责人授权依据。",
  INVALID_RULE: "规则字段不符合允许范围，请检查后重试。",
  PRODUCT_NOT_FOUND: "未找到该商品，请核对商品 ID。",
  CONFLICT: "配置已发生变化，请重新预览。",
  PREVIEW_REQUIRED: "请先预览并确认当前商品名单版本，再正式开启。",
  LIST_VERSION_CHANGED: "名单版本已变化，该商品保持关闭。请重新预览并确认最新名单后开启。",
  DOUYIN_SCOPE_CHANGED: "抖音名单或当前有效名单已更新，请重新预览。",
  PRODUCT_NOT_ENABLED: "本品首次开启前继承精诚共享基座。请先按已确认名单开启，之后可发布独立规则。",
};

export function clueRoutingFailureMessage(failure?: ClueRoutingFailure | null): string {
  if (!failure || !failureLabels[failure.code]) return "该商品处理失败，请刷新并重新预览。";
  // Only the endpoint's allowlisted business failures may carry user-visible detail.
  return failure.message || failureLabels[failure.code];
}

export function clueRoutingRequestError(error: unknown, fallback?: string): string {
  if (error instanceof ApiRequestError && error.code && failureLabels[error.code]) {
    return failureLabels[error.code];
  }
  return userFacingError(error, fallback);
}

export function clueHeadquartersResumeError(error: unknown): string {
  // This command returns reviewed Chinese business refusals in FastAPI detail.
  if (error instanceof ApiRequestError && [400, 404, 409, 422].includes(error.status) && /[\u3400-\u9fff]/.test(error.message)) return error.message;
  return userFacingError(error, "续派未完成，请检查最新订单、适用名单与锚点资料后重试。");
}

function endpoint(path: string, query?: Record<string, string | number>): string {
  const configured = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
  const base = new URL(configured, window.location.origin).toString().replace(/\/$/, "");
  const url = new URL(`${base}${path}`);
  Object.entries(query ?? {}).forEach(([key, value]) => url.searchParams.set(key, String(value)));
  return url.toString();
}

async function request<T>(path: string, options: {
  query?: Record<string, string | number>;
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  signal?: AbortSignal;
  idempotencyKey?: string;
} = {}): Promise<T> {
  const response = await fetch(endpoint(path, options.query), {
    credentials: "include",
    method: options.method ?? "GET",
    signal: options.signal,
    headers: {
      Accept: "application/json",
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const payload: unknown = await response.json().catch(() => null);
  const envelope = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  if (!response.ok) {
    const detailValue = envelope.detail ?? envelope.error ?? envelope;
    const detail = detailValue && typeof detailValue === "object" ? detailValue as Record<string, unknown> : undefined;
    throw new ApiRequestError(response.status, typeof detailValue === "string" ? detailValue : undefined, detail);
  }
  if (!("data" in envelope)) throw new ApiRequestError(502);
  if (options.method && options.method !== "GET" && !(options.body as { preview?: boolean } | undefined)?.preview) {
    clearRequestJsonCache();
  }
  return envelope.data as T;
}

export function fetchClueRoutingProducts(filters: ClueRoutingFilters, page: number, pageSize: number, signal?: AbortSignal) {
  return request<ClueRoutingProductList>("/admin/clue-routing/products", {
    query: { ...filters, page, page_size: pageSize }, signal,
  });
}

export function fetchDouyinStoreScope(productId: string, signal?: AbortSignal) {
  return request<DouyinStoreScopeDetail>(`/admin/clue-routing/products/${encodeURIComponent(productId)}/douyin-store-scope`, { signal });
}

export function submitClueRoutingBatch(body: ClueRoutingBatchWrite, idempotencyKey?: string) {
  return request<ClueRoutingBatchResult>("/admin/clue-routing/products/batch", { method: "POST", body, idempotencyKey });
}

export function fetchClueRoutingGrants(productId: string) {
  return request<ClueRoutingGrants>(`/admin/clue-routing/products/${encodeURIComponent(productId)}/grants`);
}

export function saveClueRoutingGrants(productId: string, userIds: string[]) {
  return request<ClueRoutingGrants>(`/admin/clue-routing/products/${encodeURIComponent(productId)}/grants`, { method: "PUT", body: { user_ids: userIds } });
}

export function fetchSharedClueRoutingGrants() {
  return request<ClueRoutingGrantSet>("/admin/clue-routing/shared-rule/grants");
}

export function saveSharedClueRoutingGrants(userIds: string[]) {
  return request<ClueRoutingGrantSet>("/admin/clue-routing/shared-rule/grants", { method: "PUT", body: { user_ids: userIds } });
}

export function fetchSharedClueRoutingRule() {
  return request<ClueRoutingRuleSnapshot>("/admin/clue-routing/shared-rule");
}

export function saveSharedClueRoutingRule(rules: ClueRoutingRuleWrite, preview: boolean) {
  return request<SharedClueRoutingRuleResult>("/admin/clue-routing/shared-rule", { method: "PUT", body: { rules, preview } });
}

export function resumeClueHeadquartersEntry(entryId: string) {
  return request<HeadquartersResumeResult>(`/admin/clue-allocation/headquarters-pool/${encodeURIComponent(entryId)}/resume`, { method: "POST", body: {} });
}
