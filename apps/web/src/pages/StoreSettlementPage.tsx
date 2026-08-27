import { useMemo, useState } from "react";
import {
  ApiRequestError,
  confirmStoreBillingStatement,
  fetchStoreBillingStatements,
  fetchSettlementFilterMeta,
  fetchSettlementMonthly,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { FilterBar, FilterField } from "../components/Filters";
import { SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type { BillingConfirmationSummary, FeeDirection, SettlementStatementLine } from "../types/dashboard";
import { formatCurrency, formatDateTime, formatInteger } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";
import { userFacingError } from "../utils/userFacingError";

interface StoreSettlementPageProps {
  searchParams: URLSearchParams;
}

function rateLabel(line: SettlementStatementLine): string {
  if (!line.feeRates.length) return "费率不可用";
  const formatted = line.feeRates.map((rate) => `${(Number(rate) * 100).toFixed(2).replace(/\.00$/, "")}%`);
  if (line.feeRates.length > 1) {
    const minimum = line.minFeeRate ? `${(Number(line.minFeeRate) * 100).toFixed(2).replace(/\.00$/, "")}%` : formatted[0];
    const maximum = line.maxFeeRate ? `${(Number(line.maxFeeRate) * 100).toFixed(2).replace(/\.00$/, "")}%` : formatted[formatted.length - 1];
    return `${minimum}–${maximum}；集合 ${formatted.join("、")}（共 ${line.feeRates.length} 种）`;
  }
  return formatted[0];
}

function isLineTraceable(line: SettlementStatementLine): boolean {
  return line.originalEntryCount + line.adjustmentEntryCount > 0
    && line.feeRates.length > 0
    && line.ruleVersions.length > 0;
}

function statementStatusLabel(status: string): string {
  return ({ GENERATING: "生成中", PENDING_CONFIRMATION: "待确认", CONFIRMED: "已确认", LOCKED: "已锁账" } as Record<string, string>)[status] ?? "未知状态";
}

function confirmationLabel(confirmation: BillingConfirmationSummary | null): string {
  if (!confirmation) return "待确认";
  return confirmation.confirmedAt
    ? `已确认 · ${formatDateTime(confirmation.confirmedAt)}`
    : "已确认";
}

function feeDirectionLabel(direction: FeeDirection): string {
  return direction === "PROMOTION" ? "推广服务费" : "管理服务费";
}

function lineDetailsHref(
  line: SettlementStatementLine,
  context: {
    statementId?: string;
    storeId: string;
    month: string;
    productScope: string;
    productType: string;
  },
): string {
  if (!isLineTraceable(line)) return "";
  const search = new URLSearchParams({ feeDirection: line.feeDirection, focus: "workbench" });
  line.feeRates.forEach((value) => search.append("feeRates", value));
  line.ruleVersions.forEach((value) => search.append("ruleVersions", value));
  if (context.statementId) {
    if (!line.statementLineId) return "";
    search.set("statementId", context.statementId);
    search.set("statementLineId", line.statementLineId);
  } else {
    search.set("storeId", context.storeId);
    search.set("month", context.month);
    search.set("productScope", line.productScope || context.productScope);
    search.set("productType", line.productType || context.productType);
  }
  return `/details?${search.toString()}`;
}

export function StoreSettlementPage({ searchParams }: StoreSettlementPageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const [storeId, setStoreId] = useState(
    searchParams.get("storeId") ?? searchParams.get("store_id") ?? "",
  );
  const [productScope, setProductScope] = useState(
    searchParams.get("productScope") ?? searchParams.get("product_scope") ?? "all",
  );
  const [productType, setProductType] = useState(
    searchParams.get("productType") ?? searchParams.get("product_type") ?? "",
  );
  const [confirmationDirection, setConfirmationDirection] = useState<FeeDirection | null>(null);
  const [pendingDirection, setPendingDirection] = useState<FeeDirection | null>(null);
  const [confirmationMessage, setConfirmationMessage] = useState("");
  const [confirmationState, setConfirmationState] = useState<"idle" | "success" | "error">("idle");
  const [invalidatedStatementKey, setInvalidatedStatementKey] = useState<string | null>(null);
  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const meta = metaResource.data?.data;
  const activeMonth = month || meta?.statementMonths[0] || "";
  const activeStoreId = storeId || meta?.stores[0]?.storeId || "";
  const activeProductType = productType || meta?.defaultProductType || "all";
  const productTypes = useMemo(() => {
    const scoped = meta?.productScopeTypeMap[productScope];
    return ["all", ...(scoped ?? meta?.productTypes ?? []).filter((item) => item !== "all")];
  }, [meta, productScope]);
  const settlementResource = useApiResource(
    () => fetchSettlementMonthly({
            storeId: activeStoreId,
            month: activeMonth,
            productScope,
            productType: activeProductType,
          }),
    [activeStoreId, activeMonth, productScope, activeProductType],
    { enabled: Boolean(meta && activeStoreId && activeMonth) },
  );
  const billingResource = useApiResource(
    () => fetchStoreBillingStatements({
      storeId: activeStoreId,
      month: activeMonth,
      metricScope: "MONTH",
      page: 1,
      pageSize: 1,
    }),
    [activeStoreId, activeMonth],
    { enabled: Boolean(meta && activeStoreId && activeMonth) },
  );
  const view = settlementResource.data?.data;
  const metrics = view?.metrics;
  const metaError = metaResource.rawError ? apiErrorText(metaResource.rawError, "筛选条件暂不可用，请稍后重试。") : metaResource.error;
  const settlementError = settlementResource.rawError ? apiErrorText(settlementResource.rawError, "门店分账暂不可用，请稍后重试。", { 403: "当前账号没有查看该门店分账的权限。", 404: "未找到该门店或账期。", 422: "门店分账筛选条件不合法，请重新选择。" }) : settlementResource.error;
  const billingError = billingResource.rawError ? apiErrorText(billingResource.rawError, "当前账单暂不可用，请稍后重试。", { 403: "当前账号没有查看该门店账单的权限。", 404: "未找到该门店或账期。", 422: "账单筛选条件不合法，请重新选择。" }) : billingResource.error;
  const statementCandidate = billingResource.data?.data.list[0];
  const statementCandidateKey = statementCandidate
    ? `${statementCandidate.statementId}:${statementCandidate.versionNo}`
    : null;
  const statement = statementCandidate
    && statementCandidate.storeId === activeStoreId
    && statementCandidate.month === activeMonth
    && statementCandidateKey !== invalidatedStatementKey
    && !billingResource.loading
    && !billingResource.refreshing
    && !billingError
    ? statementCandidate
    : undefined;

  const submitConfirmation = async () => {
    const direction = confirmationDirection;
    if (!direction || !statement?.isCurrent) return;
    const amount = direction === "PROMOTION"
      ? statement.promotionConfirmableAmountCent
      : statement.managementConfirmableAmountCent;

    setPendingDirection(direction);
    setConfirmationMessage("");
    setConfirmationState("idle");
    try {
      await confirmStoreBillingStatement(
        statement.statementId,
        {
          feeDirection: direction,
          confirmedAmountCent: amount,
          readVersion: statement.versionNo,
        },
        crypto.randomUUID(),
      );
      setConfirmationMessage(`${feeDirectionLabel(direction)}已确认，正在读取最新账单。`);
      setConfirmationState("success");
      setConfirmationDirection(null);
      await billingResource.reload();
    } catch (error) {
      const conflict = error instanceof ApiRequestError && error.status === 409;
      if (conflict) {
        setInvalidatedStatementKey(`${statement.statementId}:${statement.versionNo}`);
        setConfirmationDirection(null);
        billingResource.reload();
      }
      setConfirmationMessage(userFacingError(error, "确认失败，请刷新当前账单后重试。"));
      setConfirmationState("error");
    } finally {
      setPendingDirection(null);
    }
  };

  const columns: Column<SettlementStatementLine>[] = [
    { key: "product", title: "商品", minWidth: 160, render: (line) => `${line.productScope} / ${line.productType}` },
    { key: "count", title: "原始 / 调整", align: "right", render: (line) => `${formatInteger(line.originalEntryCount)} / ${formatInteger(line.adjustmentEntryCount)}` },
    { key: "originalBase", title: "原始基数", align: "right", render: (line) => formatCurrency(line.originalBaseCent) },
    { key: "adjustmentBase", title: "调整基数", align: "right", render: (line) => formatCurrency(line.adjustmentBaseCent) },
    { key: "netBase", title: "基数净额", align: "right", render: (line) => formatCurrency(line.netBaseCent) },
    { key: "rate", title: "实际费率范围 / 集合", align: "right", minWidth: 240, render: (line) => rateLabel(line) },
    { key: "original", title: "原始费用", align: "right", render: (line) => formatCurrency(line.originalFeeCent) },
    { key: "adjustment", title: "调整费用", align: "right", render: (line) => formatCurrency(line.adjustmentFeeCent) },
    { key: "net", title: "调整后净额", align: "right", render: (line) => formatCurrency(line.netFeeCent) },
    { key: "versions", title: "规则版本", minWidth: 170, render: (line) => line.ruleVersions.length > 1 ? `${line.ruleVersions.join("、")}（共 ${line.ruleVersionCount} 个）` : (line.ruleVersions[0] ?? "版本不可用") },
    { key: "traceability", title: "追溯状态", minWidth: 150, render: (line) => isLineTraceable(line) && (!view?.statement || Boolean(line.statementLineId)) ? "可下钻订单" : "缺少来源、费率、版本或账单行" },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div><p className="eyebrow">门店结算</p><h1>单店分账</h1><p>经营、推广服务费与管理服务费使用同一账期上下文。</p></div>
      </section>
      <ResourceNotice loading={metaResource.loading || settlementResource.loading || billingResource.loading} error={metaError ?? settlementError ?? billingError} />
      <FilterBar>
        <SelectField disabled={!meta} label="账期" value={activeMonth} onChange={setMonth} options={(meta?.statementMonths ?? []).map((value) => ({ value, label: value }))} />
        <FilterField label="门店"><SearchableStoreSelect disabled={!meta} value={activeStoreId} onChange={setStoreId} options={(meta?.stores ?? []).map((store) => ({ value: store.storeId, label: store.storeName }))} /></FilterField>
        <SelectField disabled={!meta} label="产品范围" value={productScope} onChange={(value) => { setProductScope(value); setProductType("all"); }} options={(meta?.productScopes ?? []).map((value) => ({ value, label: value === "all" ? "全部产品" : value }))} />
        <SelectField disabled={!meta} label="商品类型" value={activeProductType} onChange={setProductType} options={productTypes.map((value) => ({ value, label: value === "all" ? "全部类型" : value }))} />
      </FilterBar>
      {!view && settlementResource.loading ? <ResourcePanel>正在加载门店分账…</ResourcePanel> : !view ? <ResourcePanel tone="error">门店分账暂不可用，请检查权限或账期。</ResourcePanel> : (
        <>
          <section className="settlement-context-banner" aria-label="账单状态">
            <div><strong>{view.store.storeName}</strong><span>{view.month} · {view.isFormalPeriod ? "正式账期" : "测试账期"}</span></div>
            <span className="source-pill">{view.statement?.statementStatus === "LOCKED" ? "已锁账 · 冻结账单口径" : view.statement ? `${statementStatusLabel(view.statement.statementStatus)} · 已生成账单口径` : "未生成账单 · 预览口径"}</span>
          </section>
          <section className="metric-grid metric-grid--three">
            <MetricCard label="销售金额" value={formatCurrency(metrics?.salesAmountCent ?? 0)} meta={`${formatInteger(metrics?.salesOrderCount ?? 0)} 笔订单`} />
            <MetricCard label="核销金额" value={formatCurrency(metrics?.verifiedAmountCent ?? 0)} meta={`${formatInteger(metrics?.verifiedOrderCount ?? 0)} 笔核销`} />
            <MetricCard label="推广服务费净额" value={formatCurrency(metrics?.promotionNetFeeCent ?? 0)} meta={`原始 ${formatCurrency(metrics?.promotionOriginalFeeCent ?? 0)} · 调整 ${formatCurrency(metrics?.promotionAdjustmentFeeCent ?? 0)}`} />
            <MetricCard label="管理服务费净额" value={formatCurrency(metrics?.managementNetFeeCent ?? 0)} meta={`原始 ${formatCurrency(metrics?.managementOriginalFeeCent ?? 0)} · 调整 ${formatCurrency(metrics?.managementAdjustmentFeeCent ?? 0)}`} />
            <MetricCard label="结算参考净额" value={formatCurrency(metrics?.netSettlementReferenceCent ?? 0)} meta="推广费减管理费" />
          </section>
          <section className="content-section" aria-label="账单确认与异议">
            <div className="section-title">
              <div>
                <h2>当前账单确认</h2>
                <p>按费用方向分别确认；金额和版本始终以当前账单为准。</p>
              </div>
            </div>
            {statement?.isCurrent ? (
              <>
                {(["PROMOTION", "MANAGEMENT"] as const).map((direction) => {
                  const confirmation = direction === "PROMOTION"
                    ? statement.promotionConfirmation
                    : statement.managementConfirmation;
                  const amount = direction === "PROMOTION"
                    ? statement.promotionConfirmableAmountCent
                    : statement.managementConfirmableAmountCent;
                  return (
                    <div className="section-title" key={direction}>
                      <div>
                        <h3>{feeDirectionLabel(direction)}</h3>
                        <p>{confirmationLabel(confirmation)} · 当前金额 {formatCurrency(amount)}</p>
                      </div>
                      {confirmation ? <span role="status">已确认</span> : (
                        <Button
                          disabled={pendingDirection !== null}
                          loading={pendingDirection === direction}
                          onClick={() => {
                            setConfirmationMessage("");
                            setConfirmationState("idle");
                            setConfirmationDirection(direction);
                          }}
                          size="sm"
                          variant="primary"
                        >
                          确认{feeDirectionLabel(direction)}
                        </Button>
                      )}
                    </div>
                  );
                })}
                {confirmationMessage ? <p role={confirmationState === "error" ? "alert" : "status"}>{confirmationMessage}</p> : null}
                <div className="section-title">
                  <div>
                    <h3>账单异议</h3>
                    <p>证据上传能力尚未接入（DYDATA-82），暂不能提交账单异议。</p>
                  </div>
                  <Button disabled size="sm">异议提交暂不可用</Button>
                </div>
              </>
            ) : (
              <ResourcePanel>当前未生成可确认账单，页面保留预览数据；生成当前账单后才能确认费用方向。</ResourcePanel>
            )}
          </section>
          {(["PROMOTION", "MANAGEMENT"] as const).map((direction) => {
            const directionLines = view.lines.filter((line) => line.feeDirection === direction);
            return (
              <section className="content-section" key={direction}>
                <div className="section-title"><div><h2>{direction === "PROMOTION" ? "推广服务费" : "管理服务费"}</h2><p>展示原始、调整与净额；多费率按实际集合展示，不计算平均费率。</p></div></div>
                {directionLines.length ? <DataTable columns={columns} rows={directionLines} rowHref={(line) => lineDetailsHref(line, { statementId: view.statement?.statementId, storeId: view.store.storeId, month: view.month, productScope: view.productScope, productType: view.productType }) || undefined} /> : <ResourcePanel>当前筛选下没有{direction === "PROMOTION" ? "推广服务费" : "管理服务费"}汇总行。</ResourcePanel>}
              </section>
            );
          })}
          <Dialog
            actions={
              <>
                <Button disabled={pendingDirection !== null} onClick={() => setConfirmationDirection(null)} variant="secondary">返回查看</Button>
                <Button loading={pendingDirection === confirmationDirection} onClick={() => void submitConfirmation()} variant="primary">确认提交</Button>
              </>
            }
            closeDisabled={pendingDirection !== null}
            description="提交后将按当前账单版本确认对应费用方向，并立即刷新账单状态。"
            onClose={() => setConfirmationDirection(null)}
            open={confirmationDirection !== null}
            title={`确认${confirmationDirection ? feeDirectionLabel(confirmationDirection) : "账单"}`}
          >
            <p>请确认当前账单金额与费用方向无误后再提交。</p>
          </Dialog>
        </>
      )}
    </div>
  );
}
