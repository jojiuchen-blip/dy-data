import { ApiRequestError } from "../api/client";

const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  400: "提交内容不完整或格式不正确，请检查后重试。",
  401: "登录状态已失效，请重新登录后再试。",
  403: "当前账号没有执行此操作的权限。",
  404: "未找到相关数据，请刷新后重试。",
  409: "数据已发生变化，请刷新后重新操作。",
  422: "提交内容未通过校验，请检查后重试。",
  429: "操作过于频繁，请稍后再试。",
};

export function userFacingError(
  error: unknown,
  fallback = "操作未完成，请稍后重试。",
): string {
  if (error instanceof ApiRequestError) {
    if (STATUS_MESSAGES[error.status]) {
      return STATUS_MESSAGES[error.status];
    }
    if (error.status >= 500) {
      return "服务暂时不可用，请稍后重试。";
    }
  }

  if (error instanceof TypeError) {
    return "网络连接异常，请检查网络后重试。";
  }

  if (import.meta.env.DEV) {
    console.warn("[user-facing-error] Hidden internal error", error);
  }
  return fallback;
}
