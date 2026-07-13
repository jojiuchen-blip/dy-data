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

const parsedOrderDetails: OrderDetail[] = parseCsv(orderDetailCsv).map(
  (row) => {
    const rule = skuProductRuleMap.get(row.sku_id);

    return {
      order_id: row.order_id,
      coupon_id: row.coupon_id,
      product_name: rule?.product_name ?? "",
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
      is_refund_excluded: parseBoolean(row.is_refund_excluded) === true,
      paid_amount_cent: parseNumber(row.paid_amount_cent),
      commission_rate: rule?.commission_rate ?? 0,
      receivable_commission_cent: parseNumber(row.receivable_commission_cent),
      payable_commission_cent: parseNumber(row.payable_commission_cent),
    };
  },
);

interface MockStoreSeed {
  owner_account_id: string;
  owner_account_name: string;
  store_id: string;
  store_name: string;
  subject_name: string;
}

const salesMockMonths = [
  "2025-07",
  "2025-08",
  "2025-09",
  "2025-10",
  "2025-11",
  "2025-12",
  "2026-01",
  "2026-02",
  "2026-03",
  "2026-04",
  "2026-05",
  "2026-06",
];

const mockAmountBySkuId: Record<string, number> = {
  sku_168_basic: 16800,
  sku_268_basic: 26800,
  sku_evap_clean: 9800,
  sku_outer_clean: 8800,
  sku_paint_care: 88000,
};

function collectMockStores(rows: OrderDetail[]): MockStoreSeed[] {
  const stores = new Map<string, MockStoreSeed>();

  rows.forEach((row) => {
    if (row.sale_store_id && !stores.has(row.sale_store_id)) {
      stores.set(row.sale_store_id, {
        owner_account_id: row.owner_account_id,
        owner_account_name: row.owner_account_name,
        store_id: row.sale_store_id,
        store_name: row.sale_store_name,
        subject_name: row.sale_store_subject_name,
      });
    }
    if (row.verify_store_id && !stores.has(row.verify_store_id)) {
      stores.set(row.verify_store_id, {
        owner_account_id: row.owner_account_id,
        owner_account_name: row.owner_account_name,
        store_id: row.verify_store_id,
        store_name: row.verify_store_name,
        subject_name: row.verify_store_subject_name,
      });
    }
  });

  return [...stores.values()].slice(0, 5);
}

function padDatePart(value: number): string {
  return String(value).padStart(2, "0");
}

function mockDateTime(
  month: string,
  day: number,
  hour: number,
  minute: number,
  addDays = 0,
): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const date = new Date(
    Date.UTC(year, monthNumber - 1, day + addDays, hour, minute, 0),
  );

  return `${date.getUTCFullYear()}-${padDatePart(
    date.getUTCMonth() + 1,
  )}-${padDatePart(date.getUTCDate())}T${padDatePart(
    date.getUTCHours(),
  )}:${padDatePart(date.getUTCMinutes())}:00+08:00`;
}

function buildSalesDashboardMockRows(seedRows: OrderDetail[]): OrderDetail[] {
  const stores = collectMockStores(seedRows);
  const rules = skuProductRulesResponse.data.rows;

  if (stores.length === 0 || rules.length === 0) {
    return [];
  }

  const generated: OrderDetail[] = [];
  salesMockMonths.forEach((month, monthIndex) => {
    stores.forEach((store, storeIndex) => {
      const ordersThisMonth = 7 + ((monthIndex + storeIndex) % 4);

      for (let orderIndex = 0; orderIndex < ordersThisMonth; orderIndex += 1) {
        const sequence = generated.length + 1;
        const rule = rules[(orderIndex + storeIndex * 2 + monthIndex) % rules.length];
        const amountCent =
          (mockAmountBySkuId[rule.sku_id] ?? 19800) +
          ((orderIndex + monthIndex) % 4) * 500;
        const isVerified = (orderIndex + monthIndex + storeIndex) % 8 !== 0;
        const isSelfVerified =
          isVerified && (orderIndex + monthIndex + storeIndex) % 4 !== 0;
        const verifyStore = isVerified
          ? isSelfVerified
            ? store
            : stores[(storeIndex + orderIndex + 1) % stores.length]
          : undefined;
        const relationType: OrderDetail["relation_type"] = !isVerified
          ? "unverified"
          : verifyStore?.store_id === store.store_id
            ? "same_store"
            : "cross_store";
        const saleDay = 1 + ((storeIndex * 5 + orderIndex * 3) % 24);
        const cycleDays = 2 + ((monthIndex * 3 + storeIndex * 5 + orderIndex * 7) % 32);
        const saleTime = mockDateTime(
          month,
          saleDay,
          9 + (orderIndex % 9),
          (storeIndex * 11 + orderIndex * 7) % 60,
        );
        const verifyTime =
          isVerified && verifyStore
            ? mockDateTime(
                month,
                saleDay,
                10 + (orderIndex % 8),
                (storeIndex * 13 + orderIndex * 5) % 60,
                cycleDays,
              )
            : "";
        const commissionCent = Math.round(amountCent * rule.commission_rate);

        generated.push({
          order_id: `mock_sales_${String(sequence).padStart(4, "0")}`,
          coupon_id: `mock_sales_coupon_${String(sequence).padStart(4, "0")}`,
          product_name: rule.product_name ?? "",
          sku_id: rule.sku_id,
          owner_account_id: store.owner_account_id,
          owner_account_name: store.owner_account_name,
          product_type: rule.product_type,
          sale_store_id: store.store_id,
          sale_store_name: store.store_name,
          sale_store_subject_name: store.subject_name,
          sale_month: monthFromIso(saleTime),
          sale_time: saleTime,
          is_verified: isVerified,
          verify_store_id: verifyStore?.store_id ?? "",
          verify_store_name: verifyStore?.store_name ?? "",
          verify_store_subject_name: verifyStore?.subject_name ?? "",
          verify_month: monthFromIso(verifyTime),
          verify_time: verifyTime,
          relation_type: relationType,
          is_commissionable: isVerified ? relationType === "cross_store" : null,
          is_refund_excluded: (monthIndex + storeIndex + orderIndex) % 41 === 0,
          paid_amount_cent: amountCent,
          commission_rate: rule.commission_rate,
          receivable_commission_cent:
            relationType === "cross_store" ? commissionCent : 0,
          payable_commission_cent:
            relationType === "cross_store" ? commissionCent : 0,
        });
      }
    });
  });

  return generated;
}

export const orderDetails: OrderDetail[] = [
  ...parsedOrderDetails,
  ...buildSalesDashboardMockRows(parsedOrderDetails),
];

function monthFromIso(value: string): string {
  return value ? value.slice(0, 7) : "";
}

export const page1Definitions = storeRankingResponse.definitions ?? [];
export const page2Definitions = monthlySummaryResponse.definitions ?? [];
export const defaultMonth = storeRankingResponse.data.month;
export const defaultStore = monthlySummaryResponse.data.store;
