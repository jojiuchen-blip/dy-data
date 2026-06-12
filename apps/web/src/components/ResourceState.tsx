import type { ReactNode } from "react";
import type { ApiLoadResult } from "../api/client";

interface ResourceNoticeProps {
  error?: string;
  fallbackReason?: string;
  loading?: boolean;
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
  return resource.usingMock ? "mock fallback" : resource.meta.source || "api";
}

export function ResourceNotice({
  error,
  fallbackReason,
  loading = false,
}: ResourceNoticeProps) {
  if (!loading && !fallbackReason && !error) {
    return null;
  }

  return (
    <div
      className={[
        "resource-notice",
        error ? "resource-notice--error" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {loading ? <span>正在加载最新数据...</span> : null}
      {fallbackReason ? <span>{fallbackReason}</span> : null}
      {error ? <span>数据加载失败：{error}</span> : null}
    </div>
  );
}

export function ResourcePanel({
  children,
  tone = "loading",
}: ResourcePanelProps) {
  return <div className={`resource-panel resource-panel--${tone}`}>{children}</div>;
}
