import { replaceBusinessFiltersInUrl } from "../utils/businessFilters";
import { ClueStoreFilter } from "../components/ClueStoreFilter";
import type { ClueListFilters, ClueSelectedStore } from "../types/clueFilters";
import { usePublishedResource } from "../hooks/usePublishedResource";
import { usePublishedView } from "../hooks/usePublishedView";
import { fetchClueOrganizationOptions } from "../api/client";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
  type TouchEvent,
} from "react";
import {
  deleteClueFollowUpRecord,
  exportClueAssignmentRounds,
  fetchClueAssignmentRounds,
  fetchClueFilters,
  fetchPublishedClueFilters,
  fetchClueStoreOptions,
  fetchClueOrderDetail,
  fetchClueOrderPhone,
  fetchClueOverview,
  saveClueFollowUp,
} from "../api/client";
import { Button, IconButton } from "../components/Button";
import { CountPill, FilterChip, StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { GuidedTour } from "../components/GuidedTour";
import { FilterBar, FilterField } from "../components/Filters";
import { CheckboxField, FieldInput, FieldTextarea, SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import {
  ResourceNotice,
  ResourcePanel,
  resourceSourceLabel,
} from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import { useClueOnboarding } from "../hooks/useClueOnboarding";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type {
  ClueFilterMetadata,
  ClueAssignmentRound,
  ClueFollowUpAction,
  ClueFollowUpRecord,
  ClueOrderDetail,
  ClueProductScope,
  AdminUser,
} from "../types/dashboard";
import { formatDateTime, formatInteger, formatPercent } from "../utils/format";
import { toShanghaiAppointmentAt, toShanghaiAppointmentInput } from "../utils/clueAppointment";
import {
  CLUE_PRODUCT_SCOPE_OPTIONS,
  FOLLOW_24H_DESCRIPTION,
  FOLLOW_ANY_DESCRIPTION,
  SELF_STORE_VERIFICATION_DESCRIPTION,
  VERIFICATION_RATE_DESCRIPTION,
  normalizeClueProductScope,
} from "../utils/clueMetrics";
import { userFacingError } from "../utils/userFacingError";
import {
  displayClueReason,
  displayFollowUpTimingState,
  displayOrderStatus,
} from "../utils/userFacingLabels";
import "./ClueOnboarding.css";
import "./ClueFollowUp.css";

interface ClueCenterPageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
  view?: ClueCenterView;
}

type ClueCenterView = "dashboard" | "details";

type StoreClueStatus =
  | "待跟进"
  | "已跟进"
  | "超期失效"
  | "主动战败"
  | "客户要求换门店"
  | "已核销"
  | "已退款"
  | "不可跟进";

const CLUE_PAGE_SIZE_OPTIONS = [20, 50, 100];
const DEFAULT_CLUE_PAGE_SIZE = 20;

type ClueFilterKey =
  | "province"
  | "city"
  | "assignedStoreId"
  | "selectedStores"
  | "assignedDateStart"
  | "assignedDateEnd"
  | "storeDisplayStatus"
  | "selfStoreVerified"
  | "productType"
  | "productScope"
  | "organization"
  | "phone";

interface ActiveClueFilter {
  key: ClueFilterKey;
  label: string;
  value: string;
}

const storeDisplayStatusOptions: StoreClueStatus[] = [
  "待跟进",
  "已跟进",
  "超期失效",
  "主动战败",
  "已核销",
  "已退款",
  "不可跟进",
];

const verificationStatusLabels: Record<string, string> = {
  unverified: "未核销",
  self_store_verified: "本店核销",
  other_store_verified: "非本店核销",
};

const followResultLabels: Record<string, string> = {
  pending: "-",
  unreachable: "未联系上",
  lost: "线索战败",
  request_store_change: "客户要求换门店",
  appointment: "已预约",
  further_follow_up: "待进一步跟进",
  failed: "历史旧值：线索战败",
  success: "历史旧值：跟进成功（已迁移为已预约）",
  continue_following: "历史旧值：待进一步跟进",
};

const storeStatusAliases: Record<string, StoreClueStatus> = {
  active_unfollowed: "待跟进",
  active_followed: "已跟进",
  expired_pending_reassign: "超期失效",
  failed_pending_reassign: "主动战败",
  lost: "主动战败",
  failed: "主动战败",
  request_store_change: "客户要求换门店",
  converted: "已核销",
  refunded: "已退款",
};

const editableStatuses = new Set<StoreClueStatus>(["待跟进", "已跟进"]);
const invalidStatuses = new Set<StoreClueStatus>([
  "超期失效",
  "主动战败",
  "客户要求换门店",
]);

function labelFor(
  value: string | null | undefined,
  labels: Record<string, string>,
  fallback = "未知跟进结果",
) {
  if (!value) {
    return "-";
  }
  return labels[value] ?? fallback;
}

function displayValue(value: string | null | undefined): string {
  return value ? value : "-";
}

function roundLabel(value: number | null | undefined): string {
  return value !== null && value !== undefined ? `第${value}轮` : "-";
}

function optionList(values: string[] | undefined, labels?: Record<string, string>) {
  return (values ?? []).map((value) => ({
    value,
    label: labels?.[value] ?? value,
  }));
}

function clueDefaultProductType(meta: ClueFilterMetadata | undefined): string {
  return meta?.default_product_type?.trim() || "all";
}

function normalizeStoreStatus(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  if (
    [
      "待跟进",
      "已跟进",
      "超期失效",
      "主动战败",
      "已核销",
      "已退款",
      "不可跟进",
    ].includes(value)
  ) {
    return value as StoreClueStatus;
  }
  return storeStatusAliases[value] ?? null;
}

function getStoreDisplayStatus(row: ClueAssignmentRound): StoreClueStatus {
  const explicitStatus = normalizeStoreStatus(row.store_display_status);
  if (explicitStatus) {
    return explicitStatus;
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
  if (row.reassign_reason === "request_store_change") {
    return "客户要求换门店";
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
  if (row.lead_status === "closed") {
    return "不可跟进";
  }
  return "不可跟进";
}

function canOperateCurrentRound(row: ClueAssignmentRound): boolean {
  if (typeof row.can_operate_current_round === "boolean") {
    return row.can_operate_current_round;
  }
  if (row.routing_mode != null) return false;
  return (
    row.is_current_round &&
    row.round_effective_status === "active" &&
    editableStatuses.has(getStoreDisplayStatus(row))
  );
}

function canViewFullPhone(row: ClueAssignmentRound): boolean {
  return canOperateCurrentRound(row);
}

function getPhoneUnavailableReason(row: ClueAssignmentRound): string {
  const status = getStoreDisplayStatus(row);
  if (status === "超期失效") {
    return "已失效不可跟进";
  }
  if (status === "主动战败") {
    return "已主动战败，不可跟进";
  }
  if (status === "客户要求换门店") {
    return "客户要求换门店，本轮不可跟进";
  }
  if (status === "已核销") {
    return "订单已完成";
  }
  const reason = displayClueReason(row.status_reason);
  return reason === "-" ? "此线索不可操作" : reason;
}

function getFollowUpUnavailableReason(row: ClueAssignmentRound): string {
  if (!row.is_current_round || row.round_effective_status === "inactive") {
    return "本轮已结束，仅可查看跟进历史。";
  }
  const status = getStoreDisplayStatus(row);
  if (status === "超期失效") {
    return "已失效不可跟进";
  }
  if (status === "主动战败") {
    return "线索已战败，不可继续跟进";
  }
  if (status === "客户要求换门店") {
    return "客户要求换门店，本轮不可继续跟进";
  }
  if (status === "已核销") {
    return "订单已完成";
  }
  if (status === "已退款") {
    return "订单已退款，不可跟进";
  }
  const reason = displayClueReason(row.status_reason);
  return reason === "-" ? "此线索不可操作" : reason;
}

function formatInvalidatedAt(row: ClueAssignmentRound): string {
  const status = getStoreDisplayStatus(row);
  if (status === "超期失效") {
    return row.expires_at ? formatDateTime(row.expires_at) : "";
  }
  if (status === "主动战败") {
    return formatDateTime(row.expires_at ?? row.followed_at ?? row.reassigned_at);
  }
  return "";
}

function invalidationReason(row: ClueAssignmentRound): string {
  const status = getStoreDisplayStatus(row);
  if (status === "超期失效") {
    return "超期失效";
  }
  if (status === "主动战败") {
    return displayClueReason(row.reassign_reason);
  }
  return "-";
}

function roundTransitionReason(row: ClueAssignmentRound): string {
  if (row.reassign_reason) {
    return displayClueReason(row.reassign_reason);
  }
  return invalidationReason(row);
}

function clueStatusTone(status: StoreClueStatus): "warning" | "info" | "success" | "neutral" {
  if (status === "待跟进") return "info";
  if (status === "已跟进" || status === "已核销") return "success";
  if (invalidStatuses.has(status)) return "warning";
  return "neutral";
}

function currentDetailRound(
  detail: ClueOrderDetail | null,
  selectedRound: ClueAssignmentRound | null,
  selectedRoundId: string | null,
): ClueAssignmentRound | null {
  if (!detail) {
    return selectedRound;
  }
  if (selectedRoundId) {
    return detail.rounds.find((round) => round.assignment_round_id === selectedRoundId) ?? null;
  }
  return (
    detail.rounds.find((round) => round.assignment_round_id === selectedRoundId) ??
    detail.rounds.find((round) => round.round_effective_status === "active") ??
    detail.rounds[detail.rounds.length - 1] ??
    selectedRound
  );
}

function verificationStoreText(row: ClueAssignmentRound): string {
  return row.verified_store_name?.trim() || row.verified_store_id?.trim() ||
    (row.verified_at || getStoreDisplayStatus(row) === "已核销" ? "核销门店暂缺" : "—");
}

function verificationSummary(row: ClueAssignmentRound): string {
  return row.verification_summary?.trim() || (row.verified_at || getStoreDisplayStatus(row) === "已核销" ? "已核销" : "未核销");
}

function overviewRate(value: number | null | undefined): string {
  return value === undefined ? "暂不可用" : value === null ? "暂无样本" : formatPercent(value);
}

function metricSample(numerator: number | null | undefined, denominator: number | null | undefined): string {
  return numerator == null || denominator == null
    ? "按实际接收任务统计"
    : `${formatInteger(numerator)} / ${formatInteger(denominator)} 个接收任务`;
}

function recordsForRound(
  detail: ClueOrderDetail,
  assignmentRoundId: string,
  includeDeleted = false,
): ClueFollowUpRecord[] {
  return detail.follow_up_records
    .filter(
      (record) =>
        record.assignment_round_id === assignmentRoundId &&
        (includeDeleted || !record.is_deleted),
    )
    .sort((left, right) => left.created_at.localeCompare(right.created_at));
}

export function ClueCenterPage({
  currentUser,
  searchParams,
  view = "dashboard",
}: ClueCenterPageProps) {
  const isDetailsView = view === "details";
  const pageHeadingTitle = isDetailsView ? "线索跟进列表" : "经营线索概览";
  const showStoreLocationFilters =
    currentUser.store_scope_mode === "all" || currentUser.store_ids.length !== 1;
  const [orgLevel, setOrgLevel] = useState(searchParams.get("org_level") ?? "all");
  const [orgKey, setOrgKey] = useState(searchParams.get("org_key") ?? "");
  const [orgQuery, setOrgQuery] = useState("");
  const debouncedOrgQuery = useDebouncedValue(orgQuery, 200);
  const orgResource = useApiResource(
    () => fetchClueOrganizationOptions({ level: orgLevel, q: debouncedOrgQuery, selected_key: orgKey }),
    [orgLevel, debouncedOrgQuery, orgKey],
    { enabled: isDetailsView && orgLevel !== "all", clearOnReload: true },
  );
  const [province, setProvince] = useState(searchParams.get("province") ?? "");
  const [city, setCity] = useState(searchParams.get("city") ?? "");
  const [assignedStoreId, setAssignedStoreId] = useState(
    searchParams.get("assigned_store_id") ?? "",
  );
  const [selectedStores, setSelectedStores] = useState<ClueSelectedStore[] | null>(() => {
    const legacy = searchParams.get("assigned_store_id");
    return legacy ? [{ store_id: legacy, store_name: legacy }] : null;
  });
  const [storeFilterResetKey, setStoreFilterResetKey] = useState(0);
  const [storeOptionQuery, setStoreOptionQuery] = useState("");
  const [storeOptionsEnabled, setStoreOptionsEnabled] = useState(
    Boolean(searchParams.get("assigned_store_id")),
  );
  const [assignedDateStart, setAssignedDateStart] = useState(
    searchParams.get("assigned_date_start") ?? "",
  );
  const [assignedDateEnd, setAssignedDateEnd] = useState(
    searchParams.get("assigned_date_end") ?? "",
  );
  const [storeDisplayStatus, setStoreDisplayStatus] = useState(
    searchParams.get("store_display_status") ?? "",
  );
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "",
  );
  const [productScope, setProductScope] = useState<ClueProductScope>(() =>
    normalizeClueProductScope(searchParams.get("product_scope")),
  );
  const [page, setPage] = useState(1);
  // Sensitive selections remain in component memory, never URL/storage.
  const [phoneInput, setPhoneInput] = useState("");
  const [phone, setPhone] = useState("");
  const [phoneFilterError, setPhoneFilterError] = useState("");
  const applyPhoneFilter = () => {
    const value = phoneInput.trim();
    if (value && !/^1[3-9][0-9]{9}$/.test(value)) {
      setPhoneFilterError("请输入完整的11位中国大陆手机号");
      return;
    }
    setPhoneFilterError("");
    setPhoneInput(value);
    setPhone(value);
    setPage(1);
  };
  const [selfStoreVerified, setSelfStoreVerified] = useState(
    searchParams.get("verification_status") === "self_store_verified",
  );
  const [pageSize, setPageSize] = useState(DEFAULT_CLUE_PAGE_SIZE);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [selectedRound, setSelectedRound] = useState<ClueAssignmentRound | null>(
    null,
  );
  const [detail, setDetail] = useState<ClueOrderDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailReloadIndex, setDetailReloadIndex] = useState(0);
  const [revealedPhones, setRevealedPhones] = useState<Record<string, string>>({});
  const [revealingOrderId, setRevealingOrderId] = useState<string | null>(null);
  const [copyingOrderId, setCopyingOrderId] = useState<string | null>(null);
  const [phoneRevealError, setPhoneRevealError] = useState<string | null>(null);
  const [phoneActionMessage, setPhoneActionMessage] = useState<string | null>(null);
  const [exportingClues, setExportingClues] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [followResult, setFollowResult] =
    useState<ClueFollowUpAction>("further_follow_up");
  const [followNote, setFollowNote] = useState("");
  const [followAppointmentAt, setFollowAppointmentAt] = useState("");
  const [followUpError, setFollowUpError] = useState<string | null>(null);
  const [deletingFollowUpRecordId, setDeletingFollowUpRecordId] =
    useState<string | null>(null);
  const [savingFollowUp, setSavingFollowUp] = useState(false);
  const detailReturnFocusRef = useRef<HTMLElement | null>(null);
  const detailTouchStartRef = useRef<{ x: number; y: number } | null>(null);

  const debouncedStoreOptionQuery = useDebouncedValue(storeOptionQuery, 200);
  const liveFilterResource = useApiResource(() => fetchClueFilters(false), [], { enabled: isDetailsView });
  const overviewResource = usePublishedView(
    fetchPublishedClueFilters,
    (metadata, id) => fetchClueOverview({
      product_scope: productScope,
      assigned_store_id: showStoreLocationFilters ? assignedStoreId : "",
      assigned_date_start: assignedDateStart,
      assigned_date_end: assignedDateEnd,
      store_display_status: storeDisplayStatus,
      product_type: productType || clueDefaultProductType(metadata),
      org_level: "all",
      org_key: "",
      province: showStoreLocationFilters ? province : "",
      city: showStoreLocationFilters ? city : "",
    }, id),
    [assignedStoreId, assignedDateEnd, assignedDateStart, productType, productScope, city, province, showStoreLocationFilters, storeDisplayStatus],
    { enabled: !isDetailsView },
  );
  const filterResource = isDetailsView ? liveFilterResource : { ...overviewResource, data: overviewResource.filters };
  const meta = filterResource.data?.data;
  const activeProductType = productType || clueDefaultProductType(meta);
  useEffect(() => replaceBusinessFiltersInUrl({ product_type: productType || undefined,
    product_scope: !isDetailsView && productScope !== "all" ? productScope : undefined }), [productType, productScope, isDetailsView]);
  const liveStoreOptionsResource = useApiResource(
    () => fetchClueStoreOptions({ cacheScope: currentUser.user_id ?? currentUser.username,
      city, limit: 50, province, q: debouncedStoreOptionQuery, selected_store_id: assignedStoreId }),
    [assignedStoreId, city, currentUser.user_id, currentUser.username, debouncedStoreOptionQuery, province],
    { enabled: isDetailsView && showStoreLocationFilters && storeOptionsEnabled },
  );
  const publishedStoreOptionsResource = usePublishedResource(
    (publication_id) => fetchClueStoreOptions({
      // Each completed overview must recheck the current permission scope.
      cacheScope: `${currentUser.user_id ?? currentUser.username}:${crypto.randomUUID()}`,
      publication_id, city, limit: 50, province, q: debouncedStoreOptionQuery, selected_store_id: assignedStoreId,
    }),
    [assignedStoreId, city, debouncedStoreOptionQuery, province, overviewResource.revision],
    { leader: false, publicationId: overviewResource.data?.meta.publication?.id,
      enabled: !isDetailsView && showStoreLocationFilters && storeOptionsEnabled && Boolean(overviewResource.data) },
  );
  const storeOptionsResource = isDetailsView ? liveStoreOptionsResource : publishedStoreOptionsResource;
  const storeOptions = isDetailsView
    ? liveStoreOptionsResource.data?.data.stores ?? meta?.assigned_stores ?? []
    : publishedStoreOptionsResource.data?.data.stores ?? [];

  const filters: ClueListFilters = useMemo(
    () => ({
      assigned_store_id: !isDetailsView && showStoreLocationFilters ? assignedStoreId : "",
      assigned_store_ids: isDetailsView ? selectedStores?.map(store => store.store_id) ?? null : null,
      phone: isDetailsView ? phone : null,
      assigned_date_start: assignedDateStart,
      assigned_date_end: assignedDateEnd,
      store_display_status: storeDisplayStatus,
      product_type: activeProductType,
      verification_status: isDetailsView && selfStoreVerified ? "self_store_verified" : "",
      org_level: isDetailsView ? orgLevel : "all",
      org_key: isDetailsView ? orgKey : "",
      province: showStoreLocationFilters ? province : "",
      city: showStoreLocationFilters ? city : "",
    }),
    [
      assignedStoreId, selectedStores, phone,
      assignedDateEnd,
      assignedDateStart,
      activeProductType,
      selfStoreVerified,
      orgLevel, orgKey, isDetailsView,
      city,
      province,
      showStoreLocationFilters,
      storeDisplayStatus,
    ],
  );

  const activeFilterChips: ActiveClueFilter[] = useMemo(() => {
    const chips: ActiveClueFilter[] = [];
    if (isDetailsView && phone) chips.push({ key: "phone", label: "手机号", value: `${phone.slice(0, 3)}****${phone.slice(-4)}` });
    if (isDetailsView && selectedStores !== null) {
      chips.push({ key: "selectedStores", label: "门店", value: selectedStores.length ? `${selectedStores.length}家` : "无匹配" });
    }
    if (isDetailsView && orgKey) {
      chips.push({key: "organization", label: "组织", value: orgResource.data?.data.options.find(item => item.value === orgKey)?.label ?? orgKey});
    }
    if (showStoreLocationFilters && province) {
      chips.push({ key: "province", label: "省份", value: province });
    }
    if (showStoreLocationFilters && city) {
      chips.push({ key: "city", label: "城市", value: city });
    }
    if (!isDetailsView && showStoreLocationFilters && assignedStoreId) {
      chips.push({
        key: "assignedStoreId",
        label: "门店",
        value:
          storeOptions.find(
            (store) => store.store_id === assignedStoreId,
          )?.store_name ?? assignedStoreId,
      });
    }
    if (assignedDateStart) {
      chips.push({
        key: "assignedDateStart",
        label: "起始",
        value: assignedDateStart,
      });
    }
    if (assignedDateEnd) {
      chips.push({
        key: "assignedDateEnd",
        label: "截止",
        value: assignedDateEnd,
      });
    }
    if (storeDisplayStatus) {
      chips.push({
        key: "storeDisplayStatus",
        label: "状态",
        value: storeDisplayStatus,
      });
    }
    if (isDetailsView && selfStoreVerified) {
      chips.push({ key: "selfStoreVerified", label: "核销", value: "仅看自店核销" });
    }
    if (activeProductType && activeProductType !== "all") {
      chips.push({ key: "productType", label: "商品", value: activeProductType });
    }
    if (!isDetailsView && productScope !== "all") {
      chips.push({ key: "productScope", label: "商品范围", value: CLUE_PRODUCT_SCOPE_OPTIONS.find((item) => item.value === productScope)?.label ?? "全部商品" });
    }
    return chips;
  }, [
    selectedStores, phone,
    activeProductType,
    productScope,
    selfStoreVerified,
    isDetailsView, orgKey, orgResource.data,
    assignedDateEnd,
    assignedDateStart,
    assignedStoreId,
    city,
    province,
    showStoreLocationFilters,
    storeOptions,
    storeDisplayStatus,
  ]);

  const roundsResource = useApiResource(
    () => fetchClueAssignmentRounds({ filters, page, pageSize }),
    [
      phone,
      selectedStores,
      assignedStoreId,
      assignedDateEnd,
      assignedDateStart,
      city,
      page,
      pageSize,
      selfStoreVerified,
      activeProductType,
      orgLevel, orgKey, isDetailsView,
      province,
      showStoreLocationFilters,
      isDetailsView,
      storeDisplayStatus,
    ],
    { enabled: isDetailsView, clearOnReload: true },
  );
  const overview = overviewResource.data?.data;
  const overviewPublication = overviewResource.data?.meta.publication;
  const metricsWarming = Boolean(overviewPublication && overviewPublication.taskMetricsContract !== "clue-task-v3");
  const rows = roundsResource.data?.data.rows ?? [];
  const pagination = roundsResource.data?.data.pagination;
  const selectedRoundIndex = selectedRound
    ? rows.findIndex(
        (row) => row.assignment_round_id === selectedRound.assignment_round_id,
      )
    : -1;
  const currentCluePosition =
    selectedRoundIndex >= 0
      ? `第 ${selectedRoundIndex + 1} / ${rows.length} 条`
      : "";
  const hasPreviousClue = selectedRoundIndex > 0;
  const hasNextClue =
    selectedRoundIndex >= 0 && selectedRoundIndex < rows.length - 1;
  const activeResourceHasData = isDetailsView
    ? roundsResource.data !== undefined
    : overviewResource.data !== undefined;
  const activeResourceRefreshing = isDetailsView
    ? roundsResource.refreshing
    : overviewResource.refreshing;
  const loading =
    !activeResourceHasData &&
    ((filterResource.loading && meta === undefined) ||
      (isDetailsView ? roundsResource.loading : overviewResource.loading));
  const activeResourceError =
    filterResource.error ??
    (isDetailsView ? roundsResource.error : overviewResource.error);
  const displayedResourceError =
    activeResourceHasData && activeResourceError
      ? `更新失败，当前展示上次成功数据：${activeResourceError}`
      : activeResourceError;
  const activeFallbackReason =
    filterResource.data?.fallbackReason ??
    (isDetailsView
      ? roundsResource.data?.fallbackReason
      : overviewResource.data?.fallbackReason);
  const selectedOrderId = selectedRound?.order_id ?? null;
  const selectedRoundId = selectedRound?.assignment_round_id ?? null;
  const activeDetailRound = currentDetailRound(
    detail,
    selectedRound,
    selectedRoundId,
  );
  const activeDetailStatus = activeDetailRound
    ? getStoreDisplayStatus(activeDetailRound)
    : null;
  const detailProductName =
    detail?.product_name ?? activeDetailRound?.product_name ?? "-";
  const detailProductType =
    detail?.product_type ?? activeDetailRound?.product_type ?? "-";
  const detailOrderStatus = activeDetailRound
    ? displayOrderStatus(activeDetailRound.order_current_status)
    : "-";
  const canShowActiveDetailPhone = activeDetailRound
    ? canViewFullPhone(activeDetailRound)
    : false;
  const canEditFollowUp = activeDetailRound
    ? canOperateCurrentRound(activeDetailRound)
    : false;
  const canDeleteRecordsForRound = (round: ClueAssignmentRound): boolean => {
    if (typeof round.can_delete_follow_up_records === "boolean") return round.can_delete_follow_up_records;
    if (round.routing_mode != null) return false;
    return currentUser.role === "admin" && (currentUser.store_scope_mode === "all" || currentUser.store_ids.includes(round.assigned_store_id ?? ""));
  };
  const handleExportClues = async () => {
    setExportingClues(true);
    setExportError(null);
    try {
      await exportClueAssignmentRounds(filters);
    } catch (error: unknown) {
      setExportError(userFacingError(error, "线索明细导出失败，请稍后重试。"));
    } finally {
      setExportingClues(false);
    }
  };
  const openClueDetail = (
    row: ClueAssignmentRound,
    triggerElement?: HTMLElement | null,
  ) => {
    detailReturnFocusRef.current =
      triggerElement ??
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    setSelectedRound(row);
  };

  const switchSelectedClue = (direction: -1 | 1) => {
    const nextIndex = selectedRoundIndex + direction;
    const nextRound = rows[nextIndex];
    if (!nextRound) {
      return;
    }
    setSelectedRound(nextRound);
    setDetail(null);
    setDetailError(null);
    setPhoneRevealError(null);
    setPhoneActionMessage(null);
    setFollowUpError(null);
    setDeletingFollowUpRecordId(null);
  };

  const closeClueDetail = () => {
    setSelectedRound(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
    setPhoneRevealError(null);
    setPhoneActionMessage(null);
    setFollowUpError(null);
  };

  const tourCandidate =
    rows.find((row) => canOperateCurrentRound(row) && getStoreDisplayStatus(row) === "待跟进") ??
    rows.find(canOperateCurrentRound) ?? rows[0];
  const onboarding = useClueOnboarding({
    currentUser,
    isDetailsView,
    candidateRound: tourCandidate,
    candidateCanOperate: Boolean(tourCandidate && canOperateCurrentRound(tourCandidate)),
    roundsReady: roundsResource.data !== undefined,
    roundsLoading: roundsResource.loading,
    roundsRefreshing: roundsResource.refreshing,
    roundsError: roundsResource.error ?? filterResource.error,
    detailReady: detail !== null,
    detailLoading,
    detailError,
    detailHasSelectedRound: Boolean(detail?.rounds.some((round) => round.assignment_round_id === selectedRoundId)),
    canEditFollowUp,
    canShowPhone: canShowActiveDetailPhone,
    selectedRoundId,
    busy: savingFollowUp || exportingClues,
    mobileFiltersOpen,
    setMobileFiltersOpen,
    openDetail: openClueDetail,
    closeDetail: closeClueDetail,
  });

  const fetchFullPhone = async (row: ClueAssignmentRound) => {
    if (!canViewFullPhone(row)) {
      setPhoneRevealError(getPhoneUnavailableReason(row));
      return null;
    }
    setPhoneRevealError(null);
    setPhoneActionMessage(null);
    setRevealingOrderId(row.order_id);
    try {
      const result = await fetchClueOrderPhone(row.order_id);
      const fullPhone = result.data.phone;
      setRevealedPhones((current) => ({
        ...current,
        [row.order_id]: fullPhone,
      }));
      return fullPhone;
    } catch {
      setRevealedPhones((current) => {
        if (!current[row.order_id]) {
          return current;
        }
        const next = { ...current };
        delete next[row.order_id];
        return next;
      });
      setPhoneRevealError("完整手机号暂不可查看");
      return null;
    } finally {
      setRevealingOrderId(null);
    }
  };

  const revealPhone = async (row: ClueAssignmentRound) => {
    await fetchFullPhone(row);
  };

  const hidePhone = (row: ClueAssignmentRound) => {
    setRevealedPhones((current) => {
      if (!current[row.order_id]) {
        return current;
      }
      const next = { ...current };
      delete next[row.order_id];
      return next;
    });
    setPhoneRevealError(null);
    setPhoneActionMessage("完整手机号已隐藏");
  };

  const copyPhone = async (row: ClueAssignmentRound) => {
    setCopyingOrderId(row.order_id);
    try {
      const fullPhone = await fetchFullPhone(row);
      if (!fullPhone) {
        return;
      }
      await navigator.clipboard.writeText(fullPhone);
      setPhoneActionMessage("完整手机号已复制");
    } catch {
      setPhoneRevealError("完整手机号复制失败");
    } finally {
      setCopyingOrderId(null);
    }
  };

  const handleDetailTouchStart = (event: TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    detailTouchStartRef.current = { x: touch.clientX, y: touch.clientY };
  };

  const handleDetailTouchEnd = (event: TouchEvent<HTMLDivElement>) => {
    const start = detailTouchStartRef.current;
    detailTouchStartRef.current = null;
    const touch = event.changedTouches[0];
    if (!start || !touch) {
      return;
    }
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    if (Math.abs(deltaX) < 56 || Math.abs(deltaX) < Math.abs(deltaY) * 1.35) {
      return;
    }
    if (deltaX < 0) {
      switchSelectedClue(1);
    } else {
      switchSelectedClue(-1);
    }
  };

  const renderPhoneContact = (
    row: ClueAssignmentRound,
    mode: "table" | "panel" | "card" | "detail" = "table",
  ) => {
    const mayRevealFullPhone = canViewFullPhone(row);
    const revealedPhone = mayRevealFullPhone ? revealedPhones[row.order_id] : undefined;
    const displayPhone = revealedPhone || row.phone_masked || "-";
    const disabled = revealingOrderId === row.order_id || copyingOrderId === row.order_id;
    const iconMode = mode !== "panel";
    const phoneVisible = Boolean(revealedPhone);
    if (!mayRevealFullPhone) {
      return (
        <span className={`phone-reveal phone-reveal--${mode} phone-reveal--disabled`}>
          <span className="mono-cell">{displayPhone}</span>
          <span className="phone-reveal__reason">
            {getPhoneUnavailableReason(row)}
          </span>
        </span>
      );
    }

    return (
      <span className={`phone-reveal phone-reveal--${mode}`}>
        <span className="mono-cell">{displayPhone}</span>
        {iconMode ? (
          <IconButton
            disabled={disabled}
            icon={phoneVisible ? "eyeClosed" : "eye"}
            label={phoneVisible ? "隐藏完整手机号" : "查看完整手机号"}
            onClick={(event) => {
              event.stopPropagation();
              if (phoneVisible) {
                hidePhone(row);
                return;
              }
              void revealPhone(row);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            size={mode === "detail" ? "touch" : "sm"}
            title={phoneVisible ? "隐藏完整手机号" : "查看完整手机号"}
            type="button"
          />
        ) : (
          <Button
            aria-label={phoneVisible ? "隐藏完整手机号" : "查看完整手机号"}
            disabled={disabled}
            loading={revealingOrderId === row.order_id}
            onClick={(event) => {
              event.stopPropagation();
              if (phoneVisible) {
                hidePhone(row);
                return;
              }
              void revealPhone(row);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            size="sm"
            title={phoneVisible ? "隐藏完整手机号" : "查看完整手机号"}
            type="button"
            variant="text"
          >
            {phoneVisible ? "隐藏完整手机号" : revealingOrderId === row.order_id ? "读取中" : "查看完整手机号"}
          </Button>
        )}
        {iconMode ? (
          <IconButton
            disabled={disabled}
            icon="copy"
            label="复制完整手机号"
            onClick={(event) => {
              event.stopPropagation();
              void copyPhone(row);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            size={mode === "detail" ? "touch" : "sm"}
            title="复制完整手机号"
            type="button"
          />
        ) : (
          <Button
            aria-label="复制完整手机号"
            disabled={disabled}
            loading={copyingOrderId === row.order_id}
            onClick={(event) => {
              event.stopPropagation();
              void copyPhone(row);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            size="sm"
            title="复制完整手机号"
            type="button"
            variant="text"
          >
            {copyingOrderId === row.order_id ? "复制中" : "复制完整手机号"}
          </Button>
        )}
      </span>
    );
  };

  useEffect(() => {
    if (!isDetailsView && selectedRound) {
      closeClueDetail();
    }
  }, [isDetailsView, selectedRound]);

  useEffect(() => {
    if (!selectedOrderId) {
      return;
    }

    let cancelled = false;
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);

    fetchClueOrderDetail(selectedOrderId)
      .then((result) => {
        if (cancelled) {
          return;
        }
        const reloadedRound = result.data.rounds.find(
          (round) => round.assignment_round_id === selectedRoundId,
        );
        if (reloadedRound && !canViewFullPhone(reloadedRound)) {
          setRevealedPhones((current) => {
            if (!current[selectedOrderId]) {
              return current;
            }
            const next = { ...current };
            delete next[selectedOrderId];
            return next;
          });
        }
        setDetail(result.data);
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setDetailError(userFacingError(error, "线索详情加载失败，请稍后重试。"));
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedOrderId, detailReloadIndex]);

  useEffect(() => {
    setFollowResult("further_follow_up");
    setFollowNote("");
    setFollowUpError(null);
    setPhoneRevealError(null);
    setPhoneActionMessage(null);
  }, [selectedOrderId, selectedRoundId]);

  useEffect(() => {
    setFollowAppointmentAt(toShanghaiAppointmentInput(activeDetailRound?.appointment_at));
  }, [activeDetailRound?.assignment_round_id, activeDetailRound?.appointment_at]);

  useEffect(() => {
    if (!phoneActionMessage) {
      return;
    }
    const timer = window.setTimeout(() => {
      setPhoneActionMessage(null);
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [phoneActionMessage]);

  const resetFilters = () => {
    setPhone(""); setPhoneInput(""); setPhoneFilterError("");
    setOrgLevel("all"); setOrgKey(""); setOrgQuery("");
    setProvince("");
    setCity("");
    setAssignedStoreId("");
    setSelectedStores(null);
    setStoreFilterResetKey(value => value + 1);
    setAssignedDateStart("");
    setAssignedDateEnd("");
    setStoreDisplayStatus("");
    setSelfStoreVerified(false);
    setProductType("");
    setProductScope("all");
    setPage(1);
  };

  const removeFilter = (key: ClueFilterKey) => {
    setPage(1);
    if (key === "phone") {
      setPhone(""); setPhoneInput(""); setPhoneFilterError("");
    }
    if (key === "organization") {
      setOrgLevel("all"); setOrgKey(""); setOrgQuery("");
    }
    if (key === "province") {
      setProvince("");
    } else if (key === "city") {
      setCity("");
    } else if (key === "assignedStoreId") {
      setAssignedStoreId("");
    } else if (key === "selectedStores") {
      setSelectedStores(null);
    } else if (key === "assignedDateStart") {
      setAssignedDateStart("");
    } else if (key === "assignedDateEnd") {
      setAssignedDateEnd("");
    } else if (key === "storeDisplayStatus") {
      setStoreDisplayStatus("");
    } else if (key === "selfStoreVerified") {
      setSelfStoreVerified(false);
    } else if (key === "productType") {
      setProductType("all");
    } else if (key === "productScope") {
      setProductScope("all");
    }
  };

  const handleSaveFollowUp = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail || !activeDetailRound || !canEditFollowUp) {
      return;
    }
    const appointmentAt = followResult === "appointment" ? toShanghaiAppointmentAt(followAppointmentAt) : null;
    if (followResult === "appointment" && !appointmentAt) {
      setFollowUpError("请选择有效的预约到店日期时间（北京时间）。");
      return;
    }

    setSavingFollowUp(true);
    setFollowUpError(null);
    setPhoneActionMessage(null);
    try {
      await saveClueFollowUp(detail.order_id, {
        assignment_round_id: activeDetailRound.assignment_round_id,
        follow_result: followResult,
        note: followNote.trim() || null,
        ...(followResult === "appointment" ? { appointment_at: appointmentAt } : {}),
      });
      if (followResult === "lost" || followResult === "request_store_change") {
        setRevealedPhones((current) => {
          if (!current[detail.order_id]) {
            return current;
          }
          const next = { ...current };
          delete next[detail.order_id];
          return next;
        });
      }
      setFollowNote("");
      setPhoneActionMessage("跟进已保存");
      setDetailReloadIndex((current) => current + 1);
      overviewResource.reload();
      roundsResource.reload();
    } catch (error: unknown) {
      setFollowUpError(userFacingError(error, "跟进保存失败，请稍后重试。"));
    } finally {
      setSavingFollowUp(false);
    }
  };

  const handleDeleteFollowUpRecord = async (record: ClueFollowUpRecord) => {
    const round = detail?.rounds.find((item) => item.assignment_round_id === record.assignment_round_id);
    if (!round || !canDeleteRecordsForRound(round) || deletingFollowUpRecordId) {
      return;
    }
    const confirmed = window.confirm("确认删除这条跟进历史记录？");
    if (!confirmed) {
      return;
    }
    setDeletingFollowUpRecordId(record.follow_up_record_id);
    setFollowUpError(null);
    setPhoneActionMessage(null);
    try {
      await deleteClueFollowUpRecord(record.follow_up_record_id);
      setPhoneActionMessage("跟进历史已删除");
      setDetailReloadIndex((current) => current + 1);
      overviewResource.reload();
      roundsResource.reload();
    } catch (error: unknown) {
      setFollowUpError(userFacingError(error, "跟进历史删除失败，请稍后重试。"));
    } finally {
      setDeletingFollowUpRecordId(null);
    }
  };

  const columns: Column<ClueAssignmentRound>[] = [
    {
      key: "phone",
      title: "联系方式",
      minWidth: 230,
      sticky: true,
      render: (row) => (
        <div className="clue-contact-cell">
          {renderPhoneContact(row)}
          <Button
            className="clue-detail-trigger"
            data-clue-tour={row.assignment_round_id === onboarding.targetRoundId ? "open-detail" : undefined}
            onClick={(event) => {
              event.stopPropagation();
              openClueDetail(row, event.currentTarget);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            size="sm"
            type="button"
            variant="text"
          >
            查看详情
          </Button>
        </div>
      ),
    },
    {
      key: "store_display_status",
      title: "线索状态",
      minWidth: 110,
      render: (row) => {
        const status = getStoreDisplayStatus(row);
        return <StatusChip tone={clueStatusTone(status)}>{status}</StatusChip>;
      },
    },
    {
      key: "verification_summary",
      title: "核销状态",
      minWidth: 150,
      render: (row) => <span className="clue-verification-summary">{verificationSummary(row)}</span>,
    },
    {
      key: "verified_store_name",
      title: "核销门店",
      minWidth: 200,
      render: (row) => verificationStoreText(row),
    },
    {
      key: "round_no",
      title: "分配轮次",
      minWidth: 100,
      render: (row) => roundLabel(row.round_no),
    },
    {
      key: "followed_at",
      title: "本轮跟进时间",
      minWidth: 150,
      render: (row) => formatDateTime(row.followed_at),
    },
    {
      key: "product_name",
      title: "商品名称",
      align: "left",
      minWidth: 230,
      render: (row) => (
        <span className="clue-product-name">
          {displayValue(row.product_name)}
        </span>
      ),
    },
    {
      key: "product_type",
      title: "商品类型",
      minWidth: 120,
      render: (row) => row.product_type || "-",
    },
    {
      key: "assigned_at",
      title: "线索生成时间",
      minWidth: 150,
      render: (row) => formatDateTime(row.assigned_at),
    },
    {
      key: "expires_at",
      title: "本轮失效时间",
      minWidth: 150,
      render: (row) => formatInvalidatedAt(row),
    },
  ];

  return (
    <div
      className={
        isDetailsView ? "page-stack page-stack--data-workspace" : "page-stack"
      }
    >
      <div
        className={
          isDetailsView
            ? "clue-page-content clue-page-content--details"
            : "clue-page-content"
        }
      >
      <section className="page-heading">
        <div>
          <h1>{pageHeadingTitle}</h1>
          {!isDetailsView && <p>与指标看板使用相同口径。跟进和核销率按接收日期取样，自店核销量按该店首次有效核销日期取样；时间均为北京时间。</p>}
        </div>
        <div className="clue-onboarding-heading-actions" ref={(element) => {
          onboarding.replayRef.current = element?.querySelector("button") ?? null;
        }}>
          {onboarding.allowed ? (
            <Button disabled={onboarding.disabled} onClick={onboarding.start} size="touch">
              新手引导
            </Button>
          ) : null}
          <span className="source-pill">
          {isDetailsView
            ? resourceSourceLabel(roundsResource.data, roundsResource.loading)
            : resourceSourceLabel(overviewResource.data, overviewResource.loading)}
          </span>
        </div>
      </section>

      {onboarding.showInvitation ? (
        <section aria-label="线索中心新手引导邀请" className="clue-onboarding-invitation">
          <div>
            <strong>第一次跟进线索？</strong>
            <p>跟着页面提示，了解找线索、联系客户和记录跟进的流程。</p>
          </div>
          <div className="clue-onboarding-invitation__actions">
            <Button onClick={onboarding.dismissInvitation} size="touch" variant="text">稍后再看</Button>
            <Button disabled={onboarding.disabled} onClick={onboarding.start} size="touch" variant="primary">开始引导</Button>
          </div>
        </section>
      ) : null}

      <ResourceNotice analysis={!isDetailsView}
        error={displayedResourceError}
        fallbackReason={activeFallbackReason}
        loading={loading || activeResourceRefreshing}
      />

      <div className="clue-filter-mobile-summary">
        <Button
          aria-controls="clue-filter-panel"
          aria-expanded={mobileFiltersOpen}
          className="clue-filter-toggle"
          onClick={() => setMobileFiltersOpen((current) => !current)}
          type="button"
          variant="secondary"
        >
          筛选{activeFilterChips.length ? ` (${activeFilterChips.length})` : ""}
        </Button>
        {activeFilterChips.length ? (
          <div className="clue-filter-chips" aria-label="已选筛选条件">
            {activeFilterChips.map((chip) => (
              <FilterChip
                key={chip.key}
                onClick={() => removeFilter(chip.key)}
              >
                {chip.label}：{chip.value}
              </FilterChip>
            ))}
            <Button
              className="clue-filter-clear-mobile"
              onClick={resetFilters}
              size="sm"
              type="button"
              variant="text"
            >
              清空
            </Button>
          </div>
        ) : null}
      </div>

      <FilterBar
        className={`filter-bar--compact clue-filter-bar ${mobileFiltersOpen ? "is-open" : ""}`}
        id="clue-filter-panel"
      >
        {isDetailsView && <>
          <SelectField label="组织层级" value={orgLevel} options={[{value: "all", label: "全部"}, {value: "group", label: "集团"}, {value: "service_center", label: "中心"}, {value: "district", label: "大区"}, {value: "area", label: "区域"}, {value: "store", label: "门店"}]} onChange={(value) => { setOrgLevel(value); setOrgKey(""); setOrgQuery(""); setAssignedStoreId(""); setPage(1); }} />
          {orgLevel !== "all" && <FilterField label="组织范围"><SearchableStoreSelect allowEmpty emptyLabel="全部" emptyMessage="未找到可查看的组织" placeholder="搜索组织名称或门店编号" options={orgResource.data?.data.options ?? []} loading={orgResource.loading} value={orgKey} onSearch={setOrgQuery} onChange={(value) => { setOrgKey(value); setAssignedStoreId(""); setStoreOptionQuery(""); setPage(1); }} /></FilterField>}
          {orgResource.error && <ResourcePanel tone="error">{orgResource.error}</ResourcePanel>}
        </>}
        {showStoreLocationFilters ? (
          <>
            <FilterField label="省份">
              <SearchableStoreSelect
                allowEmpty
                emptyMessage="未找到省份"
                options={optionList(meta?.assigned_provinces)}
                placeholder="搜索省份"
                value={province}
                onChange={(value) => {
                  setPage(1);
                  setProvince(value);
                }}
              />
            </FilterField>
            <FilterField label="城市">
              <SearchableStoreSelect
                allowEmpty
                emptyMessage="未找到城市"
                options={optionList(meta?.assigned_cities)}
                placeholder="搜索城市"
                value={city}
                onChange={(value) => {
                  setPage(1);
                  setCity(value);
                }}
              />
            </FilterField>
            <div className={`filter-field${isDetailsView ? " clue-store-filter-field" : ""}`} role="group" aria-label="门店筛选">
              <span>门店</span>
              {isDetailsView ? <ClueStoreFilter selection={selectedStores} options={storeOptions}
                loading={storeOptionsResource.loading} scopeKey={currentUser.user_id ?? currentUser.username} resetKey={storeFilterResetKey}
                onOpen={() => setStoreOptionsEnabled(true)} onSearch={setStoreOptionQuery}
                onChange={stores => { setPage(1); setSelectedStores(stores); }} /> : <SearchableStoreSelect
                allowEmpty
                emptyMessage="未找到门店"
                loading={storeOptionsResource.loading}
                onOpen={() => setStoreOptionsEnabled(true)}
                onSearch={setStoreOptionQuery}
                options={storeOptions.map((store) => ({
                  label: store.store_name,
                  value: store.store_id,
                }))}
                placeholder="搜索门店名称"
                value={assignedStoreId}
                onChange={(value) => {
                  setPage(1);
                  setAssignedStoreId(value);
                }}
              />}
              {storeOptionsResource.error ? <p role="alert">{storeOptionsResource.error}</p> : null}
            </div>
          </>
        ) : null}
        {isDetailsView && <FilterField label="手机号精准查询">
          <FieldInput
            aria-label="手机号精准查询"
            aria-invalid={Boolean(phoneFilterError)}
            aria-describedby={phoneFilterError ? "clue-phone-filter-error" : undefined}
            autoComplete="off"
            inputMode="tel"
            placeholder="完整11位手机号"
            value={phoneInput}
            onChange={event => { setPhoneInput(event.target.value); setPhoneFilterError(""); }}
            onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); applyPhoneFilter(); } }}
          />
          <Button type="button" onClick={applyPhoneFilter}>查询手机号</Button>
          {phoneFilterError && <span id="clue-phone-filter-error" role="alert">{phoneFilterError}</span>}
        </FilterField>}
        <FilterField label={isDetailsView ? "线索生成日期起" : "统计日期起"}>
          <FieldInput
            onChange={(event) => {
              setPage(1);
              setAssignedDateStart(event.target.value);
            }}
            type="date"
            value={assignedDateStart}
          />
        </FilterField>
        <FilterField label={isDetailsView ? "线索生成日期止" : "统计日期止"}>
          <FieldInput
            onChange={(event) => {
              setPage(1);
              setAssignedDateEnd(event.target.value);
            }}
            type="date"
            value={assignedDateEnd}
          />
        </FilterField>
        <SelectField
          className="clue-tour-status"
          id="clue-status-filter"
          label="线索状态"
          onChange={(value) => {
            setPage(1);
            setStoreDisplayStatus(value);
          }}
          options={[
            { value: "", label: "全部" },
            ...storeDisplayStatusOptions.map((status) => ({
              value: status,
              label: status,
            })),
          ]}
          value={storeDisplayStatus}
        />
        {!isDetailsView && <SelectField label="商品范围" value={productScope} options={CLUE_PRODUCT_SCOPE_OPTIONS}
          onChange={(value) => setProductScope(normalizeClueProductScope(value))} />}
        <SelectField
          label="商品类型"
          onChange={(value) => {
            setPage(1);
            setProductType(value);
          }}
          options={[{ value: "all", label: "全部商品" }, ...Array.from(new Set(meta?.product_types ?? [])).filter((value) => value !== "all").map((value) => ({ value, label: value }))]}
          value={activeProductType}
        />
        {isDetailsView && (
          <CheckboxField
            label="仅看自店核销"
            description="核销门店与本轮分配门店相同"
            checked={selfStoreVerified}
            onChange={(event) => {
              setSelfStoreVerified(event.target.checked);
              setPage(1);
            }}
          />
        )}
        <Button onClick={resetFilters} type="button">
          清空筛选
        </Button>
        <Button
          aria-controls="clue-filter-panel"
          className="clue-filter-collapse-mobile"
          onClick={() => setMobileFiltersOpen(false)}
          type="button"
          variant="secondary"
        >
          收起筛选
        </Button>
      </FilterBar>

      {!isDetailsView && !overview && overviewResource.loading ? (
        <ResourcePanel>正在加载线索指标...</ResourcePanel>
      ) : !isDetailsView && !overview ? (
        <ResourcePanel tone="error">线索指标暂不可用。</ResourcePanel>
      ) : !isDetailsView && overview ? (
        <section className="metric-grid clue-metric-grid">
          <MetricCard
            label="线索总数"
            meta="当前筛选范围"
            value={formatInteger(overview.total_clues)}
          />
          <MetricCard
            label="可跟进线索"
            meta="仍需门店处理"
            value={formatInteger(overview.active_clues)}
          />
          <MetricCard
            label="24小时跟进率"
            meta={metricsWarming ? "统一指标暂不可用" : metricSample(overview.follow_24h_numerator, overview.follow_denominator)}
            value={overviewRate(metricsWarming ? undefined : overview.follow_24h_rate)}
            description={FOLLOW_24H_DESCRIPTION}
            interactiveTooltip
          />
          <MetricCard
            label="累计跟进率（辅助）"
            meta={metricsWarming ? "统一指标暂不可用" : metricSample(overview.follow_any_numerator, overview.follow_denominator)}
            value={overviewRate(metricsWarming ? undefined : overview.follow_any_rate)}
            description={FOLLOW_ANY_DESCRIPTION}
            interactiveTooltip
          />
          <MetricCard
            label="核销率"
            meta={metricsWarming ? "统一指标暂不可用" : metricSample(overview.verification_numerator, overview.verification_denominator)}
            value={overviewRate(metricsWarming ? undefined : overview.verification_rate)}
            description={VERIFICATION_RATE_DESCRIPTION}
            interactiveTooltip
          />
          <MetricCard
            label="自店核销量"
            meta="按该店首次有效核销日期计单"
            value={metricsWarming || overview.self_store_verification_count == null ? "暂不可用" : formatInteger(overview.self_store_verification_count)}
            description={SELF_STORE_VERIFICATION_DESCRIPTION}
            interactiveTooltip
          />
        </section>
      ) : null}

      {isDetailsView ? (
        <section className="content-section content-section--data-workspace">
          <div className="section-title" data-clue-tour="results">
            <div>
              <h2>当前筛选结果</h2>
              <p>
                店端只展示可判断、可操作的线索信息；导出按当前账号可见范围与当前筛选条件，联系方式为未加密明文。
              </p>
            </div>
            <div className="section-title-actions">
              {pagination ? (
                <span className="result-count">
                  共 {formatInteger(pagination.total)} 条
                </span>
              ) : null}
              <Button
                disabled={exportingClues || !pagination?.total}
                icon="fileDownload"
                loading={exportingClues}
                onClick={handleExportClues}
                size="sm"
                type="button"
              >
                {exportingClues ? "导出中" : "导出"}
              </Button>
            </div>
          </div>
          {exportError ? (
            <p className="export-error" role="status">
              导出失败：{exportError}
            </p>
          ) : null}

          {!rows.length && roundsResource.loading ? (
            <ResourcePanel>正在加载线索明细...</ResourcePanel>
          ) : (
            <>
              <div className="clue-table-view">
                <DataTable
                  columns={columns}
                  emptyText="暂无线索分配记录"
                  onRowDoubleClick={(row, event) => {
                    const trigger = event.currentTarget.querySelector<HTMLButtonElement>(
                      ".clue-detail-trigger",
                    );
                    openClueDetail(row, trigger);
                  }}
                  rows={rows}
                  stickyHeader="container"
                  tableClassName="data-table--clues"
                />
              </div>
              <div className="clue-card-list" aria-label="线索卡片列表">
                {rows.length ? (
                  rows.map((row) => {
                    const status = getStoreDisplayStatus(row);
                    return (
                      <article className="clue-card" key={row.assignment_round_id}>
                        <div className="clue-card__header">
                          <StatusChip tone={clueStatusTone(status)}>{status}</StatusChip>
                          <span>{roundLabel(row.round_no)}</span>
                        </div>
                        <div className="clue-card__phone">
                          {renderPhoneContact(row, "card")}
                        </div>
                        <div className="clue-card__product">
                          <strong>{displayValue(row.product_name)}</strong>
                          <span>{displayValue(row.product_type)}</span>
                        </div>
                        <dl className="clue-card__meta">
                          <div>
                            <dt>核销状态</dt>
                            <dd>{verificationSummary(row)}</dd>
                          </div>
                          <div>
                            <dt>核销门店</dt>
                            <dd>{verificationStoreText(row)}</dd>
                          </div>
                          <div>
                            <dt>最近跟进</dt>
                            <dd>{formatDateTime(row.followed_at)}</dd>
                          </div>
                          <div>
                            <dt>生成时间</dt>
                            <dd>{formatDateTime(row.assigned_at)}</dd>
                          </div>
                          <div>
                            <dt>本轮失效</dt>
                            <dd>{displayValue(formatInvalidatedAt(row))}</dd>
                          </div>
                        </dl>
                        <Button
                          className="clue-card__detail clue-detail-trigger"
                          data-clue-tour={row.assignment_round_id === onboarding.targetRoundId ? "open-detail" : undefined}
                          onClick={(event) => openClueDetail(row, event.currentTarget)}
                          type="button"
                          variant="primary"
                        >
                          查看详情
                        </Button>
                      </article>
                    );
                  })
                ) : (
                  <ResourcePanel>暂无线索分配记录</ResourcePanel>
                )}
              </div>
            </>
          )}

          {pagination ? (
            <TablePagination
              loading={roundsResource.loading}
              onPageChange={setPage}
              onPageSizeChange={(nextPageSize) => {
                setPageSize(nextPageSize);
                setPage(1);
              }}
              page={pagination.page}
              pageSize={pageSize}
              pageSizeOptions={CLUE_PAGE_SIZE_OPTIONS}
              rowsOnPage={rows.length}
              total={pagination.total}
              totalPages={pagination.total_pages}
            />
          ) : null}
        </section>
      ) : null}
      </div>

      {isDetailsView && selectedRound ? (
        <Dialog
          bodyClassName="ui-dialog__body--flush"
          closeLabel="关闭线索详情"
          onClose={closeClueDetail}
          open={isDetailsView && Boolean(selectedRound)}
          panelClassName="clue-detail-modal clue-followup-detail"
          returnFocusRef={detailReturnFocusRef}
          title="线索跟进详情"
        >
          <div
            className="clue-followup-detail__body"
            onTouchEnd={handleDetailTouchEnd}
            onTouchStart={handleDetailTouchStart}
          >
            {detailLoading ? (
              <ResourcePanel>正在加载详情...</ResourcePanel>
            ) : detailError ? (
              <ResourcePanel tone="error">
                线索详情暂不可用：{detailError}
              </ResourcePanel>
            ) : detail && activeDetailRound ? (
              <>
                {phoneRevealError ? (
                  <div
                    aria-atomic="true"
                    aria-live="polite"
                    className="resource-notice resource-notice--warning"
                    role="status"
                  >
                    {phoneRevealError}
                  </div>
                ) : null}
                {phoneActionMessage ? (
                  <div
                    aria-atomic="true"
                    aria-live="polite"
                    className="clue-followup-toast"
                    role="status"
                  >
                    {phoneActionMessage}
                  </div>
                ) : null}
                {followUpError ? (
                  <div
                    aria-atomic="true"
                    aria-live="assertive"
                    className="resource-notice resource-notice--error"
                    role="alert"
                  >
                    {followUpError}
                  </div>
                ) : null}
                <div className="clue-followup-detail__grid">
                  <section
                    aria-label="手机号与状态"
                    className="clue-followup-contact-status"
                    data-clue-tour="contact"
                  >
                    <div className="clue-followup-contact-card">
                      <span>联系方式 · 号码操作</span>
                      {renderPhoneContact(activeDetailRound, "detail")}
                    </div>
                    <div className="clue-followup-status-card">
                      <span>线索状态</span>
                      <StatusChip tone={clueStatusTone(activeDetailStatus ?? "不可跟进")}>
                        {activeDetailStatus ?? "不可跟进"}
                      </StatusChip>
                    </div>
                  </section>

                  <aside className="clue-followup-detail__side">
                    <section className="clue-followup-side-section clue-followup-action-section">
                      <h3>跟进操作</h3>
                      {canEditFollowUp ? (
                        <form className="clue-followup-form" onSubmit={handleSaveFollowUp}>
                          <fieldset data-clue-tour="follow-up">
                            <legend>跟进结果</legend>
                            <label>
                              <FieldInput
                                aria-label="已预约"
                                checked={followResult === "appointment"}
                                name="follow_result"
                                onChange={() => setFollowResult("appointment")}
                                type="radio"
                                value="appointment"
                              />
                              已预约
                            </label>
                            <label>
                              <FieldInput
                                aria-label="待进一步跟进"
                                checked={followResult === "further_follow_up"}
                                name="follow_result"
                                onChange={() => setFollowResult("further_follow_up")}
                                type="radio"
                                value="further_follow_up"
                              />
                              待进一步跟进
                            </label>
                            <label>
                              <FieldInput
                                aria-label="线索战败"
                                checked={followResult === "lost"}
                                name="follow_result"
                                onChange={() => setFollowResult("lost")}
                                type="radio"
                                value="lost"
                              />
                              线索战败
                            </label>
                            <label>
                              <FieldInput
                                aria-label="未联系上"
                                checked={followResult === "unreachable"}
                                name="follow_result"
                                onChange={() => setFollowResult("unreachable")}
                                type="radio"
                                value="unreachable"
                              />
                              未联系上
                            </label>
                            <label>
                              <FieldInput
                                aria-label="客户要求换门店"
                                checked={followResult === "request_store_change"}
                                name="follow_result"
                                onChange={() => setFollowResult("request_store_change")}
                                type="radio"
                                value="request_store_change"
                              />
                              客户要求换门店
                            </label>
                          </fieldset>
                          {followResult === "appointment" ? (
                            <FilterField label="预约到店时间（北京时间，必填）">
                              <FieldInput aria-label="预约到店时间（北京时间，必填）" type="datetime-local" required step={60}
                                value={followAppointmentAt} onChange={(event) => setFollowAppointmentAt(event.target.value)} />
                            </FilterField>
                          ) : null}
                          <label className="clue-followup-note">
                            <span>本次跟进结论/备注（选填）</span>
                            <FieldTextarea
                              onChange={(event) => setFollowNote(event.target.value)}
                              rows={5}
                              value={followNote}
                            />
                          </label>
                          {activeDetailRound.routing_mode != null ? <p className="clue-followup-help">每次提交会保留为一条历史记录，提交后不可撤回、修改或删除。</p> : null}
                          {followResult === "lost" || followResult === "request_store_change" ? (
                            <p className="clue-followup-help">{activeDetailRound.routing_mode != null ? "提交后将关闭该线索。" : "提交后将结束本轮跟进。"}{followResult === "request_store_change" ? "请客户自行联系意向门店。" : ""}</p>
                          ) : null}
                          <Button
                            data-clue-tour="save"
                            disabled={savingFollowUp}
                            loading={savingFollowUp}
                            type="submit"
                            variant="primary"
                          >
                            {savingFollowUp ? "保存中" : "保存本次跟进"}
                          </Button>
                        </form>
                      ) : (
                        <ResourcePanel>
                          {getFollowUpUnavailableReason(activeDetailRound)}
                        </ResourcePanel>
                      )}
                    </section>
                  </aside>

                  <main className="clue-followup-detail__main">
                    <section className="clue-followup-product clue-followup-order">
                      <div className="clue-followup-section-title">
                        <h3>商品与订单</h3>
                      </div>
                      <dl className="clue-followup-order-fields">
                        <div>
                          <dt>订单编号</dt>
                          <dd className="mono-cell">{detail.order_id}</dd>
                        </div>
                        <div className="clue-followup-order-fields__product">
                          <dt>完整商品名称</dt>
                          <dd>{displayValue(detailProductName)}</dd>
                        </div>
                        <div>
                          <dt>商品类型</dt>
                          <dd>{displayValue(detailProductType)}</dd>
                        </div>
                        <div>
                          <dt>订单状态</dt>
                          <dd>{detailOrderStatus}</dd>
                        </div>
                        <div>
                          <dt>下单时间</dt>
                          <dd>{formatDateTime(detail.order_created_at)}</dd>
                        </div>
                        <div>
                          <dt>核销门店</dt>
                          <dd>{activeDetailRound ? verificationStoreText(activeDetailRound) : "-"}</dd>
                        </div>
                      </dl>
                    </section>

                    <section className="clue-followup-history">
                      <div className="clue-followup-section-title" data-clue-tour="history">
                        <h3>线索跟进历史</h3>
                        <CountPill>
                          {detail.rounds.length}轮 · {detail.follow_up_records.length}条记录
                        </CountPill>
                      </div>
                      {detail.rounds.length ? (
                        <ol className="clue-followup-timeline">
                          {detail.rounds.map((round) => {
                            const status = getStoreDisplayStatus(round);
                            const roundRecords = recordsForRound(
                              detail,
                              round.assignment_round_id,
                              canDeleteRecordsForRound(round),
                            );
                            return (
                              <li
                                className={
                                  round.is_current_round
                                    ? "clue-followup-timeline__item clue-followup-round-card is-current"
                                    : "clue-followup-timeline__item clue-followup-round-card"
                                }
                                key={round.assignment_round_id}
                              >
                                <div className="clue-followup-timeline__head">
                                  <strong>
                                    {roundLabel(round.round_no)}
                                    {round.is_current_round ? " / 当前" : ""}
                                  </strong>
                                  <StatusChip tone={clueStatusTone(status)}>
                                    {status}
                                  </StatusChip>
                                </div>
                                <dl className="clue-followup-history-fields">
                                  <div>
                                    <dt>分配时间</dt>
                                    <dd>{formatDateTime(round.assigned_at)}</dd>
                                  </div>
                                  <div>
                                    <dt>跟进门店</dt>
                                    <dd>
                                      {displayValue(
                                        round.assigned_store_name,
                                      )}
                                    </dd>
                                  </div>
                                  <div>
                                    <dt>再分配原因</dt>
                                    <dd>{roundTransitionReason(round)}</dd>
                                  </div>
                                  <div>
                                    <dt>失效时间</dt>
                                    <dd>{displayValue(formatInvalidatedAt(round))}</dd>
                                  </div>
                                  <div>
                                    <dt>最近结果</dt>
                                    <dd>{labelFor(round.follow_result, followResultLabels)}</dd>
                                  </div>
                                  {round.appointment_at ? <div>
                                    <dt>预约到店时间</dt>
                                    <dd>{formatDateTime(round.appointment_at)}</dd>
                                  </div> : null}
                                  {round.expires_at && round.round_effective_status === "active" ? <div>
                                    <dt>本轮截止时间</dt>
                                    <dd>{formatDateTime(round.expires_at)}</dd>
                                  </div> : null}
                                </dl>
                                <div className="clue-followup-round-records">
                                  {roundRecords.length ? (
                                    <ol>
                                      {roundRecords.map((record) => (
                                        <li
                                          className="clue-followup-round-record"
                                          key={record.follow_up_record_id}
                                        >
                                          <strong>{formatDateTime(record.created_at)}</strong>
                                          <span>
                                            {labelFor(
                                              record.follow_result,
                                              followResultLabels,
                                            )}
                                          </span>
                                          <div className="clue-followup-record-content">
                                            {record.appointment_at ? <p>预约到店：{formatDateTime(record.appointment_at)}</p> : null}
                                            <p>{record.note?.trim() || "未填写备注"}</p>
                                          </div>
                                          {record.is_deleted ? (
                                            <p>
                                              已删除
                                              {record.deleted_by_username
                                                ? ` · ${record.deleted_by_username}`
                                                : ""}
                                            </p>
                                          ) : null}
                                          {record.timing_state || record.status_reason ? (
                                            <p>
                                              {[
                                                displayFollowUpTimingState(record.timing_state),
                                                displayClueReason(record.status_reason),
                                              ]
                                                .filter((value) => value !== "-")
                                                .join(" · ")}
                                            </p>
                                          ) : null}
                                          {canDeleteRecordsForRound(round) && !record.is_deleted ? (
                                            <IconButton
                                              className="clue-followup-delete-record"
                                              disabled={
                                                deletingFollowUpRecordId ===
                                                record.follow_up_record_id
                                              }
                                              icon="trash"
                                              label="删除跟进历史"
                                              onClick={() => {
                                                void handleDeleteFollowUpRecord(record);
                                              }}
                                              size="sm"
                                              title="删除跟进历史"
                                              type="button"
                                              variant="danger"
                                            />
                                          ) : null}
                                        </li>
                                      ))}
                                    </ol>
                                  ) : (
                                    <ol>
                                      <li className="clue-followup-round-record">
                                        <strong>暂无记录</strong>
                                        <span>待处理</span>
                                        <p>本轮尚未登记跟进结果。</p>
                                      </li>
                                    </ol>
                                  )}
                                </div>
                                {round.verification_facts?.length ? (
                                  <section className="clue-round-verifications" aria-label={`${roundLabel(round.round_no)}核销明细`}>
                                    <h4>核销明细 · {verificationSummary(round)}</h4>
                                    {round.verification_facts.map((fact) => {
                                      const creditedRound = detail.rounds.find((item) => item.assignment_round_id === fact.credited_assignment_round_id);
                                      return <dl className="clue-followup-history-fields" key={`${fact.verify_id}:${fact.assignment_round_id}`}>
                                        <div><dt>核销门店</dt><dd>{fact.verified_store_name || fact.verified_store_id || "核销门店暂缺"}</dd></div>
                                        <div><dt>实际核销时间</dt><dd>{formatDateTime(fact.verified_at)}</dd></div>
                                        <div><dt>核销前有效跟进</dt><dd>{fact.had_valid_follow_before_verify ? "是" : "否"}</dd></div>
                                        <div><dt>计入本轮门店核销率</dt><dd>{fact.counts_for_store_verification_rate ? "是" : "否"}</dd></div>
                                        <div><dt>补计轮次</dt><dd>{fact.is_back_credit ? (creditedRound ? roundLabel(creditedRound.round_no) : "原承接轮次") : "无"}</dd></div>
                                      </dl>;
                                    })}
                                  </section>
                                ) : null}
                              </li>
                            );
                          })}
                        </ol>
                      ) : (
                        <ResourcePanel>暂无跟进历史。</ResourcePanel>
                      )}
                    </section>
                  </main>
                </div>
                <nav
                  aria-label="切换线索"
                  className="clue-followup-detail__pager"
                >
                  <Button
                    disabled={!hasPreviousClue}
                    onClick={() => switchSelectedClue(-1)}
                    size="sm"
                    type="button"
                    variant="secondary"
                  >
                    上一条线索
                  </Button>
                  <span>{currentCluePosition}</span>
                  <Button
                    disabled={!hasNextClue}
                    onClick={() => switchSelectedClue(1)}
                    size="sm"
                    type="button"
                    variant="secondary"
                  >
                    下一条线索
                  </Button>
                </nav>
              </>
            ) : <ResourcePanel>本轮详情暂不可用，请关闭后重新打开。</ResourcePanel>}
          </div>
        </Dialog>
      ) : null}
      {onboarding.running ? <GuidedTour {...onboarding.tourProps} /> : null}
    </div>
  );
}
