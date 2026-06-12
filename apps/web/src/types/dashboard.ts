export interface ApiDefinition {
  key: string;
  label: string;
  description: string;
}

export interface ApiMeta {
  generated_at: string;
  source: string;
}

export interface ApiResponse<T> {
  data: T;
  definitions?: ApiDefinition[];
  meta: ApiMeta;
}

export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface StoreOption {
  store_id: string;
  store_name: string;
}

export interface SelectOption {
  value: string;
  label: string;
}

export interface FilterMetaData {
  stores: StoreOption[];
  product_types: string[];
  sale_months: string[];
  verify_months: string[];
}

export interface StoreRankingRow {
  rank: number;
  store_id: string;
  store_name: string;
  sales_order_count: number;
  self_sold_self_verified_count: number;
  self_sold_other_verified_count: number;
  other_sold_self_verified_count: number;
  self_verify_income_cent: number;
  effective_commission_income_cent: number;
}

export interface StoreRankingData {
  month: string;
  product_type: string;
  limit: number;
  rows: StoreRankingRow[];
}

export interface MonthlySummaryData {
  store: StoreOption;
  month: string;
  product_type: string;
  metrics: {
    estimated_receivable_commission_cent: number;
    commissionable_total_cent: number;
    estimated_payable_commission_cent: number;
  };
}

export interface ReceivableCommissionRow {
  product_type: string;
  verified_coupon_count: number;
  paid_amount_cent: number;
  commission_rate: number;
  commissionable_total_cent: number;
  estimated_receivable_commission_cent: number;
}

export interface PayableCommissionRow {
  product_type: string;
  verified_coupon_count: number;
  paid_amount_cent: number;
  commission_rate: number;
  payable_commission_cent: number;
}

export interface NonCommissionOrderRow {
  product_type: string;
  verified_coupon_count: number;
  paid_amount_cent: number;
}

export interface CommissionTablesData {
  store: StoreOption;
  month: string;
  product_type: string;
  tables: {
    receivable_commissions: ReceivableCommissionRow[];
    payable_commissions: PayableCommissionRow[];
    non_commission_orders: NonCommissionOrderRow[];
  };
}

export interface MonthlySettlementData extends MonthlySummaryData {
  tables: CommissionTablesData["tables"];
  source?: "contract-mock" | "detail-derived";
}

export interface OrderDetail {
  order_id: string;
  coupon_id: string;
  sku_id: string;
  owner_account_id: string;
  owner_account_name: string;
  product_type: string;
  sale_store_id: string;
  sale_store_name: string;
  sale_month: string;
  sale_time: string;
  is_verified: boolean;
  verify_store_id: string;
  verify_store_name: string;
  verify_month: string;
  verify_time: string;
  relation_type: "same_store" | "cross_store" | "unverified" | "unknown" | "";
  is_commissionable: boolean | null;
  paid_amount_cent: number;
  commission_rate: number;
  receivable_commission_cent: number;
  payable_commission_cent: number;
}

export interface DetailFilters {
  product_type?: string;
  sale_store_id?: string;
  exclude_sale_store_id?: string;
  sale_month?: string;
  is_verified?: string;
  verify_store_id?: string;
  exclude_verify_store_id?: string;
  verify_month?: string;
  relation_type?: string;
  is_commissionable?: string;
  q?: string;
}

export interface SkuProductCommissionRule {
  sku_id: string;
  product_type: string;
  commission_rate: number;
}

export interface SettlementViewData extends MonthlySettlementData {
  source: "contract-mock" | "detail-derived";
}

export interface OrderDetailsData {
  rows: OrderDetail[];
  pagination: Pagination;
}
