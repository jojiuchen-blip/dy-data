import { useEffect, useRef, useState, type FormEvent } from "react";
import {
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
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";

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
  buyerName: string;
  fillerPhone: string;
  taxAmount: string;
  taxRatePercent: string;
  netAmount: string;
  totalAmount: string;
  invoiceDate: string;
  invoiceNumber: string;
  invoiceNumbers: string[];
  selectedAmountCent: number;
  selectedStatementCount: number;
}

interface InvoiceValidationItem {
  key: string;
  label: string;
  passed: boolean;
}

const INVOICE_BUYER_NAME_ERROR =
  "本项应该填写“比亚迪汽车销售有限公司”，请检查您开具的发票购买方名称是否正确。";
const INVOICE_TAX_RATE_ERROR =
  "本项应该填写6%，请检查您开具的发票税率是否为6%。";

export function parseInvoiceAmountCent(value: string): number | null {
  const normalized = value.trim();
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,3})?$/.test(normalized)) {
    return null;
  }
  const [wholePart, decimalPart = ""] = normalized.split(".");
  const amountMill =
    Number(wholePart) * 1000 + Number(decimalPart.padEnd(3, "0"));
  const amountCent = Math.round(amountMill / 10);
  return Number.isSafeInteger(amountCent) ? amountCent : null;
}

export function validateInvoiceRegistration({
  buyerName,
  fillerPhone,
  taxAmount,
  taxRatePercent,
  netAmount,
  totalAmount,
  invoiceDate,
  invoiceNumber,
  invoiceNumbers,
  selectedAmountCent,
  selectedStatementCount,
}: InvoiceRegistrationValidationInput): InvoiceValidationItem[] {
  const normalizedNumber = invoiceNumber.trim();
  const netAmountCent = parseInvoiceAmountCent(netAmount) ?? -1;
  const taxAmountCent = parseInvoiceAmountCent(taxAmount) ?? -1;
  const invoiceAmountCent = parseInvoiceAmountCent(totalAmount) ?? -1;
  const normalizedTaxRate = taxRatePercent.trim().replace(/%$/, "");
  const amountFieldsAreValid =
    netAmountCent >= 0 && taxAmountCent >= 0 && invoiceAmountCent >= 0;
  const amountIdentityIsValid =
    amountFieldsAreValid &&
    Math.abs(netAmountCent + taxAmountCent - invoiceAmountCent) <= 1;

  return [
    {
      key: "selected-statements",
      label: "系统已确定可开票的完整账期",
      passed: selectedStatementCount > 0 && selectedAmountCent > 0,
    },
    {
      key: "invoice-number",
      label: "数电专票号码必须为20位纯数字且不得重复",
      passed:
        /^\d{20}$/.test(normalizedNumber) &&
        !invoiceNumbers.includes(normalizedNumber),
    },
    {
      key: "invoice-date",
      label: "开票日期必须填写，日期边界由服务器最终校验",
      passed: Boolean(invoiceDate),
    },
    {
      key: "buyer-name",
      label:
        buyerName.trim() === PROMOTION_INVOICE_BUYER_NAME
          ? "购买方名称已匹配"
          : INVOICE_BUYER_NAME_ERROR,
      passed: buyerName.trim() === PROMOTION_INVOICE_BUYER_NAME,
    },
    {
      key: "filler-phone",
      label: fillerPhone.trim()
        ? "填写人电话已填写"
        : "请填写开票信息填写人电话",
      passed: Boolean(fillerPhone.trim()),
    },
    {
      key: "tax-rate",
      label:
        Number(normalizedTaxRate) === PROMOTION_INVOICE_TAX_RATE_PERCENT
          ? "税率已匹配"
          : INVOICE_TAX_RATE_ERROR,
      passed: Number(normalizedTaxRate) === PROMOTION_INVOICE_TAX_RATE_PERCENT,
    },
    {
      key: "net-amount",
      label: netAmountCent < 0
        ? "不含税金额必须填写有效金额，最多三位小数"
        : "不含税金额格式正确",
      passed: netAmountCent >= 0,
    },
    {
      key: "tax-amount",
      label: taxAmountCent < 0
        ? "税额必须填写有效金额，最多三位小数"
        : "税额格式正确",
      passed: taxAmountCent >= 0,
    },
    {
      key: "total-amount",
      label: invoiceAmountCent < 0
        ? "价税合计必须填写有效金额，最多三位小数"
        : "价税合计格式正确",
      passed: invoiceAmountCent >= 0,
    },
    {
      key: "amount-identity",
      label: amountIdentityIsValid
        ? "不含税金额 + 税额必须等于开票金额（已通过）"
        : "不含税金额 + 税额必须等于开票金额",
      passed: amountIdentityIsValid,
    },
    {
      key: "total-amount-match",
      label: "价税合计必须等于系统确定账期的推广服务费",
      passed:
        selectedStatementCount > 0 &&
        invoiceAmountCent >= 0 &&
        invoiceAmountCent === selectedAmountCent,
      },
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
  const eligibleMonths = [
    ...new Set([...statementMonths, currentMonth]),
  ]
    .filter(
      (statementMonth) =>
        statementMonth >= formalPeriodStartMonth && statementMonth <= currentMonth,
    )
    .sort((left, right) => left.localeCompare(right));
  const responses = await Promise.all(
    eligibleMonths.map((statementMonth) =>
      fetchStoreBillingStatements({
        storeId,
        month: statementMonth,
        metricScope,
        feeDirection: "PROMOTION",
        pageSize: 50,
      }),
    ),
  );
  const allStatements = responses.flatMap((response) => response.data.list);
  const registerableStatements = allStatements.filter(
    (statement) =>
      statement.month <= currentMonth &&
      isRegisterablePromotionStatement(statement),
  );
  const requiredGroupByStatementId = new Map<string, string>();
  registerableStatements.forEach((statement) => {
    const groupId = statement.promotionInvoiceGroupId;
    if (!groupId) return;
    const requiredStatementIds = statement.promotionRequiredStatementIds.length
      ? statement.promotionRequiredStatementIds
      : [statement.statementId];
    requiredStatementIds.forEach((statementId) => {
      const previousGroupId = requiredGroupByStatementId.get(statementId);
      if (previousGroupId && previousGroupId !== groupId) {
        throw new Error("同一账期被分配到多个抵扣组，请刷新后重试。");
      }
      requiredGroupByStatementId.set(statementId, groupId);
    });
  });
  const selectedMonth = currentMonth;
  const selectedResponse =
    responses.find((response) =>
      response.data.list.some((statement) => statement.month === selectedMonth),
    ) ?? responses[responses.length - 1];
  if (!selectedResponse) {
    throw new Error("系统未返回可用的正式账期。");
  }

  const visibleStatements = new Map(
    allStatements.map((statement) => [statement.statementId, statement]),
  );
  const selectedGroupStatements = await Promise.all(
    [...requiredGroupByStatementId.entries()].map(
      async ([statementId, groupId]) => {
        const statement =
          visibleStatements.get(statementId) ??
          (await fetchStoreBillingStatement(statementId)).data;
        if (
          statement.storeId !== storeId ||
          !statement.isCurrent ||
          statement.month < formalPeriodStartMonth ||
          statement.month > currentMonth ||
          statement.promotionInvoiceGroupId !== groupId
        ) {
          throw new Error("抵扣组已变化，请刷新后重试。");
        }
        return statement;
      },
    ),
  );
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
  const [month, setMonth] = useState("");
  const [storeId, setStoreId] = useState(
    initialStoreId,
  );
  const [metricScope] = useState<BillingMetricScope>("MONTH");
  const [buyerName, setBuyerName] = useState("");
  const [fillerPhone, setFillerPhone] = useState("");
  const [taxRatePercent, setTaxRatePercent] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [netAmount, setNetAmount] = useState("");
  const [taxAmount, setTaxAmount] = useState("");
  const [totalAmount, setTotalAmount] = useState("");
  const [selectedStatements, setSelectedStatements] = useState<StoreBillingStatement[]>([]);
  const [submitMessage, setSubmitMessage] = useState("");
  const [showValidationFeedback, setShowValidationFeedback] = useState(false);
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

  const enabled = Boolean(storeId && month);
  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const filterMeta = metaResource.data?.data;
  const currentPeriodMonth = filterMeta?.statementMonths[0] ?? "";
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
    { enabled: Boolean(storeId && filterMeta && currentPeriodMonth && !replacementContext) },
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
  const selectedAmountCent = selectedStatements.reduce(
    (total, statement) =>
      total + (statement.promotionConfirmation?.confirmedAmountCent ?? 0),
    0,
  );
  const invoiceValidationItems = validateInvoiceRegistration({
    buyerName,
    fillerPhone,
    taxAmount,
    taxRatePercent,
    netAmount,
    totalAmount,
    invoiceDate,
    invoiceNumber,
    invoiceNumbers: invoices.map((invoice) => invoice.invoiceNumber),
    selectedAmountCent,
    selectedStatementCount: selectedStatements.length,
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
      `价税合计：${formatCurrency(selectedAmountCent)}`,
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
    const automaticSelection = statementResource.data?.data;
    if (!automaticSelection || replacementContext) {
      return;
    }
    setMonth(automaticSelection.selectedMonth);
    setSelectedStatements(automaticSelection.selectedGroupStatements);
  }, [statementResource.data, replacementContext]);

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

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
    if (
      selectedAmountCent <= 0 ||
      selectedStatements.some((statement) => !statement.promotionInvoiceGroupId)
    ) {
      setSubmitMessage("系统确定的抵扣组尚未形成正数净开票金额，请刷新后重试。");
      return;
    }
    const enteredTotalAmountCent = parseInvoiceAmountCent(totalAmount);
    const enteredNetAmountCent = parseInvoiceAmountCent(netAmount);
    const enteredTaxAmountCent = parseInvoiceAmountCent(taxAmount);
    if (
      enteredTotalAmountCent === null ||
      enteredNetAmountCent === null ||
      enteredTaxAmountCent === null
    ) {
      setSubmitMessage("核验未通过：金额必须有效，最多输入三位小数并四舍五入到分。");
      return;
    }
    setSubmitting(true);
    setSubmitMessage("");
    try {
      await registerPromotionInvoice(
        {
          storeId,
          buyerName: buyerName.trim(),
          fillerPhone: fillerPhone.trim(),
          taxRatePercent: Number(taxRatePercent.trim().replace(/%$/, "")),
          invoiceNumber: invoiceNumber.trim(),
          invoiceDate,
          netAmountCent: enteredNetAmountCent,
          taxAmountCent: enteredTaxAmountCent,
          invoiceAmountCent: enteredTotalAmountCent,
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
      setInvoiceNumber("");
      setInvoiceDate("");
      setBuyerName("");
      setFillerPhone("");
      setTaxRatePercent("");
      setNetAmount("");
      setTaxAmount("");
      setTotalAmount("");
      setSelectedStatements([]);
      setReplacementContext(null);
      setShowValidationFeedback(false);
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
              <div><dt>价税合计</dt><dd>{selectedStatements.length ? formatCurrency(selectedAmountCent) : "尚未生成"}</dd></div>
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
            <form ref={invoiceFormRef} className="finance-form-grid" noValidate onSubmit={handleSubmit}>
              <label>
                <span>购买方名称</span>
                <FieldInput
                  aria-label="购买方名称"
                  required
                  value={buyerName}
                  onChange={(event) => setBuyerName(event.target.value)}
                />
              </label>
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
                <span>税率</span>
                <FieldInput
                  aria-label="税率"
                  inputMode="decimal"
                  required
                  value={taxRatePercent}
                  onChange={(event) => setTaxRatePercent(event.target.value.replace(/[^\d.]/g, ""))}
                />
              </label>
              <label>
                <span>开票日期</span>
                <FieldInput type="date" required value={invoiceDate} onChange={(event) => setInvoiceDate(event.target.value)} />
              </label>
              <label>
                <span>20 位数电专票号码</span>
                <FieldInput inputMode="numeric" maxLength={20} minLength={20} pattern="[0-9]{20}" required value={invoiceNumber} onChange={(event) => setInvoiceNumber(event.target.value.replace(/\D/g, ""))} />
              </label>
              <label>
                <span>不含税金额</span>
                <FieldInput
                  aria-label="不含税金额"
                  inputMode="decimal"
                  required
                  value={netAmount}
                  onChange={(event) => setNetAmount(event.target.value)}
                />
              </label>
              <label>
                <span>税额</span>
                <FieldInput
                  aria-label="税额"
                  inputMode="decimal"
                  required
                  value={taxAmount}
                  onChange={(event) => setTaxAmount(event.target.value)}
                />
              </label>
              <label>
                <span>价税合计</span>
                <FieldInput
                  aria-label="价税合计"
                  inputMode="decimal"
                  required
                  value={totalAmount}
                  onChange={(event) => setTotalAmount(event.target.value)}
                />
              </label>

              <div className="finance-form-actions finance-form-grid__wide">
                <Button disabled={submitting} loading={submitting} type="submit" variant="primary">
                  核验并登记发票
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
                  <p>基础信息校验通过，正在提交服务器登记。</p>
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
