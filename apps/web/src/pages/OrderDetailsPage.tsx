import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_DETAIL_PAGE_SIZE,
  fetchFilterMeta,
  fetchOrderDetails,
} from "../api/client";
import { StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { SelectField } from "../components/FormControls";
import {
  ResourceNotice,
  ResourcePanel,
  resourceSourceLabel,
} from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  DetailFilters,
  FilterMetaData,
  OrderDetail,
  Pagination,
} from "../types/dashboard";
import { formatCurrency, formatDateTime, labelForBoolean } from "../utils/format";
import {
  productOptions,
  saleMonthOptions,
  storeOptions,
  verifyMonthOptions,
} from "../utils/options";
import { detailFiltersFromSearch } from "../utils/settlement";

interface OrderDetailsPageProps {
  searchParams: URLSearchParams;
}

const booleanOptions = [
  { value: "", label: "全部" },
  { value: "true", label: "是" },
  { value: "false", label: "否" },
];

const pageSizeOptions = [25, 50, 100, 200, 500];
const pageSizeSelectOptions = pageSizeOptions.map((option) => ({
  label: String(option),
  value: String(option),
}));

function BooleanStatusChip({ value }: { value: boolean | null | undefined }) {
  if (typeof value !== "boolean") {
    return <StatusChip tone="neutral">-</StatusChip>;
  }
  return <StatusChip tone={value ? "green" : "neutral"}>{labelForBoolean(value)}</StatusChip>;
}

function storeName(meta: FilterMetaData | undefined, storeId: string): string {
  return (
    meta?.stores.find((store) => store.store_id === storeId)?.store_name ||
    "未匹配门店"
  );
}

function activeChips(
  filters: DetailFilters,
  meta: FilterMetaData | undefined,
): string[] {
  const chips: string[] = [];
  if (filters.product_type && filters.product_type !== "all") {
    chips.push(`产品 ${filters.product_type}`);
  }
  if (filters.sale_store_id) {
    chips.push(`销售归属门店 ${storeName(meta, filters.sale_store_id)}`);
  }
  if (filters.exclude_sale_store_id) {
    chips.push(`排除销售归属门店 ${storeName(meta, filters.exclude_sale_store_id)}`);
  }
  if (filters.sale_month) chips.push(`销售月份 ${filters.sale_month}`);
  if (filters.is_verified) {
    chips.push(`是否核销 ${filters.is_verified === "true" ? "是" : "否"}`);
  }
  if (filters.verify_store_id) {
    chips.push(`实际核销门店 ${storeName(meta, filters.verify_store_id)}`);
  }
  if (filters.exclude_verify_store_id) {
    chips.push(`排除实际核销门店 ${storeName(meta, filters.exclude_verify_store_id)}`);
  }
  if (filters.verify_month) chips.push(`核销月份 ${filters.verify_month}`);
  if (filters.is_commissionable) {
    chips.push(`是否分佣 ${filters.is_commissionable === "true" ? "是" : "否"}`);
  }
  if (filters.q) chips.push(`搜索 ${filters.q}`);
  return chips;
}

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function detailsSearchString(
  filters: DetailFilters,
  page: number,
  pageSize: number,
): string {
  const search = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== "all") {
      search.set(key, value);
    }
  });
  if (page > 1) {
    search.set("page", String(page));
  }
  if (pageSize !== DEFAULT_DETAIL_PAGE_SIZE) {
    search.set("page_size", String(pageSize));
  }

  const query = search.toString();
  return query ? `?${query}` : "";
}

function replaceDetailsUrl(
  filters: DetailFilters,
  page: number,
  pageSize: number,
) {
  const nextUrl = `/details${detailsSearchString(filters, page, pageSize)}`;
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  if (currentUrl === nextUrl) {
    return;
  }

  window.history.replaceState(null, "", nextUrl);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function selectedStoreOption(
  meta: FilterMetaData | undefined,
  storeId: string | undefined,
) {
  if (!storeId) {
    return undefined;
  }
  return {
    store_id: storeId,
    store_name: storeName(meta, storeId),
  };
}

function PaginationControls({
  loading,
  onPageChange,
  onPageSizeChange,
  pageSize,
  pagination,
}: {
  loading: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  pageSize: number;
  pagination: Pagination | undefined;
}) {
  if (!pagination) {
    return null;
  }

  const totalPages = Math.max(1, pagination.total_pages);
  const currentPage = Math.min(Math.max(1, pagination.page), totalPages);

  return (
    <div className="pagination-controls">
      <div className="pagination-controls__summary">
        第 {currentPage} / {totalPages} 页，共 {pagination.total} 条
      </div>
      <div className="pagination-controls__actions">
        <button
          className="ghost-button"
          disabled={loading || currentPage <= 1}
          onClick={() => onPageChange(currentPage - 1)}
          type="button"
        >
          上一页
        </button>
        <button
          className="ghost-button"
          disabled={loading || currentPage >= totalPages}
          onClick={() => onPageChange(currentPage + 1)}
          type="button"
        >
          下一页
        </button>
        <div className="pagination-controls__size">
          <SelectField
            label="每页"
            onChange={(value) => onPageSizeChange(Number(value))}
            options={pageSizeSelectOptions}
            value={String(pageSize)}
          />
        </div>
      </div>
    </div>
  );
}

export function OrderDetailsPage({ searchParams }: OrderDetailsPageProps) {
  const searchKey = searchParams.toString();
  const [filters, setFilters] = useState<DetailFilters>(() =>
    detailFiltersFromSearch(searchParams),
  );
  const [page, setPage] = useState(() =>
    positiveInteger(searchParams.get("page"), 1),
  );
  const [pageSize, setPageSize] = useState(() =>
    positiveInteger(searchParams.get("page_size"), DEFAULT_DETAIL_PAGE_SIZE),
  );

  useEffect(() => {
    const nextSearchParams = new URLSearchParams(searchKey);
    setFilters(detailFiltersFromSearch(nextSearchParams));
    setPage(positiveInteger(nextSearchParams.get("page"), 1));
    setPageSize(
      positiveInteger(nextSearchParams.get("page_size"), DEFAULT_DETAIL_PAGE_SIZE),
    );
  }, [searchKey]);

  const metaResource = useApiResource(fetchFilterMeta, []);
  const detailsResource = useApiResource(
    () => fetchOrderDetails({ filters, page, pageSize }),
    [filters, page, pageSize],
  );

  const meta = metaResource.data?.data;
  const details = detailsResource.data?.data;
  const rows = details?.rows ?? [];
  const pagination = details?.pagination;
  const chips = useMemo(() => activeChips(filters, meta), [filters, meta]);

  useEffect(() => {
    replaceDetailsUrl(filters, page, pageSize);
  }, [filters, page, pageSize]);

  const updateFilter = (key: keyof DetailFilters, value: string) => {
    setFilters((current) => ({
      ...current,
      [key]: value || undefined,
    }));
    setPage(1);
  };

  const clearFilters = () => {
    setFilters({});
    setPage(1);
  };

  const columns: Column<OrderDetail>[] = [
    {
      key: "order",
      title: "订单编号",
      sticky: true,
      width: 150,
      render: (row) => row.order_id,
    },
    {
      key: "coupon",
      title: "券码",
      sticky: true,
      width: 154,
      render: (row) => row.coupon_id,
    },
    {
      key: "productName",
      title: "商品名称",
      minWidth: 240,
      render: (row) => row.product_name || "-",
    },
    {
      key: "sku",
      title: "商品编码",
      minWidth: 138,
      render: (row) => row.sku_id,
    },
    {
      key: "product",
      title: "商品类型",
      minWidth: 110,
      render: (row) => row.product_type,
    },
    {
      key: "ownerAccount",
      title: "订单归属账号",
      minWidth: 150,
      render: (row) => row.owner_account_name || "-",
    },
    {
      key: "saleStore",
      title: "销售归属门店",
      minWidth: 190,
      render: (row) => row.sale_store_name,
    },
    {
      key: "saleStoreSubject",
      title: "销售店认证主体",
      minWidth: 210,
      render: (row) => row.sale_store_subject_name || "-",
    },
    {
      key: "saleTime",
      title: "销售时间",
      minWidth: 190,
      render: (row) => formatDateTime(row.sale_time),
    },
    {
      key: "verified",
      title: "是否核销",
      align: "center",
      render: (row) => <BooleanStatusChip value={row.is_verified} />,
    },
    {
      key: "verifyStore",
      title: "实际核销门店",
      minWidth: 190,
      render: (row) => row.verify_store_name || "-",
    },
    {
      key: "verifyStoreSubject",
      title: "核销店认证主体",
      minWidth: 210,
      render: (row) => row.verify_store_subject_name || "-",
    },
    {
      key: "verifyTime",
      title: "核销时间",
      minWidth: 190,
      render: (row) => formatDateTime(row.verify_time),
    },
    {
      key: "commissionable",
      title: "是否分佣",
      align: "center",
      render: (row) => <BooleanStatusChip value={row.is_commissionable} />,
    },
    {
      key: "paid",
      title: "订单实收金额",
      align: "right",
      render: (row) => formatCurrency(row.paid_amount_cent),
    },
    {
      key: "commissionRate",
      title: "分佣比例",
      align: "right",
      render: (row) => `${(row.commission_rate * 100).toFixed(0)}%`,
    },
    {
      key: "receivable",
      title: "预计获得分佣参考额",
      align: "right",
      minWidth: 150,
      render: (row) => formatCurrency(row.receivable_commission_cent),
    },
    {
      key: "payable",
      title: "预计分出分佣参考额",
      align: "right",
      minWidth: 150,
      render: (row) => formatCurrency(row.payable_commission_cent),
    },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <h1>门店月度数据明细表</h1>
        </div>
        <span className="source-pill">
          {resourceSourceLabel(detailsResource.data, detailsResource.loading)}
        </span>
      </section>

      <ResourceNotice
        fallbackReason={
          detailsResource.data?.fallbackReason ?? metaResource.data?.fallbackReason
        }
        loading={detailsResource.loading || metaResource.loading}
        error={detailsResource.error ?? metaResource.error}
      />

      <div className="detail-filter-stack">
        <FilterBar className="filter-bar--compact detail-filter-bar detail-filter-bar--single-line">
          <FilterField label="销售归属门店">
            <SearchableStoreSelect
              allowEmpty
              options={storeOptions(meta, selectedStoreOption(meta, filters.sale_store_id))}
              value={filters.sale_store_id ?? ""}
              onChange={(value) => updateFilter("sale_store_id", value)}
            />
          </FilterField>
          <SelectField
            label="核销月份"
            onChange={(value) => updateFilter("verify_month", value)}
            options={[
              { value: "", label: "全部" },
              ...verifyMonthOptions(meta, filters.verify_month),
            ]}
            value={filters.verify_month ?? ""}
          />
          <SelectField
            label="产品范围"
            onChange={(value) => updateFilter("product_type", value)}
            options={productOptions(meta, filters.product_type ?? "all")}
            value={filters.product_type ?? "all"}
          />
          <FilterField label="订单 / 券搜索">
            <input
              placeholder="订单编号或券码"
              value={filters.q ?? ""}
              onChange={(event) => updateFilter("q", event.target.value)}
            />
          </FilterField>
          <SelectField
            label="销售月份"
            onChange={(value) => updateFilter("sale_month", value)}
            options={[
              { value: "", label: "全部" },
              ...saleMonthOptions(meta, filters.sale_month),
            ]}
            value={filters.sale_month ?? ""}
          />
          <SelectField
            label="是否核销"
            onChange={(value) => updateFilter("is_verified", value)}
            options={booleanOptions}
            value={filters.is_verified ?? ""}
          />
          <FilterField label="实际核销门店">
            <SearchableStoreSelect
              allowEmpty
              options={storeOptions(
                meta,
                selectedStoreOption(meta, filters.verify_store_id),
              )}
              value={filters.verify_store_id ?? ""}
              onChange={(value) => updateFilter("verify_store_id", value)}
            />
          </FilterField>
          <SelectField
            label="是否分佣"
            onChange={(value) => updateFilter("is_commissionable", value)}
            options={booleanOptions}
            value={filters.is_commissionable ?? ""}
          />
          <button className="ghost-button" onClick={clearFilters} type="button">
            清空筛选
          </button>
        </FilterBar>
      </div>

      {chips.length > 0 ? (
        <div className="active-filters" aria-label="当前筛选">
          {chips.map((chip) => (
            <span key={chip}>{chip}</span>
          ))}
        </div>
      ) : null}

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>明细记录</h2>
            <p>
              {pagination
                ? `${pagination.total} 条，当前页 ${rows.length} 条`
                : "正在读取记录"}
            </p>
          </div>
        </div>

        {!details && detailsResource.loading ? (
          <ResourcePanel>正在加载明细数据...</ResourcePanel>
        ) : !details ? (
          <ResourcePanel tone="error">明细数据暂不可用。</ResourcePanel>
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              stickyHeader="container"
              tableClassName="data-table--details"
            />
            <PaginationControls
              loading={detailsResource.loading}
              onPageChange={setPage}
              onPageSizeChange={(nextPageSize) => {
                setPageSize(nextPageSize);
                setPage(1);
              }}
              pageSize={pageSize}
              pagination={pagination}
            />
          </>
        )}
      </section>
    </div>
  );
}
