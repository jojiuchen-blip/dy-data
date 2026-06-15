import { useMemo, useState } from "react";
import {
  defaultMonth,
  fetchFilterMeta,
  fetchStoreRanking,
} from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { DefinitionList } from "../components/DefinitionList";
import { FilterBar, FilterField } from "../components/Filters";
import { MetricCard } from "../components/MetricCard";
import {
  ResourceNotice,
  ResourcePanel,
  resourceSourceLabel,
} from "../components/ResourceState";
import { TooltipLabel } from "../components/TooltipLabel";
import { useApiResource } from "../hooks/useApiResource";
import type { StoreRankingRow } from "../types/dashboard";
import { compactCurrency, formatCurrency, formatInteger } from "../utils/format";
import { productOptions, saleMonthOptions } from "../utils/options";

interface StoreRankingPageProps {
  searchParams: URLSearchParams;
}

export function StoreRankingPage({ searchParams }: StoreRankingPageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "all",
  );

  const metaResource = useApiResource(fetchFilterMeta, []);
  const meta = metaResource.data?.data;
  const activeMonth = month || meta?.sale_months[0] || defaultMonth;
  const rankingResource = useApiResource(
    () => fetchStoreRanking({ month: activeMonth, productType, limit: 20 }),
    [activeMonth, productType],
  );

  const ranking = rankingResource.data?.data;
  const definitions = rankingResource.data?.definitions ?? [];
  const rows = ranking?.rows ?? [];
  const definitionFor = (key: string): string | undefined =>
    definitions.find((definition) => definition.key === key)?.description;

  const totals = useMemo(
    () => ({
      sales_order_count: rows.reduce(
        (total, row) => total + row.sales_order_count,
        0,
      ),
      self_verify_income_cent: rows.reduce(
        (total, row) => total + row.self_verify_income_cent,
        0,
      ),
      effective_commission_income_cent: rows.reduce(
        (total, row) => total + row.effective_commission_income_cent,
        0,
      ),
    }),
    [rows],
  );

  const columns: Column<StoreRankingRow>[] = [
    {
      key: "rank",
      title: "排名",
      align: "center",
      render: (row) => <span className="rank-badge">{row.rank}</span>,
    },
    {
      key: "store",
      title: "门店",
      render: (row) => (
        <span className="store-name">
          {row.store_name}
          <small>{row.store_id}</small>
        </span>
      ),
    },
    {
      key: "sales",
      title: (
        <TooltipLabel
          label="销售订单数量"
          description={definitionFor("sales_order_count")}
        />
      ),
      align: "right",
      render: (row) => formatInteger(row.sales_order_count),
    },
    {
      key: "selfSelf",
      title: (
        <TooltipLabel
          label="本店卖本店核销"
          description={definitionFor("self_sold_self_verified_count")}
        />
      ),
      align: "right",
      render: (row) => formatInteger(row.self_sold_self_verified_count),
    },
    {
      key: "selfOther",
      title: (
        <TooltipLabel
          label="本店卖他店核销"
          description={definitionFor("self_sold_other_verified_count")}
        />
      ),
      align: "right",
      render: (row) => formatInteger(row.self_sold_other_verified_count),
    },
    {
      key: "otherSelf",
      title: (
        <TooltipLabel
          label="他店卖本店核销"
          description={definitionFor("other_sold_self_verified_count")}
        />
      ),
      align: "right",
      render: (row) => formatInteger(row.other_sold_self_verified_count),
    },
    {
      key: "verifyIncome",
      title: (
        <TooltipLabel
          label="本店核销收入"
          description={definitionFor("self_verify_income_cent")}
        />
      ),
      align: "right",
      render: (row) => formatCurrency(row.self_verify_income_cent),
    },
    {
      key: "commissionIncome",
      title: (
        <TooltipLabel
          label="有效分佣收入"
          description={definitionFor("effective_commission_income_cent")}
        />
      ),
      align: "right",
      render: (row) => formatCurrency(row.effective_commission_income_cent),
    },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">页面 1</p>
          <h1>全国门店销售情况榜单</h1>
        </div>
        <span className="source-pill">
          {resourceSourceLabel(rankingResource.data, rankingResource.loading)}
        </span>
      </section>

      <ResourceNotice
        fallbackReason={
          rankingResource.data?.fallbackReason ?? metaResource.data?.fallbackReason
        }
        loading={rankingResource.loading || metaResource.loading}
        error={rankingResource.error ?? metaResource.error}
      />

      <FilterBar>
        <FilterField label="月份">
          <select value={activeMonth} onChange={(event) => setMonth(event.target.value)}>
            {saleMonthOptions(meta, activeMonth).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="产品范围">
          <select
            value={productType}
            onChange={(event) => setProductType(event.target.value)}
          >
            {productOptions(meta, productType).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
      </FilterBar>

      {!ranking && rankingResource.loading ? (
        <ResourcePanel>正在加载榜单数据...</ResourcePanel>
      ) : !ranking ? (
        <ResourcePanel tone="error">榜单数据暂不可用。</ResourcePanel>
      ) : (
        <>
          <section className="metric-grid metric-grid--three">
            <MetricCard
              description={definitionFor("sales_order_count")}
              label="销售订单数量"
              meta="当前榜单合计"
              value={formatInteger(totals.sales_order_count)}
            />
            <MetricCard
              description={definitionFor("self_verify_income_cent")}
              label="本店核销收入"
              meta="按核销门店归属"
              tone="blue"
              value={compactCurrency(totals.self_verify_income_cent)}
            />
            <MetricCard
              description={definitionFor("effective_commission_income_cent")}
              label="有效分佣收入"
              meta="销售店预计获得"
              tone="amber"
              value={compactCurrency(totals.effective_commission_income_cent)}
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>前 20 门店榜单</h2>
                <p>{activeMonth} · {productType === "all" ? "全部产品" : productType}</p>
              </div>
            </div>
            <DataTable
              columns={columns}
              rows={rows}
              rowHref={(row) =>
                `/settlement?store_id=${row.store_id}&month=${activeMonth}&product_type=${encodeURIComponent(
                  productType,
                )}`
              }
            />
          </section>
        </>
      )}

      <DefinitionList
        definitions={definitions}
        extra={[
          {
            key: "month_filter",
            label: "时间筛选口径",
            description:
              "页面按所选月份展示榜单；销售订单数按销售月份归属，核销与收入类指标按核销月份归属。",
          },
          {
            key: "product_filter",
            label: "产品筛选口径",
            description:
              "product_type=all 表示全部产品，具体服务产品按商品类型字段筛选。",
          },
        ]}
        title="本页计算口径"
      />
    </div>
  );
}
