import { useState } from "react";
import {
  defaultMonth,
  defaultStore,
  fetchFilterMeta,
  fetchMonthlySettlement,
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
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { TooltipLabel } from "../components/TooltipLabel";
import { useApiResource } from "../hooks/useApiResource";
import type {
  NonCommissionOrderRow,
  PayableCommissionRow,
  ReceivableCommissionRow,
} from "../types/dashboard";
import { formatCurrency, formatInteger, formatPercent } from "../utils/format";
import {
  productOptions,
  storeOptions,
  verifyMonthOptions,
} from "../utils/options";
import { detailsHref } from "../utils/settlement";

interface StoreSettlementPageProps {
  searchParams: URLSearchParams;
}

export function StoreSettlementPage({ searchParams }: StoreSettlementPageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const [storeId, setStoreId] = useState(searchParams.get("store_id") ?? "");
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "all",
  );

  const metaResource = useApiResource(fetchFilterMeta, []);
  const meta = metaResource.data?.data;
  const activeMonth = month || meta?.verify_months[0] || defaultMonth;
  const activeStoreId = storeId || meta?.stores[0]?.store_id || defaultStore.store_id;
  const settlementResource = useApiResource(
    () => fetchMonthlySettlement({ storeId: activeStoreId, month: activeMonth, productType }),
    [activeStoreId, activeMonth, productType],
  );

  const view = settlementResource.data?.data;
  const definitions = settlementResource.data?.definitions ?? [];
  const definitionFor = (key: string): string | undefined =>
    definitions.find((definition) => definition.key === key)?.description;
  const metaStore = meta?.stores.find((store) => store.store_id === activeStoreId);
  const selectedStore =
    view?.store ??
    metaStore ??
    (activeStoreId ? { store_id: activeStoreId, store_name: activeStoreId } : defaultStore);
  const baseProduct = productType === "all" ? "all" : productType;

  const receivableHref = detailsHref({
    product_type: baseProduct,
    sale_store_id: activeStoreId,
    relation_type: "cross_store",
    is_verified: "true",
    verify_month: activeMonth,
  });
  const commissionableHref = detailsHref({
    product_type: baseProduct,
    sale_store_id: activeStoreId,
    relation_type: "cross_store",
    is_verified: "true",
    verify_month: activeMonth,
  });
  const payableHref = detailsHref({
    product_type: baseProduct,
    verify_store_id: activeStoreId,
    relation_type: "cross_store",
    is_verified: "true",
    verify_month: activeMonth,
  });

  const receivableColumns: Column<ReceivableCommissionRow>[] = [
    { key: "product", title: "商品类型", render: (row) => row.product_type },
    {
      key: "count",
      title: "核销单数",
      align: "right",
      render: (row) => formatInteger(row.verified_coupon_count),
    },
    {
      key: "paid",
      title: "订单实收金额",
      align: "right",
      render: (row) => formatCurrency(row.paid_amount_cent),
    },
    {
      key: "rate",
      title: "分佣比例",
      align: "right",
      render: (row) => formatPercent(row.commission_rate),
    },
    {
      key: "total",
      title: "可分佣总金额",
      align: "right",
      render: (row) => formatCurrency(row.commissionable_total_cent),
    },
    {
      key: "estimated",
      title: "预计应收分佣",
      align: "right",
      render: (row) => formatCurrency(row.estimated_receivable_commission_cent),
    },
  ];

  const payableColumns: Column<PayableCommissionRow>[] = [
    { key: "product", title: "商品类型", render: (row) => row.product_type },
    {
      key: "count",
      title: "单数",
      align: "right",
      render: (row) => formatInteger(row.verified_coupon_count),
    },
    {
      key: "paid",
      title: "订单实收金额",
      align: "right",
      render: (row) => formatCurrency(row.paid_amount_cent),
    },
    {
      key: "rate",
      title: "分佣比例",
      align: "right",
      render: (row) => formatPercent(row.commission_rate),
    },
    {
      key: "payable",
      title: "应付分佣",
      align: "right",
      render: (row) => formatCurrency(row.payable_commission_cent),
    },
  ];

  const nonCommissionColumns: Column<NonCommissionOrderRow>[] = [
    { key: "product", title: "商品类型", render: (row) => row.product_type },
    {
      key: "count",
      title: "单数",
      align: "right",
      render: (row) => formatInteger(row.verified_coupon_count),
    },
    {
      key: "paid",
      title: "订单实收金额",
      align: "right",
      render: (row) => formatCurrency(row.paid_amount_cent),
    },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <h1>单店月度分账看板</h1>
        </div>
        <span className="source-pill">
          {resourceSourceLabel(
            settlementResource.data,
            settlementResource.loading,
          )}
        </span>
      </section>

      <ResourceNotice
        fallbackReason={
          settlementResource.data?.fallbackReason ??
          metaResource.data?.fallbackReason
        }
        loading={settlementResource.loading || metaResource.loading}
        error={settlementResource.error ?? metaResource.error}
      />

      <FilterBar>
        <FilterField label="月份">
          <select value={activeMonth} onChange={(event) => setMonth(event.target.value)}>
            {verifyMonthOptions(meta, activeMonth).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="门店">
          <SearchableStoreSelect
            options={storeOptions(meta, selectedStore)}
            value={activeStoreId}
            onChange={setStoreId}
          />
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

      {!view && settlementResource.loading ? (
        <ResourcePanel>正在加载分账数据...</ResourcePanel>
      ) : !view ? (
        <ResourcePanel tone="error">分账数据暂不可用。</ResourcePanel>
      ) : (
        <>
          <section className="metric-grid metric-grid--three">
            <MetricCard
              description={definitionFor("estimated_receivable_commission_cent")}
              href={receivableHref}
              label="预计应收分佣"
              meta="点击查看明细"
              value={formatCurrency(
                view.metrics.estimated_receivable_commission_cent,
              )}
            />
            <MetricCard
              description={definitionFor("commissionable_total_cent")}
              href={commissionableHref}
              label="可分佣总金额"
              meta="点击查看明细"
              tone="blue"
              value={formatCurrency(view.metrics.commissionable_total_cent)}
            />
            <MetricCard
              description={definitionFor("estimated_payable_commission_cent")}
              href={payableHref}
              label="本店预计分出分佣参考额"
              meta="点击查看明细"
              tone="amber"
              value={formatCurrency(
                view.metrics.estimated_payable_commission_cent,
              )}
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>预计应收分佣：本店卖出，他店核销</h2>
                <p>{view.store.store_name} · {activeMonth}</p>
              </div>
            </div>
            <DataTable
              columns={receivableColumns}
              rows={view.tables.receivable_commissions}
              rowHref={(row) =>
                detailsHref({
                  product_type: row.product_type,
                  sale_store_id: activeStoreId,
                  relation_type: "cross_store",
                  is_verified: "true",
                  verify_month: activeMonth,
                })
              }
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>应付分佣：他店卖出，本店核销</h2>
                <p>{view.store.store_name} · {activeMonth}</p>
              </div>
            </div>
            <DataTable
              columns={payableColumns}
              rows={view.tables.payable_commissions}
              rowHref={(row) =>
                detailsHref({
                  product_type: row.product_type,
                  verify_store_id: activeStoreId,
                  relation_type: "cross_store",
                  is_verified: "true",
                  verify_month: activeMonth,
                })
              }
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>不参与分佣：本店卖出，本店核销</h2>
                <p>{view.store.store_name} · {activeMonth}</p>
              </div>
            </div>
            <DataTable
              columns={nonCommissionColumns}
              rows={view.tables.non_commission_orders}
              rowHref={(row) =>
                detailsHref({
                  product_type: row.product_type,
                  sale_store_id: activeStoreId,
                  verify_store_id: activeStoreId,
                  is_verified: "true",
                  relation_type: "same_store",
                  is_commissionable: "false",
                  verify_month: activeMonth,
                })
              }
            />
          </section>
        </>
      )}

      <DefinitionList
        definitions={definitions}
        extra={[
          {
            key: "receivable_table",
            label: "预计应收分佣表",
            description:
              "这里列出本店卖出、其他门店核销的订单。系统按商品类型汇总这些订单的实收金额，并按分佣规则测算本店预计可以收到的分佣。",
          },
          {
            key: "payable_table",
            label: "应付分佣表",
            description:
              "这里列出其他门店卖出、本店核销的订单。系统按商品类型汇总这些订单的实收金额，并按分佣规则测算本店预计需要分出的分佣。",
          },
          {
            key: "non_commission_table",
            label: "不参与分佣表",
            description:
              "这里列出本店卖出、也在本店核销的订单。这类订单没有跨店关系，所以不进入分佣计算。",
          },
          {
            key: "month_filter",
            label: "月份筛选口径",
            description:
              "页面按核销月份统计：只要券是在这个月核销，就计入本月，不按销售月份计算。",
          },
          {
            key: "product_filter",
            label: "产品筛选口径",
            description:
              "选择“全部产品”时包含所有商品类型；选择具体产品时，只统计该商品类型的订单和核销。",
          },
        ]}
        title="本页计算口径"
      />
    </div>
  );
}
