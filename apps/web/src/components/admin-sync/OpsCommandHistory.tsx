import type { AdminOpsCommand } from "../../types/dashboard";
import { formatDateTime } from "../../utils/format";
import { StatusChip } from "../Chips";
import {
  componentLabel,
  opsCommandStatusLabel,
  opsCommandStatusTone,
} from "./syncPresentation";

interface OpsCommandHistoryProps {
  commands: AdminOpsCommand[];
  error: string;
}

function commandResult(command: AdminOpsCommand): string {
  if (command.result_summary) return command.result_summary;
  if (command.result_code) return command.result_code;
  if (command.status === "pending") return "等待运维代理接收";
  if (command.status === "running") return "正在执行，尚无结果摘要";
  return "暂无结果摘要";
}

function commandTime(command: AdminOpsCommand): { label: string; value: string } {
  if (command.finished_at) {
    return { label: "完成", value: command.finished_at };
  }
  if (command.started_at) {
    return { label: "开始", value: command.started_at };
  }
  return { label: "创建", value: command.created_at };
}

export function OpsCommandHistory({ commands, error }: OpsCommandHistoryProps) {
  return (
    <section aria-labelledby="ops-command-history-title" className="ops-command-history">
      <header>
        <div>
          <h3 id="ops-command-history-title">最近 Ops 命令</h3>
          <p>状态来自服务端轮询，提交回执不视为执行成功。</p>
        </div>
        <span>{commands.length} 条</span>
      </header>
      {error ? (
        <p className="resource-notice resource-notice--warning" role="status">
          {error}
        </p>
      ) : null}
      {commands.length ? (
        <div className="ops-command-list">
          {commands.map((command) => {
            const timestamp = commandTime(command);
            return (
              <article className="ops-command-row" key={command.command_id}>
                <div className="ops-command-row__identity">
                  <strong>{componentLabel(command.target_component)}</strong>
                  <small>
                    {timestamp.label} {formatDateTime(timestamp.value)}
                  </small>
                </div>
                <StatusChip tone={opsCommandStatusTone(command.status)}>
                  {opsCommandStatusLabel(command.status)}
                </StatusChip>
                <p>{commandResult(command)}</p>
              </article>
            );
          })}
        </div>
      ) : error ? null : (
        <p className="admin-muted">暂无 Ops 命令</p>
      )}
    </section>
  );
}
