const REQUIRED_BUYER = "比亚迪汽车销售有限公司";

function shanghaiParts(submittedAt) {
  const date = new Date(submittedAt);
  if (Number.isNaN(date.getTime())) {
    throw new TypeError("提交成功时间格式不正确");
  }

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);

  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

export function getConfirmationState({ day, confirmed, disputed, systemBlocked }) {
  if (systemBlocked) return "系统异常，待修复";
  if (disputed) return "异议处理中";
  if (confirmed || day > 6) return "已确认";
  return "待确认";
}

export function getSettlementMonth(submittedAt) {
  const { year, month, day } = shanghaiParts(submittedAt);
  const monthIndex = Number(month) - 1 + (Number(day) > 10 ? 1 : 0);
  const target = new Date(Date.UTC(Number(year), monthIndex, 1));

  return `${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function validateInvoice({
  buyer,
  taxRate,
  invoiceNumber,
  total,
  expectedTotal,
  duplicateInvoiceNumbers = [],
}) {
  const errors = [];

  if (buyer !== REQUIRED_BUYER) {
    errors.push("发票对象开具错误，请检查开具至【比亚迪汽车销售有限公司】发票");
  }
  if (Number(taxRate) !== 6) {
    errors.push("发票税率错误，请开具6%税率的推广服务费发票至比亚迪汽车销售有限公司");
  }
  if (!/^\d{20}$/.test(String(invoiceNumber ?? ""))) {
    errors.push("数电专票号码需要是20位纯数字");
  } else if (duplicateInvoiceNumbers.includes(String(invoiceNumber))) {
    errors.push("该发票号码已提交，请检查后更换发票号码");
  }
  if (Number(total) !== Number(expectedTotal)) {
    errors.push("价税合计需要与所选账期的已确认金额一致");
  }

  return errors;
}

export function validateImportBatch(rows) {
  const ok = rows.length > 0 && rows.every((row) => row.valid === true);
  return {
    ok,
    accepted: ok ? rows.length : 0,
    rejected: ok ? 0 : rows.length,
  };
}

export function getRecomputeOutcome({ paid, before, after }) {
  const adjustment = Number(after) - Number(before);
  return {
    rollback: false,
    notifyStore: !paid && adjustment !== 0,
    adjustment,
    target: "下一账期",
  };
}

export function money(value) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
  }).format(Number(value));
}

export { REQUIRED_BUYER };
