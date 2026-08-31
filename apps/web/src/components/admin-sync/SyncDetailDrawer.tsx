import type { RefObject } from "react";
import type {
  AdminJobControlAction,
  AdminOperationComponent,
  AdminOperationJob,
  AdminOperationJobDetail,
} from "../../types/dashboard";
import { formatDateTime, formatInteger } from "../../utils/format";
import { Button } from "../Button";
import { StatusChip } from "../Chips";
import { Dialog } from "../Dialog";
import {
  componentLabel,
  formatBytes,
  observedStatusLabel,
  observedStatusTone,
  operationEventLabel,
  operationJobLabel,
  operationJobStatusLabel,
  operationJobTone,
  operationStageLabel,
  restartableComponentTypes,
} from "./syncPresentation";

export type SyncDrawerSelection =
  | { kind: "component"; component: AdminOperationComponent }
  | { kind: "job"; job: AdminOperationJob };

interface SyncDetailDrawerProps {
  detail: AdminOperationJobDetail | null;
  loading: boolean;
  onClose: () => void;
  onJobControl: (job: AdminOperationJob, action: AdminJobControlAction) => void;
  onRestart: (component: AdminOperationComponent) => void;
  returnFocusRef: RefObject<HTMLElement | null>;
  selection: SyncDrawerSelection | null;
}

function JsonFacts({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value);
  if (!entries.length) return <p className="admin-muted">暂无事实</p>;
  return (
    <dl className="sync-detail-facts">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{typeof item === "string" ? item : JSON.stringify(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

function heartbeatText(value: string | null): string {
  return value ? formatDateTime(value) : "未知";
}

export function SyncDetailDrawer({
  detail,
  loading,
  onClose,
  onJobControl,
  onRestart,
  returnFocusRef,
  selection,
}: SyncDetailDrawerProps) {
  const component = selection?.kind === "component" ? selection.component : null;
  const job = detail?.job ?? (selection?.kind === "job" ? selection.job : null);
  const title = component ? componentLabel(component.component_type) : job ? job.job_id : "详情";

  return (
    <Dialog
      bodyClassName="sync-detail-drawer__body"
      description={component ? "组件活动、资源和命令事实" : "任务阶段、尝试、资源和事件事实"}
      onClose={onClose}
      open={selection !== null}
      panelClassName="sync-detail-drawer"
      returnFocusRef={returnFocusRef}
      title={title}
    >
      {loading ? <p role="status">正在读取详情...</p> : null}
      {component ? (
        <div className="sync-detail-stack">
          <div className="sync-detail-heading">
            <StatusChip tone={observedStatusTone(component.observed_status)}>
              {observedStatusLabel(component.observed_status)}
            </StatusChip>
            <span>心跳 {heartbeatText(component.last_heartbeat_at)}</span>
          </div>
          <section>
            <h3>资源</h3>
            <dl className="sync-detail-facts">
              <div>
                <dt>CPU</dt>
                <dd>
                  {component.resources.cpu_percent == null ? "未知" : `${component.resources.cpu_percent}%`}
                </dd>
              </div>
              <div><dt>RSS</dt><dd>{formatBytes(component.resources.rss_bytes)}</dd></div>
              <div><dt>RSS 峰值</dt><dd>{formatBytes(component.resources.rss_peak_bytes)}</dd></div>
              <div><dt>内存限制</dt><dd>{formatBytes(component.resources.memory_limit_bytes)}</dd></div>
            </dl>
          </section>
          <section>
            <h3>当前活动</h3>
            <JsonFacts value={component.activity} />
          </section>
          <section>
            <h3>队列</h3>
            <JsonFacts value={component.queue_summary} />
          </section>
          {component.allow_restart && restartableComponentTypes.has(component.component_type) ? (
            <Button onClick={() => onRestart(component)} type="button" variant="danger">
              提交重启命令
            </Button>
          ) : (
            <p className="resource-notice">该组件仅提供观测信息，不提供控制入口。</p>
          )}
        </div>
      ) : null}
      {job && !component ? (
        <div className="sync-detail-stack">
          <div className="sync-detail-heading">
            <StatusChip tone={operationJobTone(job.status)}>
              {operationJobStatusLabel(job.status)}
            </StatusChip>
            <span>{operationStageLabel(job.current_stage)}</span>
          </div>
          <dl className="sync-detail-facts">
            <div><dt>业务日期</dt><dd>{job.business_date ?? "范围任务"}</dd></div>
            <div><dt>尝试</dt><dd>{job.attempt_count} / {job.max_attempts}</dd></div>
            <div><dt>进度</dt><dd>{formatInteger(job.progress_current)} / {formatInteger(job.progress_total)}</dd></div>
            <div><dt>读 / 写 / 影响</dt><dd>{job.rows_read} / {job.rows_written} / {job.rows_affected}</dd></div>
            <div><dt>RSS 峰值</dt><dd>{formatBytes(job.rss_peak_bytes)}</dd></div>
            <div>
              <dt>预计剩余</dt>
              <dd>{detail?.eta.state === "available" && detail.eta.remaining_seconds != null
                ? `${formatInteger(detail.eta.remaining_seconds)} 秒`
                : "估算中"}</dd>
            </div>
          </dl>
          {job.error_summary ? (
            <p className="resource-notice resource-notice--warning">
              {job.error_code ?? "任务错误"}：{job.error_summary}
            </p>
          ) : null}
          <div className="sync-detail-actions">
            {job.status === "running" && !job.pause_requested ? (
              <Button onClick={() => onJobControl(job, "pause")} type="button">
                暂停后续领取
              </Button>
            ) : null}
            {job.pause_requested ? (
              <Button onClick={() => onJobControl(job, "resume")} type="button">
                恢复队列
              </Button>
            ) : null}
            {["pending", "queued", "retry_wait", "running"].includes(job.status) ? (
              <Button onClick={() => onJobControl(job, "cancel")} type="button" variant="danger">
                取消 / 安全停止
              </Button>
            ) : null}
            {job.status === "failed" ? (
              <Button onClick={() => onJobControl(job, "retry")} type="button" variant="primary">
                人工重试
              </Button>
            ) : null}
          </div>
          <section>
            <h3>子任务进度</h3>
            {detail?.children.length ? (
              <div className="sync-detail-child-list">
                {detail.children.map((child) => (
                  <div className="sync-detail-event" key={child.job_id}>
                    <strong>{operationJobLabel(child)}</strong>
                    <span>{operationStageLabel(child.current_stage)}</span>
                    <small>{operationJobStatusLabel(child.status)}</small>
                  </div>
                ))}
              </div>
            ) : (
              <p className="admin-muted">暂无子任务事实</p>
            )}
          </section>
          <section>
            <h3>阶段</h3>
            <p>{detail?.stages.length ?? 0} 条阶段事实</p>
          </section>
          <section>
            <h3>尝试</h3>
            <p>{detail?.attempts.length ?? 0} 条尝试事实</p>
          </section>
          <section className="sync-detail-events">
            <h3>脱敏事件</h3>
            {detail?.events.length ? (
              detail.events.map((event, index) => (
                <div className="sync-detail-event" key={String(event.event_id ?? index)}>
                  <strong>{operationEventLabel(typeof event.event_type === "string" ? event.event_type : null)}</strong>
                  <small>{formatDateTime(typeof event.occurred_at === "string" ? event.occurred_at : null)}</small>
                  <span>{typeof event.reason === "string" ? event.reason : "无补充说明"}</span>
                </div>
              ))
            ) : (
              <p className="admin-muted">暂无事件</p>
            )}
          </section>
        </div>
      ) : null}
    </Dialog>
  );
}
