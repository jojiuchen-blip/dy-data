export const invoiceStatusLabels: Record<string, string> = {
  not_received: "未到票",
  received: "已到票",
  approved: "审核通过",
  rejected: "审核未通过",
};

export const refundStatusLabels: Record<string, string> = {
  none: "未退款",
  refunding: "退款中",
  refunded: "已退款",
};

export function formatCurrency(cent: number): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(cent / 100);
}

export function formatInteger(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function formatPercent(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}

export function labelForBoolean(value: boolean | null): string {
  if (value === null) {
    return "-";
  }
  return value ? "是" : "否";
}

export function compactCurrency(cent: number): string {
  const amount = cent / 100;
  if (Math.abs(amount) >= 10000) {
    return `${new Intl.NumberFormat("zh-CN", {
      maximumFractionDigits: 1,
    }).format(amount / 10000)} 万`;
  }
  return formatCurrency(cent);
}
