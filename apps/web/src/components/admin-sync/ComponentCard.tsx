import type { MouseEvent } from "react";
import type { AdminOperationComponent } from "../../types/dashboard";
import { formatDateTime } from "../../utils/format";
import { StatusChip } from "../Chips";
import { SolarIcon, type SolarIconName } from "../SolarIcon";
import {
  componentLabel,
  formatBytes,
  observedStatusLabel,
  observedStatusTone,
} from "./syncPresentation";

interface ComponentCardProps {
  component: AdminOperationComponent;
  onSelect: (event: MouseEvent<HTMLButtonElement>) => void;
}

function componentIcon(type: AdminOperationComponent["component_type"]): SolarIconName {
  if (type === "worker" || type === "browser") return "sync";
  if (type === "ops_agent") return "rules";
  return "monitor";
}

export function ComponentCard({ component, onSelect }: ComponentCardProps) {
  const label = componentLabel(component.component_type);

  return (
    <button
      aria-label={`查看${label}详情`}
      className="component-card"
      onClick={onSelect}
      type="button"
    >
      <span className="component-card__icon">
        <SolarIcon name={componentIcon(component.component_type)} size={20} />
      </span>
      <span className="component-card__main">
        <span className="component-card__title-row">
          <strong>{label}</strong>
          <StatusChip tone={observedStatusTone(component.observed_status)}>
            {observedStatusLabel(component.observed_status)}
          </StatusChip>
        </span>
        <small>{component.component_instance_id ?? "尚无实例心跳"}</small>
        <span className="component-card__metrics">
          <span>RSS {formatBytes(component.resources.rss_bytes)}</span>
          <span>队列 {component.resources.queue_depth ?? "未知"}</span>
          <span>
            心跳 {component.last_heartbeat_at ? formatDateTime(component.last_heartbeat_at) : "未知"}
          </span>
        </span>
      </span>
    </button>
  );
}
