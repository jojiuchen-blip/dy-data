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
        {hasDayProgress ? (
          <p>{month} 已完成 {successDays}/{totalDays} 天的数据采集。</p>
        ) : null}
        <p>当前可查看范围已出账门店数 {formatInteger(close.publishedStoreCount)} 家，已知待核验门店数 {formatInteger(close.blockedStoreCount)} 家。</p>
        {close.status === "complete" ? (
          <p>本月月结核验已完成。</p>
        ) : close.status === "partial" ? (
          <p>当前显示已出账的门店。其余门店的账单仍在核对，累计金额暂不可用。</p>
        ) : hasReviewEvidence ? (
          <p>月结已发现待核验数据，处理完成后继续核对可出账范围。</p>
        ) : (
          <p>月结核算与核验结果尚未就绪，门店影响范围待确认。</p>
        )}
        {close.scopeUnresolved && hasReviewEvidence ? (
          <p>仍有数据归属或影响范围待核验，暂不能确定其余门店的出账范围。</p>
        ) : null}
        {unavailable ? <p>所选账期的正式账单金额和正式账单导出暂不可用。错误码 PUBLICATION_PERIOD_NOT_READY{requestId ? `，请求编号 ${requestId}` : ""}。</p> : null}
      </div>
    </ResourcePanel>
  );
}
