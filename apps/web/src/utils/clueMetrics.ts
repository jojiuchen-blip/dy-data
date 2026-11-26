import type { ClueProductScope } from "../types/dashboard";

export const CLUE_PRODUCT_SCOPE_OPTIONS: Array<{ value: ClueProductScope; label: string }> = [
  { value: "all", label: "全部商品" },
  { value: "jingcheng", label: "精诚养车" },
  { value: "byd", label: "比亚迪本品" },
];

export const FOLLOW_24H_DESCRIPTION = "正式分配到店后固定24小时内首次有效提交的任务数 ÷ 实际接收任务数。自2026年11月1日起，核销同步前任务仍可操作时的有效提交也计入。接收24小时内全额退款或订单失效且结束前无有效提交的任务剔除。提前核销仍保留分母，核销本身不算跟进。";
export const FOLLOW_ANY_DESCRIPTION = "有过有效提交的任务数 ÷ 实际接收任务数，与24小时跟进率共用分母。计入本轮有效期间的提交及符合24小时补计条件的核销同步前提交。核销本身不算跟进，每任务最多计一次。";
export const VERIFICATION_RATE_DESCRIPTION = "本轮承接店有效核销的任务数 ÷ 本店实际接收任务数，按核销实际发生时间匹配轮次。跨店核销保留承接店分母；关单后在原承接店核销可补计其原轮次。汇总合并分子、分母重算。";
export const SELF_STORE_VERIFICATION_DESCRIPTION = "按实际核销门店统计订单数，包含未生成或未分配线索的订单。同店同订单全期只计一次，归入该店首次有效核销的北京时间日期。";

export function normalizeClueProductScope(value: string | null): ClueProductScope {
  return value === "jingcheng" || value === "byd" ? value : "all";
}
