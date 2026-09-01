import { useState } from "react";
import {
  ApiRequestError,
  confirmStoreBillingStatement,
  fetchOrderFeeDetails,
  fetchSettlementFilterMeta,
  fetchSettlementMonthly,
  fetchStoreBillingDisputes,
  fetchStoreBillingStatements,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { FilterBar, FilterField } from "../components/Filters";
import { FieldInput, FieldTextarea, SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  AdminUser,
  BillingConfirmationSummary,
  FeeDirection,
  OrderFeeDetailRow,
  StoreDisputeType,
} from "../types/dashboard";
import { formatCurrency, formatDateTime, formatInteger } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";
import { userFacingError } from "../utils/userFacingError";
import { displayFinanceSaleChannel } from "../utils/userFacingLabels";

interface StoreSettlementPageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
}

const FEE_DIRECTIONS: readonly FeeDirection[] = ["PROMOTION", "MANAGEMENT"];
const DISPUTE_TYPES: Array<{ value: StoreDisputeType; label: string }> = [
  { value: "RATE_ERROR", label: "费率错误" },
  { value: "DATA_MISSING", label: "订单/数据遗漏" },
  { value: "AMOUNT_ERROR", label: "金额错误" },
  { value: "OTHER", label: "其他" },
];

const displayMetricCurrency = (value: number | undefined) =>
  value === undefined ? "暂无数据" : formatCurrency(value);
const displayMetricCount = (value: number | undefined, unit: string) =>
  value === undefined ? "暂无数据" : `${formatInteger(value)} ${unit}`;

function feeDirectionLabel(direction: FeeDirection): string {
  return direction === "PROMOTION" ? "推广服务费" : "管理服务费";
}

function confirmationLabel(confirmation: BillingConfirmationSummary | null): string {
  if (!confirmation) return "待确认";
  return confirmation.confirmedAt
    ? `已确认 · ${formatDateTime(confirmation.confirmedAt)}`
    : "已确认";
}

export function StoreSettlementPage({ currentUser, searchParams }: StoreSettlementPageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const requestedStoreId = searchParams.get("storeId") ?? searchParams.get("store_id") ?? "";
  const [storeId, setStoreId] = useState(requestedStoreId);
  const [activeFeeDirection, setActiveFeeDirection] = useState<FeeDirection>("PROMOTION");
  const [confirmationDirection, setConfirmationDirection] = useState<FeeDirection | null>(null);
  const [pendingDirection, setPendingDirection] = useState<FeeDirection | null>(null);
  const [confirmationMessage, setConfirmationMessage] = useState("");
  const [confirmationState, setConfirmationState] = useState<"idle" | "success" | "error">("idle");
  const [invalidatedStatementKey, setInvalidatedStatementKey] = useState<string | null>(null);
  const [disputeConfirmationOpen, setDisputeConfirmationOpen] = useState(false);
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeType, setDisputeType] = useState<StoreDisputeType>("RATE_ERROR");
  const [disputeAmount, setDisputeAmount] = useState("");
  const [disputeOrders, setDisputeOrders] = useState("");
  const [disputeContactName, setDisputeContactName] = useState("");
  const [disputeContactPhone, setDisputeContactPhone] = useState("");
  const [disputeDescription, setDisputeDescription] = useState("");

  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const meta = metaResource.data?.data;
  const activeMonth = month || meta?.statementMonths[0] || "";
  const accountStoreIds = new Set(currentUser.store_ids);
  const storeOptions = (meta?.stores ?? []).filter(
    (store) => currentUser.role !== "store" || accountStoreIds.has(store.storeId),
  );
  const activeStoreId = currentUser.role === "store"
    ? (accountStoreIds.has(storeId) ? storeId : currentUser.store_ids[0] ?? "")
    : storeId || storeOptions[0]?.storeId || "";
  const productScope = searchParams.get("productScope") ?? "all";
  const activeProductType = searchParams.get("productType") ?? meta?.defaultProductType ?? "all";

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
  const cumulativeBillingResource = useApiResource(
    () => fetchStoreBillingStatements({
      storeId: activeStoreId,
      month: activeMonth,
      metricScope: "CUMULATIVE",
      page: 1,
      pageSize: 1,
    }),
    [activeStoreId, activeMonth],
    { enabled: Boolean(meta && activeStoreId && activeMonth) },
  );
  const promotionOrderResource = useApiResource(
    () => fetchOrderFeeDetails({
      storeId: activeStoreId,
      month: activeMonth,
      feeDirection: "PROMOTION",
      productScope,
      productType: activeProductType,
      page: 1,
      pageSize: 50,
    }),
    [activeStoreId, activeMonth, productScope, activeProductType],
    { enabled: Boolean(meta && activeStoreId && activeMonth) },
  );
  const managementOrderResource = useApiResource(
    () => fetchOrderFeeDetails({
      storeId: activeStoreId,
      month: activeMonth,
      feeDirection: "MANAGEMENT",
      productScope,
      productType: activeProductType,
      page: 1,
      pageSize: 50,
    }),
    [activeStoreId, activeMonth, productScope, activeProductType],
    { enabled: Boolean(meta && activeStoreId && activeMonth) },
  );

  const view = settlementResource.data?.data;
  const metrics = view?.metrics;
  const billingMetrics = cumulativeBillingResource.data?.data.metrics;
  const metaError = metaResource.rawError
    ? apiErrorText(metaResource.rawError, "筛选条件暂不可用，请稍后重试。")
    : metaResource.error;
  const settlementError = settlementResource.rawError
    ? apiErrorText(settlementResource.rawError, "门店分账暂不可用，请稍后重试。", {
      403: "当前账号没有查看该门店分账的权限。",
      404: "未找到该门店或账期。",
      422: "门店分账筛选条件不合法，请重新选择。",
    })
    : settlementResource.error;
  const billingError = billingResource.rawError
    ? apiErrorText(billingResource.rawError, "当前账单暂不可用，请稍后重试。", {
      403: "当前账号没有查看该门店账单的权限。",
      404: "未找到该门店或账期。",
      422: "账单筛选条件不合法，请重新选择。",
    })
    : billingResource.error;
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
  const disputeResource = useApiResource(
    () => fetchStoreBillingDisputes(statement?.statementId ?? ""),
    [statement?.statementId],
    { enabled: Boolean(statement?.statementId) },
  );

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
        { feeDirection: direction, confirmedAmountCent: amount, readVersion: statement.versionNo },
        crypto.randomUUID(),
      );
      setConfirmationMessage(`${feeDirectionLabel(direction)}已确认，正在读取最新账单。`);
      setConfirmationState("success");
      setConfirmationDirection(null);
      await billingResource.reload();
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) {
        setInvalidatedStatementKey(`${statement.statementId}:${statement.versionNo}`);
        setConfirmationDirection(null);
        void billingResource.reload();
      }
      setConfirmationMessage(userFacingError(error, "确认失败，请刷新当前账单后重试。"));
      setConfirmationState("error");
    } finally {
      setPendingDirection(null);
    }
  };

  const orderColumns: Column<OrderFeeDetailRow>[] = [
    { key: "order", title: "订单号", minWidth: 170, render: (row) => row.orderId },
    { key: "product", title: "商品", minWidth: 180, render: (row) => row.productName || row.skuName || row.skuId },
    { key: "channel", title: "销售渠道", render: (row) => displayFinanceSaleChannel(row.saleChannel) },
    { key: "verifiedAt", title: "核销时间", minWidth: 170, render: (row) => row.verifyTime ? formatDateTime(row.verifyTime) : "尚未核销" },
    { key: "sourceAmount", title: "实收金额", align: "right", render: (row) => formatCurrency(row.sourceAmountCent) },
    { key: "rate", title: "实际费率", align: "right", render: (row) => `${(Number(row.feeRate) * 100).toFixed(2).replace(/\.00$/, "")}%` },
    { key: "fee", title: "服务费", align: "right", render: (row) => formatCurrency(row.adjustedNetFeeCent) },
  ];
  const activeOrderResource = activeFeeDirection === "PROMOTION"
    ? promotionOrderResource
    : managementOrderResource;
  const activeOrders = activeOrderResource.data?.data.list ?? [];

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">门店结算</p>
          <h1>单店分账</h1>
          <p>推广服务费与管理服务费按同一门店、账期分别确认。</p>
        </div>
      </section>
      <ResourceNotice
        loading={metaResource.loading || settlementResource.loading || billingResource.loading || cumulativeBillingResource.loading}
        error={metaError ?? settlementError ?? billingError}
      />
      <FilterBar>
        <SelectField
          disabled={!meta}
          label="账期"
          value={activeMonth}
          onChange={(value) => { setMonth(value); setInvalidatedStatementKey(null); }}
          options={(meta?.statementMonths ?? []).map((value) => ({ value, label: value }))}
        />
        <FilterField label="门店">
          <SearchableStoreSelect
            disabled={!meta || currentUser.role === "store"}
            value={activeStoreId}
            onChange={(value) => { setStoreId(value); setInvalidatedStatementKey(null); }}
            options={storeOptions.map((store) => ({ value: store.storeId, label: store.storeName }))}
          />
        </FilterField>
      </FilterBar>

      <section className="metric-grid store-summary-metrics" aria-label="分账指标">
            <MetricCard label="销售金额" value={displayMetricCurrency(metrics?.salesAmountCent)} meta={displayMetricCount(metrics?.salesOrderCount, "笔订单")} />
            <MetricCard label="核销金额" value={displayMetricCurrency(metrics?.verifiedAmountCent)} meta={displayMetricCount(metrics?.verifiedOrderCount, "笔核销")} />
            <MetricCard label="当期推广服务费" value={displayMetricCurrency(metrics?.promotionNetFeeCent)} meta={metrics ? `原始 ${formatCurrency(metrics.promotionOriginalFeeCent)} · 调整 ${formatCurrency(metrics.promotionAdjustmentFeeCent)}` : "暂无数据"} />
            <MetricCard label="累计推广服务费" value={displayMetricCurrency(billingMetrics?.cumulative?.promotionAmountCent)} meta={billingMetrics?.cumulative ? "正式账期累计" : "暂无数据"} />
            <MetricCard label="当期管理服务费" value={displayMetricCurrency(metrics?.managementNetFeeCent)} meta={metrics ? `原始 ${formatCurrency(metrics.managementOriginalFeeCent)} · 调整 ${formatCurrency(metrics.managementAdjustmentFeeCent)}` : "暂无数据"} />
            <MetricCard label="累计管理服务费" value={displayMetricCurrency(billingMetrics?.cumulative?.managementAmountCent)} meta={billingMetrics?.cumulative ? "正式账期累计" : "暂无数据"} />
      </section>

      <section className="content-section" aria-label="账单确认与异议">
            <div className="section-title">
              <div>
                <h2>当前账单确认</h2>
                <p>推广服务费和管理服务费分别确认；金额与版本以正式账单接口为准。</p>
              </div>
            </div>
            <div className="store-finance-confirmation-grid">
              {FEE_DIRECTIONS.map((direction) => {
                const confirmation = direction === "PROMOTION" ? statement?.promotionConfirmation : statement?.managementConfirmation;
                const amount = direction === "PROMOTION" ? statement?.promotionConfirmableAmountCent : statement?.managementConfirmableAmountCent;
                const canConfirm = Boolean(statement?.isCurrent && amount !== undefined && !confirmation);
                return (
                  <article className="store-finance-direction-card" key={direction}>
                    <div>
                      <p className="eyebrow">费用方向</p>
                      <h3>{feeDirectionLabel(direction)}确认</h3>
                      <p className="store-finance-direction-card__status">{statement ? confirmationLabel(confirmation ?? null) : "尚未生成"}</p>
                      <strong>{amount === undefined ? "尚未生成" : formatCurrency(amount)}</strong>
                    </div>
                    <div className="store-finance-direction-card__actions">
                      {confirmation ? <span className="status-badge status-badge--success">已确认</span> : (
                        <Button
                          disabled={!canConfirm || pendingDirection !== null}
                          loading={pendingDirection === direction}
                          onClick={() => { setConfirmationMessage(""); setConfirmationState("idle"); setConfirmationDirection(direction); }}
                          size="sm"
                          variant="primary"
                        >
                          {statement ? `确认${feeDirectionLabel(direction)}` : "尚未生成"}
                        </Button>
                      )}
                      {direction === "PROMOTION" && confirmation && statement ? (
                        <a className="ui-button ui-button--secondary ui-button--sm" href={`/settlement/invoice?storeId=${encodeURIComponent(activeStoreId)}&month=${encodeURIComponent(activeMonth)}`}>
                          进入推广费开票
                        </a>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
            {confirmationMessage ? <p className="store-finance-action-message" role={confirmationState === "error" ? "alert" : "status"}>{confirmationMessage}</p> : null}
      </section>

      <section className="content-section store-finance-fee-details" aria-label="费用明细">
            <div className="section-title">
              <div><h2>费用明细</h2><p>推广费明细和管理费明细均来自正式订单费用接口。</p></div>
            </div>
            <div className="store-finance-fee-tabs" role="tablist" aria-label="费用明细类型">
              {FEE_DIRECTIONS.map((direction) => (
                <Button
                  aria-selected={activeFeeDirection === direction}
                  className={activeFeeDirection === direction ? "is-active" : ""}
                  key={direction}
                  onClick={() => setActiveFeeDirection(direction)}
                  role="tab"
                  size="sm"
                  type="button"
                  variant={activeFeeDirection === direction ? "primary" : "secondary"}
                >
                  {direction === "PROMOTION" ? "推广费明细" : "管理费明细"}
                </Button>
              ))}
            </div>
            <div className="store-finance-fee-tabpanel" role="tabpanel">
              <ResourceNotice loading={activeOrderResource.loading} error={activeOrderResource.error} />
              {activeOrders.length ? <DataTable columns={orderColumns} rows={activeOrders} /> : <ResourcePanel>暂无数据</ResourcePanel>}
            </div>
      </section>

      <section className="store-finance-dispute-entry" aria-label="账单异议">
            <span className="store-finance-dispute-entry__label">账单异议</span>
            <span className="store-finance-dispute-entry__empty">
              {statement?.isCurrent ? "如需核对账单，可发起异议" : "暂无可发起的账单异议"}
            </span>
            <Button className="store-finance-dispute-entry__trigger" onClick={() => setDisputeConfirmationOpen(true)} size="sm" variant="text">
              发起账单异议
            </Button>
      </section>

          {disputeResource.data?.data.list.length ? (
            <section className="content-section store-finance-dispute-list" aria-label="已提交账单异议">
              <div className="section-title"><div><h2>已提交账单异议</h2><p>仅展示当前账单的真实提交记录。</p></div></div>
              <ul>
                {disputeResource.data.data.list.map((item) => <li key={item.disputeId}>{item.statementMonth} · {feeDirectionLabel(item.feeDirection)} · {item.status} · {formatCurrency(item.disputedAmountCent)}</li>)}
              </ul>
            </section>
          ) : null}

      <Dialog
            actions={<><Button disabled={pendingDirection !== null} onClick={() => setConfirmationDirection(null)} variant="secondary">返回查看</Button><Button loading={pendingDirection === confirmationDirection} onClick={() => void submitConfirmation()} variant="primary">确认提交</Button></>}
            closeDisabled={pendingDirection !== null}
            description="提交后将按当前账单版本确认对应费用方向，并立即刷新账单状态。"
            onClose={() => setConfirmationDirection(null)}
            open={confirmationDirection !== null}
            title={`确认${confirmationDirection ? feeDirectionLabel(confirmationDirection) : "账单"}`}
          >
            <p>请确认当前账单金额与费用方向无误后再提交。</p>
          </Dialog>

      <Dialog
            actions={<><Button onClick={() => setDisputeConfirmationOpen(false)} variant="secondary">取消</Button><Button onClick={() => { setDisputeConfirmationOpen(false); setDisputeOpen(true); }} variant="primary">确认发起</Button></>}
            description="异议入口默认收起，确认后再填写异议资料。"
            onClose={() => setDisputeConfirmationOpen(false)}
            open={disputeConfirmationOpen}
            title="确认发起账单异议"
          >
            <p>发起异议前请准备充分资料，是否发起？</p>
          </Dialog>

      <Dialog
            actions={<><Button onClick={() => setDisputeOpen(false)} variant="secondary">取消</Button><Button disabled variant="primary">提交异议并开始检测</Button></>}
            description="金额和订单将按当前账单版本校验；证明材料受控上传开放后方可提交。"
            onClose={() => setDisputeOpen(false)}
            open={disputeOpen}
            panelClassName="store-finance-dispute-dialog"
            title="发起账单异议"
          >
            <div className="store-finance-dispute-form">
              <SelectField label="异议类型" onChange={(value) => setDisputeType(value as StoreDisputeType)} options={DISPUTE_TYPES} value={disputeType} />
              <div className="finance-form-grid">
                <SelectField
                  label="费用方向"
                  onChange={(value) => setActiveFeeDirection(value as FeeDirection)}
                  options={FEE_DIRECTIONS.map((value) => ({
                    label: feeDirectionLabel(value),
                    value,
                  }))}
                  value={activeFeeDirection}
                />
                <label className="ui-field"><span className="ui-field__label">争议金额（元）</span><FieldInput inputMode="decimal" value={disputeAmount} onChange={(event) => setDisputeAmount(event.target.value)} placeholder="最多三位小数" /></label>
                <label className="ui-field"><span className="ui-field__label">联系人</span><FieldInput value={disputeContactName} onChange={(event) => setDisputeContactName(event.target.value)} /></label>
                <label className="ui-field"><span className="ui-field__label">手机号</span><FieldInput inputMode="numeric" maxLength={11} value={disputeContactPhone} onChange={(event) => setDisputeContactPhone(event.target.value.replace(/\D/g, ""))} /></label>
              </div>
              <label className="ui-field"><span className="ui-field__label">争议订单</span><FieldTextarea value={disputeOrders} onChange={(event) => setDisputeOrders(event.target.value)} placeholder="每行填写：订单号,争议金额(元)；仅一条时可只填订单号" /></label>
              <label className="ui-field"><span className="ui-field__label">问题说明</span><FieldTextarea value={disputeDescription} onChange={(event) => setDisputeDescription(event.target.value)} /></label>
              <label className="ui-field"><span className="ui-field__label">证明材料</span><FieldInput aria-describedby="store-dispute-upload-status" disabled type="file" /></label>
              <p className="store-finance-action-message" id="store-dispute-upload-status" role="status">证明材料受控上传尚未开放，当前不能提交异议。</p>
            </div>
          </Dialog>
    </div>
  );
}
