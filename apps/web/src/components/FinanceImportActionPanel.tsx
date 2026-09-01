import { useEffect, useState, type FormEvent } from "react";
import {
  ApiRequestError,
  commitFinanceImport,
  correctFinanceImport,
  downloadFinanceImportErrors,
  uploadFinanceImport,
} from "../api/client";
import type { FeeDirection, FinanceImportBatchRow } from "../types/dashboard";
import { displayFinanceImportScenario } from "../utils/userFacingLabels";
import { userFacingError } from "../utils/userFacingError";
import { Button } from "./Button";
import { TextField } from "./FormControls";
import { ResourcePanel } from "./ResourceState";
import { SearchableStoreSelect } from "./SearchableStoreSelect";

const importOptions = {
  PROMOTION: [
    ["PROMOTION_FACTORY_RESULT", "推广服务费厂家结果"],
  ],
  MANAGEMENT: [
    ["MANAGEMENT_FACTORY_RESULT", "管理服务费厂家结果"],
  ],
  STORE: [
    ["BASIC_INFO", "门店基础信息"],
    ["SAP_CONFIRMATION", "SAP 确认"],
  ],
} as const;

export function FinanceImportActionPanel({
  fixedImportType,
  scope,
  month,
  onCommitted,
}: {
  fixedImportType?: string;
  scope: FeeDirection | "STORE";
  month: string;
  onCommitted: () => void;
}) {
  const options = importOptions[scope].filter(
    ([value]) => !fixedImportType || value === fixedImportType,
  );
  const [importType, setImportType] = useState<string>(
    fixedImportType ?? options[0][0],
  );
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FinanceImportBatchRow | null>(null);
  const [changeReason, setChangeReason] = useState("导入系统外已完成的财务结果");
  const [message, setMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [commitKey, setCommitKey] = useState(() => crypto.randomUUID());
  const [fileInputVersion, setFileInputVersion] = useState(0);

  useEffect(() => {
    setFile(null);
    setPreview(null);
    setMessage("");
    setCommitKey(crypto.randomUUID());
    setFileInputVersion((current) => current + 1);
  }, [fixedImportType, month]);

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setMessage("");
    setPreview(null);
    try {
      const response = await uploadFinanceImport({ importType, statementMonth: month, file });
      setPreview(response.data);
      setCommitKey(crypto.randomUUID());
      setMessage(
        response.data.errorRows > 0
          ? "整批校验未通过，请下载错误明细后修正文件。"
          : response.data.scenario === "NO_CHANGE"
            ? "内容与当前版本一致，无需重复提交。"
            : "整批校验通过，请核对版本和变更原因后提交。",
      );
    } catch (error) {
      setMessage(userFacingError(error, "上传校验失败，请稍后重试。"));
    } finally {
      setUploading(false);
    }
  };

  const handleCommit = async () => {
    if (!preview || !changeReason.trim()) return;
    setCommitting(true);
    setMessage("");
    try {
      const payload = {
        readVersion: preview.readVersion,
        changeReason: changeReason.trim(),
      };
      if (preview.scenario === "DIFF_CONFIRMATION_REQUIRED") {
        await correctFinanceImport(preview.batchId, payload, commitKey);
      } else {
        await commitFinanceImport(preview.batchId, payload, commitKey);
      }
      setMessage("导入结果已生效；导入时间作为审核通过或结算完成时间。");
      setPreview(null);
      setFile(null);
      setCommitKey(crypto.randomUUID());
      setFileInputVersion((current) => current + 1);
      onCommitted();
    } catch (error) {
      const conflict = error instanceof ApiRequestError && error.status === 409;
      if (conflict) {
        setPreview(null);
        setFile(null);
        setCommitKey(crypto.randomUUID());
        setFileInputVersion((current) => current + 1);
      }
      setMessage(
        userFacingError(
          error,
          conflict
            ? "版本已发生变化，请重新上传并预览。"
            : "提交失败，请稍后重试；本次重试将沿用同一请求标识。",
        ),
      );
    } finally {
      setCommitting(false);
    }
  };

  const canCommit = Boolean(
    preview &&
      preview.errorRows === 0 &&
      preview.scenario !== "NO_CHANGE" &&
      !preview.committedAt &&
      changeReason.trim(),
  );

  return (
    <section className="content-section finance-import-card">
      <div className="section-title">
        <div>
          <h2>导入财务数据</h2>
          <p>管理员导入系统外已完成处理的数据；原文件不保存，系统整批校验，确认后生成当前有效新版本。</p>
        </div>
        <a href={`/finance/imports?importType=${encodeURIComponent(importType)}&month=${encodeURIComponent(month)}`}>查看导入记录</a>
      </div>
      <form className="finance-form-grid" onSubmit={handleUpload}>
        <label>
          <span>导入模板</span>
          <SearchableStoreSelect
            disabled={Boolean(fixedImportType)}
            emptyMessage="未找到导入模板"
            onChange={(value) => {
              setImportType(value);
              setFile(null);
              setPreview(null);
              setMessage("");
              setCommitKey(crypto.randomUUID());
              setFileInputVersion((current) => current + 1);
            }}
            options={options.map(([value, label]) => ({ value, label }))}
            placeholder="选择导入模板"
            value={importType}
          />
        </label>
        <TextField disabled label="业务账期" value={month} />
        <TextField
          accept=".csv,.xlsx"
          key={`finance-import-file-${fileInputVersion}`}
          label="文件"
          required
          type="file"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setPreview(null);
            setMessage("");
            setCommitKey(crypto.randomUUID());
          }}
        />
        <div className="finance-form-actions"><Button disabled={!file} loading={uploading} type="submit" variant="primary">上传并预览</Button>{message ? <span role="status">{message}</span> : null}</div>
      </form>
      {preview ? (
        <div className="finance-import-preview">
          <div className="finance-import-summary">
            <span>场景<strong>{displayFinanceImportScenario(preview.scenario)}</strong></span>
            <span>成功行<strong>{preview.successRows}</strong></span>
            <span>错误行<strong>{preview.errorRows}</strong></span>
            <span>读取 / 当前版本<strong>V{preview.readVersion} / V{preview.currentVersion}</strong></span>
          </div>
          {preview.errorRows > 0 ? (
            <Button onClick={() => downloadFinanceImportErrors(preview.batchId)} variant="secondary">下载全部错误</Button>
          ) : (
            <ResourcePanel>校验结果不会自动写入，提交前仍可放弃。</ResourcePanel>
          )}
          <div className="finance-form-actions">
            <TextField fieldClassName="finance-change-reason" label="变更原因" value={changeReason} onChange={(event) => setChangeReason(event.target.value)} />
            <Button disabled={!canCommit} loading={committing} onClick={handleCommit} variant="primary">确认提交</Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
