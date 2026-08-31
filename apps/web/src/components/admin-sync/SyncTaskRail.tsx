import type { MouseEvent } from "react";
import type { AdminOperationJob } from "../../types/dashboard";
import { Button } from "../Button";
import { StatusChip } from "../Chips";
import {
  operationJobLabel,
  operationJobStatusLabel,
  operationJobTone,
  operationStageLabel,
} from "./syncPresentation";

interface SyncTaskRailProps {
  jobs: AdminOperationJob[];
  onCreateTask: () => void;
  onSelectJob: (job: AdminOperationJob, event: MouseEvent<HTMLButtonElement>) => void;
}

function progressPercent(job: AdminOperationJob): number {
  return Math.min(Math.max(job.progress_percent ?? 0, 0), 100);
}

export function SyncTaskRail({ jobs, onCreateTask, onSelectJob }: SyncTaskRailProps) {
  return (
    <aside aria-label="同步任务轨道" className="sync-task-rail">
      <header>
        <div>
          <h3>任务轨道</h3>
          <p>当前、排队与最近历史</p>
        </div>
        <Button onClick={onCreateTask} size="sm" type="button" variant="primary">
          新建同步任务
        </Button>
      </header>
      <div className="sync-task-rail__list">
        {jobs.length ? (
          jobs.slice(0, 12).map((job) => (
            <button
              aria-label={`查看${operationJobLabel(job)}详情`}
              className="sync-task-row"
              key={job.job_id}
              onClick={(event) => onSelectJob(job, event)}
              type="button"
            >
              <span className="sync-task-row__heading">
                <strong>{operationJobLabel(job)}</strong>
                <StatusChip tone={operationJobTone(job.status)}>
                  {operationJobStatusLabel(job.status)}
                </StatusChip>
              </span>
              <span>{operationStageLabel(job.current_stage)}</span>
              <span className="sync-task-row__progress">
                <span style={{ width: `${progressPercent(job)}%` }} />
              </span>
              <small>
                {job.progress_total > 0
                  ? `${job.progress_current} / ${job.progress_total}`
                  : `尝试 ${job.attempt_count} / ${job.max_attempts}`}
              </small>
            </button>
          ))
        ) : (
          <p className="sync-task-rail__empty">暂无任务事实</p>
        )}
      </div>
    </aside>
  );
}
