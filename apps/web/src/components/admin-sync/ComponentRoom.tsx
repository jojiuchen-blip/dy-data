import { useEffect, useRef, useState, type MouseEvent } from "react";
import {
  fetchAdminOperationJob,
  fetchAdminOperationsOverview,
  submitAdminJobControl,
  submitAdminOpsCommand,
} from "../../api/client";
import type {
  AdminJobControlAction,
  AdminOperationComponent,
  AdminOperationJob,
  AdminOperationJobDetail,
  AdminOperationsOverview,
} from "../../types/dashboard";
import { userFacingError } from "../../utils/userFacingError";
import { Button } from "../Button";
import { ComponentCard } from "./ComponentCard";
import { SyncControlConfirmDialog } from "./SyncControlConfirmDialog";
import { SyncDetailDrawer, type SyncDrawerSelection } from "./SyncDetailDrawer";
import { SyncTaskRail } from "./SyncTaskRail";
import {
  componentLabel,
  operationJobLabel,
  operationJobStatusLabel,
  operationStageLabel,
  restartableComponentTypes,
} from "./syncPresentation";

interface ComponentRoomProps {
  onCreateTask: () => void;
}

type ControlRequest =
  | { kind: "restart"; component: AdminOperationComponent }
  | { kind: "job"; job: AdminOperationJob; action: AdminJobControlAction };

const actionLabels: Record<AdminJobControlAction, string> = {
  pause: "暂停领取",
  resume: "恢复队列",
  cancel: "取消 / 安全停止",
  retry: "人工重试",
};

function nextIdempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export function ComponentRoom({ onCreateTask }: ComponentRoomProps) {
  const [overview, setOverview] = useState<AdminOperationsOverview | null>(null);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [selection, setSelection] = useState<SyncDrawerSelection | null>(null);
  const [detail, setDetail] = useState<AdminOperationJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [control, setControl] = useState<ControlRequest | null>(null);
  const [controlBusy, setControlBusy] = useState(false);
  const [statusText, setStatusText] = useState("");
  const lastTriggerRef = useRef<HTMLElement | null>(null);
  const detailControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const schedule = (activeCount: number) => {
      if (stopped || document.hidden) return;
      timer = window.setTimeout(load, activeCount > 0 ? 5000 : 15000);
    };

    const load = async () => {
      if (stopped || document.hidden) return;
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetchAdminOperationsOverview(controller.signal);
        if (stopped) return;
        setOverview(response.data);
        setError("");
        schedule(response.data.active_count);
      } catch (reason) {
        if (stopped || (reason instanceof DOMException && reason.name === "AbortError")) {
          return;
        }
        setError(userFacingError(reason, "组件与任务状态暂时无法读取。"));
        schedule(0);
      }
    };

    const handleVisibility = () => {
      if (document.hidden) {
        controller?.abort();
        if (timer !== undefined) window.clearTimeout(timer);
      } else {
        void load();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    void load();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refreshKey]);

  useEffect(() => {
    return () => detailControllerRef.current?.abort();
  }, []);

  const selectComponent = (
    component: AdminOperationComponent,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    detailControllerRef.current?.abort();
    detailControllerRef.current = null;
    lastTriggerRef.current = event.currentTarget;
    setDetailLoading(false);
    setDetail(null);
    setSelection({ kind: "component", component });
  };

  const selectJob = async (
    job: AdminOperationJob,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    detailControllerRef.current?.abort();
    const controller = new AbortController();
    detailControllerRef.current = controller;
    lastTriggerRef.current = event.currentTarget;
    setSelection({ kind: "job", job });
    setDetail(null);
    setDetailLoading(true);
    try {
      const response = await fetchAdminOperationJob(job.job_id, controller.signal);
      if (!controller.signal.aborted) setDetail(response.data);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setStatusText(userFacingError(reason, "任务详情暂时无法读取。"));
      }
    } finally {
      if (detailControllerRef.current === controller) {
        detailControllerRef.current = null;
        setDetailLoading(false);
      }
    }
  };

  const submitControl = async (reason: string) => {
    if (!control) return;
    setControlBusy(true);
    try {
      if (control.kind === "restart") {
        await submitAdminOpsCommand(
          control.component.component_type as "worker" | "browser",
          reason,
          nextIdempotencyKey(`restart-${control.component.component_type}`),
          control.component.current_job_id,
        );
        setStatusText("命令已提交，等待 Ops Agent 在安全边界执行；当前状态不代表重启成功。");
      } else {
        await submitAdminJobControl(
          control.job.job_id,
          control.action,
          reason,
          nextIdempotencyKey(`${control.action}-${control.job.job_id}`),
        );
        setStatusText("控制命令已提交；任务事实会在执行组件接收意图后更新。");
      }
      setControl(null);
      setRefreshKey((value) => value + 1);
    } catch (requestError) {
      setStatusText(userFacingError(requestError, "控制命令提交失败。"));
    } finally {
      setControlBusy(false);
    }
  };

  const controlTarget = control?.kind === "restart"
    ? componentLabel(control.component.component_type)
    : control?.kind === "job"
      ? operationJobLabel(control.job)
      : "";
  const controlAction = control?.kind === "restart"
    ? "重启"
    : control
      ? actionLabels[control.action]
      : "";
  const impact = control?.kind === "restart"
    ? control.component.current_job_id ?? "无已声明活动任务"
    : control?.kind === "job"
      ? `${operationStageLabel(control.job.current_stage)}，状态 ${operationJobStatusLabel(control.job.status)}`
      : "";

  return (
    <section aria-labelledby="component-room-title" className="content-section component-room-section">
      <div className="section-title">
        <div>
          <h2 id="component-room-title">组件机房</h2>
          <p>健康与活动分别呈现；没有心跳时显示未知或失联，不推测运行状态。</p>
        </div>
        <Button onClick={() => setRefreshKey((value) => value + 1)} type="button">
          刷新事实
        </Button>
      </div>
      {error ? (
        <p className="resource-notice resource-notice--warning" role="alert">
          {error}
        </p>
      ) : null}
      {statusText ? (
        <p aria-live="polite" className="resource-notice" role="status">
          {statusText}
        </p>
      ) : null}
      <div className="component-room-layout">
        <div>
          <div className="component-room-grid">
            {(overview?.components ?? []).map((component) => (
              <ComponentCard
                component={component}
                key={component.component_type}
                onSelect={(event) => selectComponent(component, event)}
              />
            ))}
          </div>
          {!overview ? <p className="admin-muted">正在读取组件心跳...</p> : null}
          <p className="component-room-boundary">
            API、Postgres、Proxy 和宿主机不提供重启入口；同步工作进程和浏览器采集组件也只提交命令，不乐观显示成功。
          </p>
        </div>
        <SyncTaskRail
          jobs={overview?.jobs ?? []}
          onCreateTask={onCreateTask}
          onSelectJob={(job, event) => void selectJob(job, event)}
        />
      </div>
      <SyncDetailDrawer
        detail={detail}
        loading={detailLoading}
        onClose={() => {
          detailControllerRef.current?.abort();
          detailControllerRef.current = null;
          setSelection(null);
          setDetail(null);
          setDetailLoading(false);
        }}
        onJobControl={(job, action) => setControl({ kind: "job", job, action })}
        onRestart={(component) => {
          if (component.allow_restart && restartableComponentTypes.has(component.component_type)) {
            setControl({ kind: "restart", component });
          }
        }}
        returnFocusRef={lastTriggerRef}
        selection={selection}
      />
      <SyncControlConfirmDialog
        actionLabel={controlAction}
        busy={controlBusy}
        impact={impact}
        onClose={() => setControl(null)}
        onConfirm={(reason) => void submitControl(reason)}
        open={control !== null}
        targetLabel={controlTarget}
      />
    </section>
  );
}
