import type { DouyinRankingLevel } from "../types/dashboard";

export type RankingMetric = "order_average" | "follow_24h_rate" | "verification_rate";
export const RANKING_METRIC_OPTIONS: Array<{ value: RankingMetric; label: string }> = [
  { value: "order_average", label: "抖音店均订单量" },
  { value: "follow_24h_rate", label: "24小时有效跟进率" },
  { value: "verification_rate", label: "订单核销率" },
];
export const RANKING_LEVEL_OPTIONS: Array<{ value: DouyinRankingLevel; label: string }> = [
  { value: "group", label: "集团" },
  { value: "service_center", label: "中心" },
  { value: "district", label: "大区" },
  { value: "area", label: "区域" },
  { value: "store", label: "门店" },
];
