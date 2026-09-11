import { useState } from "react";
import { ApiRequestError, uploadDouyinRankingConfiguration } from "../api/client";
import { Button } from "./Button";
import type { DouyinRankingConfigurationImportData } from "../types/dashboard";

function resultText(result: DouyinRankingConfigurationImportData): string {
  const pending = result.missing_organization_count ?? 0;
  return `${result.changed ? "名单版本已更新" : "名单与当前版本一致"}：${result.store_count} 家入驻门店，${result.eligible_store_count} 家精诚养车适用门店${pending ? `；${pending} 家门店的缺失层级已单列为“待补充归属”` : ""}`;
}

export function DouyinStoreOrgMappingPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [eligibilityFile, setEligibilityFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [result, setResult] = useState<DouyinRankingConfigurationImportData | null>(null);

  const handleUpload = async () => {
    if (!file && !eligibilityFile) {
      setStatusText("请先选择需要更新的名单，首次导入需要同时提供两份名单。");
      return;
    }
    setUploading(true);
    setStatusText("");
    try {
      const response = await uploadDouyinRankingConfiguration(file, eligibilityFile);
      setResult(response.data);
      setStatusText(`${resultText(response.data)}。历史组织归属继续保留。`);
    } catch (error) {
      setStatusText(
        error instanceof ApiRequestError
          ? error.message
          : "映射表上传失败，请检查文件格式后重试。",
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="content-section">
      <div className="section-title">
        <div>
          <h2>抖音打榜名单管理</h2>
          <p>
            管理含集团、服务中心、大区、区域的门店组织表及精诚养车适用门店名单。首次同时导入两份，后续可单独更新一份；缺失集团、大区或区域时单列“待补充归属”。更新后的新线索按新组织归属统计，历史快照保留，店均订单量按统计开始日的适用名单计算。
          </p>
        </div>
      </div>
      <div className="manual-sync-grid">
        <label className="filter-field">
          <span>门店组织表（CSV / XLSX，最大 10 MB）</span>
          <input
            accept=".csv,.xlsx,.xlsm"
            className="field-input"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setStatusText("");
              setResult(null);
            }}
            type="file"
          />
        </label>
        <label className="filter-field">
          <span>精诚养车适用门店名单（CSV / XLSX，最大 10 MB）</span>
          <input accept=".csv,.xlsx,.xlsm" className="field-input" type="file"
            onChange={(event) => {
              setEligibilityFile(event.target.files?.[0] ?? null);
              setStatusText("");
              setResult(null);
            }} />
        </label>
        <Button disabled={uploading} onClick={handleUpload} type="button" variant="primary">
          {uploading ? "上传中…" : "上传并更新名单"}
        </Button>
      </div>
      {statusText ? (
        <div aria-live="polite" className="resource-notice" role="status">
          {statusText}
        </div>
      ) : null}
      {result ? (
        <div className="source-pill">
          生效时间：{new Date(result.effective_from).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}
        </div>
      ) : null}
    </section>
  );
}
