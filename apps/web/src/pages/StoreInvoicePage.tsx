import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiRequestError,
  fetchPromotionInvoiceReplacementCandidates,
  fetchPromotionInvoices,
  fetchSettlementFilterMeta,
  fetchStoreBillingStatement,
  fetchStoreBillingStatements,
  registerPromotionInvoice,
  type ApiLoadResult,
} from "../api/client";
import { Button } from "../components/Button";
import { FieldInput } from "../components/FormControls";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { StoreFinanceTimeline } from "../components/StoreFinanceTimeline";
import { useApiResource } from "../hooks/useApiResource";
import type {
  AdminUser,
  BillingMetricScope,
  PromotionInvoiceLifecycleEventType,
  PromotionInvoiceReplacementCandidate,
  StoreBillingStatement,
  StoreBillingStatementListData,
  PromotionInvoiceSummary,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { createPendingRequestKey } from "../utils/pendingRequestKey";
import { initialStatementMonth, previousShanghaiStatementMonth } from "../utils/statementMonth";

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
const PROMOTION_INVOICE_BUYER_ADDRESS = "深圳市坪山新区坪山街道比亚迪路3005号";
const PROMOTION_INVOICE_BUYER_PHONE = "0755-89888888";
const PROMOTION_INVOICE_BUYER_BANK = "农行龙岗支行 41022900040008463";
const PROMOTION_INVOICE_PROJECT_NAME = "推广服务费";
const PROMOTION_INVOICE_TAX_CLASSIFICATION = "3079900000000000000";

interface InvoiceRegistrationValidationInput {
  fillerPhone: string;
  invoiceDate: string;
  invoiceNumber: string;
  invoiceNumbers: string[];
  summaryReady: boolean;
}

interface InvoiceValidationItem {
  key: string;
  label: string;
  passed: boolean;
}

export function validateInvoiceRegistration({
  fillerPhone, invoiceDate, invoiceNumber, invoiceNumbers, summaryReady,
}: InvoiceRegistrationValidationInput): InvoiceValidationItem[] {
  return [
    { key: "selected-statements", label: "系统已确定可开票的完整账期及金额", passed: summaryReady },
    { key: "invoice-number", label: "数电专票号码必须为20位半角数字且不得重复",
      passed: /^[0-9]{20}$/.test(invoiceNumber) && !invoiceNumbers.includes(invoiceNumber) },
    { key: "invoice-date", label: "开票日期必须填写，日期边界由服务器最终校验", passed: Boolean(invoiceDate) },
    { key: "filler-phone", label: "请填写开票信息填写人电话", passed: Boolean(fillerPhone.trim()) },
  ];
}

function isRegisterablePromotionStatement(statement: StoreBillingStatement): boolean {
  return Boolean(
    statement.isCurrent &&
      statement.promotionConfirmation &&
      statement.promotionInvoiceGroupId &&
      statement.promotionInvoiceableAmountCent > 0 &&
      ["PENDING_INVOICE", "REJECTED_REUPLOAD"].includes(
        statement.promotionInvoiceStatus,
      ),
  );
}

export function selectAllRegisterableInvoiceStatements(
  statements: StoreBillingStatement[],
  currentMonth: string,
): StoreBillingStatement[] {
  const visibleById = new Map(
    statements.map((statement) => [statement.statementId, statement]),
  );
  const registerable = statements
    .filter(
      (statement) =>
        statement.month <= currentMonth &&
        isRegisterablePromotionStatement(statement),
    );
  const registerableGroupIds = new Set(
    registerable.map((statement) => statement.promotionInvoiceGroupId),
  );
  const selectedStatementIds = new Set<string>();
  registerable.forEach((statement) => {
    if (!registerableGroupIds.has(statement.promotionInvoiceGroupId)) return;
    selectedStatementIds.add(statement.statementId);
    statement.promotionRequiredStatementIds.forEach((statementId) =>
      selectedStatementIds.add(statementId),
    );
  });
  return [...selectedStatementIds]
    .map((statementId) => visibleById.get(statementId))
    .filter((statement): statement is StoreBillingStatement => Boolean(statement))
    .sort(
      (left, right) =>
        left.month.localeCompare(right.month) ||
        left.statementId.localeCompare(right.statementId),
    );
}

interface SystemSelectedInvoiceGroupData extends StoreBillingStatementListData {
  selectedMonth: string;
  selectedGroupStatements: StoreBillingStatement[];
  selectedMonthStatements: StoreBillingStatement[];
}

async function loadSystemSelectedInvoiceGroup({
  currentMonth,
  formalPeriodStartMonth,
  metricScope,
  statementMonths,
  storeId,
}: {
  currentMonth: string;
  formalPeriodStartMonth: string;
  metricScope: BillingMetricScope;
  statementMonths: string[];
  storeId: string;
}): Promise<ApiLoadResult<SystemSelectedInvoiceGroupData>> {
  // The server summary owns all required carry-forward groups. Reading every
  // unrelated historical month made one failed request hide valid amounts.
  // Detail reads are restricted to the server's exact required IDs instead.
  void statementMonths;
  const selectedResponse = await fetchStoreBillingStatements({
    storeId, month: currentMonth, metricScope, feeDirection: "PROMOTION", pageSize: 50,
  });
  const summary = selectedResponse.data.promotionInvoiceSummary;
  const requiredIds = summary?.requiredStatementIds ?? [];
  if (new Set(requiredIds).size !== requiredIds.length || requiredIds.length > 240) {
    throw new Error("可开票账期组不完整，请刷新或联系管理员。");
  }
  const selectedMonth = currentMonth;
  const visibleStatements = new Map(
    selectedResponse.data.list.map((statement) => [statement.statementId, statement]),
  );
  const requiredStatements = await Promise.all(
    requiredIds.map(
      async (statementId) => {
        const statement =
          visibleStatements.get(statementId) ??
          (await fetchStoreBillingStatement(statementId)).data;
        if (
          statement.storeId !== storeId ||
          !statement.isCurrent ||
          statement.month < formalPeriodStartMonth ||
          statement.month > previousShanghaiStatementMonth() ||
          !isRegisterablePromotionStatement(statement) ||
          statement.promotionRequiredStatementIds.some((id) => !requiredIds.includes(id))
        ) {
          throw new Error("抵扣组已变化，请刷新后重试。");
        }
        return statement;
      },
    ),
  );
  const groupByRequiredId = new Map<string, string>();
  requiredStatements.forEach((statement) => {
    statement.promotionRequiredStatementIds.forEach((id) => {
      const previous = groupByRequiredId.get(id);
      if (previous && previous !== statement.promotionInvoiceGroupId) {
        throw new Error("抵扣组已变化，请刷新后重试。");
      }
      groupByRequiredId.set(id, statement.promotionInvoiceGroupId ?? "");
    });
  });
  const selectedGroupStatements = selectAllRegisterableInvoiceStatements(requiredStatements, previousShanghaiStatementMonth());
  if (selectedGroupStatements.length !== requiredIds.length) {
    throw new Error("可开票账期组已变化，请刷新后重试。");
  }
  selectedGroupStatements.sort(
    (left, right) =>
      left.month.localeCompare(right.month) ||
      left.statementId.localeCompare(right.statementId),
  );

  return {
    ...selectedResponse,
    data: {
      ...selectedResponse.data,
      list: selectedGroupStatements,
      total: selectedGroupStatements.length,
      selectedMonth,
      selectedGroupStatements,
      selectedMonthStatements: selectedResponse.data.list,
    },
  };
}

export function StoreInvoicePage({ currentUser, searchParams }: StoreInvoicePageProps) {
  const replacementContextStorageKey = `${REPLACEMENT_CONTEXT_STORAGE_PREFIX}:${
    currentUser.user_id ?? currentUser.username
  }`;
  const restoredReplacementContext = loadReplacementContext(
    replacementContextStorageKey,
  );
  const requestedStoreId =
    searchParams.get("storeId") ?? searchParams.get("store_id") ?? "";
  const initialStoreId =
    currentUser.role === "store"
      ? restoredReplacementContext &&
        currentUser.store_ids.includes(restoredReplacementContext.storeId)
        ? restoredReplacementContext.storeId
        : currentUser.store_ids.includes(requestedStoreId)
          ? requestedStoreId
          : currentUser.store_ids[0] ?? ""
      : requestedStoreId || restoredReplacementContext?.storeId || currentUser.store_ids[0] || "";
  const [month, setMonth] = useState(() => initialStatementMonth(searchParams));
  const [storeId, setStoreId] = useState(
    initialStoreId,
  );
  const [metricScope] = useState<BillingMetricScope>("MONTH");
  const [fillerPhone, setFillerPhone] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [selectedStatements, setSelectedStatements] = useState<StoreBillingStatement[]>([]);
  const [invoiceSummary, setInvoiceSummary] = useState<PromotionInvoiceSummary | null>(null);
  const [submitMessage, setSubmitMessage] = useState("");
  const [showValidationFeedback, setShowValidationFeedback] = useState(false);
  const [registrationFailed, setRegistrationFailed] = useState(false);
  const [copyMessage, setCopyMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [replacementContext, setReplacementContext] =
    useState<ReplacementContext | null>(() => {
      const restored = restoredReplacementContext;
      if (
        restored &&
        restored.storeId === storeId &&
        (currentUser.role !== "store" || currentUser.store_ids.includes(restored.storeId))
      ) {
        return restored;
      }
      return null;
    });
  const restoredReplacementInvoiceId = useRef(
    replacementContext?.invoiceId ?? null,
  );
  const invoiceFormRef = useRef<HTMLFormElement | null>(null);
  const submitInFlight = useRef(false);
  const invoiceRequest = useRef(createPendingRequestKey());

  const enabled = Boolean(storeId && month);
  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const filterMeta = metaResource.data?.data;
  const currentPeriodMonth = initialStatementMonth(searchParams);
  const statementResource = useApiResource(
    () =>
      loadSystemSelectedInvoiceGroup({
        currentMonth: currentPeriodMonth,
        formalPeriodStartMonth: filterMeta?.formalPeriodStartMonth ?? currentPeriodMonth,
        statementMonths: filterMeta?.statementMonths ?? [],
        storeId,
        metricScope,
      }),
    [
      storeId,
      metricScope,
      currentPeriodMonth,
      filterMeta?.formalPeriodStartMonth,
      filterMeta?.statementMonths.join("|"),
      replacementContext?.invoiceId,
    ],
    { enabled: Boolean(storeId && filterMeta && currentPeriodMonth && !replacementContext), clearOnReload: true },
  );
  const invoiceResource = useApiResource(
    () => fetchPromotionInvoices({ storeId, month, pageSize: 50 }),
    [storeId, month],
    { enabled },
  );
  const replacementCandidateResource = useApiResource(
    () => fetchPromotionInvoiceReplacementCandidates(storeId),
    [storeId],
    { enabled },
  );

  useEffect(() => {
    if (storeId) return;
    const accountStoreId = currentUser.store_ids[0] || filterMeta?.stores[0]?.storeId || "";
    if (accountStoreId) setStoreId(accountStoreId);
  }, [currentUser.store_ids, filterMeta?.stores, storeId]);

  useEffect(() => {
    if (!replacementContext && month !== currentPeriodMonth) {
      setMonth(currentPeriodMonth);
    }
  }, [currentPeriodMonth, month, replacementContext]);

  const invoices = invoiceResource.data?.data.list ?? [];
  const replacementCandidates =
    replacementCandidateResource.data?.data.list ?? [];
  const summaryReady = Boolean(
    invoiceSummary && invoiceSummary.invoiceAmountCent > 0 &&
    invoiceSummary.requiredStatementIds.length === selectedStatements.length &&
    selectedStatements.every((statement) =>
      invoiceSummary.requiredStatementIds.includes(statement.statementId) &&
      statement.isCurrent && statement.promotionConfirmation && statement.promotionInvoiceGroupId),
  );
  const displayInvoiceSummary = summaryReady ? invoiceSummary : null;
  const selectedMonthStatements = statementResource.data?.data.selectedMonthStatements ?? [];
  const invoiceAmountPlaceholder = metaResource.loading || statementResource.loading
    ? "正在读取账单金额"
    : metaResource.error || statementResource.error
      ? "账单金额读取失败，请重试"
      : !storeId
        ? "请选择有权限的门店"
        : selectedMonthStatements.length === 0
          ? "所选账期尚无账单"
          : selectedMonthStatements.some((statement) => !statement.promotionConfirmation)
            ? "账单待确认，尚不可开票"
            : selectedMonthStatements.every((statement) => statement.promotionAmountCent === 0)
              ? "本期金额为0，无需开票"
              : "当前无待开票金额，请核对开票或结转状态";
  const invoiceValidationItems = validateInvoiceRegistration({
    fillerPhone, invoiceDate, invoiceNumber,
    invoiceNumbers: invoices.map((invoice) => invoice.invoiceNumber),
    summaryReady,
  });
  const failedInvoiceValidationItems = invoiceValidationItems.filter(
    (item) => !item.passed,
  );

  const copyInvoiceInfo = async () => {
    const lines = [
      `名称：${PROMOTION_INVOICE_BUYER_NAME}`,
      `纳税人识别号：${PROMOTION_INVOICE_BUYER_TAXPAYER_ID}`,
      `地址：${PROMOTION_INVOICE_BUYER_ADDRESS}`,
      `电话：${PROMOTION_INVOICE_BUYER_PHONE}`,
      `开户行及账号：${PROMOTION_INVOICE_BUYER_BANK}`,
      `项目名称：${PROMOTION_INVOICE_PROJECT_NAME}`,
      `税收分类编码：${PROMOTION_INVOICE_TAX_CLASSIFICATION}`,
      `税率：${PROMOTION_INVOICE_TAX_RATE_PERCENT}%`,
      `价税合计（含税总额）：${displayInvoiceSummary ? formatCurrency(displayInvoiceSummary.invoiceAmountCent) : invoiceAmountPlaceholder}`,
      `不含税金额：${displayInvoiceSummary ? formatCurrency(displayInvoiceSummary.netAmountCent) : invoiceAmountPlaceholder}`,
      `税额：${displayInvoiceSummary ? formatCurrency(displayInvoiceSummary.taxAmountCent) : invoiceAmountPlaceholder}`,
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyMessage("开票信息已复制。");
      invoiceFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch {
      setCopyMessage("复制失败，请手动选择下方开票信息。");
    }
  };

  const loadReleasedStatements = async (context: ReplacementContext) => {
    setSelectedStatements([]);
    setInvoiceSummary(null);
    const result = await loadSystemSelectedInvoiceGroup({
      currentMonth: currentPeriodMonth,
      formalPeriodStartMonth: filterMeta?.formalPeriodStartMonth ?? currentPeriodMonth,
      statementMonths: [...(filterMeta?.statementMonths ?? []), ...context.releasedStatementMonths],
      storeId: context.storeId,
      metricScope: "MONTH",
    });
    const statements = result.data.selectedGroupStatements;
    if (context.releasedStatementMonths.some((releasedMonth) =>
      !statements.some((statement) => statement.month === releasedMonth))) {
      throw new Error("未能加载全部已释放的当前账单，请重试。");
    }
    setSelectedStatements(statements);
    setInvoiceSummary(result.data.promotionInvoiceSummary ?? null);
    setMonth(result.data.selectedMonth);
  };

  useEffect(() => {
    const automaticSelection = statementResource.data?.data;
    if (replacementContext) return;
    if (!automaticSelection || statementResource.error) {
      setSelectedStatements([]);
      setInvoiceSummary(null);
      return;
    }
    setMonth(automaticSelection.selectedMonth);
    setSelectedStatements(automaticSelection.selectedGroupStatements);
    setInvoiceSummary(automaticSelection.promotionInvoiceSummary ?? null);
  }, [statementResource.data, statementResource.error, replacementContext]);

  useEffect(() => {
    if (
      !replacementContext ||
      !filterMeta || !currentPeriodMonth ||
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
  }, [replacementContext?.invoiceId, currentPeriodMonth, filterMeta]);

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

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitInFlight.current) return;
    setRegistrationFailed(false);
    setShowValidationFeedback(true);
    const failedValidation = invoiceValidationItems.find((item) => !item.passed);
    if (failedValidation) {
      setSubmitMessage(`核验未通过：${failedValidation.label}。`);
      return;
    }
    if (selectedStatements.length === 0) {
      setSubmitMessage("当前系统账期尚无可登记的已确认推广服务费。");
      return;
    }
    if (!summaryReady) {
      setSubmitMessage("可开票账期或金额已变化，请刷新后重试。");
      return;
    }
    submitInFlight.current = true;
    setSubmitting(true);
    setSubmitMessage("");
    try {
      const payload = {
          storeId,
          fillerPhone: fillerPhone.trim(),
          invoiceNumber,
          invoiceDate,
          ...(replacementContext
            ? { replacesInvoiceId: replacementContext.invoiceId }
            : {}),
          allocations: selectedStatements.map((statement) => ({
            statementId: statement.statementId,
            statementMonth: statement.month,
            readVersion: statement.versionNo,
            promotionInvoiceGroupId: statement.promotionInvoiceGroupId ?? "",
          })),
        };
      await registerPromotionInvoice(payload,
        invoiceRequest.current.forRequest(storeId, payload));
      invoiceRequest.current.clear();
      setInvoiceNumber("");
      setInvoiceDate("");
      setFillerPhone("");
      setSelectedStatements([]);
      setInvoiceSummary(null);
      setReplacementContext(null);
      setShowValidationFeedback(false);
      window.sessionStorage.removeItem(replacementContextStorageKey);
      setSubmitMessage("发票信息已登记，状态已更新。");
      statementResource.reload();
      invoiceResource.reload();
      replacementCandidateResource.reload();
    } catch (error) {
      setRegistrationFailed(true);
      if (error instanceof ApiRequestError && [401, 403].includes(error.status)) {
        setSelectedStatements([]);
        setInvoiceSummary(null);
      }
      if (error instanceof ApiRequestError && error.status === 409) {
        setInvoiceSummary(null);
        setSelectedStatements([]);
        if (replacementContext) {
          // Replacement groups are not loaded by the automatic statement resource.
          setSubmitMessage("账单或发票状态已变化，请重新加载释放账期并核对后再提交。");
          invoiceResource.reload();
          replacementCandidateResource.reload();
          return;
        }
        statementResource.reload();
        invoiceResource.reload();
        replacementCandidateResource.reload();
      }
      setSubmitMessage(userFacingError(error, "登记失败，请稍后重试。"));
    } finally {
      submitInFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">门店结算</p>
          <h1>开票确认</h1>
        </div>
      </section>

      <ResourceNotice
        loading={metaResource.loading || statementResource.loading || invoiceResource.loading}
        error={metaResource.error ?? statementResource.error ?? invoiceResource.error}
      />

      <section className="store-finance-invoice-reminders" aria-label="开票提醒">
        <p>门店前往开票系统开具数电专票，再将发票信息上传系统，否则将无法收款。</p>
        <p>当月10号前开票提交，当月结算；10号后开票提交将在下月结算。</p>
      </section>

      <StoreFinanceTimeline
        activeStage="invoice"
        statusText="当月10日前登记成功进入当月结算批次；10日后登记进入下月结算批次。"
        statusTitle="当前环节：发票提交"
      />

      <section className="store-finance-registration">
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
        <div className="store-finance-invoice-workspace">
          <section className="store-finance-invoice-panel store-finance-invoice-info" aria-label="购买方开票信息">
            <div className="store-finance-invoice-panel__heading">
              <div>
                <p className="eyebrow">收票方资料</p>
                <h3>购买方开票信息</h3>
              </div>
              <Button icon="copy" onClick={() => void copyInvoiceInfo()} size="sm" variant="secondary">
                一键复制全部开票信息
              </Button>
            </div>
            <dl>
              <div><dt>名称</dt><dd>{PROMOTION_INVOICE_BUYER_NAME}</dd></div>
              <div><dt>纳税人识别号</dt><dd>{PROMOTION_INVOICE_BUYER_TAXPAYER_ID}</dd></div>
              <div><dt>地址</dt><dd>{PROMOTION_INVOICE_BUYER_ADDRESS}</dd></div>
              <div><dt>电话</dt><dd>{PROMOTION_INVOICE_BUYER_PHONE}</dd></div>
              <div><dt>开户行及账号</dt><dd>{PROMOTION_INVOICE_BUYER_BANK}</dd></div>
              <div><dt>项目名称</dt><dd>{PROMOTION_INVOICE_PROJECT_NAME}</dd></div>
              <div><dt>税收分类编码</dt><dd>{PROMOTION_INVOICE_TAX_CLASSIFICATION}</dd></div>
              <div><dt>税率</dt><dd>{PROMOTION_INVOICE_TAX_RATE_PERCENT}%</dd></div>
              <div><dt>价税合计（含税总额）</dt><dd>{displayInvoiceSummary ? formatCurrency(displayInvoiceSummary.invoiceAmountCent) : invoiceAmountPlaceholder}</dd></div>
              <div><dt>不含税金额</dt><dd>{displayInvoiceSummary ? formatCurrency(displayInvoiceSummary.netAmountCent) : invoiceAmountPlaceholder}</dd></div>
              <div><dt>税额（6%）</dt><dd>{displayInvoiceSummary ? formatCurrency(displayInvoiceSummary.taxAmountCent) : invoiceAmountPlaceholder}</dd></div>
            </dl>
            {copyMessage ? <p role="status">{copyMessage}</p> : null}
          </section>

          <section className="store-finance-invoice-panel store-finance-invoice-panel--registration" aria-label="填写数电专票信息">
            <div className="store-finance-invoice-panel__heading">
              <div>
                <p className="eyebrow">发票登记</p>
                <h3>填写数电专票信息</h3>
              </div>
            </div>
            <p>仅校验号码格式与登记条件，不进行税务验真。</p>
            <form ref={invoiceFormRef} className="finance-form-grid" noValidate onSubmit={handleSubmit}>
              <label>
                <span>填写人电话</span>
                <FieldInput
                  aria-label="填写人电话"
                  inputMode="tel"
                  required
                  value={fillerPhone}
                  onChange={(event) => setFillerPhone(event.target.value)}
                />
              </label>
              <label>
                <span>开票日期</span>
                <FieldInput type="date" required value={invoiceDate} onChange={(event) => setInvoiceDate(event.target.value)} />
              </label>
              <label>
                <span>20 位数电专票号码</span>
                <FieldInput inputMode="numeric" pattern="[0-9]{20}" required value={invoiceNumber} onChange={(event) => setInvoiceNumber(event.target.value)} />
              </label>

              <div className="finance-form-actions finance-form-grid__wide">
                <Button disabled={submitting} loading={submitting} type="submit" variant="primary">
                  校验并登记发票
                </Button>
              </div>
            </form>
            {showValidationFeedback ? (
              <section className="store-finance-validation-response" aria-live="polite">
                <strong>系统校验结果</strong>
                {failedInvoiceValidationItems.length > 0 ? (
                  <ul className="store-finance-verification-list">
                    {failedInvoiceValidationItems.map((item) => (
                      <li className="is-error" key={item.key}>
                        <span aria-hidden="true">!</span>
                        {item.label}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>{registrationFailed ? "登记未成功，请核对下方错误后重试。" : submitting ? "格式校验通过，正在提交服务器登记。" : "请核对登记信息后提交。"}</p>
                )}
              </section>
            ) : null}
          </section>
        </div>
        {submitMessage ? <p role="status">{submitMessage}</p> : null}
      </section>

    </div>
  );
}
