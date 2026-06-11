import { useEffect, useMemo, useState } from "react";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { orderDetails } from "../data/mockData";
import type { DetailFilters, OrderDetail } from "../types/dashboard";
import {
  formatCurrency,
  invoiceStatusLabels,
  labelForBoolean,
  refundStatusLabels,
} from "../utils/format";
import {
  detailFiltersFromSearch,
  filterOrderDetails,
  getMonthOptions,
  getProductOptions,
  getStoreName,
  getStoreOptions,
} from "../utils/settlement";

interface OrderDetailsPageProps {
  searchParams: URLSearchParams;
}

const booleanOptions = [
  { value: "", label: "全部" },
  { value: "true", label: "是" },
  { value: "false", label: "否" },
];

const invoiceOptions = [
  { value: "", label: "全部" },
  { value: "not_received", label: invoiceStatusLabels.not_received },
  { value: "received", label: invoiceStatusLabels.received },
  { value: "approved", label: invoiceStatusLabels.approved },
  { value: "rejected", label: invoiceStatusLabels.rejected },
];

const refundOptions = [
  { value: "", label: "全部" },
  { value: "none", label: refundStatusLabels.none },
  { value: "refunding", label: refundStatusLabels.refunding },
  { value: "refunded", label: refundStatusLabels.refunded },
];

function statusLabel(map: Record<string, string>, value: string) {
  return map[value] ?? value;
}

function activeChips(filters: DetailFilters): string[] {
  const chips: string[] = [];
  if (filters.month) chips.push(`跳转月份 ${filters.month}`);
  if (filters.product_type && filters.product_type !== "all")
    chips.push(`产品 ${filters.product_type}`);
  if (filters.sale_store_id)
    chips.push(`销售归属门店 ${getStoreName(filters.sale_store_id)}`);
  if (filters.exclude_sale_store_id)
    chips.push(`排除销售归属门店 ${getStoreName(filters.exclude_sale_store_id)}`);
  if (filters.sale_month) chips.push(`销售月份 ${filters.sale_month}`);
  if (filters.is_verified) chips.push(`是否核销 ${filters.is_verified === "true" ? "是" : "否"}`);
  if (filters.verify_store_id)
    chips.push(`实际核销门店 ${getStoreName(filters.verify_store_id)}`);
  if (filters.exclude_verify_store_id)
    chips.push(`排除实际核销门店 ${getStoreName(filters.exclude_verify_store_id)}`);
  if (filters.verify_month) chips.push(`核销月份 ${filters.verify_month}`);
  if (filters.is_commissionable)
    chips.push(`是否分佣 ${filters.is_commissionable === "true" ? "是" : "否"}`);
  if (filters.invoice_status)
    chips.push(`到票状态 ${statusLabel(invoiceStatusLabels, filters.invoice_status)}`);
  if (filters.refund_status)
    chips.push(`退款状态 ${statusLabel(refundStatusLabels, filters.refund_status)}`);
  if (filters.q) chips.push(`搜索 ${filters.q}`);
  return chips;
}

export function OrderDetailsPage({ searchParams }: OrderDetailsPageProps) {
  const searchKey = searchParams.toString();
  const [filters, setFilters] = useState<DetailFilters>(() =>
    detailFiltersFromSearch(searchParams),
  );

  useEffect(() => {
    setFilters(detailFiltersFromSearch(new URLSearchParams(searchKey)));
  }, [searchKey]);

  const filteredRows = useMemo(
    () => filterOrderDetails(orderDetails, filters),
    [filters],
  );

  const updateFilter = (key: keyof DetailFilters, value: string) => {
    setFilters((current) => ({
      ...current,
      [key]: value || undefined,
    }));
  };

  const columns: Column<OrderDetail>[] = [
    { key: "order", title: "订单 ID", render: (row) => row.order_id },
    { key: "coupon", title: "券 ID", render: (row) => row.coupon_id },
    { key: "product", title: "商品类型", render: (row) => row.product_type },
    {
      key: "saleStore",
      title: "销售归属门店",
      render: (row) => row.sale_store_name,
    },
    { key: "saleMonth", title: "销售月份", render: (row) => row.sale_month },
    {
      key: "verified",
      title: "是否核销",
      align: "center",
      render: (row) => <span className="status-chip">{labelForBoolean(row.is_verified)}</span>,
    },
    {
      key: "verifyStore",
      title: "实际核销门店",
      render: (row) => row.verify_store_name || "-",
    },
    {
      key: "verifyMonth",
      title: "核销月份",
      render: (row) => row.verify_month || "-",
    },
    {
      key: "commissionable",
      title: "是否分佣",
      align: "center",
      render: (row) => (
        <span className="status-chip">{labelForBoolean(row.is_commissionable)}</span>
      ),
    },
    {
      key: "invoice",
      title: "到票状态",
      render: (row) => statusLabel(invoiceStatusLabels, row.invoice_status),
    },
    {
      key: "refund",
      title: "退款状态",
      render: (row) => statusLabel(refundStatusLabels, row.refund_status),
    },
    {
      key: "paid",
      title: "订单实收金额",
      align: "right",
      render: (row) => formatCurrency(row.paid_amount_cent),
    },
    {
      key: "receivable",
      title: "预计获得分佣参考额",
      align: "right",
      render: (row) => formatCurrency(row.receivable_commission_cent),
    },
    {
      key: "payable",
      title: "预计分出分佣参考额",
      align: "right",
      render: (row) => formatCurrency(row.payable_commission_cent),
    },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">页面 3</p>
          <h1>门店月度数据明细表</h1>
        </div>
        <span className="source-pill">page3_order_detail.csv</span>
      </section>

      <FilterBar>
        <FilterField label="产品范围">
          <select
            value={filters.product_type ?? "all"}
            onChange={(event) => updateFilter("product_type", event.target.value)}
          >
            {getProductOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="销售归属门店">
          <select
            value={filters.sale_store_id ?? ""}
            onChange={(event) => updateFilter("sale_store_id", event.target.value)}
          >
            <option value="">全部</option>
            {getStoreOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="销售月份">
          <select
            value={filters.sale_month ?? ""}
            onChange={(event) => updateFilter("sale_month", event.target.value)}
          >
            <option value="">全部</option>
            {getMonthOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="是否核销">
          <select
            value={filters.is_verified ?? ""}
            onChange={(event) => updateFilter("is_verified", event.target.value)}
          >
            {booleanOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="实际核销门店">
          <select
            value={filters.verify_store_id ?? ""}
            onChange={(event) => updateFilter("verify_store_id", event.target.value)}
          >
            <option value="">全部</option>
            {getStoreOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="核销月份">
          <select
            value={filters.verify_month ?? ""}
            onChange={(event) => updateFilter("verify_month", event.target.value)}
          >
            <option value="">全部</option>
            {getMonthOptions().map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="是否分佣">
          <select
            value={filters.is_commissionable ?? ""}
            onChange={(event) =>
              updateFilter("is_commissionable", event.target.value)
            }
          >
            {booleanOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="到票状态">
          <select
            value={filters.invoice_status ?? ""}
            onChange={(event) => updateFilter("invoice_status", event.target.value)}
          >
            {invoiceOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="退款状态">
          <select
            value={filters.refund_status ?? ""}
            onChange={(event) => updateFilter("refund_status", event.target.value)}
          >
            {refundOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="订单 / 券搜索">
          <input
            placeholder="订单 ID 或券 ID"
            value={filters.q ?? ""}
            onChange={(event) => updateFilter("q", event.target.value)}
          />
        </FilterField>
        <button className="ghost-button" onClick={() => setFilters({})} type="button">
          清空筛选
        </button>
      </FilterBar>

      {activeChips(filters).length > 0 ? (
        <div className="active-filters" aria-label="当前筛选">
          {activeChips(filters).map((chip) => (
            <span key={chip}>{chip}</span>
          ))}
        </div>
      ) : null}

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>明细记录</h2>
            <p>{filteredRows.length} / {orderDetails.length} 条</p>
          </div>
        </div>
        <DataTable columns={columns} rows={filteredRows} />
      </section>
    </div>
  );
}
