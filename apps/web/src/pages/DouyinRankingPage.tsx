import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { DouyinRankingExportDialog } from "../components/DouyinRankingExportDialog";
import { RANKING_METRIC_OPTIONS, type RankingMetric } from "../utils/rankingOptions";
import { fetchDouyinRanking } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { FieldInput, SelectField } from "../components/FormControls";
import { TooltipLabel } from "../components/TooltipLabel";
import { MetricCard } from "../components/MetricCard";
import { TablePagination } from "../components/TablePagination";
import { ResourceNotice, ResourcePanel, resourceSourceLabel } from "../components/ResourceState";
import { useApiResource } from "../hooks/useApiResource";
import type { DouyinRankingLevel, DouyinRankingRow } from "../types/dashboard";
import { formatDateTime, formatInteger, formatPercent } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";
import {
  RANKING_EARLIEST_DATE,
  normalizeRankingDateRange,
  updateRankingPeriodEnd,
  updateRankingPeriodStart,
} from "../utils/douyinRankingDates";

interface DouyinRankingPageProps {
  searchParams: URLSearchParams;
}

const PAGE_SIZE = 50;
const LEVEL_OPTIONS: Array<{ value: DouyinRankingLevel; label: string }> = [
  { value: "group", label: "集团" },
  { value: "service_center", label: "服务中心" },
  { value: "district", label: "大区" },
  { value: "area", label: "区域" },
  { value: "store", label: "门店" },
];

function displayRate(value: number | null | undefined) {
  return value === null || value === undefined ? "暂无样本" : formatPercent(value);
}

function displayAverage(value: number | null | undefined) {
  return value === null || value === undefined ? "暂无数据" : value.toFixed(2);
}

const FOLLOW_24H_DESCRIPTION = "24小时内有人工跟进记录的轮次 ÷ 全部正式分配轮次。未接通、战败也算；核销不自动计入，退款不剔除。";
const FOLLOW_DESCRIPTION = "有人工跟进记录的轮次 ÷ 全部正式分配轮次，不限24小时。核销不自动计入，退款不剔除。";

function displayCount(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : formatInteger(value);
}

function AuxiliaryFollowRates({ metrics }: { metrics: Pick<DouyinRankingRow, "followRate" | "followAnyNumerator" | "followAnyDenominator"> | undefined }) {
  return <span className="ranking-follow-auxiliary">
    <small><TooltipLabel label="跟进率" description={FOLLOW_DESCRIPTION} interactive hideIcon /> {displayRate(metrics?.followRate)}（{displayCount(metrics?.followAnyNumerator)}/{displayCount(metrics?.followAnyDenominator)}）</small>
  </span>;
}

function drilldownHref(
  row: DouyinRankingRow,
  level: DouyinRankingLevel,
  periodStart: string,
  periodEnd: string,
  groupName: string,
  serviceCenterName: string,
  districtName: string,
  areaName: string,
  sortBy: RankingMetric,
  productScope: string,
) {
  const params = new URLSearchParams({ periodStart, periodEnd, sortBy, productScope });
  if (level === "group") {
    params.set("level", "service_center");
    params.set("groupName", row.name);
  } else if (level === "service_center") {
    params.set("level", "district");
    params.set("groupName", groupName);
    params.set("serviceCenterName", row.name);
  } else if (level === "district") {
    params.set("level", "area");
    params.set("groupName", groupName);
    params.set("serviceCenterName", serviceCenterName);
    params.set("districtName", row.name);
  } else if (level === "area") {
    params.set("level", "store");
    params.set("groupName", groupName);
    params.set("serviceCenterName", serviceCenterName);
    params.set("districtName", districtName);
    params.set("areaName", row.name);
  } else {
    return undefined;
  }
  return `/metrics/douyin-ranking?${params.toString()}`;
}

export function DouyinRankingPage({ searchParams }: DouyinRankingPageProps) {
  const initialRange = useMemo(() => normalizeRankingDateRange(searchParams), [searchParams]);
  const [periodStart, setPeriodStart] = useState(initialRange.periodStart);
  const [periodEnd, setPeriodEnd] = useState(initialRange.periodEnd);
  const [level, setLevel] = useState<DouyinRankingLevel>(
    (searchParams.get("level") as DouyinRankingLevel) || "group",
  );
  const [groupName, setGroupName] = useState(searchParams.get("groupName") ?? "");
  const [serviceCenterName, setServiceCenterName] = useState(searchParams.get("serviceCenterName") ?? "");
  const [districtName, setDistrictName] = useState(searchParams.get("districtName") ?? "");
  const [areaName, setAreaName] = useState(searchParams.get("areaName") ?? "");
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<RankingMetric>(() => RANKING_METRIC_OPTIONS.find((item) => item.value === searchParams.get("sortBy"))?.value ?? "order_average");
  const [productScope, setProductScope] = useState(() => ["all", "jingcheng", "byd"].includes(searchParams.get("productScope") ?? "") ? searchParams.get("productScope")! : "jingcheng");
  const productLabel = ({all: "全部商品", jingcheng: "精诚养车商品", byd: "比亚迪本品"} as Record<string, string>)[productScope];
  const [exportOpen, setExportOpen] = useState(false);

  const rankingResource = useApiResource(
    () => fetchDouyinRanking({
      productScope,
      periodStart,
      periodEnd,
      level,
      groupName: groupName || undefined,
      serviceCenterName: serviceCenterName || undefined,
      districtName: districtName || undefined,
      areaName: areaName || undefined,
      page,
      pageSize: PAGE_SIZE,
      sortBy,
      sortOrder: "DESC",
    }),
    [productScope, periodStart, periodEnd, level, groupName, serviceCenterName, districtName, areaName, page, sortBy],
    { clearOnReload: true },
  );
  const ranking = rankingResource.data?.data;
  const hasQualityIssues = Object.entries(ranking?.qualityJson ?? {}).some(
    ([key, count]) => key !== "followRoundsUnderObservation" && count > 0,
  );
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") rankingResource.reload();
    }, 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [rankingResource.reload]);
  const error = rankingResource.rawError
    ? apiErrorText(rankingResource.rawError, "打榜看板暂不可用，请稍后重试。", {
      403: "当前账号没有查看打榜看板的权限。",
      422: "所选日期的数据尚未准备好，或筛选条件不正确，请调整后重试。",
    })
    : rankingResource.error;
  const rows = ranking?.rows ?? [];
  const totals = ranking?.totals;
  const sourceLabel = ranking?.dataMode === "synthetic" ? "虚拟测试快照" : resourceSourceLabel(rankingResource.data, rankingResource.loading);

  const orderDescription = `所选日期内门店及所属职人的全渠道${productLabel}订单数，按订单去重、期初组织归属汇总。`;
  const averageDescription = "订单量 ÷ 适用门店数（含零销量门店）。名单和组织归属按统计开始日固定。";
  const verificationDescription = `本店线索关联订单中在本店成功核销的订单数 ÷ 本店线索关联订单数，按订单去重。上级组织汇总分子、分母计算。`;
  const metricTitle = (label: string, description: string) => <TooltipLabel label={label} description={description} interactive hideIcon />;
  const columns: Column<DouyinRankingRow>[] = [
    { key: "rank", title: "排名", align: "center", render: (row) => <span className="rank-badge">{row.rank ?? "—"}</span> },
    {
      key: "name",
      title: LEVEL_OPTIONS.find((item) => item.value === level)?.label ?? "组织",
      minWidth: 180,
      render: (row) => {
        const href = drilldownHref(row, level, periodStart, periodEnd, groupName, serviceCenterName, districtName, areaName, sortBy, productScope);
        return href ? <a href={href}>{row.name}</a> : row.name;
      },
    },
    { key: "storeCount", title: metricTitle("适用门店数", averageDescription), align: "right", render: (row) => formatInteger(row.storeCount) },
    { key: "orderCount", title: metricTitle("抖音订单量", orderDescription), align: "right", render: (row) => formatInteger(row.orderCount) },
    { key: "orderAverage", title: metricTitle("店均订单量", averageDescription), align: "right", render: (row) => displayAverage(row.orderAverage) },
    { key: "follow24hRate", title: metricTitle("24小时有效跟进率", FOLLOW_24H_DESCRIPTION), align: "right", render: (row) => <><span className="ranking-follow-main">{displayRate(row.follow24hRate)}（{formatInteger(row.followNumerator)}/{formatInteger(row.followDenominator)}）</span><AuxiliaryFollowRates metrics={row} /></> },
    { key: "verificationRate", title: metricTitle("订单核销率", verificationDescription), align: "right", render: (row) => `${displayRate(row.verificationRate)}（${formatInteger(row.verificationNumerator)}/${formatInteger(row.verificationDenominator)}）` },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
        <p className="eyebrow">指标看板 · 抖音打榜</p>
          <h1>抖音经营打榜看板</h1>
          <p>按集团、服务中心、大区、区域和门店查看抖音订单、线索跟进与核销表现。</p>
        </div>
      </section>
      {exportOpen && <DouyinRankingExportDialog periodStart={periodStart} periodEnd={periodEnd} today={initialRange.today} level={level}
        productScope={productScope} filters={{ groupName, serviceCenterName, districtName, areaName }} onClose={() => setExportOpen(false)} />}
      <ResourceNotice loading={rankingResource.loading} error={error} fallbackReason={rankingResource.data?.fallbackReason} />
      {ranking?.dataMode === "synthetic" && <ResourcePanel>{ranking.previewNote} 快照：{ranking.snapshotId}</ResourcePanel>}
      {ranking?.dataMode === "business" && hasQualityIssues && <ResourcePanel>部分数据的门店归属或历史绑定资料尚待核验，当前排名仅供参考；未能唯一归属的数据暂未计入。</ResourcePanel>}
      <FilterBar>
        <SelectField label="商品类型" value={productScope} onChange={(value) => { setProductScope(value); setPage(1); }} options={[{value: "all", label: "全部商品"}, {value: "jingcheng", label: "精诚养车商品"}, {value: "byd", label: "比亚迪本品"}]} />
        <FilterField label="开始日期"><FieldInput type="date" min={RANKING_EARLIEST_DATE} max={initialRange.today} value={periodStart} onChange={(event) => { const next = updateRankingPeriodStart(event.target.value, periodEnd, initialRange.today); setPeriodStart(next.periodStart); setPeriodEnd(next.periodEnd); setPage(1); }} /></FilterField>
        <FilterField label="结束日期"><FieldInput type="date" min={periodStart} max={initialRange.today} value={periodEnd} onChange={(event) => { setPeriodEnd(updateRankingPeriodEnd(event.target.value, periodStart, initialRange.today)); setPage(1); }} /></FilterField>
        <SelectField label="查看层级" value={level} onChange={(value) => { setLevel(value as DouyinRankingLevel); setPage(1); }} options={LEVEL_OPTIONS} />
        <SelectField label="排名依据" value={sortBy} onChange={(value) => { setSortBy(value as RankingMetric); setPage(1); }} options={RANKING_METRIC_OPTIONS} />
        <Button onClick={() => setExportOpen(true)}>导出排行</Button>
        <FilterField label="集团"><FieldInput value={groupName} placeholder="按名称筛选" onChange={(event) => { setGroupName(event.target.value); setPage(1); }} /></FilterField>
        <FilterField label="服务中心"><FieldInput value={serviceCenterName} placeholder="按名称筛选" onChange={(event) => { setServiceCenterName(event.target.value); setPage(1); }} /></FilterField>
        <FilterField label="大区"><FieldInput value={districtName} placeholder="按名称筛选" onChange={(event) => { setDistrictName(event.target.value); setPage(1); }} /></FilterField>
        <FilterField label="区域"><FieldInput value={areaName} placeholder="按名称筛选" onChange={(event) => { setAreaName(event.target.value); setPage(1); }} /></FilterField>
        <Button type="button" disabled={rankingResource.loading || rankingResource.refreshing} onClick={rankingResource.reload}>刷新数据</Button>
      </FilterBar>
      {!ranking && rankingResource.loading ? <ResourcePanel>正在加载打榜指标…</ResourcePanel> : !ranking ? <ResourcePanel tone="error">打榜看板暂不可用。</ResourcePanel> : (
        <>
          <section className="metric-grid metric-grid--three">
            <MetricCard interactiveTooltip hideTooltipIcon label="抖音订单量" value={formatInteger(totals?.orderCount ?? 0)} meta={<><TooltipLabel label="店均订单量" description={averageDescription} interactive hideIcon /> {displayAverage(totals?.orderAverage)} · {sourceLabel}</>} description={orderDescription} />
            <MetricCard interactiveTooltip hideTooltipIcon label="线索24小时有效跟进率" value={displayRate(totals?.follow24hRate)} meta={<><div>有效 {formatInteger(totals?.followNumerator ?? 0)} / 分配 {formatInteger(totals?.followDenominator ?? 0)}</div><AuxiliaryFollowRates metrics={totals} /></>} description={`${productLabel}对应的正式分配线索。${FOLLOW_24H_DESCRIPTION}`} />
            <MetricCard interactiveTooltip hideTooltipIcon label="抖音订单核销率" value={displayRate(totals?.verificationRate)} meta={`核销 ${formatInteger(totals?.verificationNumerator ?? 0)} / 关联 ${formatInteger(totals?.verificationDenominator ?? 0)}`} description={verificationDescription} />
          </section>
          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>{LEVEL_OPTIONS.find((item) => item.value === level)?.label ?? "组织"}排名 · {RANKING_METRIC_OPTIONS.find((item) => item.value === sortBy)?.label}</h2>
                <p>共 {ranking.total} 个结果 · 统计 {ranking.periodStart.slice(0, 10)} 至 {ranking.periodEnd.slice(0, 10)} · 数据源：{sourceLabel}</p>
              </div>
              <div className="section-title__meta">最近数据：{formatDateTime(ranking.latestObservedAt)}</div>
            </div>
            {rows.length ? <DataTable columns={columns} rows={rows} /> : <ResourcePanel>当前统计范围没有可展示数据，请检查筛选范围及快照更新状态。</ResourcePanel>}
            <TablePagination page={page} pageSize={PAGE_SIZE} total={ranking.total}
              totalPages={Math.max(1, Math.ceil(ranking.total / PAGE_SIZE))}
              rowsOnPage={rows.length} loading={rankingResource.loading || rankingResource.refreshing}
              onPageChange={setPage} />
          </section>
        </>
      )}
    </div>
  );
}
