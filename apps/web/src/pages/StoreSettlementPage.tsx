import { useMemo, useState } from "react";
import { DataTable, type Column } from "../components/DataTable";
import { DefinitionList } from "../components/DefinitionList";
import { FilterBar, FilterField } from "../components/Filters";
import { MetricCard } from "../components/MetricCard";
import { TooltipLabel } from "../components/TooltipLabel";
import { defaultMonth, defaultStore, page2Definitions } from "../data/mockData";
import type {
  NonCommissionOrderRow,
  PayableCommissionRow,
  ReceivableCommissionRow,
} from "../types/dashboard";
import { formatCurrency, formatInteger, formatPercent } from "../utils/format";
import {
  detailsHref,
  getMonthOptions,
  getProductOptions,
  getSettlementView,
  getStoreOptions,
} from "../utils/settlement";

interface StoreSettlementPageProps {
  searchParams: URLSearchParams;
}

function definitionFor(key: string): string | undefined {
  return page2Definitions.find((definition) => definition.key === key)?.description;
}

export function StoreSettlementPage({ searchParams }: StoreSettlementPageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? defaultMonth);
  const [storeId, setStoreId] = useState(
    searchParams.get("store_id") ?? defaultStore.store_id,
  );
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "all",
  );

  const view = useMemo(
    () => getSettlementView(storeId, month, productType),
    [storeId, month, productType],
  );

  const baseProduct = productType === "all" ? "all" : productType;

  const receivableHref = detailsHref({
    product_type: baseProduct,
    sale_store_id: storeId,
    exclude_verify_store_id: storeId,
    is_verified: "true",
    invoice_status: "approved",
    month,
    month_basis: "invoice_approved",
  });
  const commissionableHref = detailsHref({
    product_type: baseProduct,
    sale_store_id: storeId,
    relation_type: "cross_store",
    is_verified: "true",
    verify_month: month,
    month_basis: "verify_month",
  });
  const payableHref = detailsHref({
    product_type: baseProduct,
    verify_store_id: storeId,
    relation_type: "cross_store",
    is_verified: "true",
    verify_month: month,
    month_basis: "verify_month",
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
      key: "invoiced",
      title: "已到票单数",
      align: "right",
      render: (row) => formatInteger(row.invoiced_coupon_count),
    },
    {
      key: "current",
      title: "当期应收分佣",
      align: "right",
      render: (row) => formatCurrency(row.current_receivable_commission_cent),
    },
    {
      key: "pending",
      title: "未到票待确认分佣",
      align: "right",
      render: (row) => formatCurrency(row.pending_invoice_commission_cent),
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
          <p className="eyebrow">页面 2</p>
          <h1>单店月度分账看板</h1>
        </div>
        <span className="source-pill">
          {view.source === "contract-mock" ? "contract mock" : "detail derived"}
        </span>
      </section>

      <FilterBar>
        <FilterField label="月份">
          <select value={month} onChange={(event) => setMonth(event.target.value)}>
            {getMonthOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="门店">
          <select value={storeId} onChange={(event) => setStoreId(event.target.value)}>
            {getStoreOptions().map((option) => (
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
            {getProductOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
      </FilterBar>

      <section className="metric-grid metric-grid--three">
        <MetricCard
          description={definitionFor("current_receivable_commission_cent")}
          href={receivableHref}
          label="当期应收分佣"
          meta="点击查看明细"
          value={formatCurrency(view.metrics.current_receivable_commission_cent)}
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
          value={formatCurrency(view.metrics.estimated_payable_commission_cent)}
        />
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>应收分佣：本店卖出，他店核销</h2>
            <p>{view.store.store_name} · {month}</p>
          </div>
        </div>
        <DataTable
          columns={receivableColumns}
          rows={view.tables.receivable_commissions}
          rowHref={(row) =>
            detailsHref({
              product_type: row.product_type,
              sale_store_id: storeId,
              relation_type: "cross_store",
              is_verified: "true",
              verify_month: month,
              month_basis: "verify_month",
            })
          }
        />
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>应付分佣：他店卖出，本店核销</h2>
            <p>{view.store.store_name} · {month}</p>
          </div>
        </div>
        <DataTable
          columns={payableColumns}
          rows={view.tables.payable_commissions}
          rowHref={(row) =>
            detailsHref({
              product_type: row.product_type,
              verify_store_id: storeId,
              relation_type: "cross_store",
              is_verified: "true",
              verify_month: month,
              month_basis: "verify_month",
            })
          }
        />
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>不参与分佣：本店卖出，本店核销</h2>
            <p>{view.store.store_name} · {month}</p>
          </div>
        </div>
        <DataTable
          columns={nonCommissionColumns}
          rows={view.tables.non_commission_orders}
          rowHref={(row) =>
            detailsHref({
              product_type: row.product_type,
              sale_store_id: storeId,
              verify_store_id: storeId,
              is_verified: "true",
              relation_type: "same_store",
              is_commissionable: "false",
              verify_month: month,
              month_basis: "verify_month",
            })
          }
        />
      </section>

      <DefinitionList
        definitions={page2Definitions}
        extra={[
          {
            key: "receivable_table",
            label: "应收分佣表",
            description:
              "本店销售、其他门店核销的已核销订单，按商品类型汇总订单实收、分佣比例、可分佣金额、到票单数和当期应收分佣。",
          },
          {
            key: "payable_table",
            label: "应付分佣表",
            description:
              "其他门店销售、本店核销的已核销订单，按商品类型汇总订单实收、分佣比例和本店预计分出分佣参考额。",
          },
          {
            key: "non_commission_table",
            label: "不参与分佣表",
            description:
              "销售归属门店和实际核销门店一致的已核销订单，不进入跨店分佣计算。",
          },
          {
            key: "month_filter",
            label: "月份筛选口径",
            description:
              "可分佣总金额和应付分佣按核销月份归属；当期应收分佣按到票或审核通过时间归属。",
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
