import { useEffect, useMemo, useState } from "react";
import {
  fetchClueAssignmentRounds,
  fetchClueFilters,
  fetchClueOrderDetail,
  fetchClueOrderPhone,
  fetchClueOverview,
} from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { MetricCard } from "../components/MetricCard";
import {
  ResourceNotice,
  ResourcePanel,
  resourceSourceLabel,
} from "../components/ResourceState";
import { SolarIcon } from "../components/SolarIcon";
import { useApiResource } from "../hooks/useApiResource";
import type {
  ClueAssignmentRound,
  ClueOrderDetail,
  ClueOverviewFilters,
} from "../types/dashboard";
import { formatDateTime, formatInteger, formatPercent } from "../utils/format";

interface ClueCenterPageProps {
  searchParams: URLSearchParams;
}

const PAGE_SIZE = 20;

const leadStatusLabels: Record<string, string> = {
  active: "有效线索",
  pending_reassign: "待再分配",
  converted: "已转化",
  closed: "已关闭",
};

const roundStatusLabels: Record<string, string> = {
  active_unfollowed: "未跟进",
  active_followed: "已跟进",
  failed_pending_reassign: "跟进失败待再分配",
  expired_pending_reassign: "超时待再分配",
  reassigned: "已再分配",
};

const followResultLabels: Record<string, string> = {
  pending: "未跟进",
  success: "成功跟进",
  failed: "跟进失败",
  unreachable: "未接通",
  continue_following: "继续跟进",
};

const reassignReasonLabels: Record<string, string> = {
  timeout: "超时未跟进",
  follow_failed: "门店反馈跟进失败",
  manual: "人工再分配",
};

const roundNames = ["第一轮", "第二轮", "第三轮", "第四轮", "第五轮"];

function labelFor(value: string | null | undefined, labels: Record<string, string>) {
  if (!value) {
    return "-";
  }
  return labels[value] ?? value;
}

function displayValue(value: string | null | undefined): string {
  return value ? value : "-";
}

function roundLabel(index: number, total: number): string {
  const base = roundNames[index] ?? `第${index + 1}轮`;
  return index === total - 1 ? `${base} / 当前` : base;
}

function formatRemainingSeconds(value: number | null): string {
  if (value === null) {
    return "";
  }
  if (value <= 0) {
    return "0分钟";
  }
  const hours = Math.floor(value / 3600);
  const minutes = Math.ceil((value % 3600) / 60);
  if (hours <= 0) {
    return `${minutes}分钟`;
  }
  return `${hours}小时${minutes > 0 ? `${minutes}分钟` : ""}`;
}

function optionList(values: string[] | undefined, labels?: Record<string, string>) {
  return (values ?? []).map((value) => ({
    value,
    label: labels?.[value] ?? value,
  }));
}

export function ClueCenterPage({ searchParams }: ClueCenterPageProps) {
  const [assignedDateStart, setAssignedDateStart] = useState(
    searchParams.get("assigned_date_start") ?? "",
  );
  const [assignedDateEnd, setAssignedDateEnd] = useState(
    searchParams.get("assigned_date_end") ?? "",
  );
  const [leadStatus, setLeadStatus] = useState(searchParams.get("lead_status") ?? "");
  const [roundStatus, setRoundStatus] = useState(
    searchParams.get("round_status") ?? "",
  );
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "",
  );
  const [city, setCity] = useState(searchParams.get("city") ?? "");
  const [page, setPage] = useState(1);
  const [selectedRound, setSelectedRound] = useState<ClueAssignmentRound | null>(
    null,
  );
  const [detail, setDetail] = useState<ClueOrderDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailSource, setDetailSource] = useState("");
  const [revealedPhones, setRevealedPhones] = useState<Record<string, string>>({});
  const [revealingOrderId, setRevealingOrderId] = useState<string | null>(null);
  const [phoneRevealError, setPhoneRevealError] = useState<string | null>(null);

  const filterResource = useApiResource(fetchClueFilters, []);
  const meta = filterResource.data?.data;

  const filters: ClueOverviewFilters = useMemo(
    () => ({
      assigned_date_start: assignedDateStart,
      assigned_date_end: assignedDateEnd,
      lead_status: leadStatus,
      round_status: roundStatus,
      product_type: productType,
      city,
    }),
    [
      assignedDateEnd,
      assignedDateStart,
      city,
      leadStatus,
      productType,
      roundStatus,
    ],
  );

  const overviewResource = useApiResource(
    () => fetchClueOverview(filters),
    [
      assignedDateEnd,
      assignedDateStart,
      city,
      leadStatus,
      productType,
      roundStatus,
    ],
  );
  const roundsResource = useApiResource(
    () => fetchClueAssignmentRounds({ filters, page, pageSize: PAGE_SIZE }),
    [
      assignedDateEnd,
      assignedDateStart,
      city,
      leadStatus,
      page,
      productType,
      roundStatus,
    ],
  );
  const overview = overviewResource.data?.data;
  const rows = roundsResource.data?.data.rows ?? [];
  const pagination = roundsResource.data?.data.pagination;
  const loading =
    filterResource.loading || overviewResource.loading || roundsResource.loading;
  const selectedOrderId = selectedRound?.order_id ?? null;
  const selectedRoundId = selectedRound?.assignment_round_id ?? null;
  const detailProductLabel = detail
    ? [detail.product_name, detail.product_type].filter(Boolean).join(" / ") ||
      detail.product_id ||
      "-"
    : "-";
  const detailRegionLabel = detail
    ? [detail.assigned_province, detail.assigned_city].filter(Boolean).join(" / ") ||
      "-"
    : "-";

  const openClueDetail = (row: ClueAssignmentRound) => {
    setSelectedRound(row);
  };

  const closeClueDetail = () => {
    setSelectedRound(null);
    setDetail(null);
    setDetailError(null);
    setDetailSource("");
    setDetailLoading(false);
  };

  const revealPhone = async (orderId: string) => {
    if (revealedPhones[orderId]) {
      return;
    }
    setPhoneRevealError(null);
    setRevealingOrderId(orderId);
    try {
      const result = await fetchClueOrderPhone(orderId);
      setRevealedPhones((current) => ({
        ...current,
        [orderId]: result.data.phone,
      }));
    } catch (error: unknown) {
      setPhoneRevealError(
        error instanceof Error ? error.message : "手机号暂不可查看",
      );
    } finally {
      setRevealingOrderId(null);
    }
  };

  const renderPhoneContact = (orderId: string, phoneMasked: string) => {
    const revealedPhone = revealedPhones[orderId];
    const displayPhone = revealedPhone || phoneMasked || "-";
    const canReveal = Boolean(phoneMasked) && !revealedPhone;
    return (
      <span className="phone-reveal">
        <span className="mono-cell">{displayPhone}</span>
        {canReveal ? (
          <button
            className="link-button"
            disabled={revealingOrderId === orderId}
            onClick={(event) => {
              event.stopPropagation();
              void revealPhone(orderId);
            }}
            type="button"
          >
            {revealingOrderId === orderId ? "读取中" : "查看"}
          </button>
        ) : null}
      </span>
    );
  };

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
        setDetailSource(
          result.usingMock ? "mock fallback" : result.meta.source || "api",
        );
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
  }, [selectedOrderId]);

  useEffect(() => {
    if (!selectedOrderId) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeClueDetail();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedOrderId]);

  const resetFilters = () => {
    setAssignedDateStart("");
    setAssignedDateEnd("");
    setLeadStatus("");
    setRoundStatus("");
    setProductType("");
    setCity("");
    setPage(1);
  };

  const columns: Column<ClueAssignmentRound>[] = [
    {
      key: "round_effective_status",
      title: "当前轮次",
      minWidth: 110,
      render: (row) => (
        <span className="status-chip">
          {row.round_effective_status === "active" ? "当前生效" : "历史轮次"}
        </span>
      ),
    },
    {
      key: "round_id",
      title: "线索轮次ID",
      minWidth: 180,
      sticky: true,
      render: (row) => (
        <button
          className="link-button mono-cell"
          onClick={(event) => {
            event.stopPropagation();
            openClueDetail(row);
          }}
          type="button"
        >
          {row.assignment_round_id}
        </button>
      ),
    },
    {
      key: "lead_status",
      title: "线索状态",
      minWidth: 110,
      render: (row) => (
        <span className="status-chip">{labelFor(row.lead_status, leadStatusLabels)}</span>
      ),
    },
    {
      key: "round_status",
      title: "轮次状态",
      minWidth: 150,
      render: (row) => (
        <span className="status-chip">
          {labelFor(row.round_status, roundStatusLabels)}
        </span>
      ),
    },
    {
      key: "assigned_at",
      title: "线索生成时间",
      minWidth: 150,
      render: (row) => formatDateTime(row.assigned_at),
    },
    {
      key: "remaining",
      title: "距离再分配剩余时间",
      minWidth: 150,
      render: (row) => formatRemainingSeconds(row.remaining_reassign_seconds),
    },
    {
      key: "phone",
      title: "手机号",
      minWidth: 150,
      render: (row) => renderPhoneContact(row.order_id, row.phone_masked),
    },
    {
      key: "product_type",
      title: "商品类型",
      minWidth: 120,
      render: (row) => row.product_type || "-",
    },
    {
      key: "author",
      title: "达人/作者",
      minWidth: 130,
      render: (row) => row.author_nickname || "-",
    },
    {
      key: "followed_at",
      title: "跟进时间",
      minWidth: 150,
      render: (row) => formatDateTime(row.followed_at),
    },
    {
      key: "follow_result",
      title: "跟进结果",
      minWidth: 120,
      render: (row) => labelFor(row.follow_result, followResultLabels),
    },
    {
      key: "reassigned_at",
      title: "再分配时间",
      minWidth: 150,
      render: (row) => formatDateTime(row.reassigned_at),
    },
    {
      key: "verified",
      title: "自店核销",
      align: "center",
      minWidth: 100,
      render: (row) => (row.is_self_store_verified ? "是" : "否"),
    },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Clue allocation center</p>
          <h1>线索跟进分配中心</h1>
        </div>
        <span className="source-pill">
          {resourceSourceLabel(roundsResource.data, roundsResource.loading)}
        </span>
      </section>

      <ResourceNotice
        error={
          filterResource.error ?? overviewResource.error ?? roundsResource.error
        }
        fallbackReason={
          filterResource.data?.fallbackReason ??
          overviewResource.data?.fallbackReason ??
          roundsResource.data?.fallbackReason
        }
        loading={loading}
      />

      <FilterBar className="clue-filter-bar">
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
        <FilterField label="线索状态">
          <select
            onChange={(event) => {
              setPage(1);
              setLeadStatus(event.target.value);
            }}
            value={leadStatus}
          >
            <option value="">全部</option>
            {optionList(meta?.lead_statuses, leadStatusLabels).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="轮次状态">
          <select
            onChange={(event) => {
              setPage(1);
              setRoundStatus(event.target.value);
            }}
            value={roundStatus}
          >
            <option value="">全部</option>
            {optionList(meta?.round_statuses, roundStatusLabels).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="商品类型">
          <select
            onChange={(event) => {
              setPage(1);
              setProductType(event.target.value);
            }}
            value={productType}
          >
            <option value="">全部</option>
            {optionList(meta?.product_types).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="城市">
          <select
            onChange={(event) => {
              setPage(1);
              setCity(event.target.value);
            }}
            value={city}
          >
            <option value="">全部</option>
            {optionList(meta?.assigned_cities).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <button className="ghost-button" onClick={resetFilters} type="button">
          清空筛选
        </button>
      </FilterBar>

      {!overview && overviewResource.loading ? (
        <ResourcePanel>正在加载线索指标...</ResourcePanel>
      ) : !overview ? (
        <ResourcePanel tone="error">线索指标暂不可用。</ResourcePanel>
      ) : (
        <section className="metric-grid clue-metric-grid">
          <MetricCard
            label="线索总数"
            meta="筛选范围内订单粒度"
            value={formatInteger(overview.total_clues)}
          />
          <MetricCard
            label="有效线索总数"
            meta="当前仍需门店处理"
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
            label="自店核销比例"
            meta="成功且本店核销"
            tone="blue"
            value={formatPercent(overview.self_store_verify_rate)}
          />
          <MetricCard
            label="待再分配"
            meta="失败或超时待处理"
            tone="amber"
            value={formatInteger(overview.pending_reassign_count)}
          />
        </section>
      )}

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>线索明细</h2>
            <p>订单粒度轮次记录，手机号脱敏展示。</p>
          </div>
          {pagination ? (
            <span className="source-pill">
              共 {formatInteger(pagination.total)} 条
            </span>
          ) : null}
        </div>

        {!rows.length && roundsResource.loading ? (
          <ResourcePanel>正在加载线索明细...</ResourcePanel>
        ) : (
          <DataTable
            columns={columns}
            emptyText="暂无线索分配记录"
            onRowDoubleClick={openClueDetail}
            rows={rows}
            tableClassName="data-table--clues"
          />
        )}

        <div className="pagination-controls">
          <span className="pagination-controls__summary">
            第 {formatInteger(pagination?.page ?? page)} /{" "}
            {formatInteger(pagination?.total_pages ?? 1)} 页
          </span>
          <div className="pagination-controls__actions">
            <button
              className="ghost-button"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              type="button"
            >
              上一页
            </button>
            <button
              className="ghost-button"
              disabled={pagination ? page >= pagination.total_pages : true}
              onClick={() =>
                setPage((current) =>
                  Math.min(pagination?.total_pages ?? current, current + 1),
                )
              }
              type="button"
            >
              下一页
            </button>
          </div>
        </div>
      </section>

      {selectedRound ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeClueDetail();
            }
          }}
          role="presentation"
        >
          <section
            aria-labelledby="clue-detail-title"
            aria-modal="true"
            className="clue-detail-modal"
            role="dialog"
          >
            <header className="clue-detail-modal__header">
              <div>
                <p className="eyebrow">Clue flow</p>
                <h2 id="clue-detail-title">线索流转详情</h2>
              </div>
              <div className="clue-detail-modal__actions">
                <span className="source-pill">
                  {detailLoading ? "加载中" : detailSource || "api"}
                </span>
                <button
                  aria-label="关闭线索详情"
                  className="modal-close"
                  onClick={closeClueDetail}
                  type="button"
                >
                  <SolarIcon name="close" size={18} />
                </button>
              </div>
            </header>

            {detailLoading ? (
              <ResourcePanel>正在加载线索流转...</ResourcePanel>
            ) : detailError ? (
              <ResourcePanel tone="error">
                线索详情暂不可用：{detailError}
              </ResourcePanel>
            ) : detail ? (
              <div className="clue-detail-body">
                {phoneRevealError ? (
                  <div className="resource-notice resource-notice--warning">
                    {phoneRevealError}
                  </div>
                ) : null}
                <div className="clue-detail-summary">
                  <div>
                    <span>联系方式</span>
                    <strong>
                      {renderPhoneContact(detail.order_id, detail.phone_masked)}
                    </strong>
                  </div>
                  <div>
                    <span>涉及商品</span>
                    <strong>{detailProductLabel}</strong>
                  </div>
                  <div>
                    <span>订单ID</span>
                    <strong className="mono-cell">{detail.order_id}</strong>
                  </div>
                  <div>
                    <span>城市</span>
                    <strong>{detailRegionLabel}</strong>
                  </div>
                </div>

                {detail.rounds.length ? (
                  <ol className="clue-flow-list">
                    {detail.rounds.map((round, index) => (
                      <li
                        className={[
                          "clue-flow-item",
                          round.assignment_round_id === selectedRoundId
                            ? "is-selected"
                            : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        key={round.assignment_round_id}
                      >
                        <div className="clue-flow-item__header">
                          <div>
                            <span className="clue-flow-round">
                              {roundLabel(index, detail.rounds.length)}
                            </span>
                            <strong className="mono-cell">
                              {round.assignment_round_id}
                            </strong>
                          </div>
                          <span className="status-chip">
                            {labelFor(round.round_status, roundStatusLabels)}
                          </span>
                        </div>
                        <dl className="clue-flow-fields">
                          <div>
                            <dt>线索生成时间</dt>
                            <dd>{formatDateTime(round.assigned_at)}</dd>
                          </div>
                          <div>
                            <dt>再分配原因</dt>
                            <dd>
                              {labelFor(round.reassign_reason, reassignReasonLabels)}
                            </dd>
                          </div>
                          <div>
                            <dt>跟进时间</dt>
                            <dd>{formatDateTime(round.followed_at)}</dd>
                          </div>
                          <div>
                            <dt>跟进结果</dt>
                            <dd>{labelFor(round.follow_result, followResultLabels)}</dd>
                          </div>
                        </dl>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <ResourcePanel>暂无线索流转历史。</ResourcePanel>
                )}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}
