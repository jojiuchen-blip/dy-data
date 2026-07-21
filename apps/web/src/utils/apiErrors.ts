import { ApiRequestError } from "../api/client";

export function apiErrorText(
  error: unknown,
  fallback: string,
  statusMessages: Partial<Record<number, string>> = {},
): string {
  if (!(error instanceof ApiRequestError)) return fallback;
  const parts = [statusMessages[error.status] ?? fallback];
  if (Array.isArray(error.fieldErrors) && error.fieldErrors.length) {
    const fieldSummary = error.fieldErrors
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const field = "field" in item ? String(item.field) : "字段";
        const reason = "reason" in item ? String(item.reason) : "不合法";
        return `${field}：${reason}`;
      })
      .filter(Boolean)
      .join("；");
    if (fieldSummary) parts.push(fieldSummary);
  }
  if (error.requestId) parts.push(`请求编号：${error.requestId}`);
  return parts.join(" ");
}
