import { useEffect, useState } from "react";
import {
  downloadFinanceDisputes,
  fetchFinanceDisputeDetection,
  fetchFinanceDisputes,
  fetchStoreBillingStatements,
  startFinanceDisputeDetection,
  transitionFinanceDispute,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { SelectField, TextareaField, TextField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { useApiResource } from "../hooks/useApiResource";
import type {
  FeeDirection,
  FinanceDisputeDetection,
  FinanceDisputeRow,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { parseYuanToCent } from "../utils/money";
import { userFacingError } from "../utils/userFacingError";
import {
  displayFeeDirection,
  displayFinanceDisputeDetectionStatus,
  displayFinanceDisputeStatus,
  displayFinanceDisputeType,
} from "../utils/userFacingLabels";

function countMetric(value: number | undefined): string {
  return typeof value === "number" ? `${value} 条` : "—";
}

function isDetectionActive(detection: FinanceDisputeDetection | null | undefined): boolean {
  return detection?.status === "QUEUED" || detection?.status === "RUNNING";
}

function detectionSummary(row: FinanceDisputeRow): string {
  const detection = row.latestDetection;
  if (!detection) return "尚未检测";
  if (detection.status === "SUCCEEDED") return detection.resultSummary ?? "检测完成";
  if (detection.status === "FAILED") return detection.failureReason ?? "检测失败";
  return `${displayFinanceDisputeDetectionStatus(detection.status)} · ${detection.progressPercent}%`;
}

const DISPUTE_TRANSITION_OPTIONS = {
  PENDING: [
    { value: "IN_REVIEW", label: "审核中" },
    { value: "ACCEPTED_WITH_ADJUSTMENT", label: "成立并调整" },
    { value: "REJECTED", label: "不成立" },
  ],
  IN_REVIEW: [
    { value: "PENDING_ADMIN_APPROVAL", label: "待管理员审批" },
    { value: "REJECTED", label: "不成立" },
  ],
  PENDING_ADMIN_APPROVAL: [
    { value: "ACCEPTED_WITH_ADJUSTMENT", label: "成立并调整" },
    { value: "REJECTED", label: "不成立" },
  ],
} as const;

function transitionOptionsFor(status: string) {
  return DISPUTE_TRANSITION_OPTIONS[status as keyof typeof DISPUTE_TRANSITION_OPTIONS] ?? [];
}

export function FinanceDisputesPage({ searchParams }: { searchParams: URLSearchParams }) {
  const [month, setMonth] = useState(searchParams.get("month") ?? "");
  const [storeId, setStoreId] = useState(searchParams.get("storeId") ?? "");
  const [feeDirection, setFeeDirection] = useState<FeeDirection | "">(searchParams.get("feeDirection") as FeeDirection | "" ?? "");
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [selected, setSelected] = useState<FinanceDisputeRow | null>(null);
  const [detection, setDetection] = useState<FinanceDisputeDetection | null>(null);
  const [detectionBusy, setDetectionBusy] = useState(false);
  const [detectionMessage, setDetectionMessage] = useState("");
  const [targetStatus, setTargetStatus] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");
  const [adjustmentYuan, setAdjustmentYuan] = useState("");
  const [detectionKey, setDetectionKey] = useState(() => crypto.randomUUID());
  const [transitionKey, setTransitionKey] = useState(() => crypto.randomUUID());
  const [actionMessage, setActionMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const adjustmentAmountCent = parseYuanToCent(adjustmentYuan);
  const adjustmentIsValid = targetStatus !== "ACCEPTED_WITH_ADJUSTMENT" || adjustmentAmountCent !== null;
  const query = {
    month: month || undefined,
    storeId: storeId || undefined,
    feeDirection: feeDirection || undefined,
    status: status || undefined,
    pageSize: 50,
  };
  const resource = useApiResource(() => fetchFinanceDisputes(query), [month, storeId, feeDirection, status]);
  const resourceBusy = resource.loading || resource.refreshing;
  const metrics = resource.data?.data.metrics;
  const currentDetection = detection ?? selected?.latestDetection ?? null;
  const transitionOptions = selected ? transitionOptionsFor(selected.status) : [];

  useEffect(() => {
    if (!selected || !currentDetection || !isDetectionActive(currentDetection)) return undefined;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const response = await fetchFinanceDisputeDetection(selected.disputeId, currentDetection.detectionId);
        if (cancelled) return;
        setDetection(response.data);
        setDetectionMessage("");
        if (isDetectionActive(response.data)) {
          timer = window.setTimeout(poll, 2000);
        } else {
          resource.reload();
        }
      } catch (error) {
        if (cancelled) return;
        setDetectionMessage(userFacingError(error, "检测进度读取失败，请稍后重试。"));
      }
    };
    timer = window.setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [selected?.disputeId, currentDetection?.detectionId, currentDetection?.status]);

  const openDetail = (row: FinanceDisputeRow) => {
    const options = transitionOptionsFor(row.status);
    setSelected(row);
    setDetection(row.latestDetection);
    setDetectionMessage("");
    setActionMessage("");
    setTargetStatus(options[0]?.value ?? "");
    setResolutionNote("");
    setAdjustmentYuan("");
    setDetectionKey(crypto.randomUUID());
    setTransitionKey(crypto.randomUUID());
  };

  const columns: Column<FinanceDisputeRow>[] = [
    { key: "id", title: "异议编号", minWidth: 190, sticky: true, render: (row) => row.disputeId },
    { key: "type", title: "异议类型", minWidth: 150, render: (row) => displayFinanceDisputeType(row.disputeType) },
    { key: "store", title: "门店", minWidth: 220, render: (row) => <span><strong>{row.storeName}</strong><br /><small>{row.storeId}</small></span> },
    { key: "directionMonth", title: "费用方向 / 账期", minWidth: 170, render: (row) => `${displayFeeDirection(row.feeDirection)} / ${row.statementMonth}` },
    { key: "amount", title: "异议金额", minWidth: 130, align: "right", render: (row) => formatCurrency(row.disputedAmountCent) },
    { key: "detection", title: "系统检测结果", minWidth: 260, render: detectionSummary },
    { key: "status", title: "状态", minWidth: 150, render: (row) => displayFinanceDisputeStatus(row.status) },
    { key: "action", title: "操作", minWidth: 140, render: (row) => <Button size="sm" onClick={() => openDetail(row)} variant="text">{isDetectionActive(row.latestDetection) ? "查看检测进度" : "处理"}</Button> },
  ];

  const startDetection = async () => {
    if (!selected) return;
    setDetectionBusy(true);
    setDetectionMessage("");
    try {
      const response = await startFinanceDisputeDetection(selected.disputeId, detectionKey);
      setDetection(response.data);
      setDetectionKey(crypto.randomUUID());
      setDetectionMessage("检测任务已创建；页面仅展示正式 API 返回的状态、进度和结果。");
      resource.reload();
    } catch (error) {
      setDetectionMessage(userFacingError(error, "系统检测启动失败，请稍后重试。"));
    } finally {
      setDetectionBusy(false);
    }
  };

  const handleExport = async () => {
    setExportBusy(true);
    setActionMessage("");
    try {
      const result = await downloadFinanceDisputes(query);
      setActionMessage(result.result === "EMPTY" ? "当前筛选无异议，已下载仅含表头的文件。" : `已导出账单异议：${result.fileName}`);
    } catch (error) {
      setActionMessage(userFacingError(error, "账单异议导出失败，请稍后重试。"));
    } finally {
      setExportBusy(false);
    }
  };

  const handleTransition = async () => {
    if (!selected || !resolutionNote.trim()) return;
    let validatedAdjustmentAmountCent: number | undefined;
    if (targetStatus === "ACCEPTED_WITH_ADJUSTMENT") {
      if (adjustmentAmountCent === null) {
        setActionMessage("请输入有效且非零的调整金额，最多保留两位小数。");
        return;
      }
      validatedAdjustmentAmountCent = adjustmentAmountCent;
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
      await transitionFinanceDispute(
        selected.disputeId,
        {
          targetStatus,
          resolutionNote: resolutionNote.trim(),
          readVersion: current.versionNo,
          adjustmentAmountCent: validatedAdjustmentAmountCent,
        },
        transitionKey,
      );
      setActionMessage("异议状态已更新。");
      setSelected(null);
      setResolutionNote("");
      setAdjustmentYuan("");
      setTransitionKey(crypto.randomUUID());
      resource.reload();
    } catch (error) {
      setActionMessage(userFacingError(error, "处理失败，请稍后重试。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div><p className="eyebrow">财务管理员</p><h1>账单异议</h1><p>处理账单金额、费率和订单遗漏异议；系统检测只提供正式事实一致性证据，不自动作出业务裁决。</p></div>
        <div className="finance-heading__actions"><Button loading={exportBusy} onClick={handleExport} variant="secondary">导出账单异议</Button></div>
      </section>

      <section className="metric-grid finance-metric-grid finance-metric-grid--four">
        <MetricCard label="账单金额异议" value={countMetric(metrics?.amountDisputeCount)} />
        <MetricCard label="系统检测中" value={countMetric(metrics?.detectingCount)} />
        <MetricCard label="待管理员处理" value={countMetric(metrics?.pendingAdminCount)} />
        <MetricCard label="今日已完成" value={countMetric(metrics?.completedTodayCount)} />
      </section>

      <section className="finance-filter-bar" aria-label="异议筛选条件">
        <TextField label="账期" onChange={(event) => setMonth(event.target.value)} type="month" value={month} />
        <TextField label="门店 ID" onChange={(event) => setStoreId(event.target.value)} value={storeId} />
        <SelectField label="费用方向" onChange={(value) => setFeeDirection(value as FeeDirection | "")} options={[{ value: "", label: "全部" }, { value: "PROMOTION", label: "推广服务费" }, { value: "MANAGEMENT", label: "管理服务费" }]} value={feeDirection} />
        <SelectField label="处理状态" onChange={setStatus} options={[{ value: "", label: "全部" }, { value: "PENDING", label: "待处理" }, { value: "IN_REVIEW", label: "审核中" }, { value: "PENDING_ADMIN_APPROVAL", label: "待管理员审批" }, { value: "ACCEPTED_WITH_ADJUSTMENT", label: "成立并调整" }, { value: "REJECTED", label: "不成立" }]} value={status} />
      </section>
      <ResourceNotice loading={resourceBusy} error={resource.error} />
      {actionMessage && !selected ? <p role="status">{actionMessage}</p> : null}

      <section className="content-section">
        <div className="section-title"><div><h2>异议清单</h2><p>共 {resource.data?.data.total ?? 0} 条；检测进度与失败原因刷新后仍由正式 API 恢复。</p></div></div>
        <DataTable columns={columns} emptyText="当前筛选下暂无账单异议" rows={resource.data?.data.list ?? []} state={resourceBusy ? "loading" : resource.error ? "error" : "ready"} tableClassName="finance-dispute-table" />
      </section>

      {selected ? (
        <aside className="finance-detail-drawer" aria-label="账单异议详情">
          <header><div><p className="eyebrow">金额异议详情</p><h2>{selected.disputeId}</h2></div><Button onClick={() => setSelected(null)} variant="text">关闭</Button></header>
          <dl className="finance-audit-facts">
            <div><dt>门店</dt><dd>{selected.storeName} / {selected.storeId}</dd></div>
            <div><dt>异议类型</dt><dd>{displayFinanceDisputeType(selected.disputeType)}</dd></div>
            <div><dt>费用方向 / 账期</dt><dd>{displayFeeDirection(selected.feeDirection)} / {selected.statementMonth}</dd></div>
            <div><dt>异议金额</dt><dd>{formatCurrency(selected.disputedAmountCent)}</dd></div>
            <div><dt>提交时间</dt><dd>{formatDateTime(selected.submittedAt)}</dd></div>
            <div><dt>具体原因</dt><dd>{selected.description}</dd></div>
          </dl>

          <section className="finance-dispute-detection">
            <div className="section-title"><div><h3>系统检测</h3><p>检测只核对正式账单、订单范围、金额与版本一致性，不自动判定异议成立或不成立。</p></div></div>
            {currentDetection ? (
              <dl className="finance-audit-facts">
                <div><dt>状态</dt><dd>{displayFinanceDisputeDetectionStatus(currentDetection.status)}</dd></div>
                <div><dt>进度</dt><dd>{currentDetection.progressPercent}%</dd></div>
                <div><dt>检测结果</dt><dd>{currentDetection.resultSummary ?? "—"}</dd></div>
                <div><dt>失败原因</dt><dd>{currentDetection.failureReason ?? "—"}</dd></div>
                <div><dt>更新时间</dt><dd>{formatDateTime(currentDetection.updatedAt)}</dd></div>
              </dl>
            ) : <ResourcePanel>尚未启动系统检测。</ResourcePanel>}
            {detectionMessage ? <ResourcePanel tone={currentDetection?.status === "FAILED" ? "error" : "loading"}>{detectionMessage}</ResourcePanel> : null}
            {!isDetectionActive(currentDetection) ? <Button loading={detectionBusy} onClick={startDetection} variant="secondary">{currentDetection ? "重新检测" : "启动系统检测"}</Button> : <Button disabled variant="secondary">查看检测进度</Button>}
          </section>

          {transitionOptions.length > 0 ? (
            <section className="finance-dispute-resolution">
              <h3>管理员处理</h3>
              <SelectField
                label="处理结果"
                onChange={(value) => {
                  setTargetStatus(value);
                  setTransitionKey(crypto.randomUUID());
                }}
                options={[...transitionOptions]}
                value={targetStatus}
              />
              {targetStatus === "ACCEPTED_WITH_ADJUSTMENT" ? <TextField label="调整金额（元，非零）" onChange={(event) => { setAdjustmentYuan(event.target.value); setTransitionKey(crypto.randomUUID()); }} required step="0.01" type="number" value={adjustmentYuan} /> : null}
              <TextareaField label="处理说明" onChange={(event) => { setResolutionNote(event.target.value); setTransitionKey(crypto.randomUUID()); }} required rows={3} value={resolutionNote} />
              {actionMessage ? <p role="status">{actionMessage}</p> : null}
              <Button disabled={saving || !resolutionNote.trim() || !adjustmentIsValid} loading={saving} onClick={handleTransition} variant="primary">确认处理</Button>
            </section>
          ) : <ResourcePanel>当前异议已完成处理，没有可用的下一状态。</ResourcePanel>}
        </aside>
      ) : null}
    </div>
  );
}
