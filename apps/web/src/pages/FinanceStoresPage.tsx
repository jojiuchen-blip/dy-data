import { useState } from "react";
import {
  ApiRequestError,
  decideSapSuggestion,
  fetchFinanceStores,
  fetchStoreSapSuggestions,
  submitSapSuggestion,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FinanceImportActionPanel } from "../components/FinanceImportActionPanel";
import { FieldInput, SelectField } from "../components/FormControls";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  AdminUser,
  BillingMetricScope,
  FeeDirection,
  FinanceStoreRow,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";

type SapDecisionAction = "CONFIRM" | "CORRECT" | "REJECT";
type ActionState = "idle" | "loading" | "success" | "error" | "conflict";

function defaultStatementMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function suggestionStatusLabel(status: FinanceStoreRow["suggestionStatus"]): string {
  if (status === null) return "暂无建议";
  return {
    PENDING: "待处理",
    CONFIRMED: "已确认",
    CORRECTED: "修正后确认",
    REJECTED: "已驳回",
  }[status];
}

function actionErrorMessage(error: unknown): { state: ActionState; message: string } {
  const message = userFacingError(error, "操作失败，请稍后重试。");
  return error instanceof ApiRequestError && error.status === 409
    ? { state: "conflict", message: "数据版本已变化，请刷新后重新处理。" }
    : { state: "error", message };
}

interface FinanceStoresPageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
}

export function FinanceStoresPage({ currentUser, searchParams }: FinanceStoresPageProps) {
  const isStore = currentUser.role === "store";
  const [month, setMonth] = useState(searchParams.get("month") ?? defaultStatementMonth());
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [storeId, setStoreId] = useState(
    searchParams.get("storeId") ?? currentUser.store_ids[0] ?? "",
  );
  const [feeDirection, setFeeDirection] = useState<FeeDirection>("PROMOTION");
  const [metricScope, setMetricScope] = useState<BillingMetricScope>("MONTH");
  const [suggestedSapCode, setSuggestedSapCode] = useState("");
  const [suggestionNote, setSuggestionNote] = useState("");
  const [selectedSuggestion, setSelectedSuggestion] = useState<FinanceStoreRow | null>(null);
  const [decisionAction, setDecisionAction] = useState<SapDecisionAction>("CONFIRM");
  const [confirmedSapCode, setConfirmedSapCode] = useState("");
  const [handlingReason, setHandlingReason] = useState("");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [actionMessage, setActionMessage] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  const financeResource = useApiResource(
    () => fetchFinanceStores({ month, feeDirection, metricScope, q: query || undefined, pageSize: 50 }),
    [month, feeDirection, metricScope, query],
    { enabled: !isStore },
  );
  const storeSuggestionResource = useApiResource(
    () => fetchStoreSapSuggestions(storeId),
    [storeId],
    { enabled: isStore && Boolean(storeId) },
  );

  const resetAction = () => {
    setActionState("idle");
    setActionMessage("");
    setIdempotencyKey(crypto.randomUUID());
  };

  const submitStoreSuggestion = async () => {
    if (!storeId || !suggestedSapCode.trim() || !suggestionNote.trim()) return;
    setActionState("loading");
    setActionMessage("");
    try {
      await submitSapSuggestion(
        storeId,
        {
          suggestedSapCode: suggestedSapCode.trim(),
          suggestionNote: suggestionNote.trim(),
          readVersion: storeSuggestionResource.data?.data.currentVersion ?? 0,
        },
        idempotencyKey,
      );
      setSuggestedSapCode("");
      setSuggestionNote("");
      setActionState("success");
      setActionMessage("SAP 建议已提交，等待内部管理员处理；不会阻断账单或开票。");
      setIdempotencyKey(crypto.randomUUID());
      storeSuggestionResource.reload();
    } catch (error) {
      const result = actionErrorMessage(error);
      setActionState(result.state);
      setActionMessage(result.message);
    }
  };

  const openDecision = (row: FinanceStoreRow) => {
    setSelectedSuggestion(row);
    setDecisionAction("CONFIRM");
    setConfirmedSapCode(row.suggestedSapCode ?? "");
    setHandlingReason("");
    resetAction();
  };

  const submitDecision = async () => {
    if (!selectedSuggestion?.suggestionId || !handlingReason.trim()) return;
    if (decisionAction !== "REJECT" && !confirmedSapCode.trim()) return;
    setActionState("loading");
    setActionMessage("");
    try {
      await decideSapSuggestion(
        selectedSuggestion.suggestionId,
        {
          action: decisionAction,
          ...(decisionAction === "REJECT" ? {} : { confirmedSapCode: confirmedSapCode.trim() }),
          handlingReason: handlingReason.trim(),
          suggestionVersion: selectedSuggestion.suggestionVersion,
          expectedConfirmedVersion: selectedSuggestion.confirmedVersion,
        },
        idempotencyKey,
      );
      setActionState("success");
      setActionMessage("SAP 建议处理成功，当前有效版本已刷新。");
      setIdempotencyKey(crypto.randomUUID());
      financeResource.reload();
    } catch (error) {
      const result = actionErrorMessage(error);
      setActionState(result.state);
      setActionMessage(result.message);
    }
  };

  const columns: Column<FinanceStoreRow>[] = [
    { key: "store", title: "门店", minWidth: 210, sticky: true, render: (row) => <span><strong>{row.storeName}</strong><br /><small>{row.storeId}</small></span> },
    { key: "sap", title: "SAP 编码", render: (row) => row.sapCode ?? "-" },
    { key: "suggestion", title: "SAP 建议", minWidth: 190, render: (row) => <span>{row.suggestedSapCode ?? "-"}<br /><small>{suggestionStatusLabel(row.suggestionStatus)} · V{row.suggestionVersion}</small></span> },
    { key: "total", title: "账单总额", align: "right", render: (row) => formatCurrency(row.statementTotalCent) },
    { key: "confirmed", title: "已确认金额", align: "right", render: (row) => formatCurrency(row.confirmedAmountCent) },
    { key: "pending", title: "待开票金额", align: "right", render: (row) => formatCurrency(row.pendingInvoiceAmountCent) },
    { key: "issued", title: "已开票/扣款金额", align: "right", render: (row) => formatCurrency(row.issuedAmountCent) },
    { key: "updated", title: "更新时间", minWidth: 170, render: (row) => formatDateTime(row.suggestionUpdatedAt ?? row.updatedAt) },
    { key: "action", title: "操作", render: (row) => row.suggestionId && row.suggestionStatus === "PENDING" ? <Button onClick={() => openDecision(row)} size="sm" variant="text">处理建议</Button> : null },
  ];

  if (isStore) {
    const suggestions = storeSuggestionResource.data?.data.list ?? [];
    return (
      <div className="page-stack finance-page">
        <section className="page-heading finance-heading"><div><p className="eyebrow">门店账号</p><h1>SAP 编码建议</h1><p>门店 ID 是唯一匹配键；SAP 建议由内部管理员处理，不阻断账单确认、开票或结算。</p></div></section>
        <section className="finance-filter-bar" aria-label="SAP 建议门店">
          <label><span>门店</span><SearchableStoreSelect emptyMessage="没有可用门店" onChange={(value) => { setStoreId(value); resetAction(); }} options={currentUser.store_ids.map((value) => ({ value, label: value }))} placeholder="选择门店" value={storeId} /></label>
        </section>
        <ResourceNotice loading={storeSuggestionResource.loading} error={storeSuggestionResource.error} />
        <section className="content-section finance-registration-card">
          <div className="section-title"><div><h2>提交 SAP 建议</h2><p>当前建议版本 V{storeSuggestionResource.data?.data.currentVersion ?? 0}；当前确认版本 V{storeSuggestionResource.data?.data.confirmedVersion ?? 0}。</p></div></div>
          <div className="finance-form-grid">
            <label><span>建议 SAP 编码</span><FieldInput required value={suggestedSapCode} onChange={(event) => setSuggestedSapCode(event.target.value)} /></label>
            <label><span>说明</span><FieldInput required value={suggestionNote} onChange={(event) => setSuggestionNote(event.target.value)} /></label>
            <div className="finance-form-actions"><Button disabled={!suggestedSapCode.trim() || !suggestionNote.trim()} loading={actionState === "loading"} onClick={submitStoreSuggestion} variant="primary">提交建议</Button></div>
          </div>
          {actionMessage ? <p role={actionState === "error" || actionState === "conflict" ? "alert" : "status"}>{actionMessage}</p> : null}
        </section>
        <section className="content-section"><div className="section-title"><div><h2>建议历史</h2><p>历史版本永久保留。</p></div></div><DataTable columns={[
          { key: "sap", title: "建议 SAP", render: (row) => row.suggestedSapCode },
          { key: "status", title: "状态", render: (row) => row.status },
          { key: "version", title: "建议版本", render: (row) => `V${row.versionNo}` },
          { key: "submitted", title: "提交时间", render: (row) => formatDateTime(row.submittedAt) },
          { key: "reason", title: "处理原因", render: (row) => row.handlingReason ?? "-" },
        ]} rows={suggestions} state={storeSuggestionResource.loading ? "loading" : storeSuggestionResource.error ? "error" : "ready"} /></section>
      </div>
    );
  }

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading"><div><p className="eyebrow">财务管理员</p><h1>门店财务汇总</h1><p>门店 ID 是唯一匹配键；SAP 编码仅作为展示信息，不参与数据匹配。</p></div></section>
      <section className="finance-filter-bar" aria-label="门店财务筛选条件">
        <label><span>账期</span><FieldInput type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
        <label><span>费用方向</span><SearchableStoreSelect emptyMessage="未找到费用方向" onChange={(value) => setFeeDirection(value as FeeDirection)} options={[{ value: "PROMOTION", label: "推广服务费" }, { value: "MANAGEMENT", label: "管理服务费" }]} placeholder="选择费用方向" value={feeDirection} /></label>
        <label><span>指标口径</span><SearchableStoreSelect emptyMessage="未找到指标口径" onChange={(value) => setMetricScope(value as BillingMetricScope)} options={[{ value: "MONTH", label: "单月" }, { value: "CUMULATIVE", label: "累计" }]} placeholder="选择指标口径" value={metricScope} /></label>
        <label><span>搜索门店</span><FieldInput placeholder="门店 ID、名称或 SAP" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      </section>
      <ResourceNotice loading={financeResource.loading} error={financeResource.error} />
      <section className="content-section"><div className="section-title"><div><h2>门店汇总</h2><p>共 {financeResource.data?.data.total ?? 0} 家门店。</p></div></div><DataTable columns={columns} rows={financeResource.data?.data.list ?? []} state={financeResource.loading ? "loading" : financeResource.error ? "error" : "ready"} /></section>
      {selectedSuggestion ? <section className="content-section finance-registration-card">
        <div className="section-title"><div><h2>处理 SAP 建议</h2><p>{selectedSuggestion.storeName} · 建议 V{selectedSuggestion.suggestionVersion} · 确认 V{selectedSuggestion.confirmedVersion}</p></div><Button onClick={() => setSelectedSuggestion(null)} variant="text">关闭</Button></div>
        <ResourcePanel>门店建议：{selectedSuggestion.suggestedSapCode}；说明：{selectedSuggestion.suggestionNote ?? "-"}</ResourcePanel>
        <div className="finance-form-grid">
          <SelectField label="处理动作" onChange={(value) => { const action = value as SapDecisionAction; setDecisionAction(action); if (action === "CONFIRM") setConfirmedSapCode(selectedSuggestion.suggestedSapCode ?? ""); resetAction(); }} options={[{ value: "CONFIRM", label: "确认建议值" }, { value: "CORRECT", label: "修正后确认" }, { value: "REJECT", label: "驳回" }]} value={decisionAction} />
          {decisionAction !== "REJECT" ? <label><span>确认 SAP 编码</span><FieldInput required value={confirmedSapCode} onChange={(event) => setConfirmedSapCode(event.target.value)} /></label> : null}
          <label><span>处理原因</span><FieldInput required value={handlingReason} onChange={(event) => setHandlingReason(event.target.value)} /></label>
          <div className="finance-form-actions"><Button disabled={!handlingReason.trim() || (decisionAction !== "REJECT" && !confirmedSapCode.trim())} loading={actionState === "loading"} onClick={submitDecision} variant="primary">提交处理结果</Button></div>
        </div>
        {actionMessage ? <p role={actionState === "error" || actionState === "conflict" ? "alert" : "status"}>{actionMessage}</p> : null}
      </section> : null}
      <FinanceImportActionPanel scope="STORE" month={month} onCommitted={() => financeResource.reload()} />
    </div>
  );
}
