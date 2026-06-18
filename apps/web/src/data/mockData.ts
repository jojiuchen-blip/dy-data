import page1Raw from "./mock/page1_store_ranking.json";
import page2SummaryRaw from "./mock/page2_store_month_summary.json";
import page2TablesRaw from "./mock/page2_commission_tables.json";
import orderDetailCsv from "./mock/page3_order_detail.csv?raw";
import skuProductRulesRaw from "./mock/sku_product_commission_rules.json";
import clueCenterRaw from "./mock/clue_center.json";
import type {
  ApiResponse,
  ClueAssignmentRoundData,
  ClueFilterMetadata,
  ClueOrderDetail,
  ClueOverviewMetrics,
  ClueReassignRuleData,
  ClueRebuildResult,
  CommissionTablesData,
  MonthlySummaryData,
  OrderDetail,
  SkuProductCommissionRule,
  StoreRankingData,
} from "../types/dashboard";
import { parseCsv } from "../utils/csv";

export const storeRankingResponse =
  page1Raw as ApiResponse<StoreRankingData>;
export const monthlySummaryResponse =
  page2SummaryRaw as ApiResponse<MonthlySummaryData>;
export const commissionTablesResponse =
  page2TablesRaw as ApiResponse<CommissionTablesData>;
export const skuProductRulesResponse = skuProductRulesRaw as ApiResponse<{
  rows: SkuProductCommissionRule[];
}>;
export const clueCenterResponses = clueCenterRaw as unknown as {
  filters: ApiResponse<ClueFilterMetadata>;
  overview: ApiResponse<ClueOverviewMetrics>;
  assignment_rounds: ApiResponse<ClueAssignmentRoundData>;
  order_details?: Record<string, ApiResponse<ClueOrderDetail>>;
  rule: ApiResponse<ClueReassignRuleData>;
  rebuild: ApiResponse<ClueRebuildResult>;
};

const skuProductRuleMap = new Map(
  skuProductRulesResponse.data.rows.map((rule) => [rule.sku_id, rule]),
);

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
  (row) => {
    const rule = skuProductRuleMap.get(row.sku_id);

    return {
      order_id: row.order_id,
      coupon_id: row.coupon_id,
      sku_id: row.sku_id,
      owner_account_id: row.owner_account_id,
      owner_account_name: row.owner_account_name,
      product_type: rule?.product_type ?? "未映射",
      sale_store_id: row.sale_store_id,
      sale_store_name: row.sale_store_name,
      sale_store_subject_name: row.sale_store_subject_name ?? "",
      sale_month: monthFromIso(row.sale_time),
      sale_time: row.sale_time,
      is_verified: parseBoolean(row.is_verified) === true,
      verify_store_id: row.verify_store_id,
      verify_store_name: row.verify_store_name,
      verify_store_subject_name: row.verify_store_subject_name ?? "",
      verify_month: monthFromIso(row.verify_time),
      verify_time: row.verify_time,
      relation_type: row.relation_type as OrderDetail["relation_type"],
      is_commissionable: parseBoolean(row.is_commissionable),
      paid_amount_cent: parseNumber(row.paid_amount_cent),
      commission_rate: rule?.commission_rate ?? 0,
      receivable_commission_cent: parseNumber(row.receivable_commission_cent),
      payable_commission_cent: parseNumber(row.payable_commission_cent),
    };
  },
);

function monthFromIso(value: string): string {
  return value ? value.slice(0, 7) : "";
}

export const page1Definitions = storeRankingResponse.definitions ?? [];
export const page2Definitions = monthlySummaryResponse.definitions ?? [];
export const defaultMonth = storeRankingResponse.data.month;
export const defaultStore = monthlySummaryResponse.data.store;
