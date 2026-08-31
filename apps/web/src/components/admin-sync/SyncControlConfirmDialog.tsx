import { useEffect, useState, type RefObject } from "react";
import { Button } from "../Button";
import { Dialog } from "../Dialog";
import { FieldInput } from "../FormControls";

interface SyncControlConfirmDialogProps {
  actionLabel: string;
  busy: boolean;
  error: string;
  impact: string;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  open: boolean;
  returnFocusRef: RefObject<HTMLElement | null>;
  targetLabel: string;
}

export function SyncControlConfirmDialog({
  actionLabel,
  busy,
  error,
  impact,
  onClose,
  onConfirm,
  open,
  returnFocusRef,
  targetLabel,
}: SyncControlConfirmDialogProps) {
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  return (
    <Dialog
      actions={
        <>
          <Button disabled={busy} onClick={onClose} type="button">
            取消
          </Button>
          <Button
            disabled={!reason.trim()}
            loading={busy}
            onClick={() => onConfirm(reason.trim())}
            type="button"
            variant={
              actionLabel.includes("取消") || actionLabel.includes("重启")
                ? "danger"
                : "primary"
            }
          >
            提交{actionLabel}
          </Button>
        </>
      }
      closeDisabled={busy}
      description="此处只提交控制意图，不代表操作已经成功。"
      onClose={onClose}
      open={open}
      returnFocusRef={returnFocusRef}
      title={`${actionLabel} · ${targetLabel}`}
    >
      <div className="sync-control-confirm">
        <p>
          <strong>当前活动任务：</strong>
          {impact}
        </p>
        <p>
          同步工作进程或浏览器采集组件会在安全边界内处理；中断后的任务依赖租约恢复和数据库检查点继续。
        </p>
        {error ? (
          <p className="resource-notice resource-notice--warning" role="alert">
            {error}
          </p>
        ) : null}
        <label className="filter-field">
          <span>操作原因</span>
          <FieldInput
            autoFocus
            onChange={(event) => setReason(event.target.value)}
            placeholder="说明为什么需要执行此操作"
            value={reason}
          />
        </label>
      </div>
    </Dialog>
  );
}
