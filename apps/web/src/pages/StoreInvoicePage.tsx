import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  createPromotionInvoiceLifecycleEvent,
  fetchPromotionInvoiceDetail,
  fetchPromotionInvoiceReplacementCandidates,
  fetchPromotionInvoices,
  fetchStoreBillingStatement,
  fetchStoreBillingStatements,
  registerPromotionInvoice,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  AdminUser,
  BillingMetricScope,
  PromotionInvoiceDetail,
  PromotionInvoiceLifecycleEventType,
  PromotionInvoiceReplacementCandidate,
  PromotionInvoiceRow,
  StoreBillingStatement,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { displayFinanceInvoiceStatus } from "../utils/userFacingLabels";

interface StoreInvoicePageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
}

interface ReplacementContext {
  storeId: string;
  invoiceId: string;
  invoiceNumber: string;
  eventType: PromotionInvoiceLifecycleEventType;
  reason: string;
  releasedStatementMonths: string[];
}

const REPLACEMENT_CONTEXT_STORAGE_PREFIX = "dydata19-promotion-replacement";

function loadReplacementContext(storageKey: string): ReplacementContext | null {
  try {
    const value = window.sessionStorage.getItem(storageKey);
    if (!value) return null;
    const parsed = JSON.parse(value) as ReplacementContext;
    return parsed.storeId && parsed.invoiceId && parsed.invoiceNumber
      ? parsed
      : null;
  } catch {
    return null;
  }
}

const PROMOTION_INVOICE_BUYER_NAME = "比亚迪汽车销售有限公司";
const PROMOTION_INVOICE_BUYER_TAXPAYER_ID = "914403007604674476";
const PROMOTION_INVOICE_TAX_RATE_PERCENT = 6;

function defaultStatementMonth(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${now.getFullYear()}-${month}`;
}

export function StoreInvoicePage({ currentUser, searchParams }: StoreInvoicePageProps) {
  const replacementContextStorageKey = `${REPLACEMENT_CONTEXT_STORAGE_PREFIX}:${
    currentUser.user_id ?? currentUser.username
  }`;
  const [month, setMonth] = useState(
    searchParams.get("month") ?? defaultStatementMonth(),
  );
  const [storeId, setStoreId] = useState(
    searchParams.get("storeId") ??
      loadReplacementContext(replacementContextStorageKey)?.storeId ??
      currentUser.store_ids[0] ??
      "",
  );
  const [metricScope, setMetricScope] =
    useState<BillingMetricScope>("MONTH");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [selectedStatements, setSelectedStatements] = useState<StoreBillingStatement[]>([]);
  const [submitMessage, setSubmitMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [lifecycleInvoiceId, setLifecycleInvoiceId] = useState<string | null>(null);
  const [replacementContext, setReplacementContext] =
    useState<ReplacementContext | null>(() => {
      const restored = loadReplacementContext(replacementContextStorageKey);
      return currentUser.role === "store" &&
        restored?.storeId === storeId &&
        currentUser.store_ids.includes(restored.storeId)
        ? restored
        : null;
    });
  const restoredReplacementInvoiceId = useRef(
    replacementContext?.invoiceId ?? null,
  );
  const [invoiceDetail, setInvoiceDetail] = useState<PromotionInvoiceDetail | null>(null);

  const enabled = Boolean(storeId && month);
  const statementResource = useApiResource(
    () =>
      fetchStoreBillingStatements({
        storeId,
        month,
        metricScope,
        feeDirection: "PROMOTION",
        pageSize: 50,
      }),
    [storeId, month, metricScope],
    { enabled },
  );
  const invoiceResource = useApiResource(
    () => fetchPromotionInvoices({ storeId, month, pageSize: 50 }),
    [storeId, month],
    { enabled },
  );
  const replacementCandidateResource = useApiResource(
    () => fetchPromotionInvoiceReplacementCandidates(storeId),
    [storeId],
    { enabled: enabled && currentUser.role === "store" },
  );

  const statements = statementResource.data?.data.list ?? [];
  const invoices = invoiceResource.data?.data.list ?? [];
  const metrics = statementResource.data?.data.metrics;
  const replacementCandidates =
    replacementCandidateResource.data?.data.list ?? [];
  const registerableStatements = useMemo(
    () =>
      statements.filter(
        (statement) =>
          statement.isCurrent &&
          statement.promotionConfirmation &&
          statement.promotionInvoiceGroupId &&
          statement.promotionInvoiceableAmountCent > 0 &&
          ["PENDING_INVOICE", "REJECTED_REUPLOAD"].includes(
            statement.promotionInvoiceStatus,
          ),
      ),
    [statements],
  );
  const selectedAmountCent = selectedStatements.reduce(
    (total, statement) =>
      total + (statement.promotionConfirmation?.confirmedAmountCent ?? 0),
    0,
  );
  const positiveOriginalAmountCent = selectedStatements.reduce(
    (total, statement) =>
      total + Math.max(statement.promotionConfirmation?.confirmedAmountCent ?? 0, 0),
    0,
  );
  const negativeOffsetAmountCent = selectedStatements.reduce(
    (total, statement) =>
      total + Math.min(statement.promotionConfirmation?.confirmedAmountCent ?? 0, 0),
    0,
  );

  const toggleInvoiceGroup = async (statement: StoreBillingStatement) => {
    if (replacementContext) {
      return;
    }
    const groupId = statement.promotionInvoiceGroupId;
    if (!groupId || statement.promotionInvoiceableAmountCent <= 0) {
      return;
    }
    if (selectedStatements.some((item) => item.promotionInvoiceGroupId === groupId)) {
      setSelectedStatements((current) =>
        current.filter((item) => item.promotionInvoiceGroupId !== groupId),
      );
      return;
    }
    setSubmitMessage("");
    try {
      const visibleStatements = new Map(
        statements.map((item) => [item.statementId, item]),
      );
      const groupStatements = await Promise.all(
        statement.promotionRequiredStatementIds.map(async (statementId) => {
          const visible = visibleStatements.get(statementId);
          if (visible) {
            return visible;
          }
          return (await fetchStoreBillingStatement(statementId)).data;
        }),
      );
      if (
        groupStatements.some(
          (item) =>
            item.promotionInvoiceGroupId !== groupId ||
            item.promotionInvoiceableAmountCent !==
              statement.promotionInvoiceableAmountCent,
        )
      ) {
        throw new Error("抵扣组已变化，请刷新后重新选择。");
      }
      setSelectedStatements((current) => {
        const next = new Map(current.map((item) => [item.statementId, item]));
        groupStatements.forEach((item) => next.set(item.statementId, item));
        return [...next.values()].sort((left, right) =>
          left.month.localeCompare(right.month),
        );
      });
    } catch (error) {
      setSubmitMessage(userFacingError(error, "抵扣组加载失败。"));
    }
  };

  const loadReleasedStatements = async (context: ReplacementContext) => {
    const responses = await Promise.all(
      context.releasedStatementMonths.map((releasedMonth) =>
        fetchStoreBillingStatements({
          storeId: context.storeId,
          month: releasedMonth,
          metricScope: "MONTH",
          feeDirection: "PROMOTION",
          pageSize: 50,
        }),
      ),
    );
    const releasedStatements = responses
      .flatMap((response) => response.data.list)
      .filter(
        (statement) =>
          statement.isCurrent &&
          statement.promotionConfirmation &&
          context.releasedStatementMonths.includes(statement.month),
      );
    const loadedMonths = new Set(releasedStatements.map((statement) => statement.month));
    if (
      context.releasedStatementMonths.some(
        (releasedMonth) => !loadedMonths.has(releasedMonth),
      )
    ) {
      throw new Error("未能加载全部已释放的当前账单，请重试。");
    }
    if (
      releasedStatements.some(
        (statement) =>
          !statement.promotionInvoiceGroupId ||
          statement.promotionInvoiceableAmountCent <= 0,
      )
    ) {
      throw new Error("已释放账期仍在结转抵扣中，形成正数净额后才能登记替换发票。");
    }
    const visibleById = new Map(
      releasedStatements.map((statement) => [statement.statementId, statement]),
    );
    const requiredGroupByStatementId = new Map<string, string>();
    releasedStatements.forEach((statement) => {
      statement.promotionRequiredStatementIds.forEach((statementId) => {
        const previousGroup = requiredGroupByStatementId.get(statementId);
        if (previousGroup && previousGroup !== statement.promotionInvoiceGroupId) {
          throw new Error("释放账期对应的抵扣组已变化，请重试。");
        }
        requiredGroupByStatementId.set(
          statementId,
          statement.promotionInvoiceGroupId as string,
        );
      });
    });
    const expandedStatements = await Promise.all(
      [...requiredGroupByStatementId.entries()].map(async ([statementId, groupId]) => {
        const statement = visibleById.get(statementId) ??
          (await fetchStoreBillingStatement(statementId)).data;
        if (statement.promotionInvoiceGroupId !== groupId) {
          throw new Error("抵扣组已变化，请刷新后重新选择。");
        }
        return statement;
      }),
    );
    setSelectedStatements(
      expandedStatements.sort((left, right) => left.month.localeCompare(right.month)),
    );
    if (context.releasedStatementMonths[0]) {
      setMonth(context.releasedStatementMonths[0]);
    }
  };

  useEffect(() => {
    if (
      !replacementContext ||
      restoredReplacementInvoiceId.current !== replacementContext.invoiceId
    ) {
      return;
    }
    restoredReplacementInvoiceId.current = null;
    setSubmitting(true);
    setSubmitMessage("");
    void loadReleasedStatements(replacementContext)
      .then(() => setSubmitMessage("已恢复待替换发票并加载完整账期组。"))
      .catch((error) =>
        setSubmitMessage(
          userFacingError(error, "待替换发票恢复失败。"),
        ),
      )
      .finally(() => setSubmitting(false));
  }, [replacementContext?.invoiceId]);

  const resumeReplacementCandidate = async (
    candidate: PromotionInvoiceReplacementCandidate,
  ) => {
    const context: ReplacementContext = {
      storeId,
      invoiceId: candidate.invoice.invoiceId,
      invoiceNumber: candidate.invoice.invoiceNumber,
      eventType: candidate.lifecycleEvent.eventType,
      reason: candidate.lifecycleEvent.reason,
      releasedStatementMonths: candidate.releasedStatementMonths,
    };
    setReplacementContext(context);
    window.sessionStorage.setItem(
      replacementContextStorageKey,
      JSON.stringify(context),
    );
    setSubmitting(true);
    setSubmitMessage("");
    try {
      await loadReleasedStatements(context);
      setSubmitMessage("已恢复待替换发票并加载完整账期组。");
    } catch (error) {
      setSubmitMessage(
        userFacingError(error, "待替换发票恢复失败。"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleInvoiceHistory = async (invoiceId: string) => {
    setSubmitMessage("");
    try {
      const result = await fetchPromotionInvoiceDetail(invoiceId);
      setInvoiceDetail(result.data);
    } catch (error) {
      setSubmitMessage(userFacingError(error, "发票历史加载失败。"));
    }
  };

  const handleLifecycleEvent = async (
    row: PromotionInvoiceRow,
    eventType: PromotionInvoiceLifecycleEventType,
  ) => {
    const actionLabel = eventType === "RED_FLUSHED" ? "红冲" : "作废";
    const reason = window.prompt(`请输入系统外${actionLabel}原因`);
    if (!reason?.trim()) {
      return;
    }
    if (!window.confirm(`确认该发票已在系统外完成${actionLabel}？系统只登记事实并释放全部账期。`)) {
      return;
    }
    setLifecycleInvoiceId(row.invoiceId);
    setSubmitMessage("");
    let lifecycleRecorded = false;
    try {
      const result = await createPromotionInvoiceLifecycleEvent(
        row.invoiceId,
        { eventType, reason: reason.trim(), readVersion: row.versionNo },
        crypto.randomUUID(),
      );
      const releasedMonths = result.data.releasedStatementMonths;
      lifecycleRecorded = true;
      const nextReplacementContext: ReplacementContext = {
        storeId: row.storeId,
        invoiceId: row.invoiceId,
        invoiceNumber: row.invoiceNumber,
        eventType,
        reason: reason.trim(),
        releasedStatementMonths: releasedMonths,
      };
      setReplacementContext(nextReplacementContext);
      window.sessionStorage.setItem(
        replacementContextStorageKey,
        JSON.stringify(nextReplacementContext),
      );
      setInvoiceDetail(null);
      statementResource.reload();
      invoiceResource.reload();
      replacementCandidateResource.reload();
      await loadReleasedStatements(nextReplacementContext);
      setSubmitMessage(`已登记系统外${actionLabel}事实；请使用新发票号码覆盖全部释放账期。`);
    } catch (error) {
      const message = userFacingError(error, `${actionLabel}登记失败。`);
      setSubmitMessage(
        lifecycleRecorded
          ? `系统外${actionLabel}事实已登记，但释放账期自动加载失败：${message}`
          : message,
      );
    } finally {
      setLifecycleInvoiceId(null);
    }
  };

  const statementColumns: Column<StoreBillingStatement>[] = [
    { key: "month", title: "账期", render: (row) => row.month },
    { key: "version", title: "账单版本", render: (row) => `V${row.versionNo}` },
    {
      key: "amount",
      title: "推广服务费",
      align: "right",
      render: (row) => formatCurrency(row.promotionAmountCent),
    },
    {
      key: "confirmed",
      title: "已确认金额",
      align: "right",
      render: (row) =>
        formatCurrency(row.promotionConfirmation?.confirmedAmountCent ?? 0),
    },
    {
      key: "invoiceable",
      title: "抵扣与可开票",
      minWidth: 260,
      render: (row) => {
        const confirmedAmount =
          row.promotionConfirmation?.confirmedAmountCent ?? 0;
        if (confirmedAmount < 0) {
          return `结转抵扣中 · 当前结转余额 ${formatCurrency(row.promotionCarryforwardBalanceCent)}`;
        }
        if (!row.promotionInvoiceGroupId) {
          return "-";
        }
        return `抵扣前 ${formatCurrency(row.promotionPositiveAmountCent)} · 负数抵扣 ${formatCurrency(row.promotionNegativeAmountCent)} · 可开票净额 ${formatCurrency(row.promotionInvoiceableAmountCent)}`;
      },
    },
    {
      key: "status",
      title: "发票状态",
      render: (row) => displayFinanceInvoiceStatus(row.promotionInvoiceStatus),
    },
    {
      key: "management",
      title: "管理服务费 / 状态",
      align: "right",
      render: (row) => `${formatCurrency(row.managementAmountCent)} · ${displayFinanceInvoiceStatus(row.managementInvoiceStatus)}`,
    },
    {
      key: "allocation",
      title: "抵扣组",
      render: (row) => {
        const eligible = registerableStatements.some(
          (item) => item.statementId === row.statementId,
        );
        const selected = selectedStatements.some(
          (item) =>
            item.promotionInvoiceGroupId === row.promotionInvoiceGroupId,
        );
        if ((row.promotionConfirmation?.confirmedAmountCent ?? 0) < 0 && !eligible) {
          return "结转抵扣中";
        }
        return eligible ? (
          <Button
            disabled={Boolean(replacementContext)}
            onClick={() => void toggleInvoiceGroup(row)}
            size="sm"
            variant={selected ? "secondary" : "text"}
          >
            {selected ? "移除整组" : "选择抵扣组"}
          </Button>
        ) : "-";
      },
    },
  ];

  const invoiceColumns: Column<PromotionInvoiceRow>[] = [
    { key: "number", title: "发票号码", minWidth: 210, render: (row) => row.invoiceNumber },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "batch", title: "结算批次", render: (row) => row.settlementBatchMonth },
    { key: "date", title: "开票日期", render: (row) => row.invoiceDate },
    {
      key: "amount",
      title: "已开票金额",
      align: "right",
      render: (row) => formatCurrency(row.allocatedAmountCent),
    },
    { key: "status", title: "状态", render: (row) => displayFinanceInvoiceStatus(row.status) },
    { key: "time", title: "系统登记时间", render: (row) => formatDateTime(row.registeredAt) },
    {
      key: "actions",
      title: "操作",
      minWidth: 250,
      render: (row) => (
        <div className="table-actions">
          <Button onClick={() => handleInvoiceHistory(row.invoiceId)} size="sm" variant="text">
            历史
          </Button>
          {currentUser.role === "store" && row.isCurrent ? (
            <>
              <Button
                loading={lifecycleInvoiceId === row.invoiceId}
                onClick={() => handleLifecycleEvent(row, "RED_FLUSHED")}
                size="sm"
                variant="text"
              >
                登记红冲
              </Button>
              <Button
                loading={lifecycleInvoiceId === row.invoiceId}
                onClick={() => handleLifecycleEvent(row, "VOIDED")}
                size="sm"
                variant="danger"
              >
                登记作废
              </Button>
            </>
          ) : null}
        </div>
      ),
    },
  ];

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (selectedStatements.length === 0) {
      setSubmitMessage("请至少选择一个可登记的已确认推广费账期。");
      return;
    }
    if (
      selectedAmountCent <= 0 ||
      selectedStatements.some((statement) => !statement.promotionInvoiceGroupId)
    ) {
      setSubmitMessage("所选抵扣组尚未形成正数净开票金额，请刷新后重新选择。");
      return;
    }
    setSubmitting(true);
    setSubmitMessage("");
    const replacedInvoiceId = replacementContext?.invoiceId ?? null;
    try {
      await registerPromotionInvoice(
        {
          storeId,
          buyerName: PROMOTION_INVOICE_BUYER_NAME,
          taxRatePercent: PROMOTION_INVOICE_TAX_RATE_PERCENT,
          invoiceNumber: invoiceNumber.trim(),
          invoiceDate,
          invoiceAmountCent: selectedAmountCent,
          ...(replacementContext
            ? { replacesInvoiceId: replacementContext.invoiceId }
            : {}),
          allocations: selectedStatements.map((statement) => ({
            statementId: statement.statementId,
            statementMonth: statement.month,
            allocatedAmountCent:
              statement.promotionConfirmation?.confirmedAmountCent ?? 0,
            readVersion: statement.versionNo,
            promotionInvoiceGroupId: statement.promotionInvoiceGroupId ?? "",
          })),
        },
        crypto.randomUUID(),
      );
      if (replacedInvoiceId) {
        const refreshedDetail = await fetchPromotionInvoiceDetail(replacedInvoiceId);
        setInvoiceDetail(refreshedDetail.data);
      }
      setInvoiceNumber("");
      setInvoiceDate("");
      setSelectedStatements([]);
      setReplacementContext(null);
      window.sessionStorage.removeItem(replacementContextStorageKey);
      setSubmitMessage("发票信息已登记，状态已更新。");
      statementResource.reload();
      invoiceResource.reload();
      replacementCandidateResource.reload();
    } catch (error) {
      setSubmitMessage(userFacingError(error, "登记失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">门店结算</p>
          <h1>开票确认</h1>
          <p>开票在系统外完成；系统不创建开票申请单，也不负责真正开票，只登记信息和回传状态。</p>
        </div>
      </section>

      <section className="finance-filter-bar" aria-label="开票筛选条件">
        <label>
          <span>门店 ID</span>
          <FieldInput
            value={storeId}
            onChange={(event) => {
              setStoreId(event.target.value);
              setSelectedStatements([]);
              setReplacementContext(null);
              window.sessionStorage.removeItem(replacementContextStorageKey);
              setInvoiceDetail(null);
            }}
          />
        </label>
        <label>
          <span>账期</span>
          <FieldInput type="month" value={month} onChange={(event) => setMonth(event.target.value)} />
        </label>
        <label>
          <span>指标口径</span>
          <SearchableStoreSelect
            emptyMessage="未找到指标口径"
            onChange={(value) => setMetricScope(value as BillingMetricScope)}
            options={[
              { value: "MONTH", label: "单月" },
              { value: "CUMULATIVE", label: "累计" },
            ]}
            placeholder="选择指标口径"
            value={metricScope}
          />
        </label>
      </section>

      <ResourceNotice
        loading={statementResource.loading || invoiceResource.loading || replacementCandidateResource.loading}
        error={statementResource.error ?? invoiceResource.error ?? replacementCandidateResource.error}
      />

      <section className="metric-grid metric-grid--three">
        <MetricCard label="推广服务费账单" value={formatCurrency((metricScope === "CUMULATIVE" ? metrics?.cumulative : metrics?.month)?.promotionAmountCent ?? 0)} />
        <MetricCard label="管理服务费账单" value={formatCurrency((metricScope === "CUMULATIVE" ? metrics?.cumulative : metrics?.month)?.managementAmountCent ?? 0)} />
        <MetricCard label="本张发票已选金额" value={formatCurrency(selectedAmountCent)} />
      </section>

      <section className="content-section">
        <div className="section-title">
          <div><h2>推广费账单</h2><p>逐月筛选并把一个或多个完整账期加入同一张发票；已选账期会跨筛选月份保留。</p></div>
        </div>
        <DataTable columns={statementColumns} rows={statements} state={statementResource.loading ? "loading" : statementResource.error ? "error" : "ready"} />
      </section>

      <section className="content-section finance-registration-card">
        <div className="section-title">
          <div><h2>登记发票信息</h2><p>系统校验提交内容无误的服务器时间作为成功登记时间。</p></div>
        </div>
        {!replacementContext && replacementCandidates.length > 0 ? (
          <ResourcePanel>
            <strong>有 {replacementCandidates.length} 张发票等待继续替换</strong>
            {replacementCandidates.map((candidate) => (
              <Button
                key={candidate.invoice.invoiceId}
                onClick={() => void resumeReplacementCandidate(candidate)}
                size="sm"
                variant="text"
              >
                恢复替换 {candidate.invoice.invoiceNumber}
              </Button>
            ))}
          </ResourcePanel>
        ) : null}
        {replacementContext ? (
          <ResourcePanel>
            替换原发票 {replacementContext.invoiceNumber}；系统外
            {replacementContext.eventType === "RED_FLUSHED" ? "红冲" : "作废"}
            原因：{replacementContext.reason}；必须使用新发票号码覆盖账期
            {replacementContext.releasedStatementMonths.join("、")}。
            <Button
              onClick={() => {
                setSubmitting(true);
                loadReleasedStatements(replacementContext)
                  .then(() => setSubmitMessage("已重新加载全部释放账期。"))
                  .catch((error) => setSubmitMessage(
                    userFacingError(error, "释放账期加载失败。"),
                  ))
                  .finally(() => setSubmitting(false));
              }}
              size="sm"
              variant="text"
            >
              重新加载释放账期
            </Button>
          </ResourcePanel>
        ) : null}
        {selectedStatements.length === 0 ? (
          <ResourcePanel>请从推广费账单中加入至少一个可登记账期。</ResourcePanel>
        ) : (
          <form className="finance-form-grid" onSubmit={handleSubmit}>
            <div className="finance-selected-periods">
              <span>已选账期</span>
              <strong>{selectedStatements.map((statement) => statement.month).join("、")}</strong>
            </div>
            <div className="finance-selected-periods">
              <span>正数原费用</span>
              <strong>{formatCurrency(positiveOriginalAmountCent)}</strong>
            </div>
            <div className="finance-selected-periods">
              <span>负数抵扣</span>
              <strong>{formatCurrency(negativeOffsetAmountCent)}</strong>
            </div>
            <div className="finance-selected-periods">
              <span>净开票金额</span>
              <strong>{formatCurrency(selectedAmountCent)}</strong>
            </div>
            <label>
              <span>购买方名称</span>
              <FieldInput disabled value={PROMOTION_INVOICE_BUYER_NAME} />
            </label>
            <label>
              <span>购买方纳税人识别号</span>
              <FieldInput disabled value={PROMOTION_INVOICE_BUYER_TAXPAYER_ID} />
            </label>
            <label>
              <span>税率</span>
              <FieldInput disabled value={`${PROMOTION_INVOICE_TAX_RATE_PERCENT}%`} />
            </label>
            <label>
              <span>20 位数电专票号码</span>
              <FieldInput inputMode="numeric" maxLength={20} minLength={20} pattern="[0-9]{20}" required value={invoiceNumber} onChange={(event) => setInvoiceNumber(event.target.value)} />
            </label>
            <label>
              <span>开票日期</span>
              <FieldInput type="date" required value={invoiceDate} onChange={(event) => setInvoiceDate(event.target.value)} />
            </label>
            <label>
              <span>发票金额</span>
              <FieldInput disabled value={formatCurrency(selectedAmountCent)} />
            </label>
            <div className="finance-form-actions">
              <Button loading={submitting} type="submit" variant="primary">登记并提交</Button>
            </div>
          </form>
        )}
        {submitMessage ? <p role="status">{submitMessage}</p> : null}
      </section>

      <section className="content-section">
        <div className="section-title"><div><h2>开票记录</h2><p>只展示当前有效记录及管理员导入后的状态。</p></div></div>
        <DataTable columns={invoiceColumns} rows={invoices} state={invoiceResource.loading ? "loading" : invoiceResource.error ? "error" : "ready"} />
        {invoiceDetail ? (
          <ResourcePanel>
            <strong>发票 {invoiceDetail.invoiceNumber} 历史</strong>
            <p>物理发票版本：{invoiceDetail.versions.length}；厂家状态事件：{invoiceDetail.statusEvents.length}。</p>
            {invoiceDetail.lifecycleEvents.length > 0 ? (
              <p>
                生命周期事件：{invoiceDetail.lifecycleEvents.map((event) =>
                  `${event.eventType === "RED_FLUSHED" ? "红冲" : "作废"}（${event.reason}）`,
                ).join("、")}
              </p>
            ) : <p>暂无红冲或作废记录。</p>}
            {invoiceDetail.replacements.length > 0 ? (
              <p>替换发票：{invoiceDetail.replacements.map((item) => item.invoiceNumber).join("、")}</p>
            ) : null}
            {invoiceDetail.replacementChain.length > 1 ? (
              <p>替换链：{invoiceDetail.replacementChain.map((item) => item.invoiceNumber).join(" → ")}</p>
            ) : null}
          </ResourcePanel>
        ) : null}
      </section>
    </div>
  );
}
