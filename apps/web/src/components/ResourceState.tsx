import type { ReactNode } from "react";
import type { ApiLoadResult } from "../api/client";
import { userFacingError } from "../utils/userFacingError";

interface ResourceNoticeProps {
  error?: string;
  fallbackReason?: string;
  loading?: boolean;
  analysis?: boolean;
}

interface ResourcePanelProps {
  children: ReactNode;
  tone?: "loading" | "error";
}

export function resourceSourceLabel<T>(
  resource: ApiLoadResult<T> | undefined,
  loading: boolean,
): string {
  if (!resource && loading) {
    return "加载中";
  }
  if (!resource) {
    return "暂无数据";
  }
  return resource.usingMock ? "演示数据" : resource.meta.publication ? "已发布数据" : "实时数据";
}

export function ResourceNotice({
  error,
  fallbackReason,
  loading = false,
  analysis = false,
}: ResourceNoticeProps) {
  if (!loading && !fallbackReason && !error) {
    return null;
  }

  return (
    <div
      aria-atomic="true"
      aria-live={error ? "assertive" : "polite"}
      className={[
        "resource-notice",
        error ? "resource-notice--error" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      role={error ? "alert" : "status"}
    >
      {loading ? <span>{analysis ? "正在读取所选范围的已发布结果..." : "正在加载最新数据..."}</span> : null}
      {fallbackReason ? <span>{fallbackReason}</span> : null}
      {error ? <span>{analysis ? error : userFacingError(error, "数据加载失败，请稍后重试。")}</span> : null}
    </div>
  );
}

export function ResourcePanel({
  children,
  tone = "loading",
}: ResourcePanelProps) {
  return (
    <div
      aria-atomic="true"
      aria-live={tone === "error" ? "assertive" : "polite"}
      className={`resource-panel resource-panel--${tone}`}
      role={tone === "error" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
