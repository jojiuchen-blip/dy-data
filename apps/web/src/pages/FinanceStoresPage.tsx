import { useState } from "react";
import {
  ApiRequestError,
  correctFinanceStoreSap,
  downloadFinanceImportTemplate,
  downloadFinanceSapDiscrepancies,
  downloadFinanceStores,
  fetchFinanceStores,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FinanceImportActionPanel } from "../components/FinanceImportActionPanel";
import { SelectField, TextField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice } from "../components/ResourceState";
import { Tabs } from "../components/SelectionControls";
import { useApiResource } from "../hooks/useApiResource";
import type {
  AdminUser,
  BillingMetricScope,
  FeeDirection,
  FinanceStoreRow,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { displayFinanceSapStatus } from "../utils/userFacingLabels";

type StoreTab = "base" | "sap";
type ActionState = "idle" | "loading" | "success" | "error" | "conflict";

function defaultStatementMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function countMetric(value: number | undefined): string {
  return typeof value === "number" ? `${value} 家` : "—";
}

interface FinanceStoresPageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
}

export function FinanceStoresPage({ currentUser, searchParams }: FinanceStoresPageProps) {
  const [tab, setTab] = useState<StoreTab>(searchParams.get("tab") === "sap" ? "sap" : "base");
  const [month, setMonth] = useState(searchParams.get("month") ?? defaultStatementMonth());
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [feeDirection, setFeeDirection] = useState<FeeDirection>("PROMOTION");
  const [metricScope, setMetricScope] = useState<BillingMetricScope>("MONTH");
  const [showImport, setShowImport] = useState(false);
  const [selectedRow, setSelectedRow] = useState<FinanceStoreRow | null>(null);
  const [finalSapCode, setFinalSapCode] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [notice, setNotice] = useState("");
  const [noticeIsError, setNoticeIsError] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  const financeQuery = {
    month,
    feeDirection,
    metricScope,
    q: query.trim() || undefined,
    sapDiscrepanciesOnly: tab === "sap",
    pageSize: 50,
  };
  const financeResource = useApiResource(
    () => fetchFinanceStores(financeQuery),
    [month, feeDirection, metricScope, query, tab],
  );
  const resourceBusy = financeResource.loading || financeResource.refreshing;
  const rows = financeResource.data?.data.list ?? [];
  const sapMetrics = financeResource.data?.data.sapMetrics;
  const roleContext = currentUser.role === "highest_admin" ? "最高管理员" : "财务管理员";
  const expectedConfirmedVersion = selectedRow?.confirmedVersion ?? 0;

  const baseColumns: Column<FinanceStoreRow>[] = [
    { key: "storeId", title: "门店ID（所属账户关联poi-id）", minWidth: 230, sticky: true, render: (row) => row.storeId },
    { key: "storeName", title: "服务店名称", minWidth: 220, render: (row) => row.storeName },
    { key: "effectiveSap", title: "有效SAP编码", minWidth: 150, render: (row) => row.effectiveSapCode ?? "—" },
    { key: "updatedAt", title: "最近导入时间", minWidth: 170, render: (row) => formatDateTime(row.effectiveSapUpdatedAt ?? row.updatedAt) },
    { key: "sapStatus", title: "SAP确认状态", minWidth: 150, render: (row) => displayFinanceSapStatus(row.sapStatus) },
  ];

  const sapColumns: Column<FinanceStoreRow>[] = [
    { key: "dispute", title: "异议编号", minWidth: 180, sticky: true, render: (row) => row.discrepancyId ?? "—" },
    { key: "store", title: "门店", minWidth: 220, render: (row) => <span><strong>{row.storeName}</strong><br /><small>{row.storeId}</small></span> },
    { key: "effectiveSap", title: "有效 SAP", minWidth: 150, render: (row) => row.effectiveSapCode ?? "—" },
    { key: "status", title: "当前状态", minWidth: 150, render: (row) => displayFinanceSapStatus(row.sapStatus) },
    { key: "detected", title: "检测时间", minWidth: 170, render: (row) => formatDateTime(row.discrepancyDetectedAt) },
    { key: "action", title: "操作", minWidth: 120, render: (row) => <Button onClick={() => openCorrection(row)} size="sm" variant="text">查看详情</Button> },
  ];

  const openCorrection = (row: FinanceStoreRow) => {
    setSelectedRow(row);
    setFinalSapCode(row.effectiveSapCode ?? row.financeImportedSapCode ?? "");
    setChangeReason("");
    setActionState("idle");
    setNotice("");
    setNoticeIsError(false);
    setIdempotencyKey(crypto.randomUUID());
  };

  const handleTabChange = (nextTab: StoreTab) => {
    setTab(nextTab);
    setShowImport(false);
    setSelectedRow(null);
    setNotice("");
    setNoticeIsError(false);
  };

  const handleTemplateDownload = async (importType: "BASIC_INFO" | "SAP_CONFIRMATION") => {
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

  const handleBaseExport = async () => {
    setDownloadBusy(true);
    setNotice("");
    setNoticeIsError(false);
    try {
      const result = await downloadFinanceStores(financeQuery);
      setNotice(result.result === "EMPTY" ? "当前筛选无门店，已下载仅含表头的文件。" : `已导出门店基础信息：${result.fileName}`);
    } catch (error) {
      setNoticeIsError(true);
      setNotice(userFacingError(error, "门店基础信息导出失败，请稍后重试。"));
    } finally {
      setDownloadBusy(false);
    }
  };

  const handleSapExport = async () => {
    setDownloadBusy(true);
    setNotice("");
    setNoticeIsError(false);
    try {
      const result = await downloadFinanceSapDiscrepancies(financeQuery);
      setNotice(result.result === "EMPTY" ? "当前筛选无 SAP 差异，已下载仅含表头的文件。" : `已导出 SAP 差异清单：${result.fileName}`);
    } catch (error) {
      setNoticeIsError(true);
      setNotice(userFacingError(error, "SAP 差异清单导出失败，请稍后重试。"));
    } finally {
      setDownloadBusy(false);
    }
  };

  const submitCorrection = async () => {
    if (!selectedRow || !finalSapCode.trim() || !changeReason.trim()) return;
    setActionState("loading");
    setNotice("");
    setNoticeIsError(false);
    try {
      await correctFinanceStoreSap(
        selectedRow.storeId,
        {
          finalSapCode: finalSapCode.trim(),
          changeReason: changeReason.trim(),
          readVersion: selectedRow.effectiveSapVersion,
        },
        idempotencyKey,
      );
      setActionState("success");
      setNotice("有效 SAP 已生成新版本；门店原值、财务导入值、操作人和时间继续保留。历史账单与订单快照不回写。");
      setSelectedRow(null);
      setIdempotencyKey(crypto.randomUUID());
      financeResource.reload();
    } catch (error) {
      const conflict = error instanceof ApiRequestError && error.status === 409;
      setActionState(conflict ? "conflict" : "error");
      setNoticeIsError(true);
      setNotice(conflict ? "有效 SAP 版本已变化，请刷新后重新核对。" : userFacingError(error, "SAP 矫正失败，请稍后重试。"));
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">{roleContext}</p>
          <h1>门店基础信息</h1>
          <p>门店 ID 是唯一匹配键；财务导入值是当前有效 SAP 来源，门店原值和每次财务版本永久保留。</p>
        </div>
        {tab === "base" ? (
          <div className="finance-heading__actions">
            <Button loading={downloadBusy} onClick={() => handleTemplateDownload("BASIC_INFO")} variant="secondary">下载基础信息导入模板</Button>
            <Button loading={downloadBusy} onClick={handleBaseExport} variant="secondary">导出门店基础信息</Button>
            <Button onClick={() => setShowImport((current) => !current)} variant="primary">导入门店基础信息</Button>
          </div>
        ) : null}
      </section>

      <Tabs
        ariaLabel="门店基础信息页面"
        className="finance-page-tabs"
        onChange={handleTabChange}
        options={[{ value: "base", label: "基础信息" }, { value: "sap", label: "SAP异议处理" }]}
        value={tab}
      />

      {tab === "base" ? (
        <>
          <div className="finance-policy-banner" role="note">
            <strong>历史账期保留当时快照</strong>
            <span>重新导入的服务店名称和有效 SAP 仅影响后续新账期，不刷新历史账单与订单明细。</span>
          </div>
          {showImport ? <FinanceImportActionPanel fixedImportType="BASIC_INFO" month={month} onCommitted={() => financeResource.reload()} scope="STORE" /> : null}
        </>
      ) : (
        <>
          <div className="finance-sap-actions" role="group" aria-label="SAP异议操作">
            <Button loading={downloadBusy} onClick={handleSapExport} variant="secondary">导出 SAP 编码差异清单</Button>
            <Button loading={downloadBusy} onClick={() => handleTemplateDownload("SAP_CONFIRMATION")} variant="secondary">下载 SAP 编码确认模板</Button>
            <Button onClick={() => setShowImport((current) => !current)} variant="primary">导入最终确认 SAP 编码</Button>
          </div>
          {showImport ? <FinanceImportActionPanel fixedImportType="SAP_CONFIRMATION" month={month} onCommitted={() => financeResource.reload()} scope="STORE" /> : null}
          <section className="metric-grid finance-metric-grid finance-metric-grid--four">
            <MetricCard label="SAP 差异" value={countMetric(sapMetrics?.discrepancyCount)} />
            <MetricCard label="待门店确认" value={countMetric(sapMetrics?.pendingStoreConfirmationCount)} />
            <MetricCard label="财务可代确认" value={countMetric(sapMetrics?.financeActionableCount)} />
            <MetricCard label="今日已确认" value={countMetric(sapMetrics?.confirmedTodayCount)} />
          </section>
        </>
      )}

      <section className="finance-filter-bar" aria-label="门店财务筛选条件">
        <TextField label="账期" onChange={(event) => setMonth(event.target.value)} type="month" value={month} />
        <SelectField label="费用方向" onChange={(value) => setFeeDirection(value as FeeDirection)} options={[{ value: "PROMOTION", label: "推广服务费" }, { value: "MANAGEMENT", label: "管理服务费" }]} value={feeDirection} />
        <SelectField label="指标口径" onChange={(value) => setMetricScope(value as BillingMetricScope)} options={[{ value: "MONTH", label: "单月" }, { value: "CUMULATIVE", label: "累计" }]} value={metricScope} />
        <TextField label="搜索门店" onChange={(event) => setQuery(event.target.value)} placeholder="门店 ID、名称或 SAP" type="search" value={query} />
      </section>
      <ResourceNotice loading={resourceBusy} error={financeResource.error} />
      {notice ? <p role={noticeIsError ? "alert" : "status"}>{notice}</p> : null}

      {tab === "base" ? (
        <section className="content-section">
          <div className="section-title"><div><h2>门店基础信息</h2><p>共 {financeResource.data?.data.total ?? 0} 家门店；金额和 SAP 均由正式接口返回。</p></div></div>
          <DataTable columns={baseColumns} emptyText="当前筛选下暂无门店" rows={rows} state={resourceBusy ? "loading" : financeResource.error ? "error" : "ready"} tableClassName="finance-store-table" />
        </section>
      ) : (
        <section className="content-section">
          <div className="section-title"><div><h2>SAP 编码差异</h2><p>财务可重新导入最终 SAP，也可逐条矫正；每次写入均生成版本审计。</p></div></div>
          <DataTable columns={sapColumns} emptyText="当前筛选下暂无 SAP 差异" rows={rows} state={resourceBusy ? "loading" : financeResource.error ? "error" : "ready"} tableClassName="finance-sap-table" />
        </section>
      )}

      {selectedRow ? (
        <aside className="finance-detail-drawer" aria-label="SAP 差异详情">
          <header><div><p className="eyebrow">SAP 差异详情</p><h2>{selectedRow.storeName}</h2></div><Button onClick={() => setSelectedRow(null)} variant="text">关闭</Button></header>
          <dl className="finance-audit-facts">
            <div><dt>门店维护值</dt><dd>{selectedRow.storeMaintainedSapCode ?? "—"}</dd></div>
            <div><dt>财务导入值</dt><dd>{selectedRow.financeImportedSapCode ?? "—"}</dd></div>
            <div><dt>当前有效 SAP</dt><dd>{selectedRow.effectiveSapCode ?? "—"}</dd></div>
            <div><dt>有效版本</dt><dd>V{selectedRow.effectiveSapVersion}</dd></div>
            <div><dt>操作人</dt><dd>{selectedRow.effectiveSapUpdatedBy ?? "—"}</dd></div>
            <div><dt>更新时间</dt><dd>{formatDateTime(selectedRow.effectiveSapUpdatedAt)}</dd></div>
            <div><dt>门店建议版本</dt><dd>V{selectedRow.suggestionVersion} / 确认 V{expectedConfirmedVersion}</dd></div>
            <div><dt>账单总额</dt><dd>{formatCurrency(selectedRow.statementTotalCent)}</dd></div>
          </dl>
          <section className="finance-sap-correction">
            <h3>单条矫正有效 SAP</h3>
            <p>提交后财务值直接成为当前有效值，并保留旧版本；历史账单和订单快照不回写。</p>
            <TextField label="最终有效 SAP" onChange={(event) => setFinalSapCode(event.target.value)} value={finalSapCode} />
            <TextField label="矫正原因" onChange={(event) => setChangeReason(event.target.value)} value={changeReason} />
            <Button disabled={!finalSapCode.trim() || !changeReason.trim()} loading={actionState === "loading"} onClick={submitCorrection} variant="primary">确认矫正并生成新版本</Button>
          </section>
        </aside>
      ) : null}
    </div>
  );
}
