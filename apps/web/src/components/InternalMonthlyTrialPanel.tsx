import { useId, useRef, useState } from "react";
import { ApiRequestError, downloadMonthlyTrial, downloadMonthlyTrialStores, fetchMonthlyTrial, fetchMonthlyTrialStores } from "../api/client";
import { useApiResource } from "../hooks/useApiResource";
import { useDashboardPublication } from "../hooks/PublicationContext";
import type { AdminUser, FeeDirection } from "../types/dashboard";
import type { MonthlyTrialData, MonthlyTrialRecordStatus, MonthlyTrialRow, MonthlyTrialStoreRow } from "../types/monthlyTrial";
import { formatCurrency, formatDateTime, formatInteger, formatPercent } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { Button } from "./Button";
import { DataTable, type Column } from "./DataTable";
import { SelectField } from "./FormControls";
import { MetricCard } from "./MetricCard";
import { ResourceNotice, ResourcePanel } from "./ResourceState";
import { SegmentedControl } from "./SelectionControls";
import { TablePagination } from "./TablePagination";

interface InternalMonthlyTrialPanelProps {
  currentUser: AdminUser;
  month: string;
  feeDirection?: FeeDirection;
  productType?: string;
  q?: string;
  publicationId?: string;
  defaultOpen?: boolean;
}

const PAGE_SIZE = 50;
const TRIAL_DIRECTIONS = [
  { value: "PROMOTION", label: "推广服务费", pageKey: "FIN01" },
  { value: "MANAGEMENT", label: "管理服务费", pageKey: "FIN02" },
] as const;
const STATUS_LABELS: Record<MonthlyTrialRecordStatus, string> = {
  CALCULATED: "已算费用",
  PENDING: "待核验",
  EXCLUDED: "未计费",
};

function trialAmount(value: number | null | undefined): string {
  return typeof value === "number" ? formatCurrency(value) : "待核验";
}

function trialCount(value: number | null | undefined): string {
  return typeof value === "number" ? `${formatInteger(value)} 张` : "待核验";
}

function trialError(error: unknown): string {
  if (error instanceof ApiRequestError && error.code === "PUBLICATION_TRIAL_NOT_READY") {
    return "所选账期的内部试算尚未就绪，请稍后读取最新试算。";
  }
  if (error instanceof ApiRequestError && error.status === 410) {
    return "原试算版本已过期，请读取最新试算后重试。";
  }
  return userFacingError(error, "内部试算读取失败，请稍后重试。");
}

const columns: Column<MonthlyTrialRow>[] = [
  { key: "coupon", title: "券号", align: "left", minWidth: 180, render: (row) => row.couponId },
  { key: "order", title: "订单编号", align: "left", minWidth: 180, render: (row) => row.orderId },
  { key: "product", title: "商品类型", render: (row) => row.productType && row.productType.toLowerCase() !== "unknown" ? row.productType : "待核验" },
  { key: "base", title: "计费基数", align: "right", minWidth: 120, render: (row) => row.recordStatus === "EXCLUDED" ? "—" : trialAmount(row.baseAmountCent) },
  { key: "rate", title: "费率", align: "right", render: (row) => {
    if (row.recordStatus === "EXCLUDED") return "—";
    return row.feeRate?.trim() && Number.isFinite(Number(row.feeRate)) ? formatPercent(Number(row.feeRate)) : "待核验";
  } },
  { key: "fee", title: "试算费用", align: "right", minWidth: 120, render: (row) => row.recordStatus === "EXCLUDED" ? "—" : trialAmount(row.feeAmountCent) },
  { key: "status", title: "核算状态", render: (row) => STATUS_LABELS[row.recordStatus] ?? "未知状态" },
  { key: "reason", title: "核查说明", align: "left", minWidth: 220, render: (row) => row.reason || "—" },
];

const storeColumns: Column<MonthlyTrialStoreRow>[] = [
  { key: "fee", title: "已算试算费用", align: "right", minWidth: 150, render: (row) => trialAmount(row.calculatedFeeCent) },
  { key: "completeFee", title: "完整试算金额", align: "right", minWidth: 150, render: (row) => row.coverageComplete ? trialAmount(row.calculatedFeeCent) : "待核验" },
  { key: "calculated", title: "已算费用券数", align: "right", render: (row) => trialCount(row.calculatedCouponCount) },
  { key: "pending", title: "待核验券数", align: "right", render: (row) => trialCount(row.pendingCouponCount) },
  { key: "excluded", title: "未计费券数", align: "right", render: (row) => trialCount(row.excludedCouponCount) },
  { key: "candidate", title: "候选券数", align: "right", render: (row) => trialCount(row.candidateCouponCount) },
  { key: "coverage", title: "核查范围", render: (row) => row.coverageComplete ? "已完成" : "待核验" },
];

export function InternalMonthlyTrialPanel(props: InternalMonthlyTrialPanelProps) {
  const [expandedOverride, setExpanded] = useState<boolean>();
  const panelId = useId();
  if (props.currentUser.role !== "admin" || props.month < "2026-10") return null;
  const directions = TRIAL_DIRECTIONS.filter(({ value, pageKey }) =>
    (!props.feeDirection || props.feeDirection === value) && props.currentUser.page_keys.includes(pageKey));
  if (directions.length === 0) return null;
  const expanded = expandedOverride ?? props.defaultOpen ?? false;
  return (
    <div className="page-stack">
      <div>
        <Button aria-controls={panelId} aria-expanded={expanded} onClick={() => setExpanded(!expanded)} variant="secondary">
          {expanded ? "收起内部试算" : "查看内部试算"}
        </Button>
      </div>
      <div hidden={!expanded} id={panelId}>{expanded ? <InternalTrialReadPanel {...props} directions={directions} /> : null}</div>
    </div>
  );
}

function InternalTrialReadPanel({
  currentUser, month, feeDirection, productType = "all", q, publicationId, directions,
}: InternalMonthlyTrialPanelProps & { directions: Array<(typeof TRIAL_DIRECTIONS)[number]> }) {
  const { refreshIndex, refreshLatest } = useDashboardPublication();
  const [selectedDirection, setDirection] = useState<FeeDirection>("PROMOTION");
  const direction = directions.find(({ value }) => value === selectedDirection)?.value ?? directions[0].value;
  const [view, setView] = useState<"COUPONS" | "STORES">(feeDirection ? "COUPONS" : "STORES");
  const [recordStatus, setRecordStatus] = useState<MonthlyTrialRecordStatus | "">("");
  const [pageState, setPageState] = useState({ filter: "", page: 1 });
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [notice, setNotice] = useState<{ filter: string; text: string; error: boolean }>();
  const downloadInFlight = useRef(false);
  const epoch = JSON.stringify([currentUser.username, currentUser.store_scope_mode, currentUser.store_ids, currentUser.page_keys, refreshIndex, publicationId]);
  const pin = useRef<{ epoch: string; id?: string }>({ epoch });
  const filter = JSON.stringify([month, direction, productType, q, recordStatus, view]);
  const page = pageState.filter === filter ? pageState.page : 1;
  const requestKey = JSON.stringify([epoch, filter, page]);
  const currentRequest = useRef(requestKey);
  currentRequest.current = requestKey;
  const commonQuery = {
    month,
    feeDirection: direction,
    productType,
    q: q?.trim() || undefined,
    recordStatus: recordStatus || undefined,
  };

  const resource = useApiResource(async () => {
    const publication_id = publicationId ?? (pin.current.epoch === epoch ? pin.current.id : undefined);
    const load = view === "STORES" ? fetchMonthlyTrialStores : fetchMonthlyTrial;
    const result = await load({ ...commonQuery, page, pageSize: PAGE_SIZE, publication_id });
    const id = result.meta.publication?.id;
    if (!id || result.data.month !== month || result.data.feeDirection !== direction || result.data.status !== "TRIAL" || (publication_id && id !== publication_id)) {
      throw new Error("内部试算版本或账期不一致。");
    }
    if (currentRequest.current === requestKey) pin.current = { epoch, id };
    return { ...result, data: { ...result.data, requestKey } };
  }, [requestKey], { clearOnReload: true });

  const result = resource.data?.data.requestKey === requestKey ? resource.data : undefined;
  const data: MonthlyTrialData<MonthlyTrialRow | MonthlyTrialStoreRow> | undefined = result?.data;
  const busy = resource.loading || resource.refreshing || !result;
  const title = direction === "PROMOTION" ? "推广服务费" : "管理服务费";
  const storeColumn: Column<MonthlyTrialRow | MonthlyTrialStoreRow> = {
    key: "store", title: direction === "PROMOTION" ? "销售门店" : "核销门店",
    align: "left", minWidth: 180, render: (row) => row.storeName ?? "归属待核验",
  };
  const error = resource.rawError ? trialError(resource.rawError) : undefined;
  const summary = data?.summary;
  const coverage = data?.coverage;

  const exportTrial = async () => {
    const publication_id = result?.meta.publication?.id;
    if (!publication_id || downloadInFlight.current || busy) return;
    downloadInFlight.current = true;
    setDownloadBusy(true);
    setNotice(undefined);
    try {
      const exportView = view === "STORES" ? downloadMonthlyTrialStores : downloadMonthlyTrial;
      const download = await exportView({ ...commonQuery, publication_id });
      setNotice({ filter, error: false, text: download.result === "EMPTY" ? `${download.fileName} 已下载，当前筛选下没有明细。` : `${download.fileName} 已下载。` });
    } catch (downloadError) {
      setNotice({ filter, error: true, text: `试算下载失败，${trialError(downloadError)}` });
    } finally {
      downloadInFlight.current = false;
      setDownloadBusy(false);
    }
  };

  return (
    <section aria-label="内部月度试算" className="content-section page-stack">
      <div className="section-title">
        <div>
          <h2>{month} {title}内部试算</h2>
          <p>仅显示已核算金额。</p>
        </div>
      </div>
      <SegmentedControl className="segmented-control" ariaLabel="内部试算视图" value={view} onChange={setView} options={[{ value: "STORES", label: "门店汇总" }, { value: "COUPONS", label: "逐券明细" }]} />
      <div className="finance-workbench__filters">
        {directions.length > 1 ? <SelectField label="试算费用方向" value={direction} onChange={(value) => setDirection(value as FeeDirection)} options={directions} /> : null}
        <SelectField label="试算核算状态" value={recordStatus} onChange={(value) => setRecordStatus(value as MonthlyTrialRecordStatus | "")} options={[{ value: "", label: "全部核算状态" }, { value: "CALCULATED", label: "已算费用" }, { value: "PENDING", label: "待核验" }, { value: "EXCLUDED", label: "未计费" }]} />
      </div>
      <div className="finance-workbench__actions">
        <Button disabled={busy || Boolean(error)} loading={downloadBusy} onClick={() => { void exportTrial(); }} variant="secondary">{view === "STORES" ? "导出门店试算汇总" : "导出内部试算明细"}</Button>
        <Button disabled={resource.loading || resource.refreshing} onClick={refreshLatest} variant="text">读取最新试算</Button>
      </div>
      <ResourceNotice analysis loading={resource.loading || resource.refreshing} error={error} />
      {notice?.filter === filter ? <p role={notice.error ? "alert" : "status"}>{notice.text}</p> : null}
      {!data && !resource.loading && !resource.refreshing && !error ? <ResourcePanel>当前账期暂无内部试算。</ResourcePanel> : null}
      {data ? (
        <>
          <div className="metric-grid store-summary-metrics">
            <MetricCard label="已算试算费用" value={trialAmount(summary?.calculatedFeeCent)} />
            <MetricCard label="已算费用券数" value={trialCount(summary?.calculatedCouponCount)} />
            <MetricCard label="待核验券数" value={trialCount(summary?.pendingCouponCount)} />
            <MetricCard label="候选券数" value={trialCount(summary?.candidateCouponCount)} />
          </div>
          <details>
            <summary>查看核查说明</summary>
            <p>试算更新时间 {formatDateTime(result?.meta.publication?.publishedAt)}，未计费 {trialCount(summary?.excludedCouponCount)}。</p>
            {typeof coverage?.sourceSuccessDays === "number" && typeof coverage.sourceTotalDays === "number" ? <p>来源采集已完成 {coverage.sourceSuccessDays}/{coverage.sourceTotalDays} 天。</p> : null}
            {coverage?.scopeUnresolved ? <p>部分记录的门店归属或影响范围仍待核验，完整应计金额待核验。</p> : null}
            {coverage?.note ? <p>{coverage.note}</p> : null}
            {coverage?.reasons.length ? <ul>{coverage.reasons.map((reason) => <li key={JSON.stringify([reason.code, reason.label])}>{reason.label}，{formatInteger(reason.couponCount)} 张券。</li>)}</ul> : null}
          </details>
          {view === "STORES" ? (
            <DataTable columns={[storeColumn, ...storeColumns]} rows={data.list as MonthlyTrialStoreRow[]} emptyText="当前筛选下没有门店试算汇总" />
          ) : (
            <DataTable columns={[storeColumn, ...columns]} rows={data.list as MonthlyTrialRow[]} emptyText="当前筛选下没有试算明细" />
          )}
          <TablePagination page={data.page} pageSize={data.pageSize} total={data.total} totalPages={Math.max(1, Math.ceil(data.total / data.pageSize))} rowsOnPage={data.list.length} loading={resource.loading || resource.refreshing} onPageChange={(nextPage) => setPageState({ filter, page: nextPage })} />
        </>
      ) : null}
    </section>
  );
}
