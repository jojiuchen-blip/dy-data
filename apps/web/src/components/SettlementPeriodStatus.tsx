import type { SettlementMonthReadiness, SettlementPeriodAvailability } from "../types/dashboard";
import { formatInteger } from "../utils/format";
import { ResourcePanel } from "./ResourceState";

interface SettlementPeriodStatusProps {
  month: string;
  readiness?: SettlementMonthReadiness;
  monthlyClose?: SettlementPeriodAvailability["monthlyClose"];
  unavailable?: boolean;
  requestId?: string;
}

export function SettlementPeriodStatus({ month, readiness, monthlyClose, unavailable = false, requestId }: SettlementPeriodStatusProps) {
  const close = readiness?.monthlyClose ?? monthlyClose;
  if (!close) return null;

  const successDays = readiness?.successDays;
  const totalDays = readiness?.totalDays;
  const hasDayProgress = typeof successDays === "number" && typeof totalDays === "number"
    && Number.isInteger(successDays) && Number.isInteger(totalDays)
    && successDays >= 0 && totalDays > 0 && successDays <= totalDays;
  const hasReviewEvidence = close.blockedStoreCount > 0 || close.publishedStoreCount > 0;

  return (
    <ResourcePanel tone={unavailable ? "error" : "loading"}>
      <div aria-label="账期处理进度">
        {close.status === "complete" ? (
          <p>本月月结核验已完成。</p>
        ) : close.status === "partial" ? (
          <p>当前显示已出账的门店。其余账单核对中，累计金额暂不可用。</p>
        ) : (
          <p>本账期正式账单尚未就绪。</p>
        )}
        <details>
          <summary>账期进度 · 已出账门店数 {formatInteger(close.publishedStoreCount)} 家，已知待核验门店数 {formatInteger(close.blockedStoreCount)} 家</summary>
          {hasDayProgress ? <p>{month} 已完成 {successDays}/{totalDays} 天的数据采集。</p> : null}
          {close.scopeUnresolved ? (
            <p>{hasReviewEvidence ? "仍有数据归属或影响范围待核验。" : "门店影响范围待确认。"}</p>
          ) : null}
          {unavailable ? <p>正式账单和导出暂不可用{requestId ? `，请求编号 ${requestId}` : ""}。</p> : null}
        </details>
      </div>
    </ResourcePanel>
  );
}
