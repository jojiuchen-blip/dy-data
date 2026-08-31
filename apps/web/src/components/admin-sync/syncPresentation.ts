import type {
  AdminObservedStatus,
  AdminOperationComponent,
  AdminOperationJob,
} from "../../types/dashboard";
import type { ChipTone } from "../Chips";

export const restartableComponentTypes = new Set(["worker", "browser"]);

const componentLabels: Record<AdminOperationComponent["component_type"], string> = {
  api: "接口服务",
  postgres: "业务数据库",
  worker: "同步工作进程",
  browser: "浏览器采集组件",
  proxy: "访问代理",
  ops_agent: "运维代理",
};

const observedLabels: Record<AdminObservedStatus, string> = {
  starting: "启动中",
  healthy: "健康",
  degraded: "降级",
  draining: "排空中",
  unhealthy: "异常",
  stopped: "已停止",
  lost: "失联",
  unknown: "未知",
};

const stageLabels: Record<string, string> = {
  plan: "规划",
  collect: "采集",
  settle: "结算",
  finalize: "最终汇总",
  complete: "已完成",
};

const eventLabels: Record<string, string> = {
  admin_cancel_requested: "已请求取消",
  admin_pause_requested: "已请求暂停领取",
  admin_resume_requested: "已请求恢复队列",
  admin_retry_requested: "已请求人工重试",
  admin_sync_created: "已创建同步任务",
};

export function componentLabel(type: AdminOperationComponent["component_type"]): string {
  return componentLabels[type];
}

export function observedStatusLabel(status: AdminObservedStatus): string {
  return observedLabels[status] ?? "未知";
}

export function observedStatusTone(status: AdminObservedStatus): ChipTone {
  if (status === "healthy") return "success";
  if (status === "starting" || status === "draining") return "info";
  if (status === "degraded" || status === "unknown") return "warning";
  if (status === "unhealthy" || status === "lost" || status === "stopped") return "danger";
  return "neutral";
}

export function operationJobLabel(job: AdminOperationJob): string {
  return job.business_date ?? (job.job_kind === "finalize" ? "最终汇总" : "同步父任务");
}

export function operationStageLabel(value: string | null | undefined): string {
  if (!value) return "等待领取";
  return stageLabels[value] ?? "未知阶段";
}

export function operationEventLabel(value: string | null | undefined): string {
  if (!value) return "系统事件";
  return eventLabels[value] ?? "系统事件";
}

export function operationJobStatusLabel(status: AdminOperationJob["status"]): string {
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  if (status === "running") return "运行中";
  if (status === "retry_wait") return "等待重试";
  if (status === "partial") return "部分完成";
  return "等待中";
}

export function operationJobTone(status: AdminOperationJob["status"]): ChipTone {
  if (status === "success") return "success";
  if (status === "running") return "info";
  if (status === "failed" || status === "cancelled") return "danger";
  return "warning";
}

export function formatBytes(value: number | null | undefined): string {
  if (!value) return "未知";
  const units = ["B", "KB", "MB", "GB"];
  let result = value;
  let index = 0;
  while (result >= 1024 && index < units.length - 1) {
    result /= 1024;
    index += 1;
  }
  return `${result.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}
