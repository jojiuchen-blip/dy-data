import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { fetchDouyinRanking } from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { FieldInput, SelectField } from "../components/FormControls";
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

function drilldownHref(
  row: DouyinRankingRow,
  level: DouyinRankingLevel,
  periodStart: string,
  periodEnd: string,
  groupName: string,
  serviceCenterName: string,
  districtName: string,
  areaName: string,
) {
  const params = new URLSearchParams({ periodStart, periodEnd });
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

  const rankingResource = useApiResource(
    () => fetchDouyinRanking({
      periodStart,
      periodEnd,
      level,
      groupName: groupName || undefined,
      serviceCenterName: serviceCenterName || undefined,
      districtName: districtName || undefined,
      areaName: areaName || undefined,
      page,
      pageSize: PAGE_SIZE,
      sortBy: "order_average",
      sortOrder: "DESC",
    }),
    [periodStart, periodEnd, level, groupName, serviceCenterName, districtName, areaName, page],
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

  const columns: Column<DouyinRankingRow>[] = [
    { key: "rank", title: "排名", align: "center", render: (row) => <span className="rank-badge">{row.rank ?? "—"}</span> },
    {
      key: "name",
      title: LEVEL_OPTIONS.find((item) => item.value === level)?.label ?? "组织",
      minWidth: 180,
      render: (row) => {
        const href = drilldownHref(row, level, periodStart, periodEnd, groupName, serviceCenterName, districtName, areaName);
        return href ? <a href={href}>{row.name}</a> : row.name;
      },
    },
    { key: "storeCount", title: "适用门店数", align: "right", render: (row) => formatInteger(row.storeCount) },
    { key: "orderCount", title: "抖音订单量", align: "right", render: (row) => formatInteger(row.orderCount) },
    { key: "orderAverage", title: "店均订单量", align: "right", render: (row) => displayAverage(row.orderAverage) },
    { key: "follow24hRate", title: "24小时有效跟进率", align: "right", render: (row) => <><div>{displayRate(row.follow24hRate)}（{formatInteger(row.followNumerator)}/{formatInteger(row.followDenominator)}）</div><small title="正式分配后截至数据更新时间已有有效跟进的轮次占比，不限制在24小时内；每轮只计一次，仅供辅助判断。">跟进率 {displayRate(row.followRate)}</small></> },
    { key: "verificationRate", title: "订单核销率", align: "right", render: (row) => `${displayRate(row.verificationRate)}（${formatInteger(row.verificationNumerator)}/${formatInteger(row.verificationDenominator)}）` },
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
      <ResourceNotice loading={rankingResource.loading} error={error} fallbackReason={rankingResource.data?.fallbackReason} />
      {ranking?.dataMode === "synthetic" && <ResourcePanel>{ranking.previewNote} 快照：{ranking.snapshotId}</ResourcePanel>}
      {ranking?.dataMode === "business" && hasQualityIssues && <ResourcePanel>部分数据的门店归属或历史绑定资料尚待核验，当前排名仅供参考；未能唯一归属的数据暂未计入。</ResourcePanel>}
      <FilterBar>
        <FilterField label="开始日期"><FieldInput type="date" min={RANKING_EARLIEST_DATE} max={initialRange.today} value={periodStart} onChange={(event) => { const next = updateRankingPeriodStart(event.target.value, periodEnd, initialRange.today); setPeriodStart(next.periodStart); setPeriodEnd(next.periodEnd); setPage(1); }} /></FilterField>
        <FilterField label="结束日期"><FieldInput type="date" min={periodStart} max={initialRange.today} value={periodEnd} onChange={(event) => { setPeriodEnd(updateRankingPeriodEnd(event.target.value, periodStart, initialRange.today)); setPage(1); }} /></FilterField>
        <SelectField label="查看层级" value={level} onChange={(value) => { setLevel(value as DouyinRankingLevel); setPage(1); }} options={LEVEL_OPTIONS} />
        <FilterField label="集团"><FieldInput value={groupName} placeholder="按名称筛选" onChange={(event) => { setGroupName(event.target.value); setPage(1); }} /></FilterField>
        <FilterField label="服务中心"><FieldInput value={serviceCenterName} placeholder="按名称筛选" onChange={(event) => { setServiceCenterName(event.target.value); setPage(1); }} /></FilterField>
        <FilterField label="大区"><FieldInput value={districtName} placeholder="按名称筛选" onChange={(event) => { setDistrictName(event.target.value); setPage(1); }} /></FilterField>
        <FilterField label="区域"><FieldInput value={areaName} placeholder="按名称筛选" onChange={(event) => { setAreaName(event.target.value); setPage(1); }} /></FilterField>
        <Button type="button" disabled={rankingResource.loading || rankingResource.refreshing} onClick={rankingResource.reload}>刷新数据</Button>
      </FilterBar>
      {!ranking && rankingResource.loading ? <ResourcePanel>正在加载打榜指标…</ResourcePanel> : !ranking ? <ResourcePanel tone="error">打榜看板暂不可用。</ResourcePanel> : (
        <>
          <section className="metric-grid metric-grid--three">
            <MetricCard label="抖音订单量" value={formatInteger(totals?.orderCount ?? 0)} meta={`店均 ${displayAverage(totals?.orderAverage)} · ${sourceLabel}`} description="门店及所属职人的全渠道精诚养车订单，按订单 ID 去重；订单量和店均统一按统计开始日组织归属，适用门店名单同日固定，含零销量门店。" />
            <MetricCard label="线索24小时有效跟进率" value={displayRate(totals?.follow24hRate)} meta={<><div>有效 {formatInteger(totals?.followNumerator ?? 0)} / 分配 {formatInteger(totals?.followDenominator ?? 0)}</div><small title="正式分配后截至数据更新时间已有有效跟进的轮次占比，不限制在24小时内；每轮只计一次，仅供辅助判断。">跟进率 {displayRate(totals?.followRate)}</small></>} description="精诚养车商品对应的正式分配线索，在分配后 24 小时内完成真实联系并在系统回填。" />
            <MetricCard label="抖音订单核销率" value={displayRate(totals?.verificationRate)} meta={`核销 ${formatInteger(totals?.verificationNumerator ?? 0)} / 关联 ${formatInteger(totals?.verificationDenominator ?? 0)}`} description="正式分配给本店的精诚养车线索关联订单中，在本店成功核销的比例；上级组织汇总各店分子和分母。" />
          </section>
          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>{LEVEL_OPTIONS.find((item) => item.value === level)?.label ?? "组织"}排名</h2>
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
