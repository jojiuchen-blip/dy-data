import { useState } from "react";
import {
  ApiRequestError,
  correctManagementInvoice,
  downloadFinanceImportTemplate,
  downloadFinanceInvoices,
  fetchFinanceInvoices,
  fetchFinanceSummary,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FinanceImportActionPanel } from "../components/FinanceImportActionPanel";
import { SelectField, TextField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice } from "../components/ResourceState";
import { useApiResource } from "../hooks/useApiResource";
import type {
  BillingMetricScope,
  FeeDirection,
  FinanceInvoiceRow,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { displayFinanceInvoiceStatus } from "../utils/userFacingLabels";

interface FinanceFeePageProps {
  feeDirection: FeeDirection;
  searchParams: URLSearchParams;
}

type CorrectionDraft = {
  row: FinanceInvoiceRow;
  readVersion: number;
  invoiceNumber: string;
  invoiceDate: string;
  invoiceAmountCent: string;
  deductionDate: string;
  deductionAmountCent: string;
  changeReason: string;
  idempotencyKey: string;
};

function defaultStatementMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function currencyMetric(value: number | undefined): string {
  return typeof value === "number" ? formatCurrency(value) : "—";
}

function financeInvoiceStatusLabel(status: string, direction: FeeDirection): string {
  if (direction === "MANAGEMENT") {
    return ({
      PENDING_INVOICE: "待开票",
      APPROVED_SETTLED: "已开票 / 已扣款",
      REJECTED_REUPLOAD: "待重新导入",
    } as Record<string, string>)[status] ?? "未知发票 / 扣款状态";
  }
  return displayFinanceInvoiceStatus(status);
}

function managementCorrectionValidationError(correction: CorrectionDraft): string {
  if (!/^\d{20}$/.test(correction.invoiceNumber.trim())) {
    return "发票号码必须为 20 位数字。";
  }
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(correction.invoiceDate)
    || !/^\d{4}-\d{2}-\d{2}$/.test(correction.deductionDate)
  ) {
    return "发票日期和厂家扣款日期必须完整填写。";
  }
  const invoiceAmountCent = Number(correction.invoiceAmountCent);
  const deductionAmountCent = Number(correction.deductionAmountCent);
  if (
    !Number.isInteger(invoiceAmountCent)
    || invoiceAmountCent <= 0
    || !Number.isInteger(deductionAmountCent)
    || deductionAmountCent <= 0
    || invoiceAmountCent !== deductionAmountCent
  ) {
    return "发票金额与厂家扣款金额必须为相同的正整数分。";
  }
  const reason = correction.changeReason.trim();
  if (!reason) return "更正原因必填。";
  if (reason.length > 1000) return "更正原因不得超过 1000 字。";
  return "";
}

function navigateTo(href: string) {
  window.history.pushState(null, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

export function FinanceFeePage({ feeDirection, searchParams }: FinanceFeePageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? defaultStatementMonth());
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [invoiceStatus, setInvoiceStatus] = useState(searchParams.get("invoiceStatus") ?? "");
  const [metricScope, setMetricScope] = useState<BillingMetricScope>("MONTH");
  const [showImport, setShowImport] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [notice, setNotice] = useState("");
  const [noticeIsError, setNoticeIsError] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [correction, setCorrection] = useState<CorrectionDraft | null>(null);
  const [correctionState, setCorrectionState] = useState<"idle" | "loading" | "success" | "error" | "conflict">("idle");
  const [correctionMessage, setCorrectionMessage] = useState("");
  const correctionValidationError = correction
    ? managementCorrectionValidationError(correction)
    : "";
  const canSubmitCorrection = Boolean(
    correction && !correctionValidationError && correctionState !== "loading",
  );
  const title = feeDirection === "PROMOTION" ? "推广服务费" : "管理服务费";
  const importType = feeDirection === "PROMOTION"
    ? "PROMOTION_FACTORY_RESULT"
    : "MANAGEMENT_FACTORY_RESULT";

  const commonQuery = {
    month,
    feeDirection,
    metricScope,
    q: search.trim() || undefined,
    invoiceStatus: invoiceStatus || undefined,
  };
  const summaryResource = useApiResource(
    () => fetchFinanceSummary(commonQuery),
    [month, feeDirection, metricScope, search, invoiceStatus],
  );
  const invoiceResource = useApiResource(
    () => fetchFinanceInvoices({
      ...commonQuery,
      includeHistory: feeDirection === "MANAGEMENT" && showHistory,
      pageSize: 50,
    }),
    [month, feeDirection, metricScope, search, invoiceStatus, showHistory],
  );
  const metrics = summaryResource.data?.data.metrics;
  const rows = invoiceResource.data?.data.list ?? [];
  const resourceBusy = summaryResource.loading
    || summaryResource.refreshing
    || invoiceResource.loading
    || invoiceResource.refreshing;

  const openCorrection = (row: FinanceInvoiceRow) => {
    if (
      feeDirection !== "MANAGEMENT"
      || !row.invoiceId
      || !row.isCurrent
      || !row.invoiceNumber
      || !row.invoiceDate
      || row.invoiceAmountCent === null
      || row.versionNo === null
    ) return;
    setCorrection({
      row,
      readVersion: row.versionNo,
      invoiceNumber: row.invoiceNumber,
      invoiceDate: row.invoiceDate,
      invoiceAmountCent: String(row.invoiceAmountCent),
      deductionDate: row.factoryDeductionDate ?? row.invoiceDate,
      deductionAmountCent: String(row.factoryDeductionAmountCent ?? row.invoiceAmountCent),
      changeReason: "",
      idempotencyKey: crypto.randomUUID(),
    });
    setCorrectionState("idle");
    setCorrectionMessage("");
  };

  const updateCorrection = (updates: Partial<Omit<CorrectionDraft, "row" | "readVersion" | "idempotencyKey">>) => {
    setCorrection((current) => current ? {
      ...current,
      ...updates,
      idempotencyKey: crypto.randomUUID(),
    } : current);
  };

  const promotionColumns: Column<FinanceInvoiceRow>[] = [
    { key: "store", title: "门店", minWidth: 210, sticky: true, render: (row) => <span><strong>{row.storeName ?? row.storeId}</strong><br /><small>{row.storeId}</small></span> },
    { key: "sap", title: "有效 SAP", minWidth: 130, render: (row) => row.effectiveSapCode ?? "—" },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "total", title: "推广费总额", align: "right", render: (row) => formatCurrency(row.statementAmountCent) },
    { key: "confirmed", title: "已确认金额", align: "right", render: (row) => typeof row.confirmedAmountCent === "number" ? formatCurrency(row.confirmedAmountCent) : "—" },
    { key: "number", title: "数电专票号码", minWidth: 210, render: (row) => row.invoiceNumber ?? "—" },
    { key: "submitted", title: "提交成功时间", minWidth: 170, render: (row) => row.registeredAt ? formatDateTime(row.registeredAt) : "—" },
    { key: "settlementMonth", title: "结算归属月", render: (row) => row.settlementBatchMonth ?? "—" },
    { key: "status", title: "发票审核状态", minWidth: 170, render: (row) => financeInvoiceStatusLabel(row.status, feeDirection) },
    { key: "reason", title: "审核原因", minWidth: 220, render: (row) => row.rejectionReason ?? "—" },
  ];
  const managementColumns: Column<FinanceInvoiceRow>[] = [
    { key: "store", title: "门店", minWidth: 210, sticky: true, render: (row) => <span><strong>{row.storeName ?? row.storeId}</strong><br /><small>{row.storeId}</small></span> },
    { key: "sap", title: "有效 SAP", minWidth: 130, render: (row) => row.effectiveSapCode ?? "—" },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "total", title: "管理费总额", align: "right", render: (row) => formatCurrency(row.statementAmountCent) },
    { key: "confirmed", title: "已确认金额", align: "right", render: (row) => typeof row.confirmedAmountCent === "number" ? formatCurrency(row.confirmedAmountCent) : "—" },
    { key: "number", title: "发票号码", minWidth: 210, render: (row) => row.invoiceNumber ?? "—" },
    { key: "amount", title: "发票金额", align: "right", render: (row) => typeof row.invoiceAmountCent === "number" ? formatCurrency(row.invoiceAmountCent) : "—" },
    { key: "date", title: "开票时间", minWidth: 160, render: (row) => row.invoiceDate ?? "—" },
    { key: "status", title: "状态", minWidth: 160, render: (row) => financeInvoiceStatusLabel(row.status, feeDirection) },
  ];

  const handleTemplateDownload = async () => {
    setDownloadBusy(true);
    setNotice("");
    setNoticeIsError(false);
    try {
      await downloadFinanceImportTemplate(importType);
      setNotice("模板已下载，文件仅包含正式字段和填写说明。");
    } catch (error) {
      setNoticeIsError(true);
      setNotice(userFacingError(error, "模板下载失败，请稍后重试。"));
    } finally {
      setDownloadBusy(false);
    }
  };

  const handleExport = async () => {
    setExportBusy(true);
    setNotice("");
    setNoticeIsError(false);
    try {
      const result = await downloadFinanceInvoices(commonQuery);
      setNotice(result.result === "EMPTY" ? "当前筛选无记录，已下载仅含表头的文件。" : `已导出当前筛选结果：${result.fileName}`);
    } catch (error) {
      setNoticeIsError(true);
      setNotice(userFacingError(error, "导出失败，请稍后重试。"));
    } finally {
      setExportBusy(false);
    }
  };

  const resetFilters = () => {
    setMonth(defaultStatementMonth());
    setSearch("");
    setInvoiceStatus("");
    setMetricScope("MONTH");
  };

  const submitCorrection = async () => {
    if (!correction || managementCorrectionValidationError(correction)) return;
    setCorrectionState("loading");
    setCorrectionMessage("");
    try {
      const response = await correctManagementInvoice(
        correction.row.storeId,
        correction.row.statementMonth,
        {
          invoiceNumber: correction.invoiceNumber,
          invoiceDate: correction.invoiceDate,
          invoiceAmountCent: Number(correction.invoiceAmountCent),
          deductionDate: correction.deductionDate,
          deductionAmountCent: Number(correction.deductionAmountCent),
          changeReason: correction.changeReason.trim(),
          readVersion: correction.readVersion,
        },
        correction.idempotencyKey,
      );
      setCorrection((current) => current ? {
        ...current,
        row: response.data,
        readVersion: response.data.versionNo ?? current.readVersion,
        idempotencyKey: crypto.randomUUID(),
      } : current);
      setCorrectionState("success");
      setCorrectionMessage("更正已立即生效，并保留原历史版本。");
      summaryResource.reload();
      invoiceResource.reload();
    } catch (error) {
      const conflict = error instanceof ApiRequestError && error.status === 409;
      setCorrectionState(conflict ? "conflict" : "error");
      setCorrectionMessage(conflict ? "版本已变化，请刷新当前版本后重新提交。" : userFacingError(error, "更正失败，请重试。"));
    }
  };

  const statusOptions = feeDirection === "PROMOTION"
    ? [
        { value: "", label: "全部状态" },
        { value: "SUBMITTED_PENDING_FACTORY_REVIEW", label: "提交成功，待厂端审核" },
        { value: "APPROVED_SETTLED", label: "审核通过，已结算" },
        { value: "REJECTED_REUPLOAD", label: "审核不通过" },
      ]
    : [
        { value: "", label: "全部状态" },
        { value: "PENDING_INVOICE", label: "待开票" },
        { value: "APPROVED_SETTLED", label: "已开票" },
      ];

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">财务管理员</p>
          <h1>{title}</h1>
          <p>{feeDirection === "PROMOTION" ? "门店提交成功后进入列表；厂家审核结果和结算事实由财务导入。" : "展示全量已确认账单；厂家发票、扣款及更正结果由正式财务数据驱动。"}</p>
        </div>
        <div className="finance-heading__actions">
          <Button loading={downloadBusy} onClick={handleTemplateDownload} variant="secondary">
            {feeDirection === "PROMOTION" ? "下载推广服务费厂家导入模板" : "下载管理服务费厂家导入模板"}
          </Button>
          <Button onClick={() => setShowImport((current) => !current)} variant="primary">
            {feeDirection === "PROMOTION" ? "导入推广服务费厂家信息" : "导入管理服务费厂家信息"}
          </Button>
        </div>
      </section>

      <ResourceNotice loading={resourceBusy} error={summaryResource.error ?? invoiceResource.error} />
      <section className={`metric-grid finance-metric-grid ${feeDirection === "MANAGEMENT" ? "finance-metric-grid--four" : ""}`}>
        <MetricCard label={feeDirection === "PROMOTION" ? "推广费总额" : "管理费总额"} value={currencyMetric(metrics?.statementTotalCent)} />
        <MetricCard label="已确认金额" value={currencyMetric(metrics?.confirmedAmountCent)} />
        <MetricCard label="待开票金额" value={currencyMetric(metrics?.pendingInvoiceAmountCent)} />
        <MetricCard label="已开票金额" value={currencyMetric(metrics?.issuedAmountCent)} />
        {feeDirection === "PROMOTION" ? <MetricCard label="审核通过已结算金额" value={currencyMetric(metrics?.settledOrDeductedAmountCent)} /> : null}
      </section>

      {showImport ? (
        <FinanceImportActionPanel
          fixedImportType={importType}
          month={month}
          onCommitted={() => {
            summaryResource.reload();
            invoiceResource.reload();
          }}
          scope={feeDirection}
        />
      ) : null}

      <div className="finance-guidance" role="note">
        账期、状态与搜索条件同时作用于列表、金额汇总和导出结果。
      </div>
      <section className="finance-workbench" aria-label={`${title}筛选与操作`}>
        <div className="finance-workbench__filters">
          <TextField label="搜索" onChange={(event) => setSearch(event.target.value)} placeholder="搜索门店、SAP 或发票号码" type="search" value={search} />
          <TextField label="筛选账期" onChange={(event) => setMonth(event.target.value)} type="month" value={month} />
          <SelectField label={feeDirection === "PROMOTION" ? "发票审核状态" : "开票状态"} onChange={setInvoiceStatus} options={statusOptions} value={invoiceStatus} />
          <SelectField label="指标口径" onChange={(value) => setMetricScope(value as BillingMetricScope)} options={[{ value: "MONTH", label: "单月" }, { value: "CUMULATIVE", label: "累计" }]} value={metricScope} />
        </div>
        <div className="finance-workbench__actions">
          <Button onClick={() => navigateTo(feeDirection === "PROMOTION" ? "/finance/orders/promotion" : "/finance/orders/management")} variant="secondary">查看{title}订单明细</Button>
          <Button loading={exportBusy} onClick={handleExport} variant="secondary">导出当前筛选结果</Button>
          <Button onClick={resetFilters} variant="text">重置筛选</Button>
          {feeDirection === "MANAGEMENT" ? <Button onClick={() => setShowHistory((value) => !value)} variant="text">{showHistory ? "仅看当前版本" : "查看历史版本"}</Button> : null}
        </div>
      </section>
      {notice ? <p role={noticeIsError ? "alert" : "status"}>{notice}</p> : null}

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>{feeDirection === "PROMOTION" ? "推广费发票明细" : "管理服务费发票与扣款明细"}</h2>
            <p>{feeDirection === "MANAGEMENT" ? "双击当前版本可发起更正，历史版本永久保留。" : "厂家审核原因、归属月和结算状态均由正式接口返回。"}</p>
          </div>
        </div>
        <DataTable
          columns={feeDirection === "PROMOTION" ? promotionColumns : managementColumns}
          emptyText="当前筛选下暂无记录"
          onRowAction={feeDirection === "MANAGEMENT" ? openCorrection : undefined}
          onRowDoubleClick={feeDirection === "MANAGEMENT" ? openCorrection : undefined}
          rowActionLabel={(row) => row.invoiceId && row.isCurrent ? "更正" : undefined}
          rows={rows}
          state={resourceBusy ? "loading" : invoiceResource.error ? "error" : "ready"}
          tableClassName="finance-fee-table"
        />
      </section>

      {feeDirection === "MANAGEMENT" && correction ? (
        <section className="content-section finance-correction-panel">
          <div className="section-title">
            <div><h2>更正管理服务费记录</h2><p>{correction.row.storeId} · {correction.row.statementMonth} · 当前 V{correction.row.versionNo}；金额可编辑，提交时校验版本并保留历史。</p></div>
            <Button onClick={() => setCorrection(null)} variant="text">关闭</Button>
          </div>
          <div className="finance-form-grid">
            <TextField label="发票号码" onChange={(event) => updateCorrection({ invoiceNumber: event.target.value })} value={correction.invoiceNumber} />
            <TextField label="发票日期" onChange={(event) => updateCorrection({ invoiceDate: event.target.value })} type="date" value={correction.invoiceDate} />
            <TextField label="厂家扣款日期" onChange={(event) => updateCorrection({ deductionDate: event.target.value })} type="date" value={correction.deductionDate} />
            <TextField label="发票金额（分）" min="1" onChange={(event) => updateCorrection({ invoiceAmountCent: event.target.value })} step="1" type="number" value={correction.invoiceAmountCent} />
            <TextField label="厂家扣款金额（分）" min="1" onChange={(event) => updateCorrection({ deductionAmountCent: event.target.value })} step="1" type="number" value={correction.deductionAmountCent} />
            <TextField label="更正原因" onChange={(event) => updateCorrection({ changeReason: event.target.value })} value={correction.changeReason} />
          </div>
          {correctionValidationError ? <p role="alert">{correctionValidationError}</p> : null}
          {correctionMessage ? <p role={correctionState === "error" || correctionState === "conflict" ? "alert" : "status"}>{correctionMessage}</p> : null}
          <Button disabled={!canSubmitCorrection} loading={correctionState === "loading"} onClick={submitCorrection} variant="primary">确认更正</Button>
        </section>
      ) : null}
    </div>
  );
}
