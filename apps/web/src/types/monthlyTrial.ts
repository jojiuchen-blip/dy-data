import type { FeeDirection } from "./dashboard";

export type MonthlyTrialRecordStatus = "CALCULATED" | "PENDING" | "EXCLUDED";

export interface MonthlyTrialQuery {
  month: string;
  feeDirection: FeeDirection;
  productType?: string;
  storeId?: string;
  q?: string;
  recordStatus?: MonthlyTrialRecordStatus;
  page?: number;
  pageSize?: number;
  publication_id?: string;
}

export interface MonthlyTrialRow {
  couponId: string;
  orderId: string;
  storeId: string | null;
  storeName: string | null;
  productType: string;
  skuId: string | null;
  feeAmountCent: number | null;
  baseAmountCent: number | null;
  feeRate: string | null;
  ruleVersion: string | null;
  recordStatus: MonthlyTrialRecordStatus;
  reason: string | null;
}

export interface MonthlyTrialData {
  month: string;
  feeDirection: FeeDirection;
  status: "TRIAL";
  summary: {
    calculatedFeeCent: number | null;
    calculatedCouponCount: number | null;
    pendingCouponCount: number | null;
    candidateCouponCount: number | null;
    excludedCouponCount: number | null;
    coverageComplete: boolean;
  };
  coverage: {
    scopeUnresolved: boolean;
    sourceSuccessDays: number | null;
    sourceTotalDays: number | null;
    reasons: Array<{ code: string; label: string; couponCount: number }>;
    note: string;
  };
  list: MonthlyTrialRow[];
  total: number;
  page: number;
  pageSize: number;
}
