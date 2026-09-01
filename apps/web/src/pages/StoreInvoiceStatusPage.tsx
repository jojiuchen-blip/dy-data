import { useState } from "react";
import {
  createPromotionInvoiceLifecycleEvent,
  fetchPromotionInvoiceDetail,
  fetchPromotionInvoiceReplacementCandidates,
  fetchSettlementFilterMeta,
  fetchStoreInvoiceStatus,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type {
  AdminUser,
  PromotionInvoiceDetail,
  PromotionInvoiceLifecycleEventType,
  PromotionInvoiceReplacementCandidate,
  StoreInvoiceDifferenceRow,
  StoreInvoiceStatusMetricData,
  StoreManagementInvoiceStatusRow,
  StorePromotionInvoiceStatusRow,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";
import { displayFinanceInvoiceStatus } from "../utils/userFacingLabels";

interface StoreInvoiceStatusPageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
}

const INVOICE_PAGE_SIZE = 20;
const REPLACEMENT_CONTEXT_STORAGE_PREFIX = "dydata19-promotion-replacement";

interface ReplacementContext {
  storeId: string;
  invoiceId: string;
  invoiceNumber: string;
  eventType: PromotionInvoiceLifecycleEventType;
  reason: string;
  releasedStatementMonths: string[];
}

const displayAmount = (metrics: StoreInvoiceStatusMetricData | null | undefined, key: keyof StoreInvoiceStatusMetricData) =>
  metrics?.hasData ? formatCurrency(metrics[key] as number) : "暂无数据";

function displayPromotionInvoiceRecordStatus(status: string): string {
  switch (status) {
    case "SUBMITTED_PENDING_FACTORY_REVIEW":
      return "已登记";
    case "APPROVED_SETTLED":
      return "已结算";
    case "REJECTED_REUPLOAD":
      return "已退回";
    default:
      return "暂无数据";
  }
}

export function StoreInvoiceStatusPage({ currentUser, searchParams }: StoreInvoiceStatusPageProps) {
  const initialInvoiceNumber = searchParams.get("invoiceNumber") ?? "";
  const [invoiceNumberInput, setInvoiceNumberInput] = useState(initialInvoiceNumber);
  const [invoiceNumberQuery, setInvoiceNumberQuery] = useState(initialInvoiceNumber);
  const [invoiceSearchMessage, setInvoiceSearchMessage] = useState("");
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [invoicePage, setInvoicePage] = useState(1);
  const [lifecycleInvoiceId, setLifecycleInvoiceId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState("");

  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const meta = metaResource.data?.data;
  const activeStoreId = currentUser.store_ids[0] || meta?.stores[0]?.storeId || "";
  const activeMonth = meta?.statementMonths[0] || "";
  const normalizedInvoiceNumber = invoiceNumberQuery.trim();
  // An exact invoice-number query must search every authorized period; the
  // month filter is only sent for ordinary period browsing.
  const invoiceSearchMonth = normalizedInvoiceNumber ? undefined : activeMonth;
  const invoiceResource = useApiResource(
    () => fetchStoreInvoiceStatus({
      storeId: activeStoreId,
      month: invoiceSearchMonth,
      invoiceNumber: normalizedInvoiceNumber || undefined,
      page: invoicePage,
      pageSize: INVOICE_PAGE_SIZE,
    }),
    [activeStoreId, invoiceSearchMonth, normalizedInvoiceNumber, invoicePage],
    { enabled: Boolean(meta && activeStoreId) },
  );
  const detailResource = useApiResource(
    () => fetchPromotionInvoiceDetail(selectedInvoiceId ?? ""),
    [selectedInvoiceId],
    { enabled: Boolean(selectedInvoiceId) },
  );
  const replacementCandidateResource = useApiResource(
    () => fetchPromotionInvoiceReplacementCandidates(activeStoreId),
    [activeStoreId],
    { enabled: Boolean(meta && activeStoreId) },
  );
  const data = invoiceResource.data?.data;
  const metrics = data?.metrics;
  const promotionInvoices = data?.promotionInvoices ?? [];
  const managementInvoices = data?.managementInvoices ?? [];
  const differenceLedger = data?.differenceLedger ?? [];
  const replacementCandidates = replacementCandidateResource.data?.data.list ?? [];
  const replacementCandidateByInvoiceId = new Map(
    replacementCandidates.map((candidate) => [candidate.invoice.invoiceId, candidate]),
  );
  const metaError = metaResource.rawError ? apiErrorText(metaResource.rawError, "筛选条件暂不可用，请稍后重试。") : metaResource.error;
  const invoiceError = invoiceResource.rawError ? apiErrorText(invoiceResource.rawError, "发票状态暂不可用，请稍后重试。", { 403: "当前账号没有查看该门店发票的权限。", 422: "发票状态筛选条件不合法，请重新选择。" }) : invoiceResource.error;

  const applyInvoiceSearch = () => {
    const normalized = invoiceNumberInput.trim();
    if (normalized && !/^\d{20}$/.test(normalized)) {
      setInvoiceSearchMessage("请输入完整的 20 位数电专票号码。");
      return;
    }
    setInvoiceSearchMessage("");
    setInvoiceNumberQuery(normalized);
    setInvoicePage(1);
    setSelectedInvoiceId(null);
  };

  const replacementContextStorageKey = `${REPLACEMENT_CONTEXT_STORAGE_PREFIX}:${
    currentUser.user_id ?? currentUser.username
  }`;

  const openReplacement = (context: ReplacementContext) => {
    window.sessionStorage.setItem(
      replacementContextStorageKey,
      JSON.stringify(context),
    );
    window.location.assign(
      `/settlement/invoice?storeId=${encodeURIComponent(context.storeId)}`,
    );
  };

  const resumeReplacementCandidate = (
    candidate: PromotionInvoiceReplacementCandidate,
  ) => {
    openReplacement({
      storeId: candidate.invoice.storeId,
      invoiceId: candidate.invoice.invoiceId,
      invoiceNumber: candidate.invoice.invoiceNumber,
      eventType: candidate.lifecycleEvent.eventType,
      reason: candidate.lifecycleEvent.reason,
      releasedStatementMonths: candidate.releasedStatementMonths,
    });
  };

  const handleLifecycleEvent = async (
    invoice: StorePromotionInvoiceStatusRow,
    eventType: PromotionInvoiceLifecycleEventType,
  ) => {
    const actionLabel = eventType === "RED_FLUSHED" ? "红冲" : "作废";
    const reason = window.prompt(`请输入系统外${actionLabel}原因`);
    if (!reason?.trim()) return;
    if (!window.confirm(`确认该发票已在系统外完成${actionLabel}？系统只登记事实并释放全部账期。`)) {
      return;
    }
    setLifecycleInvoiceId(invoice.invoiceId);
    setActionMessage("");
    try {
      const result = await createPromotionInvoiceLifecycleEvent(
        invoice.invoiceId,
        {
          eventType,
          reason: reason.trim(),
          readVersion: invoice.versionNo,
        },
        crypto.randomUUID(),
      );
      const context: ReplacementContext = {
        storeId: invoice.storeId,
        invoiceId: invoice.invoiceId,
        invoiceNumber: invoice.invoiceNumber,
        eventType,
        reason: reason.trim(),
        releasedStatementMonths: result.data.releasedStatementMonths,
      };
      setActionMessage(`已登记系统外${actionLabel}事实；必须使用新发票号码覆盖账期后重新开票。`);
      openReplacement(context);
    } catch (error) {
      setActionMessage(apiErrorText(error, `${actionLabel}登记失败，请刷新后重试。`));
    } finally {
      setLifecycleInvoiceId(null);
    }
  };

  const promotionColumns: Column<StorePromotionInvoiceStatusRow>[] = [
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "number", title: "发票号码", minWidth: 210, render: (row) => row.invoiceNumber },
    { key: "invoiceStatus", title: "发票状态", render: (row) => displayPromotionInvoiceRecordStatus(row.status) },
    { key: "review", title: "审核结果", minWidth: 180, render: (row) => displayFinanceInvoiceStatus(row.status) },
    { key: "reason", title: "原因", minWidth: 180, render: (row) => row.rejectionReason ?? "暂无数据" },
    { key: "settlement", title: "结算归属", render: (row) => row.settlementBatchMonth || "暂无数据" },
    { key: "action", title: "操作", render: (row) => <Button onClick={() => setSelectedInvoiceId(row.invoiceId)} size="sm" variant={selectedInvoiceId === row.invoiceId ? "soft" : "secondary"}>查看详情</Button> },
  ];
  const managementColumns: Column<StoreManagementInvoiceStatusRow>[] = [
    { key: "service", title: "服务名称", render: () => "管理服务费" },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "number", title: "发票号码", minWidth: 210, render: (row) => row.invoiceNumber },
    { key: "date", title: "开票日期", render: (row) => row.invoiceDate || "暂无数据" },
    { key: "status", title: "发票状态", minWidth: 150, render: (row) => displayFinanceInvoiceStatus(row.status) },
  ];
  const differenceColumns: Column<StoreInvoiceDifferenceRow>[] = [
    { key: "source", title: "来源账期", render: (row) => row.sourceStatementMonth },
    { key: "reason", title: "差额原因", render: (row) => row.reason },
    { key: "amount", title: "差额金额", align: "right", render: (row) => formatCurrency(row.differenceAmountCent) },
    { key: "target", title: "目标账期", render: (row) => row.targetStatementMonth },
  ];
  const detail = detailResource.data?.data as PromotionInvoiceDetail | undefined;
  const latestStatus = detail?.statusEvents[detail.statusEvents.length - 1];
  const selectedRow = selectedInvoiceId
    ? promotionInvoices.find((row) => row.invoiceId === selectedInvoiceId)
    : undefined;
  const selectedReplacementCandidate = selectedInvoiceId
    ? replacementCandidateByInvoiceId.get(selectedInvoiceId)
    : undefined;

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div><p className="eyebrow">门店结算</p><h1>发票状态查看</h1></div>
      </section>
      <form className="store-finance-invoice-search" onSubmit={(event) => { event.preventDefault(); applyInvoiceSearch(); }}>
        <label className="ui-field">
          <span className="ui-field__label">发票号码</span>
          <FieldInput inputMode="numeric" maxLength={20} onChange={(event) => setInvoiceNumberInput(event.target.value.replace(/\D/g, ""))} placeholder="输入完整发票号码" value={invoiceNumberInput} />
        </label>
        <Button type="submit" variant="secondary">服务端精确查询</Button>
      </form>
      {invoiceSearchMessage ? <p className="store-finance-action-message" role="alert">{invoiceSearchMessage}</p> : null}
      <ResourceNotice error={metaError ?? invoiceError} loading={metaResource.loading || invoiceResource.loading} />

      <section className="metric-grid store-summary-metrics" aria-label="发票汇总">
        <MetricCard label="账单总额" value={displayAmount(metrics, "statementTotalCent")} />
        <MetricCard label="已确认金额" value={displayAmount(metrics, "confirmedAmountCent")} />
        <MetricCard label="已开票金额" value={displayAmount(metrics, "issuedAmountCent")} />
        <MetricCard label="审核通过/已结算金额" value={displayAmount(metrics, "approvedAmountCent")} />
        <MetricCard label="待开票金额" value={displayAmount(metrics, "pendingInvoiceAmountCent")} />
      </section>

      <section className="content-section">
        <div className="section-title"><div><h2>推广发票记录</h2><p>发票号码在服务端跨授权账期精确查询后分页。</p></div></div>
        <DataTable columns={promotionColumns} emptyText="暂无数据" rows={promotionInvoices} state={invoiceResource.loading ? "loading" : invoiceError ? "error" : "ready"} />
        {data ? <TablePagination loading={invoiceResource.loading} onPageChange={(nextPage) => { setInvoicePage(nextPage); setSelectedInvoiceId(null); }} page={data.page} pageSize={data.pageSize} rowsOnPage={promotionInvoices.length} total={data.promotionTotal} totalPages={Math.max(1, Math.ceil(data.promotionTotal / data.pageSize))} /> : null}
      </section>
      <section className="content-section">
        <div className="section-title"><div><h2>管理服务费发票信息</h2><p>无正式记录时显示暂无数据。</p></div></div>
        <DataTable columns={managementColumns} emptyText="暂无数据" rows={managementInvoices} state={invoiceResource.loading ? "loading" : invoiceError ? "error" : "ready"} />
      </section>
      <section className="content-section">
        <div className="section-title"><div><h2>差额台账</h2><p>仅展示正式接口返回的管理服务费结转抵扣记录。</p></div></div>
        <DataTable columns={differenceColumns} emptyText="暂无数据" rows={differenceLedger} state={invoiceResource.loading ? "loading" : invoiceError ? "error" : "ready"} />
      </section>
      {selectedInvoiceId ? <section className="content-section store-finance-status-detail" aria-label="发票审核详情">
        <div className="section-title"><div><h2>审核详情</h2><p>发票状态事件和账期分配来自真实接口。</p></div></div>
        {detailResource.loading ? <ResourcePanel>正在加载发票详情…</ResourcePanel> : !detail ? <ResourcePanel>暂无数据</ResourcePanel> : <>
          <div className="store-finance-status-detail__grid"><dl><div><dt>发票号码</dt><dd>{detail.invoiceNumber}</dd></div><div><dt>审核状态</dt><dd>{displayFinanceInvoiceStatus(detail.status)}</dd></div><div><dt>发票金额</dt><dd>{formatCurrency(detail.invoiceAmountCent)}</dd></div><div><dt>登记时间</dt><dd>{formatDateTime(detail.registeredAt)}</dd></div><div><dt>最近回传</dt><dd>{latestStatus ? formatDateTime(latestStatus.occurredAt) : "暂无数据"}</dd></div><div><dt>审核原因</dt><dd>{detail.status === "REJECTED_REUPLOAD" ? (latestStatus?.resultReason ?? selectedRow?.rejectionReason ?? "暂无数据") : "当前状态无需补充审核原因"}</dd></div></dl><div><h3>结算账期分配</h3>{detail.allocations.length ? <ul>{detail.allocations.map((allocation) => <li key={allocation.allocationId}>{allocation.statementMonth} · {formatCurrency(allocation.allocatedAmountCent)} · 结算归属月 {allocation.settlementBatchMonth}</li>)}</ul> : <p>暂无数据</p>}</div></div>
          {detail.status === "REJECTED_REUPLOAD" ? <div className="store-finance-status-detail__actions">
            {selectedReplacementCandidate ? <Button onClick={() => resumeReplacementCandidate(selectedReplacementCandidate)} size="sm" variant="primary">重新开票</Button> : <>
              <Button disabled={lifecycleInvoiceId === detail.invoiceId} loading={lifecycleInvoiceId === detail.invoiceId} onClick={() => selectedRow && void handleLifecycleEvent(selectedRow, "RED_FLUSHED")} size="sm" variant="secondary">登记红冲</Button>
              <Button disabled={lifecycleInvoiceId === detail.invoiceId} loading={lifecycleInvoiceId === detail.invoiceId} onClick={() => selectedRow && void handleLifecycleEvent(selectedRow, "VOIDED")} size="sm" variant="secondary">登记作废</Button>
            </>}
          </div> : null}
        </>}
      </section> : null}
      {actionMessage ? <p role="status">{actionMessage}</p> : null}
    </div>
  );
}
