import { useRef, useState } from "react";
import {
  commitSkuFeeRuleImport,
  createIdempotencyKey,
  downloadSkuFeeRuleImportResult,
  downloadSkuFeeRuleImportTemplate,
  fetchSkuFeeRuleImportDetail,
  uploadSkuFeeRuleImport,
} from "../api/client";
import type { ImportBatchItem, ImportRowItem } from "../types/dashboard";
import { apiErrorText } from "../utils/apiErrors";
import { formatInteger } from "../utils/format";
import {
  displayImportBatchStatus,
  displayImportRowStatus,
} from "../utils/userFacingLabels";
import { Button } from "./Button";
import { StatusChip, type ChipTone } from "./Chips";
import { Dialog } from "./Dialog";
import { FieldInput } from "./FormControls";

const FIRST_EFFECTIVE_DATE = "2026-08-01";

function statusTone(value: string): ChipTone {
  if (["COMPLETED", "COMMITTED", "VALID"].includes(value)) return "success";
  if (["VALIDATION_FAILED", "FAILED", "INVALID", "COMMIT_FAILED"].includes(value)) {
    return "danger";
  }
  if (["PENDING_COMMIT", "COMMITTING", "PENDING"].includes(value)) return "warning";
  return "neutral";
}

interface AdminSkuRuleImportDrawerProps {
  batches: ImportBatchItem[];
  initialBatch: ImportBatchItem | null;
  onChanged: () => Promise<void>;
  onClose: () => void;
  open: boolean;
}

export function AdminSkuRuleImportDrawer({
  batches,
  initialBatch,
  onChanged,
  onClose,
  open,
}: AdminSkuRuleImportDrawerProps) {
  const importCommitIntent = useRef<{ fingerprint: string; key: string } | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importDate, setImportDate] = useState(FIRST_EFFECTIVE_DATE);
  const [importReason, setImportReason] = useState("");
  const [activeBatch, setActiveBatch] = useState<ImportBatchItem | null>(initialBatch);
  const [errorRows, setErrorRows] = useState<ImportRowItem[]>([]);
  const [hasMoreErrors, setHasMoreErrors] = useState(false);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");

  const uploadImport = async () => {
    if (!importFile) {
      setNotice("请先选择 UTF-8 CSV 或 XLSX 文件。");
      return;
    }
    setWorking(true);
    setNotice("");
    try {
      const response = await uploadSkuFeeRuleImport(importFile, importDate);
      setActiveBatch(response.data.batch);
      setErrorRows(response.data.errorPreview);
      setHasMoreErrors(response.data.hasMoreErrors);
      setNotice(
        response.data.batch.batchStatus === "PENDING_COMMIT"
          ? "全量预校验通过，可以确认原子提交。"
          : "预校验发现错误，整批未写入。请按行号、字段和原因修改文件后重新上传。",
      );
      await onChanged();
    } catch (error) {
      setNotice(apiErrorText(error, "文件上传或预校验失败。", {
        422: "文件内容或生效日期不符合导入要求。",
      }));
    } finally {
      setWorking(false);
    }
  };

  const commitImport = async () => {
    if (!activeBatch || activeBatch.batchStatus !== "PENDING_COMMIT" || !importReason.trim()) {
      setNotice("只有全量校验通过的批次才能提交，并且必须填写变更原因。");
      return;
    }
    const fingerprint = JSON.stringify({
      batchId: activeBatch.batchId,
      changeReason: importReason.trim(),
    });
    if (importCommitIntent.current?.fingerprint !== fingerprint) {
      importCommitIntent.current = {
        fingerprint,
        key: createIdempotencyKey("sku-fee-import"),
      };
    }
    setWorking(true);
    setNotice("");
    try {
      const response = await commitSkuFeeRuleImport(
        activeBatch.batchId,
        importReason.trim(),
        importCommitIntent.current.key,
      );
      importCommitIntent.current = null;
      setActiveBatch(response.data.batch);
      setNotice(`整批已原子写入 ${formatInteger(response.data.batch.successCount)} 条规则。`);
      await onChanged();
    } catch (error) {
      setNotice(apiErrorText(error, "整批原子提交失败，正式规则未部分写入。", {
        403: "当前账号不是最高管理员，不能提交正式规则。",
        409: "提交时发现版本冲突，整批已回滚。",
      }));
    } finally {
      setWorking(false);
    }
  };

  const chooseBatch = async (batch: ImportBatchItem) => {
    setWorking(true);
    setActiveBatch(batch);
    setErrorRows([]);
    setHasMoreErrors(false);
    try {
      const response = await fetchSkuFeeRuleImportDetail(batch.batchId);
      setActiveBatch(response.data.batch);
      setErrorRows(response.data.rows.list);
      setHasMoreErrors(response.data.rows.total > response.data.rows.list.length);
      setNotice(`已读取导入批次 ${batch.batchId} 的校验详情。`);
    } catch (error) {
      setNotice(apiErrorText(error, "导入批次详情暂时无法读取。"));
    } finally {
      setWorking(false);
    }
  };

  return (
    <Dialog
      actions={
        <>
          <Button disabled={working} onClick={onClose} type="button">
            关闭
          </Button>
          <Button
            disabled={working || activeBatch?.batchStatus !== "PENDING_COMMIT"}
            onClick={() => void commitImport()}
            type="button"
            variant="primary"
          >
            确认原子提交
          </Button>
        </>
      }
      closeDisabled={working}
      description="先上传并全量预校验；任一行错误时整批不写入，全部通过后才可原子提交。"
      onClose={onClose}
      open={open}
      panelClassName="admin-import-drawer"
      title="批量导入设置"
    >
      {notice ? <div aria-live="polite" className="resource-notice" role="status">{notice}</div> : null}

      <div className="admin-form-grid admin-import-drawer__form">
        <label className="filter-field">
          <span>CSV / XLSX 文件</span>
          <FieldInput
            accept=".csv,.xlsx"
            onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
            type="file"
          />
        </label>
        <label className="filter-field">
          <span>整批生效日期</span>
          <FieldInput
            min={FIRST_EFFECTIVE_DATE}
            onChange={(event) => setImportDate(event.target.value)}
            type="date"
            value={importDate}
          />
        </label>
        <div className="admin-header-actions">
          <Button onClick={() => void downloadSkuFeeRuleImportTemplate()} type="button">
            下载标准模板
          </Button>
          <Button disabled={working || !importFile} onClick={() => void uploadImport()} type="button">
            上传并预校验
          </Button>
        </div>
        <label className="filter-field admin-form-grid__wide">
          <span>提交变更原因</span>
          <FieldInput
            maxLength={512}
            onChange={(event) => setImportReason(event.target.value)}
            placeholder="说明本次整批变更原因"
            value={importReason}
          />
        </label>
      </div>

      {activeBatch ? (
        <div className="resource-panel">
          <div className="admin-batch-summary">
            <StatusChip tone={statusTone(activeBatch.batchStatus)}>
              {displayImportBatchStatus(activeBatch.batchStatus)}
            </StatusChip>
            <span>总计 {formatInteger(activeBatch.totalCount)}</span>
            <span>合法 {formatInteger(activeBatch.validCount)}</span>
            <span>失败 {formatInteger(activeBatch.failedCount)}</span>
            <span>正式写入 {formatInteger(activeBatch.successCount)}</span>
            {activeBatch.hasResultFile ? (
              <Button
                onClick={() => void downloadSkuFeeRuleImportResult(activeBatch.batchId)}
                size="sm"
              >
                下载结果文件
              </Button>
            ) : null}
          </div>
          {activeBatch.batchStatus === "VALIDATION_FAILED" ? (
            <p className="admin-error">整批未写入。以下按原文件行号列出已返回错误。</p>
          ) : null}
          {errorRows.map((row) => (
            <div className="admin-import-error" key={row.rowNumber}>
              <strong>第 {row.rowNumber} 行 · {displayImportRowStatus(row.validationStatus)}</strong>
              {row.errors.map((error) => (
                <span key={`${row.rowNumber}-${error.field}-${error.code}`}>
                  {error.field}：{error.message}
                </span>
              ))}
            </div>
          ))}
          {hasMoreErrors ? <p className="admin-muted">还有更多错误，请下载结果文件查看。</p> : null}
        </div>
      ) : null}

      <div className="admin-batch-list">
        {batches.map((batch) => (
          <button
            className="admin-batch-list__item"
            disabled={working}
            key={batch.batchId}
            onClick={() => void chooseBatch(batch)}
            type="button"
          >
            <span>{batch.fileName}</span>
            <StatusChip tone={statusTone(batch.batchStatus)}>
              {displayImportBatchStatus(batch.batchStatus)}
            </StatusChip>
            <span>{batch.effectiveDate}</span>
          </button>
        ))}
      </div>
    </Dialog>
  );
}
