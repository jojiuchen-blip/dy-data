import { useState } from "react";
import {
  ApiRequestError,
  downloadFinanceImportErrors,
  fetchFinanceImportDetail,
  fetchFinanceImports,
  reverseFinanceImport,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput } from "../components/FormControls";
import { ResourceNotice } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  FinanceImportBatchRow,
  FinanceImportErrorRow,
  FinanceImportReversalRow,
} from "../types/dashboard";
import { formatDateTime, formatInteger } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import {
  displayFinanceImportScenario,
  displayFinanceImportType,
} from "../utils/userFacingLabels";

const importTypes = [
  ["", "全部类型"],
  ["BASIC_INFO", "门店基础信息"],
  ["PROMOTION_FACTORY_RESULT", "推广服务费厂家结果"],
  ["MANAGEMENT_FACTORY_RESULT", "管理服务费厂家结果"],
  ["SAP_CONFIRMATION", "SAP 确认"],
] as const;

export function FinanceImportsPage({ searchParams }: { searchParams: URLSearchParams }) {
  const [importType, setImportType] = useState(searchParams.get("importType") ?? "");
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [reversalKey, setReversalKey] = useState(() => crypto.randomUUID());
  const [reversalState, setReversalState] = useState<"idle" | "loading" | "success" | "error" | "conflict">("idle");
  const [reversalMessage, setReversalMessage] = useState("");
  const listResource = useApiResource(
    () => fetchFinanceImports({ importType: importType || undefined, statementMonth: month || undefined, pageSize: 50 }),
    [importType, month],
  );
  const detailResource = useApiResource(
    () => fetchFinanceImportDetail(selectedBatchId, { errorPageSize: 50 }),
    [selectedBatchId],
    { enabled: Boolean(selectedBatchId) },
  );

  const columns: Column<FinanceImportBatchRow>[] = [
    { key: "file", title: "文件", minWidth: 210, sticky: true, render: (row) => row.fileName },
    { key: "type", title: "导入类型", minWidth: 180, render: (row) => displayFinanceImportType(row.importType) },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "scenario", title: "处理结果", minWidth: 180, render: (row) => displayFinanceImportScenario(row.scenario) },
    { key: "version", title: "读取 / 当前版本", render: (row) => `V${row.readVersion} / V${row.currentVersion}` },
    { key: "rows", title: "成功 / 错误 / 总行", align: "right", render: (row) => `${formatInteger(row.successRows)} / ${formatInteger(row.errorRows)} / ${formatInteger(row.totalRows)}` },
    { key: "submitted", title: "导入时间", minWidth: 170, render: (row) => formatDateTime(row.submittedAt) },
    { key: "operator", title: "操作人", render: (row) => row.committedBy ?? row.submittedBy },
    { key: "action", title: "操作", render: (row) => <Button onClick={() => {
      setSelectedBatchId(row.batchId);
      setChangeReason("");
      setReversalKey(crypto.randomUUID());
      setReversalState("idle");
      setReversalMessage("");
    }} size="sm" variant="text">查看</Button> },
  ];
  const errorColumns: Column<FinanceImportErrorRow>[] = [
    { key: "row", title: "原文件行号", render: (row) => row.rowNumber },
    { key: "business", title: "业务唯一键", minWidth: 180, render: (row) => row.businessKey },
    { key: "field", title: "字段", render: (row) => row.field },
    { key: "value", title: "原始值", minWidth: 160, render: (row) => row.originalValue ?? "-" },
    { key: "reason", title: "错误原因", minWidth: 220, render: (row) => row.reason },
    { key: "suggestion", title: "建议修正方式", minWidth: 220, render: (row) => row.suggestion },
  ];
  const reversalColumns: Column<FinanceImportReversalRow>[] = [
    { key: "business", title: "业务唯一键", minWidth: 180, render: (row) => row.businessKey },
    { key: "original", title: "原目标", minWidth: 180, render: (row) => row.originalTargetRecordId ?? "-" },
    { key: "previous", title: "上一目标", minWidth: 180, render: (row) => row.previousTargetRecordId ?? "-" },
    { key: "reversal", title: "反向目标", minWidth: 180, render: (row) => row.reversalTargetRecordId ?? "-" },
    { key: "effect", title: "覆盖效果", render: (row) => row.effectType ?? "未撤销" },
    { key: "current", title: "当前有效", render: (row) => row.isCurrent ? "是" : "否" },
  ];
  const detail = detailResource.data?.data;
  const submitReversal = async () => {
    if (!detail || !changeReason.trim()) return;
    setReversalState("loading");
    setReversalMessage("");
    try {
      const result = await reverseFinanceImport(
        detail.batchId,
        { readVersion: detail.currentVersion, changeReason: changeReason.trim() },
        reversalKey,
      );
      setReversalState("success");
      setReversalMessage(`撤销批次 ${result.data.batchId} 已生成，原批次和业务历史均保留。`);
      listResource.reload();
      detailResource.reload();
    } catch (error) {
      const message = userFacingError(error, "撤销失败，请重试。");
      const conflict = error instanceof ApiRequestError && error.status === 409;
      setReversalState(conflict ? "conflict" : "error");
      setReversalMessage(conflict ? "批次或逐行业务版本已变化，请刷新后检查。" : message);
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading"><div><p className="eyebrow">财务管理员</p><h1>导入记录</h1><p>本页只读查询批次、错误、差异、版本覆盖关系和操作审计；导入操作从推广费或管理服务费页面发起。</p></div></section>
      <section className="finance-filter-bar" aria-label="导入记录筛选条件">
        <label>
          <span>导入类型</span>
          <SearchableStoreSelect
            allowEmpty
            emptyLabel="全部类型"
            emptyMessage="未找到导入类型"
            onChange={setImportType}
            options={importTypes
              .filter(([value]) => Boolean(value))
              .map(([value, label]) => ({ value, label }))}
            placeholder="选择导入类型"
            value={importType}
          />
        </label>
        <label><span>业务账期</span><FieldInput type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
      </section>
      <ResourceNotice loading={listResource.loading} error={listResource.error} />
      <section className="content-section"><div className="section-title"><div><h2>导入批次</h2><p>当前有效版本和历史更正记录均永久保留。</p></div></div><DataTable columns={columns} rows={listResource.data?.data.list ?? []} state={listResource.loading ? "loading" : listResource.error ? "error" : "ready"} /></section>
      {selectedBatchId ? (
        <section className="content-section finance-import-detail">
          <div className="section-title"><div><h2>批次详情</h2><p>{detail?.fileName ?? selectedBatchId}</p></div><Button onClick={() => setSelectedBatchId("")} variant="text">关闭</Button></div>
          <ResourceNotice loading={detailResource.loading} error={detailResource.error} />
          {detail ? <>
            <div className="finance-import-summary"><span>场景<strong>{displayFinanceImportScenario(detail.scenario)}</strong></span><span>成功<strong>{detail.successRows}</strong></span><span>错误<strong>{detail.errorRows}</strong></span><span>版本<strong>V{detail.readVersion} / V{detail.currentVersion}</strong></span></div>
            {detail.reversesBatchId ? <p>本批次用于撤销：<strong>{detail.reversesBatchId}</strong></p> : null}
            {detail.reversedByBatchId ? <p>本批次已由以下批次撤销：<strong>{detail.reversedByBatchId}</strong></p> : null}
            <p>覆盖链：{detail.reversalChain.join(" → ")}</p>
            {!detail.canReverse && detail.reverseNotAllowedReason ? <p role="status">不可撤销：{detail.reverseNotAllowedReason}</p> : null}
            <div className="section-title"><div><h3>逐业务键撤销覆盖链</h3><p>展示原目标、上一目标、反向目标、覆盖效果和当前有效性。</p></div></div>
            <DataTable columns={reversalColumns} rows={detail.reversalRows.list} emptyText="本批次没有可展示的业务键" />
            <DataTable columns={errorColumns} rows={detail.errors.list} emptyText="本批次没有校验错误" />
            {detail.errorRows > 0 ? <Button onClick={() => downloadFinanceImportErrors(detail.batchId)} variant="secondary">下载全部错误</Button> : null}
            {detail.canReverse ? <div className="finance-reversal-panel">
              <label><span>撤销原因</span><FieldInput value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="说明为何需要生成更正覆盖版本" /></label>
              <p>撤销批次会逐业务键校验当前版本；任一行已被覆盖时整批不会写入。</p>
              {reversalMessage ? <p role={reversalState === "error" || reversalState === "conflict" ? "alert" : "status"}>{reversalMessage}</p> : null}
              <Button disabled={reversalState === "loading" || !changeReason.trim()} onClick={submitReversal} variant="secondary">{reversalState === "loading" ? "撤销中…" : "撤销批次"}</Button>
            </div> : null}
          </> : null}
        </section>
      ) : null}
    </div>
  );
}
