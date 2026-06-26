import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";
import {
  fetchClueAssignmentRounds,
  fetchClueFilters,
  fetchClueOrderDetail,
  fetchClueOrderPhone,
  fetchClueOverview,
  saveClueFollowUp,
} from "../api/client";
import { FilterChip, StatusChip } from "../components/Chips";
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
import { SolarIcon } from "../components/SolarIcon";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type {
  ClueAssignmentRound,
  ClueFollowUpRecord,
  ClueFollowUpResult,
  ClueOrderDetail,
  ClueOverviewFilters,
  AdminUser,
} from "../types/dashboard";
import { formatDateTime, formatInteger, formatPercent } from "../utils/format";

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
  | "leadStatus"
  | "productType"
  | "verificationStatus";

interface ActiveClueFilter {
  key: ClueFilterKey;
  label: string;
  value: string;
}

const leadStatusLabels: Record<string, string> = {
  active: "可跟进",
  pending_reassign: "待处理",
  converted: "已核销",
  refunded: "已退款",
  closed: "不可跟进",
};

const verificationStatusLabels: Record<string, string> = {
  unverified: "未核销",
  self_store_verified: "本店核销",
  other_store_verified: "非本店核销",
};

const followResultLabels: Record<string, string> = {
  pending: "-",
  unreachable: "未接通",
  lost: "线索战败",
  failed: "线索战败",
  success: "跟进成功",
  continue_following: "继续跟进",
};

const reassignReasonLabels: Record<string, string> = {
  timeout: "超期失效",
  follow_failed: "线索战败",
  "follow_lost": "线索战败",
  manual: "人工调整",
  "线索战败": "线索战败",
};

const storeStatusAliases: Record<string, StoreClueStatus> = {
  active_unfollowed: "待跟进",
  active_followed: "已跟进",
  expired_pending_reassign: "超期失效",
  failed_pending_reassign: "主动战败",
  lost: "主动战败",
  failed: "主动战败",
  converted: "已核销",
  refunded: "已退款",
};

const editableStatuses = new Set<StoreClueStatus>(["待跟进", "已跟进"]);
const invalidStatuses = new Set<StoreClueStatus>(["超期失效", "主动战败"]);

function labelFor(value: string | null | undefined, labels: Record<string, string>) {
  if (!value) {
    return "-";
  }
  return labels[value] ?? value;
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

function canViewFullPhone(row: ClueAssignmentRound): boolean {
  return (
    row.is_current_round &&
    row.round_effective_status === "active" &&
    editableStatuses.has(getStoreDisplayStatus(row))
  );
}

function getPhoneUnavailableReason(row: ClueAssignmentRound): string {
  const status = getStoreDisplayStatus(row);
  if (status === "超期失效") {
    return "已失效不可跟进";
  }
  if (status === "主动战败") {
    return "已主动战败，不可跟进";
  }
  if (status === "已核销") {
    return "订单已完成";
  }
  return "不可跟进";
}

function getFollowUpUnavailableReason(row: ClueAssignmentRound): string {
  const status = getStoreDisplayStatus(row);
  if (status === "超期失效") {
    return "已失效不可跟进";
  }
  if (status === "主动战败") {
    return "线索已战败，不可继续跟进";
  }
  if (status === "已核销") {
    return "订单已完成";
  }
  if (status === "已退款") {
    return "订单已退款，不可跟进";
  }
  return "不可跟进";
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
    return labelFor(row.reassign_reason, reassignReasonLabels);
  }
  return "-";
}

function clueStatusTone(status: StoreClueStatus): "amber" | "blue" | "green" | "neutral" {
  if (status === "待跟进") return "blue";
  if (status === "已跟进" || status === "已核销") return "green";
  if (invalidStatuses.has(status)) return "amber";
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
): ClueFollowUpRecord[] {
  return detail.follow_up_records.filter(
    (record) => record.assignment_round_id === assignmentRoundId,
  );
}

function storeScopeLabel(
  assignedStoreId: string | null | undefined,
  selectedStoreId: string | null | undefined,
): string {
  if (!selectedStoreId || assignedStoreId === selectedStoreId) {
    return "本店";
  }
  return "其他门店";
}

export function ClueCenterPage({
  currentUser,
  searchParams,
  view = "dashboard",
}: ClueCenterPageProps) {
  const isDetailsView = view === "details";
  const pageHeadingTitle = isDetailsView ? "线索跟进列表" : "经营线索概览";
  const showStoreLocationFilters =
    currentUser.role !== "store" || currentUser.store_ids.length !== 1;
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
  const [leadStatus, setLeadStatus] = useState(searchParams.get("lead_status") ?? "");
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "",
  );
  const [verificationStatus, setVerificationStatus] = useState(
    searchParams.get("verification_status") ?? "",
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
  const [detailSource, setDetailSource] = useState("");
  const [detailReloadIndex, setDetailReloadIndex] = useState(0);
  const [revealedPhones, setRevealedPhones] = useState<Record<string, string>>({});
  const [revealingOrderId, setRevealingOrderId] = useState<string | null>(null);
  const [copyingOrderId, setCopyingOrderId] = useState<string | null>(null);
  const [phoneRevealError, setPhoneRevealError] = useState<string | null>(null);
  const [phoneActionMessage, setPhoneActionMessage] = useState<string | null>(null);
  const [followResult, setFollowResult] =
    useState<ClueFollowUpResult>("unreachable");
  const [followNote, setFollowNote] = useState("");
  const [followUpError, setFollowUpError] = useState<string | null>(null);
  const [savingFollowUp, setSavingFollowUp] = useState(false);
  const detailReturnFocusRef = useRef<HTMLElement | null>(null);

  const filterResource = useApiResource(fetchClueFilters, []);
  const meta = filterResource.data?.data;

  const filters: ClueOverviewFilters = useMemo(
    () => ({
      assigned_store_id: showStoreLocationFilters ? assignedStoreId : "",
      assigned_date_start: assignedDateStart,
      assigned_date_end: assignedDateEnd,
      lead_status: leadStatus,
      product_type: productType,
      province: showStoreLocationFilters ? province : "",
      city: showStoreLocationFilters ? city : "",
      verification_status: verificationStatus,
    }),
    [
      assignedStoreId,
      assignedDateEnd,
      assignedDateStart,
      city,
      leadStatus,
      productType,
      province,
      showStoreLocationFilters,
      verificationStatus,
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
    if (leadStatus) {
      chips.push({
        key: "leadStatus",
        label: "状态",
        value: labelFor(leadStatus, leadStatusLabels),
      });
    }
    if (productType) {
      chips.push({ key: "productType", label: "商品", value: productType });
    }
    if (verificationStatus) {
      chips.push({
        key: "verificationStatus",
        label: "核销",
        value: labelFor(verificationStatus, verificationStatusLabels),
      });
    }
    return chips;
  }, [
    assignedDateEnd,
    assignedDateStart,
    assignedStoreId,
    city,
    leadStatus,
    meta?.assigned_stores,
    productType,
    province,
    showStoreLocationFilters,
    verificationStatus,
  ]);

  const overviewResource = useApiResource(
    () => fetchClueOverview(filters),
    [
      assignedStoreId,
      assignedDateEnd,
      assignedDateStart,
      city,
      leadStatus,
      productType,
      province,
      showStoreLocationFilters,
      verificationStatus,
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
      leadStatus,
      page,
      pageSize,
      productType,
      province,
      showStoreLocationFilters,
      verificationStatus,
      isDetailsView,
    ],
    { enabled: isDetailsView },
  );
  const overview = overviewResource.data?.data;
  const rows = roundsResource.data?.data.rows ?? [];
  const pagination = roundsResource.data?.data.pagination;
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
  const selectedStoreId = selectedRound?.assigned_store_id ?? null;
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
  const canShowActiveDetailPhone = activeDetailRound
    ? canViewFullPhone(activeDetailRound)
    : false;
  const canEditFollowUp = canShowActiveDetailPhone;
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

  const closeClueDetail = () => {
    setSelectedRound(null);
    setDetail(null);
    setDetailError(null);
    setDetailSource("");
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
    if (revealedPhones[row.order_id]) {
      return revealedPhones[row.order_id];
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

  const renderPhoneContact = (
    row: ClueAssignmentRound,
    mode: "table" | "panel" | "card" = "table",
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
        <button
          aria-label={phoneVisible ? "隐藏完整手机号" : "查看完整手机号"}
          className={iconMode ? "phone-action-button" : "link-button"}
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation();
            if (phoneVisible) {
              hidePhone(row);
              return;
            }
            void revealPhone(row);
          }}
          onDoubleClick={(event) => event.stopPropagation()}
          title={phoneVisible ? "隐藏完整手机号" : "查看完整手机号"}
          type="button"
        >
          {iconMode ? (
            <SolarIcon name={phoneVisible ? "eyeClosed" : "eye"} size={16} />
          ) : phoneVisible ? (
            "隐藏完整手机号"
          ) : revealingOrderId === row.order_id ? (
            "读取中"
          ) : (
            "查看完整手机号"
          )}
        </button>
        <button
          aria-label="复制完整手机号"
          className={iconMode ? "phone-action-button" : "link-button"}
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation();
            void copyPhone(row);
          }}
          onDoubleClick={(event) => event.stopPropagation()}
          title="复制完整手机号"
          type="button"
        >
          {iconMode ? (
            <SolarIcon name="copy" size={16} />
          ) : copyingOrderId === row.order_id ? (
            "复制中"
          ) : (
            "复制完整手机号"
          )}
        </button>
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
    setDetailSource("");
    setDetailLoading(true);

    fetchClueOrderDetail(selectedOrderId)
      .then((result) => {
        if (cancelled) {
          return;
        }
        setDetail(result.data);
        setDetailSource(result.usingMock ? "演示数据" : "实时数据");
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
    setFollowResult("unreachable");
    setFollowNote("");
    setFollowUpError(null);
    setPhoneRevealError(null);
    setPhoneActionMessage(null);
  }, [selectedOrderId]);

  const resetFilters = () => {
    setProvince("");
    setCity("");
    setAssignedStoreId("");
    setAssignedDateStart("");
    setAssignedDateEnd("");
    setLeadStatus("");
    setProductType("");
    setVerificationStatus("");
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
    } else if (key === "leadStatus") {
      setLeadStatus("");
    } else if (key === "productType") {
      setProductType("");
    } else if (key === "verificationStatus") {
      setVerificationStatus("");
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
      if (followResult === "lost") {
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

  const columns: Column<ClueAssignmentRound>[] = [
    {
      key: "phone",
      title: "联系方式",
      minWidth: 230,
      sticky: true,
      render: (row) => (
        <div className="clue-contact-cell">
          {renderPhoneContact(row)}
          <button
            className="link-button clue-detail-trigger"
            onClick={(event) => {
              event.stopPropagation();
              openClueDetail(row, event.currentTarget);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            type="button"
          >
            查看详情
          </button>
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
        <button
          aria-controls="clue-filter-panel"
          aria-expanded={mobileFiltersOpen}
          className="ghost-button clue-filter-toggle"
          onClick={() => setMobileFiltersOpen((current) => !current)}
          type="button"
        >
          筛选{activeFilterChips.length ? ` (${activeFilterChips.length})` : ""}
        </button>
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
            <button
              className="link-button clue-filter-clear-mobile"
              onClick={resetFilters}
              type="button"
            >
              清空
            </button>
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
            setLeadStatus(value);
          }}
          options={[
            { value: "", label: "全部" },
            ...optionList(meta?.lead_statuses, leadStatusLabels),
          ]}
          value={leadStatus}
        />
        <SelectField
          label="商品类型"
          onChange={(value) => {
            setPage(1);
            setProductType(value);
          }}
          options={[{ value: "", label: "全部" }, ...optionList(meta?.product_types)]}
          value={productType}
        />
        <SelectField
          label="核销状态"
          onChange={(value) => {
            setPage(1);
            setVerificationStatus(value);
          }}
          options={[
            { value: "", label: "全部" },
            ...optionList(meta?.verification_statuses, verificationStatusLabels),
          ]}
          value={verificationStatus}
        />
        <button className="ghost-button" onClick={resetFilters} type="button">
          清空筛选
        </button>
        <button
          aria-controls="clue-filter-panel"
          className="ghost-button clue-filter-collapse-mobile"
          onClick={() => setMobileFiltersOpen(false)}
          type="button"
        >
          收起筛选
        </button>
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
            tone="blue"
            value={formatInteger(overview.active_clues)}
          />
          <MetricCard
            label="跟进比例"
            meta="已产生跟进行为"
            value={formatPercent(overview.follow_rate)}
          />
          <MetricCard
            label="跟进成功率"
            meta="成功跟进 / 全部线索"
            tone="amber"
            value={formatPercent(overview.follow_success_rate)}
          />
          <MetricCard
            label="核销比例"
            meta="成功且完成核销"
            tone="blue"
            value={formatPercent(overview.self_store_verify_rate)}
          />
          <MetricCard
            label="待处理"
            meta="战败或超期"
            tone="amber"
            value={formatInteger(overview.pending_reassign_count)}
          />
        </section>
      ) : null}

      {isDetailsView ? (
        <section className="content-section content-section--data-workspace">
          <div className="section-title">
            <div>
              <h2>当前筛选结果</h2>
              <p>店端只展示可判断、可操作的线索信息，完整号码需按权限读取。</p>
            </div>
            {pagination ? (
              <span className="result-count">
                共 {formatInteger(pagination.total)} 条
              </span>
            ) : null}
          </div>

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
                        <button
                          className="primary-button clue-card__detail clue-detail-trigger"
                          onClick={(event) => openClueDetail(row, event.currentTarget)}
                          type="button"
                        >
                          查看详情
                        </button>
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
          description={
            <span className="source-pill">
              {detailLoading ? "加载中" : detailSource || "实时数据"}
            </span>
          }
          onClose={closeClueDetail}
          open={isDetailsView && Boolean(selectedRound)}
          panelClassName="clue-detail-modal clue-followup-detail"
          returnFocusRef={detailReturnFocusRef}
          title="跟进详情"
        >
          <div className="clue-followup-detail__body">
            {detailLoading ? (
              <ResourcePanel>正在加载详情...</ResourcePanel>
            ) : detailError ? (
              <ResourcePanel tone="error">
                线索详情暂不可用：{detailError}
              </ResourcePanel>
            ) : detail && activeDetailRound ? (
              <div className="clue-followup-detail__body">
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
                    className="resource-notice"
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
                  <main className="clue-followup-detail__main">
                    <section className="clue-followup-detail__summary">
                      <div>
                        <span>线索状态</span>
                        <StatusChip tone={clueStatusTone(activeDetailStatus ?? "不可跟进")}>
                          {activeDetailStatus ?? "不可跟进"}
                        </StatusChip>
                      </div>
                      <div>
                        <span>订单编号</span>
                        <strong className="mono-cell">{detail.order_id}</strong>
                      </div>
                      <div>
                        <span>商品类型</span>
                        <strong>{displayValue(detailProductType)}</strong>
                      </div>
                      <div>
                        <span>线索生成时间</span>
                        <strong>{formatDateTime(activeDetailRound.assigned_at)}</strong>
                      </div>
                      <div>
                        <span>跟进轮次</span>
                        <strong>{roundLabel(activeDetailRound.round_no)}</strong>
                      </div>
                    </section>

                    <section className="clue-followup-product">
                      <span>完整商品名称</span>
                      <strong>{displayValue(detailProductName)}</strong>
                    </section>

                    <section className="clue-followup-history">
                      <div className="clue-followup-section-title">
                        <h3>跟进历史</h3>
                      </div>
                      {detail.rounds.length ? (
                        <ol className="clue-followup-timeline">
                          {detail.rounds.map((round) => {
                            const status = getStoreDisplayStatus(round);
                            const roundRecords = recordsForRound(
                              detail,
                              round.assignment_round_id,
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
                                  <div>
                                    <span>
                                      {roundLabel(round.round_no)} ·{" "}
                                      {storeScopeLabel(
                                        round.assigned_store_id,
                                        selectedStoreId,
                                      )}
                                    </span>
                                    <strong>{status}</strong>
                                  </div>
                                  {round.is_current_round ? (
                                    <StatusChip tone="green">当前</StatusChip>
                                  ) : null}
                                </div>
                                <dl className="clue-followup-history-fields">
                                  <div>
                                    <dt>分配时间</dt>
                                    <dd>{formatDateTime(round.assigned_at)}</dd>
                                  </div>
                                  <div>
                                    <dt>处理范围</dt>
                                    <dd>
                                      {storeScopeLabel(
                                        round.assigned_store_id,
                                        selectedStoreId,
                                      )}
                                    </dd>
                                  </div>
                                  <div>
                                    <dt>再分配原因</dt>
                                    <dd>{invalidationReason(round)}</dd>
                                  </div>
                                  <div>
                                    <dt>跟进时间</dt>
                                    <dd>{formatDateTime(round.followed_at)}</dd>
                                  </div>
                                  <div>
                                    <dt>跟进结果</dt>
                                    <dd>{labelFor(round.follow_result, followResultLabels)}</dd>
                                  </div>
                                  <div>
                                    <dt>本轮失效时间</dt>
                                    <dd>{displayValue(formatInvalidatedAt(round))}</dd>
                                  </div>
                                </dl>
                                <div className="clue-followup-round-records">
                                  <h4>本轮跟进记录</h4>
                                  {roundRecords.length ? (
                                    <ol>
                                      {roundRecords.map((record) => (
                                        <li key={record.follow_up_record_id}>
                                          <div>
                                            <strong>
                                              {labelFor(
                                                record.follow_result,
                                                followResultLabels,
                                              )}
                                            </strong>
                                            <span>{formatDateTime(record.created_at)}</span>
                                          </div>
                                          <p>{displayValue(record.note)}</p>
                                        </li>
                                      ))}
                                    </ol>
                                  ) : (
                                    <p>暂无本轮跟进记录</p>
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

                  <aside className="clue-followup-detail__side">
                    <section className="clue-followup-side-section">
                      <h3>号码操作</h3>
                      {renderPhoneContact(activeDetailRound, "panel")}
                    </section>

                    <section className="clue-followup-side-section">
                      <h3>跟进操作</h3>
                      {canEditFollowUp ? (
                        <form className="clue-followup-form" onSubmit={handleSaveFollowUp}>
                          <fieldset>
                            <legend>跟进结果</legend>
                            <label>
                              <input
                                checked={followResult === "unreachable"}
                                name="follow_result"
                                onChange={() => setFollowResult("unreachable")}
                                type="radio"
                                value="unreachable"
                              />
                              未接通
                            </label>
                            <label>
                              <input
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
                                checked={followResult === "success"}
                                name="follow_result"
                                onChange={() => setFollowResult("success")}
                                type="radio"
                                value="success"
                              />
                              跟进成功
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
                          <button
                            className="primary-button"
                            disabled={savingFollowUp}
                            type="submit"
                          >
                            {savingFollowUp ? "保存中" : "保存跟进"}
                          </button>
                        </form>
                      ) : (
                        <ResourcePanel>
                          {getFollowUpUnavailableReason(activeDetailRound)}
                        </ResourcePanel>
                      )}
                    </section>
                  </aside>
                </div>
              </div>
            ) : null}
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
