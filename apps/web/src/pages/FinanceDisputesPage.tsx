import { useState } from "react";
import {
  fetchFinanceDisputes,
  fetchStoreBillingStatements,
  transitionFinanceDispute,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput, FieldTextarea } from "../components/FormControls";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type { FeeDirection, FinanceDisputeRow } from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import {
  displayFeeDirection,
  displayFinanceDisputeStatus,
  displayFinanceDisputeType,
} from "../utils/userFacingLabels";

function isValidAdjustmentYuan(value: string): boolean {
  const amount = Number(value);
  return Number.isFinite(amount) && amount !== 0;
}

export function FinanceDisputesPage({ searchParams }: { searchParams: URLSearchParams }) {
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const [storeId, setStoreId] = useState(searchParams.get("storeId") ?? "");
  const [feeDirection, setFeeDirection] = useState<FeeDirection | "">("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<FinanceDisputeRow | null>(null);
  const [targetStatus, setTargetStatus] = useState("IN_REVIEW");
  const [resolutionNote, setResolutionNote] = useState("");
  const [adjustmentYuan, setAdjustmentYuan] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const adjustmentIsValid = targetStatus !== "ACCEPTED_WITH_ADJUSTMENT" || isValidAdjustmentYuan(adjustmentYuan);
  const resource = useApiResource(
    () => fetchFinanceDisputes({ month: month || undefined, storeId: storeId || undefined, feeDirection: feeDirection || undefined, status: status || undefined, pageSize: 50 }),
    [month, storeId, feeDirection, status],
  );
  const columns: Column<FinanceDisputeRow>[] = [
    { key: "id", title: "异议编号", minWidth: 190, sticky: true, render: (row) => row.disputeId },
    { key: "store", title: "门店 ID", minWidth: 150, render: (row) => row.storeId },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "direction", title: "费用方向", render: (row) => displayFeeDirection(row.feeDirection) },
    { key: "type", title: "异议类型", render: (row) => displayFinanceDisputeType(row.disputeType) },
    { key: "amount", title: "异议金额", align: "right", render: (row) => formatCurrency(row.disputedAmountCent) },
    { key: "status", title: "状态", render: (row) => displayFinanceDisputeStatus(row.status) },
    { key: "submitted", title: "提交时间", minWidth: 170, render: (row) => formatDateTime(row.submittedAt) },
    { key: "action", title: "操作", render: (row) => <Button size="sm" onClick={() => { setSelected(row); setActionMessage(""); }} variant="text">处理</Button> },
  ];

  const handleTransition = async () => {
    if (!selected || !resolutionNote.trim()) return;
    if (targetStatus === "ACCEPTED_WITH_ADJUSTMENT" && !isValidAdjustmentYuan(adjustmentYuan)) {
      setActionMessage("请输入有限且非零的调整金额。");
      return;
    }
    setSaving(true);
    setActionMessage("");
    try {
      const statements = await fetchStoreBillingStatements({
        storeId: selected.storeId,
        month: selected.statementMonth,
        metricScope: "MONTH",
        feeDirection: selected.feeDirection,
        pageSize: 50,
      });
      const current = statements.data.list.find((item) => item.isCurrent);
      if (!current) {
        setActionMessage("未找到当前有效账单版本，请刷新后重试。");
        return;
      }
      await transitionFinanceDispute(selected.disputeId, {
        targetStatus,
        resolutionNote: resolutionNote.trim(),
        readVersion: current.versionNo,
        adjustmentAmountCent: targetStatus === "ACCEPTED_WITH_ADJUSTMENT" ? Math.round(Number(adjustmentYuan) * 100) : undefined,
      });
      setActionMessage("异议状态已更新。");
      setSelected(null);
      setResolutionNote("");
      setAdjustmentYuan("");
      resource.reload();
    } catch (error) {
      setActionMessage(userFacingError(error, "处理失败，请稍后重试。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading"><div><p className="eyebrow">财务管理员</p><h1>账单异议</h1><p>门店提交异议和证明资料，内部管理员在本页处理；异议不阻断推广费或管理服务费后续流程。</p></div></section>
      <section className="finance-filter-bar" aria-label="异议筛选条件">
        <label><span>账期</span><FieldInput type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
        <label><span>门店 ID</span><FieldInput value={storeId} onChange={(event) => setStoreId(event.target.value)} /></label>
        <label>
          <span>费用方向</span>
          <SearchableStoreSelect
            allowEmpty
            emptyLabel="全部"
            emptyMessage="未找到费用方向"
            onChange={(value) => setFeeDirection(value as FeeDirection | "")}
            options={[
              { value: "PROMOTION", label: "推广服务费" },
              { value: "MANAGEMENT", label: "管理服务费" },
            ]}
            placeholder="选择费用方向"
            value={feeDirection}
          />
        </label>
        <label>
          <span>处理状态</span>
          <SearchableStoreSelect
            allowEmpty
            emptyLabel="全部"
            emptyMessage="未找到处理状态"
            onChange={setStatus}
            options={[
              { value: "PENDING", label: "待处理" },
              { value: "IN_REVIEW", label: "审核中" },
              { value: "PENDING_ADMIN_APPROVAL", label: "待管理员审批" },
              { value: "ACCEPTED_WITH_ADJUSTMENT", label: "成立并调整" },
              { value: "REJECTED", label: "不成立" },
            ]}
            placeholder="选择处理状态"
            value={status}
          />
        </label>
      </section>
      <ResourceNotice loading={resource.loading} error={resource.error} />
      <section className="content-section"><div className="section-title"><div><h2>异议清单</h2><p>共 {resource.data?.data.total ?? 0} 条。</p></div></div><DataTable columns={columns} rows={resource.data?.data.list ?? []} state={resource.loading ? "loading" : resource.error ? "error" : "ready"} /></section>
      {selected ? (
        <section className="content-section finance-action-panel" aria-label="异议处理面板">
          <div className="section-title"><div><h2>处理 {selected.disputeId}</h2><p>{selected.description}</p></div><Button onClick={() => setSelected(null)} variant="text">关闭</Button></div>
          <div className="finance-form-grid">
            <label>
              <span>处理结果</span>
              <SearchableStoreSelect
                emptyMessage="未找到处理结果"
                onChange={setTargetStatus}
                options={[
                  { value: "IN_REVIEW", label: "审核中" },
                  { value: "PENDING_ADMIN_APPROVAL", label: "待管理员审批" },
                  { value: "ACCEPTED_WITH_ADJUSTMENT", label: "成立并调整" },
                  { value: "REJECTED", label: "不成立" },
                ]}
                placeholder="选择处理结果"
                value={targetStatus}
              />
            </label>
            {targetStatus === "ACCEPTED_WITH_ADJUSTMENT" ? <label><span>调整金额（元，非零）</span><FieldInput required type="number" step="0.01" value={adjustmentYuan} onChange={(event) => setAdjustmentYuan(event.target.value)} /></label> : null}
            <label className="finance-form-grid__wide"><span>处理说明</span><FieldTextarea required rows={3} value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} /></label>
            <div className="finance-form-actions"><Button disabled={saving || !resolutionNote.trim() || !adjustmentIsValid} loading={saving} onClick={handleTransition} variant="primary">确认处理</Button>{actionMessage ? <span role="status">{actionMessage}</span> : null}</div>
          </div>
        </section>
      ) : actionMessage ? <ResourcePanel>{actionMessage}</ResourcePanel> : null}
    </div>
  );
}
