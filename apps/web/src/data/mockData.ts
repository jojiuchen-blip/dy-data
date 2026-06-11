import page1Raw from "./mock/page1_store_ranking.json";
import page2SummaryRaw from "./mock/page2_store_month_summary.json";
import page2TablesRaw from "./mock/page2_commission_tables.json";
import orderDetailCsv from "./mock/page3_order_detail.csv?raw";
import type {
  ApiResponse,
  CommissionTablesData,
  MonthlySummaryData,
  OrderDetail,
  StoreRankingData,
} from "../types/dashboard";
import { parseCsv } from "../utils/csv";

export const storeRankingResponse =
  page1Raw as ApiResponse<StoreRankingData>;
export const monthlySummaryResponse =
  page2SummaryRaw as ApiResponse<MonthlySummaryData>;
export const commissionTablesResponse =
  page2TablesRaw as ApiResponse<CommissionTablesData>;

function parseBoolean(value: string): boolean | null {
  if (!value) {
    return null;
  }
  return value.toLowerCase() === "true";
}

function parseNumber(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export const orderDetails: OrderDetail[] = parseCsv(orderDetailCsv).map(
  (row) => ({
    detail_id: row.detail_id,
    order_id: row.order_id,
    coupon_id: row.coupon_id,
    verify_id: row.verify_id,
    product_type: row.product_type,
    sale_store_id: row.sale_store_id,
    sale_store_name: row.sale_store_name,
    sale_month: row.sale_month,
    sale_time: row.sale_time,
    is_verified: parseBoolean(row.is_verified) === true,
    verify_store_id: row.verify_store_id,
    verify_store_name: row.verify_store_name,
    verify_month: row.verify_month,
    verify_time: row.verify_time,
    relation_type: row.relation_type as OrderDetail["relation_type"],
    is_commissionable: parseBoolean(row.is_commissionable),
    invoice_status: row.invoice_status,
    refund_status: row.refund_status,
    refund_amount_cent: parseNumber(row.refund_amount_cent),
    paid_amount_cent: parseNumber(row.paid_amount_cent),
    commission_rate: parseNumber(row.commission_rate),
    receivable_commission_cent: parseNumber(row.receivable_commission_cent),
    payable_commission_cent: parseNumber(row.payable_commission_cent),
  }),
);

export const page1Definitions = storeRankingResponse.definitions ?? [];
export const page2Definitions = monthlySummaryResponse.definitions ?? [];
export const defaultMonth = storeRankingResponse.data.month;
export const defaultStore = monthlySummaryResponse.data.store;
