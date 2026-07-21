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
  fetchClueOrderDetail,
  fetchClueOrderPhone,
  fetchClueOverview,
  saveClueFollowUp,
} from "../api/client";
import { Button, IconButton } from "../components/Button";
import { CountPill, FilterChip, StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { FilterBar, FilterField } from "../components/Filters";
import { SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import {
  ResourceNotice,
  ResourcePanel,
  resourceSourceLabel,
} from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type {
  ClueFilterMetadata,
  ClueAssignmentRound,
  ClueFollowUpAction,
  ClueFollowUpRecord,
  ClueOrderDetail,
  ClueOverviewFilters,
  AdminUser,
} from "../types/dashboard";
import { formatDateTime, formatInteger, formatPercent } from "../utils/format";
import {
  displayClueReason,
  displayFollowUpTimingState,
  displayOrderStatus,
} from "../utils/userFacingLabels";

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
  | "assignedDateStart"
  | "assignedDateEnd"
  | "storeDisplayStatus"
  | "productType";

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
  unreachable: "未接通",
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
  return value ? `第${value}轮` : "-";
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

function verificationStatusText(row: ClueAssignmentRound): string {
  if (!row.verified_store_id) {
    return "未核销";
  }
  return row.is_self_store_verified ? "本店核销" : "非本店核销";
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
  return (
    detail.rounds.find((round) => round.assignment_round_id === selectedRoundId) ??
    detail.rounds.find((round) => round.round_effective_status === "active") ??
    detail.rounds[detail.rounds.length - 1] ??
    selectedRound
  );
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
  const [province, setProvince] = useState(searchParams.get("province") ?? "");
  const [city, setCity] = useState(searchParams.get("city") ?? "");
  const [assignedStoreId, setAssignedStoreId] = useState(
    searchParams.get("assigned_store_id") ?? "",
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
  const [page, setPage] = useState(1);
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
  const [followUpError, setFollowUpError] = useState<string | null>(null);
  const [deletingFollowUpRecordId, setDeletingFollowUpRecordId] =
    useState<string | null>(null);
  const [savingFollowUp, setSavingFollowUp] = useState(false);
  const detailReturnFocusRef = useRef<HTMLElement | null>(null);
  const detailTouchStartRef = useRef<{ x: number; y: number } | null>(null);

  const filterResource = useApiResource(fetchClueFilters, []);
  const meta = filterResource.data?.data;
  const activeProductType = productType || clueDefaultProductType(meta);

  const filters: ClueOverviewFilters = useMemo(
    () => ({
      assigned_store_id: showStoreLocationFilters ? assignedStoreId : "",
      assigned_date_start: assignedDateStart,
      assigned_date_end: assignedDateEnd,
      store_display_status: storeDisplayStatus,
      product_type: activeProductType,
      province: showStoreLocationFilters ? province : "",
      city: showStoreLocationFilters ? city : "",
    }),
    [
      assignedStoreId,
      assignedDateEnd,
      assignedDateStart,
      activeProductType,
      city,
      province,
      showStoreLocationFilters,
      storeDisplayStatus,
    ],
  );

  const activeFilterChips: ActiveClueFilter[] = useMemo(() => {
    const chips: ActiveClueFilter[] = [];
    if (showStoreLocationFilters && province) {
      chips.push({ key: "province", label: "省份", value: province });
    }
    if (showStoreLocationFilters && city) {
      chips.push({ key: "city", label: "城市", value: city });
    }
    if (showStoreLocationFilters && assignedStoreId) {
      chips.push({
        key: "assignedStoreId",
        label: "门店",
        value:
          meta?.assigned_stores.find(
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
    if (activeProductType && activeProductType !== "all") {
      chips.push({ key: "productType", label: "商品", value: activeProductType });
    }
    return chips;
  }, [
    activeProductType,
    assignedDateEnd,
    assignedDateStart,
    assignedStoreId,
    city,
    meta?.assigned_stores,
    province,
    showStoreLocationFilters,
    storeDisplayStatus,
  ]);

  const overviewResource = useApiResource(
    () => fetchClueOverview(filters),
    [
      assignedStoreId,
      assignedDateEnd,
      assignedDateStart,
      activeProductType,
      city,
      province,
      showStoreLocationFilters,
      storeDisplayStatus,
    ],
    { enabled: !isDetailsView },
  );
  const roundsResource = useApiResource(
    () => fetchClueAssignmentRounds({ filters, page, pageSize }),
    [
      assignedStoreId,
      assignedDateEnd,
      assignedDateStart,
      city,
      page,
      pageSize,
      activeProductType,
      province,
      showStoreLocationFilters,
      isDetailsView,
      storeDisplayStatus,
    ],
    { enabled: isDetailsView },
  );
  const overview = overviewResource.data?.data;
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
  const loading =
    filterResource.loading ||
    (isDetailsView ? roundsResource.loading : overviewResource.loading);
  const activeResourceError =
    filterResource.error ??
    (isDetailsView ? roundsResource.error : overviewResource.error);
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
  const detailVerificationStatus = activeDetailRound
    ? verificationStatusText(activeDetailRound)
    : "-";
  const canShowActiveDetailPhone = activeDetailRound
    ? canViewFullPhone(activeDetailRound)
    : false;
  const canEditFollowUp = activeDetailRound
    ? canOperateCurrentRound(activeDetailRound)
    : false;
  const canDeleteFollowUpRecords = currentUser.is_highest_admin === true;
  const handleExportClues = async () => {
    setExportingClues(true);
    setExportError(null);
    try {
      await exportClueAssignmentRounds(filters);
    } catch (error: unknown) {
      setExportError(error instanceof Error ? error.message : "线索明细导出失败");
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
        setDetailError(error instanceof Error ? error.message : "线索详情加载失败");
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
  }, [selectedOrderId]);

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
    setProvince("");
    setCity("");
    setAssignedStoreId("");
    setAssignedDateStart("");
    setAssignedDateEnd("");
    setStoreDisplayStatus("");
    setProductType("");
    setPage(1);
  };

  const removeFilter = (key: ClueFilterKey) => {
    setPage(1);
    if (key === "province") {
      setProvince("");
    } else if (key === "city") {
      setCity("");
    } else if (key === "assignedStoreId") {
      setAssignedStoreId("");
    } else if (key === "assignedDateStart") {
      setAssignedDateStart("");
    } else if (key === "assignedDateEnd") {
      setAssignedDateEnd("");
    } else if (key === "storeDisplayStatus") {
      setStoreDisplayStatus("");
    } else if (key === "productType") {
      setProductType("all");
    }
  };

  const handleSaveFollowUp = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail || !activeDetailRound || !canEditFollowUp) {
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
      setFollowUpError(error instanceof Error ? error.message : "跟进保存失败");
    } finally {
      setSavingFollowUp(false);
    }
  };

  const handleDeleteFollowUpRecord = async (record: ClueFollowUpRecord) => {
    if (!canDeleteFollowUpRecords || deletingFollowUpRecordId) {
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
      setFollowUpError(
        error instanceof Error ? error.message : "跟进历史删除失败",
      );
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
        </div>
        <span className="source-pill">
          {isDetailsView
            ? resourceSourceLabel(roundsResource.data, roundsResource.loading)
            : resourceSourceLabel(overviewResource.data, overviewResource.loading)}
        </span>
      </section>

      <ResourceNotice
        error={activeResourceError}
        fallbackReason={activeFallbackReason}
        loading={loading}
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
            <FilterField label="门店">
              <SearchableStoreSelect
                allowEmpty
                emptyMessage="未找到门店"
                options={(meta?.assigned_stores ?? []).map((store) => ({
                  label: store.store_name,
                  value: store.store_id,
                }))}
                placeholder="搜索门店名称"
                value={assignedStoreId}
                onChange={(value) => {
                  setPage(1);
                  setAssignedStoreId(value);
                }}
              />
            </FilterField>
          </>
        ) : null}
        <FilterField label="线索生成日期起">
          <input
            onChange={(event) => {
              setPage(1);
              setAssignedDateStart(event.target.value);
            }}
            type="date"
            value={assignedDateStart}
          />
        </FilterField>
        <FilterField label="线索生成日期止">
          <input
            onChange={(event) => {
              setPage(1);
              setAssignedDateEnd(event.target.value);
            }}
            type="date"
            value={assignedDateEnd}
          />
        </FilterField>
        <SelectField
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
        <SelectField
          label="商品类型"
          onChange={(value) => {
            setPage(1);
            setProductType(value);
          }}
          options={[{ value: "all", label: "全部" }, ...optionList(meta?.product_types)]}
          value={activeProductType}
        />
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
            meta="筛选范围内订单粒度"
            value={formatInteger(overview.total_clues)}
          />
          <MetricCard
            label="可跟进线索"
            meta="仍需门店处理"
            value={formatInteger(overview.active_clues)}
          />
          <MetricCard
            label="线索跟进率"
            meta="成功跟进 / 全部线索"
            value={formatPercent(overview.follow_success_rate)}
          />
          <MetricCard
            label="核销数"
            meta="进入跟进池后已核销"
            value={formatInteger(overview.verified_count)}
          />
          <MetricCard
            label="核销比例"
            meta="成功且完成核销"
            value={formatPercent(overview.self_store_verify_rate)}
          />
          <MetricCard
            label="待处理"
            meta="战败或超期"
            value={formatInteger(overview.pending_reassign_count)}
          />
        </section>
      ) : null}

      {isDetailsView ? (
        <section className="content-section content-section--data-workspace">
          <div className="section-title">
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
                          <fieldset>
                            <legend>跟进结果</legend>
                            <label>
                              <input
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
                              <input
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
                              <input
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
                              <input
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
                              <input
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
                          <label className="clue-followup-note">
                            <span>本次跟进结论/备注</span>
                            <textarea
                              onChange={(event) => setFollowNote(event.target.value)}
                              rows={5}
                              value={followNote}
                            />
                          </label>
                          <Button
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
                          <dd>{formatDateTime(activeDetailRound.assigned_at)}</dd>
                        </div>
                        <div>
                          <dt>核销状态</dt>
                          <dd>{detailVerificationStatus}</dd>
                        </div>
                      </dl>
                    </section>

                    <section className="clue-followup-history">
                      <div className="clue-followup-section-title">
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
                              canDeleteFollowUpRecords,
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
                                          <p>{displayValue(record.note)}</p>
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
                                          {canDeleteFollowUpRecords && !record.is_deleted ? (
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
            ) : null}
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
