import { useEffect, useMemo, useRef, useState } from "react";
import {
  commitSkuFeeRuleImport,
  createIdempotencyKey,
  downloadSkuFeeRuleImportResult,
  downloadSkuFeeRuleImportTemplate,
  fetchSkuFeeRuleImports,
  fetchSkuFeeRuleImportDetail,
  fetchSkuFeeRules,
  fetchSkuProducts,
  publishSkuFeeRule,
  updateSkuProduct,
  uploadSkuFeeRuleImport,
} from "../api/client";
import type {
  ImportBatchItem,
  ImportRowItem,
  SkuFeeRuleItem,
  SkuProductItem,
} from "../types/dashboard";
import { apiErrorText } from "../utils/apiErrors";
import { formatDateTime, formatInteger } from "../utils/format";
import {
  displayFeeRuleStatus,
  displayImportBatchStatus,
  displayImportRowStatus,
  displayProductStatus,
} from "../utils/userFacingLabels";
import { Button } from "./Button";
import { StatusChip, type ChipTone } from "./Chips";
import { DataTable, type Column } from "./DataTable";
import { SelectField } from "./FormControls";

const FIRST_EFFECTIVE_DATE = "2026-08-01";

function percentInputToRate(value: string): string | null {
  const percent = Number(value.trim());
  if (!Number.isFinite(percent) || percent < 0 || percent > 100) return null;
  return (percent / 100).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}

function formatRate(value: string | null | undefined): string {
  const rate = Number(value ?? "0");
  return Number.isFinite(rate)
    ? `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 6 }).format(rate * 100)}%`
    : "-";
}

function statusTone(value: string): ChipTone {
  if (["ACTIVE", "COMPLETED", "COMMITTED", "VALID"].includes(value)) return "success";
  if (["VALIDATION_FAILED", "FAILED", "INVALID", "COMMIT_FAILED"].includes(value)) {
    return "danger";
  }
  if (["PENDING_COMMIT", "COMMITTING", "PENDING"].includes(value)) return "warning";
  return "neutral";
}

export function AdminSkuGovernancePanel() {
  const feePublishIntent = useRef<{ fingerprint: string; key: string } | null>(null);
  const importCommitIntent = useRef<{ fingerprint: string; key: string } | null>(null);
  const [products, setProducts] = useState<SkuProductItem[]>([]);
  const [feeRules, setFeeRules] = useState<SkuFeeRuleItem[]>([]);
  const [batches, setBatches] = useState<ImportBatchItem[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<SkuProductItem | null>(null);
  const [productQuery, setProductQuery] = useState("");
  const [productScope, setProductScope] = useState("");
  const [productType, setProductType] = useState("");
  const [isServiceProduct, setIsServiceProduct] = useState(true);
  const [ruleSkuId, setRuleSkuId] = useState("");
  const [promotionRate, setPromotionRate] = useState("10");
  const [managementRate, setManagementRate] = useState("10");
  const [sameRate, setSameRate] = useState(true);
  const [effectiveDate, setEffectiveDate] = useState(FIRST_EFFECTIVE_DATE);
  const [ruleStatus, setRuleStatus] = useState<"ACTIVE" | "INACTIVE">("ACTIVE");
  const [changeReason, setChangeReason] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importDate, setImportDate] = useState(FIRST_EFFECTIVE_DATE);
  const [importReason, setImportReason] = useState("");
  const [activeBatch, setActiveBatch] = useState<ImportBatchItem | null>(null);
  const [errorRows, setErrorRows] = useState<ImportRowItem[]>([]);
  const [hasMoreErrors, setHasMoreErrors] = useState(false);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");

  const loadProducts = async (q = productQuery) => {
    const response = await fetchSkuProducts({ page: 1, pageSize: 50, q: q.trim() });
    setProducts(response.data.list);
    return response.data.list;
  };

  const loadFeeRules = async () => {
    const response = await fetchSkuFeeRules({ page: 1, pageSize: 20 });
    setFeeRules(response.data.list);
  };

  const loadBatches = async () => {
    const response = await fetchSkuFeeRuleImports({ page: 1, pageSize: 10 });
    setBatches(response.data.list);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([loadProducts(""), loadFeeRules(), loadBatches()])
      .catch((error) => {
        if (!cancelled) setNotice(apiErrorText(error, "商品治理数据暂时无法读取。"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const chooseProduct = (row: SkuProductItem) => {
    setSelectedProduct(row);
    setProductScope(row.productScope);
    setProductType(row.productType);
    setIsServiceProduct(row.isServiceProduct);
    setRuleSkuId(row.skuId);
  };

  const saveProduct = async () => {
    if (!selectedProduct || !productScope.trim() || !productType.trim()) {
      setNotice("请选择商品，并完整填写产品范围和商品类型。");
      return;
    }
    setWorking(true);
    try {
      await updateSkuProduct(selectedProduct.skuId, {
        productScope: productScope.trim(),
        productType: productType.trim(),
        isServiceProduct,
      });
      const reloaded = await loadProducts();
      const saved = reloaded.find((item) => item.skuId === selectedProduct.skuId) ?? null;
      setSelectedProduct(saved);
      setNotice(`SKU ${selectedProduct.skuId} 的人工分类已保存并重新加载回显。`);
    } catch (error) {
      setNotice(apiErrorText(error, "商品人工分类保存失败。", { 403: "当前账号无保存权限。" }));
    } finally {
      setWorking(false);
    }
  };

  const publishRule = async () => {
    const promotion = percentInputToRate(promotionRate);
    const management = percentInputToRate(managementRate);
    if (!ruleSkuId.trim() || !promotion || !management || !changeReason.trim()) {
      setNotice("请完整填写 SKU、两项费率、生效自然日和变更原因；费率范围为 0%～100%。");
      return;
    }
    if (sameRate && promotion !== management) {
      setNotice("当前选择两项费率一致，请先同步费率或取消一致选项。");
      return;
    }
    const payload = {
      skuId: ruleSkuId.trim(),
      promotionServiceFeeRate: promotion,
      managementServiceFeeRate: management,
      effectiveDate,
      ruleStatus,
      changeReason: changeReason.trim(),
    };
    const fingerprint = JSON.stringify(payload);
    if (feePublishIntent.current?.fingerprint !== fingerprint) {
      feePublishIntent.current = {
        fingerprint,
        key: createIdempotencyKey("sku-fee-rule"),
      };
    }
    setWorking(true);
    try {
      const response = await publishSkuFeeRule(payload, feePublishIntent.current.key);
      feePublishIntent.current = null;
      await loadFeeRules();
      setNotice(`双费率版本 ${response.data.ruleVersion} 已发布，历史版本不会被覆盖。`);
      setChangeReason("");
    } catch (error) {
      setNotice(apiErrorText(error, "双费率版本发布失败。", {
        403: "当前账号不是最高管理员，不能发布费率版本。",
        409: "该 SKU 在所选生效日已有版本，请选择其他自然日。",
        422: "费率、生效日或变更原因不合法。",
      }));
    } finally {
      setWorking(false);
    }
  };

  const uploadImport = async () => {
    if (!importFile) {
      setNotice("请先选择 UTF-8 CSV 或 XLSX 文件。");
      return;
    }
    setWorking(true);
    try {
      const response = await uploadSkuFeeRuleImport(importFile, importDate);
      setActiveBatch(response.data.batch);
      setErrorRows(response.data.errorPreview);
      setHasMoreErrors(response.data.hasMoreErrors);
      await loadBatches();
      setNotice(
        response.data.batch.batchStatus === "PENDING_COMMIT"
          ? "全量预校验通过，可确认原子提交。"
          : "预校验发现错误，整批未写入。请按行号、字段和原因修正后重新上传。",
      );
    } catch (error) {
      setNotice(apiErrorText(error, "文件上传或预校验失败。", { 422: "文件或生效日不符合导入要求。" }));
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
    try {
      const response = await commitSkuFeeRuleImport(
        activeBatch.batchId,
        importReason.trim(),
        importCommitIntent.current.key,
      );
      importCommitIntent.current = null;
      setActiveBatch(response.data.batch);
      setNotice(`整批已原子写入 ${formatInteger(response.data.batch.successCount)} 条规则。`);
      await Promise.all([loadBatches(), loadFeeRules()]);
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

  const productColumns: Column<SkuProductItem>[] = useMemo(() => [
    { key: "sku", title: "SKU ID", align: "left", render: (row) => <span className="mono-cell">{row.skuId}</span> },
    { key: "name", title: "商品 / SKU 名称", align: "left", render: (row) => row.productName || row.skuName || "-" },
    { key: "owner", title: "商品归属账号", align: "left", render: (row) => row.ownerAccountName || row.ownerAccountId || "未返回" },
    { key: "creator", title: "创建账号", align: "left", render: (row) => row.creatorAccountName || row.creatorAccountId || "未返回" },
    { key: "status", title: "商品状态", render: (row) => <StatusChip tone={row.productStatus === "ACTIVE" ? "success" : "neutral"}>{displayProductStatus(row.productStatus)}</StatusChip> },
    { key: "manual", title: "人工分类", render: (row) => `${row.productScope || "未配置"} / ${row.productType || "未配置"}` },
    { key: "action", title: "操作", render: (row) => <Button onClick={() => chooseProduct(row)} size="sm">编辑人工字段</Button> },
  ], []);

  const feeColumns: Column<SkuFeeRuleItem>[] = [
    { key: "version", title: "版本", align: "left", render: (row) => <span className="mono-cell">{row.ruleVersion}</span> },
    { key: "sku", title: "SKU ID", align: "left", render: (row) => row.skuId },
    { key: "date", title: "生效自然日", render: (row) => row.effectiveDate },
    { key: "promotion", title: "推广服务费比例", align: "right", render: (row) => formatRate(row.promotionServiceFeeRate) },
    { key: "management", title: "管理服务费比例", align: "right", render: (row) => formatRate(row.managementServiceFeeRate) },
    { key: "status", title: "状态", render: (row) => <StatusChip tone={statusTone(row.ruleStatus)}>{displayFeeRuleStatus(row.ruleStatus)}</StatusChip> },
    { key: "reason", title: "变更原因", align: "left", render: (row) => row.changeReason },
    { key: "audit", title: "发布记录", align: "left", render: (row) => `${row.createdBy} / ${formatDateTime(row.publishedAt)}` },
  ];

  return (
    <div className="admin-governance-stack">
      {notice ? <div aria-live="polite" className="resource-notice" role="status">{notice}</div> : null}

      <section className="content-section">
        <div className="section-title">
          <div><h2>商品人工分类</h2><p>平台商品、归属账号、创建账号和在线状态只读；仅可修改产品范围、商品类型和服务商品标记。</p></div>
          <span className="source-pill">{loading ? "加载中" : `${formatInteger(products.length)} 条`}</span>
        </div>
        <div className="admin-tools">
          <label className="filter-field"><span>搜索商品规格（SKU）</span><input onChange={(event) => setProductQuery(event.target.value)} placeholder="SKU ID、SKU 名称或商品名称" value={productQuery} /></label>
          <Button disabled={loading} onClick={() => void loadProducts()} type="button">查询</Button>
        </div>
        <DataTable columns={productColumns} emptyText="暂无商品快照" rows={products} state={loading ? "loading" : "ready"} tableClassName="admin-rule-table" />
        {selectedProduct ? (
          <div className="admin-inline-editor">
            <strong>编辑 SKU {selectedProduct.skuId}</strong>
            <label className="filter-field"><span>产品范围</span><input onChange={(event) => setProductScope(event.target.value)} value={productScope} /></label>
            <label className="filter-field"><span>商品类型</span><input onChange={(event) => setProductType(event.target.value)} value={productType} /></label>
            <label className="filter-field checkbox-field"><span>服务类商品</span><input checked={isServiceProduct} onChange={(event) => setIsServiceProduct(event.target.checked)} type="checkbox" /></label>
            <Button disabled={working} onClick={() => void saveProduct()} type="button" variant="primary">保存并重新加载</Button>
          </div>
        ) : null}
      </section>

      <section className="content-section">
        <div className="section-title"><div><h2>双费率版本发布</h2><p>每次发布生成不可变版本；同一 SKU 与生效自然日冲突时拒绝，不覆盖历史结果。</p></div></div>
        <div className="admin-form-grid">
          <label className="filter-field"><span>SKU ID</span><input onChange={(event) => setRuleSkuId(event.target.value)} value={ruleSkuId} /></label>
          <label className="filter-field checkbox-field"><span>两项费率一致</span><input checked={sameRate} onChange={(event) => { setSameRate(event.target.checked); if (event.target.checked) setManagementRate(promotionRate); }} type="checkbox" /></label>
          <label className="filter-field"><span>推广服务费比例（%）</span><input inputMode="decimal" onChange={(event) => { setPromotionRate(event.target.value); if (sameRate) setManagementRate(event.target.value); }} value={promotionRate} /></label>
          <label className="filter-field"><span>管理服务费比例（%）</span><input disabled={sameRate} inputMode="decimal" onChange={(event) => setManagementRate(event.target.value)} value={managementRate} /></label>
          <label className="filter-field"><span>生效自然日</span><input min={FIRST_EFFECTIVE_DATE} onChange={(event) => setEffectiveDate(event.target.value)} type="date" value={effectiveDate} /></label>
          <SelectField label="规则状态" onChange={(value) => setRuleStatus(value as "ACTIVE" | "INACTIVE")} options={[{ value: "ACTIVE", label: "启用" }, { value: "INACTIVE", label: "停用" }]} value={ruleStatus} />
          <label className="filter-field admin-form-grid__wide"><span>变更原因</span><input maxLength={512} onChange={(event) => setChangeReason(event.target.value)} placeholder="说明本次发布原因" value={changeReason} /></label>
          <Button disabled={working} onClick={() => void publishRule()} type="button" variant="primary">发布新版本</Button>
        </div>
        <DataTable columns={feeColumns} emptyText="暂无双费率版本" rows={feeRules} tableClassName="admin-rule-table" />
      </section>

      <section className="content-section">
        <div className="section-title"><div><h2>批量导入与原子提交</h2><p>先上传并全量预校验；任一行错误时整批未写入，只有全部通过才可确认原子提交。</p></div><Button onClick={() => void downloadSkuFeeRuleImportTemplate()} type="button">下载标准模板</Button></div>
        <div className="admin-form-grid">
          <label className="filter-field"><span>CSV / XLSX 文件</span><input accept=".csv,.xlsx" onChange={(event) => setImportFile(event.target.files?.[0] ?? null)} type="file" /></label>
          <label className="filter-field"><span>整批生效自然日</span><input min={FIRST_EFFECTIVE_DATE} onChange={(event) => setImportDate(event.target.value)} type="date" value={importDate} /></label>
          <Button disabled={working || !importFile} onClick={() => void uploadImport()} type="button">上传并预校验</Button>
          <label className="filter-field admin-form-grid__wide"><span>提交变更原因</span><input maxLength={512} onChange={(event) => setImportReason(event.target.value)} value={importReason} /></label>
          <Button disabled={working || activeBatch?.batchStatus !== "PENDING_COMMIT"} onClick={() => void commitImport()} type="button" variant="primary">确认原子提交</Button>
        </div>
        {activeBatch ? (
          <div className="resource-panel">
            <div className="admin-batch-summary"><StatusChip tone={statusTone(activeBatch.batchStatus)}>{displayImportBatchStatus(activeBatch.batchStatus)}</StatusChip><span>总计 {formatInteger(activeBatch.totalCount)}</span><span>合法 {formatInteger(activeBatch.validCount)}</span><span>失败 {formatInteger(activeBatch.failedCount)}</span><span>正式写入 {formatInteger(activeBatch.successCount)}</span>{activeBatch.hasResultFile ? <Button onClick={() => void downloadSkuFeeRuleImportResult(activeBatch.batchId)} size="sm">下载结果文件</Button> : null}</div>
            {activeBatch.batchStatus === "VALIDATION_FAILED" ? <p className="admin-error">整批未写入。以下按原文件行号列出全部已返回错误。</p> : null}
            {errorRows.map((row) => <div className="admin-import-error" key={row.rowNumber}><strong>第 {row.rowNumber} 行 · {displayImportRowStatus(row.validationStatus)}</strong>{row.errors.map((error) => <span key={`${row.rowNumber}-${error.field}-${error.code}`}>{error.field}：{error.message}</span>)}</div>)}
            {hasMoreErrors ? <p className="admin-muted">还有更多错误，请下载结果文件查看。</p> : null}
          </div>
        ) : null}
        <div className="admin-batch-list">
          {batches.map((batch) => <button className="admin-batch-list__item" disabled={working} key={batch.batchId} onClick={() => void chooseBatch(batch)} type="button"><span>{batch.fileName}</span><StatusChip tone={statusTone(batch.batchStatus)}>{displayImportBatchStatus(batch.batchStatus)}</StatusChip><span>{batch.effectiveDate}</span></button>)}
        </div>
      </section>
    </div>
  );
}
