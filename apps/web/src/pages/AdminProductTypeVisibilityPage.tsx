import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  bulkUpdateSkuProducts,
  commitSkuProductImport,
  downloadSkuProductImportTemplate,
  fetchFilterMeta,
  fetchSkuProducts,
  updateSkuProduct,
  uploadSkuProductImport,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { FieldInput, SelectField, TextField } from "../components/FormControls";
import { TablePagination } from "../components/TablePagination";
import type {
  SkuProductConfigurationStatus,
  SkuProductImportUploadData,
  SkuProductItem,
  SkuProductManualFieldsUpdate,
} from "../types/dashboard";
import { formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";

type ViewMode = "pending" | "configured";
type EditorMode = "single" | "bulk" | null;
type FieldMode = "keep" | "set";

const PAGE_SIZE = 50;

const statusLabels: Record<SkuProductConfigurationStatus, string> = {
  UNCONFIGURED: "未配置",
  PARTIAL: "部分配置",
  CONFIGURED: "已配置",
};

function modeFromUrl(): ViewMode {
  return new URLSearchParams(window.location.search).get("view") === "configured"
    ? "configured"
    : "pending";
}

function urlValue(key: string): string {
  return new URLSearchParams(window.location.search).get(key) ?? "";
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) return "登录已过期，请重新登录。";
    if (error.status === 404) return "部分 SKU 已不存在，请刷新列表后重试。";
  }
  return userFacingError(error, "操作未完成，请稍后重试。");
}

export function AdminProductTypeVisibilityPage() {
  const [viewMode, setViewMode] = useState<ViewMode>(modeFromUrl);
  const [rows, setRows] = useState<SkuProductItem[]>([]);
  const [page, setPage] = useState(() => Math.max(1, Number(urlValue("page")) || 1));
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState({ unconfigured: 0, partial: 0, configured: 0 });
  const [query, setQuery] = useState(() => urlValue("q"));
  const [productScope, setProductScope] = useState(() => urlValue("productScope"));
  const [productType, setProductType] = useState(() => urlValue("productType"));
  const [scopeTypeMap, setScopeTypeMap] = useState<Record<string, string[]>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [editorMode, setEditorMode] = useState<EditorMode>(null);
  const [editingRow, setEditingRow] = useState<SkuProductItem | null>(null);
  const [scopeMode, setScopeMode] = useState<FieldMode>("keep");
  const [typeMode, setTypeMode] = useState<FieldMode>("keep");
  const [scopeValue, setScopeValue] = useState("");
  const [typeValue, setTypeValue] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<SkuProductImportUploadData | null>(null);

  const loadRows = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchSkuProducts({
        page,
        pageSize: PAGE_SIZE,
        q: query.trim() || undefined,
        productScope: productScope || undefined,
        productType: productType || undefined,
        configurationStatus: viewMode === "pending" ? "PENDING" : "CONFIGURED",
      });
      setRows(response.data.list);
      setTotal(response.data.total);
      setCounts(response.data.statusCounts);
      setNotice("");
    } catch (error) {
      setRows([]);
      setNotice(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [page, productScope, productType, query, viewMode]);

  useEffect(() => {
    void loadRows();
  }, [loadRows]);

  useEffect(() => {
    void fetchFilterMeta().then((response) => {
      setScopeTypeMap(response.data.product_scope_type_map ?? {});
    });
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("view", viewMode);
    params.set("page", String(page));
    if (query) params.set("q", query); else params.delete("q");
    if (productScope) params.set("productScope", productScope); else params.delete("productScope");
    if (productType) params.set("productType", productType); else params.delete("productType");
    window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }, [page, productScope, productType, query, viewMode]);

  const productScopes = useMemo(() => Object.keys(scopeTypeMap).sort((left, right) => left.localeCompare(right, "zh-Hans-CN")), [scopeTypeMap]);
  const filteredProductTypes = useMemo(() => {
    const values = productScope ? scopeTypeMap[productScope] ?? [] : Object.values(scopeTypeMap).flat();
    return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
  }, [productScope, scopeTypeMap]);

  const switchView = (next: ViewMode) => {
    setViewMode(next);
    setPage(1);
  };

  const toggleSelected = (skuId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(skuId)) next.delete(skuId); else next.add(skuId);
      return next;
    });
  };

  const openEditor = (mode: Exclude<EditorMode, null>, row?: SkuProductItem) => {
    setEditorMode(mode);
    setEditingRow(row ?? null);
    setScopeMode("keep");
    setTypeMode("keep");
    setScopeValue(row?.productScope ?? "");
    setTypeValue(row?.productType ?? "");
  };

  const buildUpdate = (): SkuProductManualFieldsUpdate | null => {
    const payload: SkuProductManualFieldsUpdate = {};
    if (scopeMode === "set" && scopeValue.trim()) payload.productScope = scopeValue.trim();
    if (typeMode === "set" && typeValue.trim()) payload.productType = typeValue.trim();
    return Object.keys(payload).length ? payload : null;
  };

  const saveEditor = async () => {
    const payload = buildUpdate();
    if (!payload) {
      setNotice("请至少设置产品范围或商品类型中的一项。");
      return;
    }
    setSaving(true);
    try {
      if (editorMode === "single" && editingRow) {
        await updateSkuProduct(editingRow.skuId, {
          ...payload,
          expectedManualModifiedAt: editingRow.manualModifiedAt,
        });
        setNotice(`SKU ${editingRow.skuId} 已更新。`);
      } else {
        await bulkUpdateSkuProducts({ skuIds: Array.from(selected), ...payload });
        setNotice(`已批量更新 ${selected.size} 个 SKU。`);
        setSelected(new Set());
      }
      setEditorMode(null);
      await loadRows();
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const uploadImport = async () => {
    if (!importFile) return;
    setSaving(true);
    try {
      const response = await uploadSkuProductImport(importFile);
      setImportPreview(response.data);
      setNotice(response.data.batch.failedCount ? "文件存在错误，请修正后重新导入。" : "预校验通过，请确认后写入。 ");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const commitImport = async () => {
    if (!importPreview || importPreview.batch.batchStatus !== "PENDING_COMMIT") return;
    setSaving(true);
    try {
      await commitSkuProductImport(importPreview.batch.batchId);
      setNotice(`已导入并更新 ${importPreview.batch.validCount} 个 SKU。`);
      setImportOpen(false);
      setImportPreview(null);
      setImportFile(null);
      await loadRows();
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const columns = useMemo<Column<SkuProductItem>[]>(() => [
    {
      key: "select",
      title: "选择",
      width: 64,
      render: (row) => <FieldInput aria-label={`选择 ${row.skuId}`} checked={selected.has(row.skuId)} onChange={() => toggleSelected(row.skuId)} type="checkbox" />,
    },
    { key: "sku", title: "SKU 编码", minWidth: 150, render: (row) => <code>{row.skuId}</code> },
    { key: "name", title: "商品名称", minWidth: 200, render: (row) => row.skuName || row.productName || "-" },
    { key: "scope", title: "产品范围", minWidth: 150, render: (row) => row.productScope || "未设置" },
    { key: "type", title: "商品类型", minWidth: 150, render: (row) => row.productType || "未设置" },
    { key: "status", title: "配置状态", width: 110, render: (row) => <span className={`product-types-status is-${row.configurationStatus.toLowerCase()}`}>{statusLabels[row.configurationStatus]}</span> },
    { key: "modified", title: "最后修改", minWidth: 170, render: (row) => row.manualModifiedAt ? <>{formatDateTime(row.manualModifiedAt)}<small>{row.manualModifiedBy || "-"}</small></> : "-" },
    { key: "action", title: "操作", width: 100, render: (row) => <Button onClick={() => openEditor("single", row)} size="sm" variant="secondary">设置</Button> },
  ], [selected]);

  return (
    <div className="admin-page product-types-workbench">
      <section className="admin-header product-types-header">
        <div>
          <span className="source-pill">SKU 人工分类</span>
          <h1>商品口径</h1>
          <p className="admin-muted">产品范围和商品类型会同时用于线索中心、核销表现和订单分佣。所有商品都可展示；订单分佣还要求商品存在有效分佣规则。</p>
        </div>
        <Button onClick={() => setImportOpen(true)} variant="secondary">批量导入</Button>
      </section>

      <nav aria-label="商品口径配置状态" className="product-types-tabs">
        <Button onClick={() => switchView("pending")} variant={viewMode === "pending" ? "primary" : "secondary"}>待完善 <span>{counts.unconfigured + counts.partial}</span></Button>
        <Button onClick={() => switchView("configured")} variant={viewMode === "configured" ? "primary" : "secondary"}>已配置 <span>{counts.configured}</span></Button>
      </nav>

      {notice ? <div aria-live="polite" className="resource-notice" role="status">{notice}</div> : null}

      <section className="content-section product-types-panel">
        <div className="product-types-toolbar">
          <div className="product-types-filters">
            <TextField label="查询 SKU / 商品名称" onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="输入关键词" value={query} />
            <SelectField label="产品范围" onChange={(value) => { setProductScope(value); if (productType && !(scopeTypeMap[value] ?? []).includes(productType)) setProductType(""); setPage(1); }} options={[{ label: "全部产品范围", value: "" }, ...productScopes.map((value) => ({ label: value, value }))]} value={productScope} />
            <SelectField label="商品类型" onChange={(value) => { setProductType(value); setPage(1); }} options={[{ label: "全部商品类型", value: "" }, ...filteredProductTypes.map((value) => ({ label: value, value }))]} value={productType} />
          </div>
          <div className="product-types-selection">
            <span>已跨页选择 <strong>{selected.size}</strong> 个 SKU</span>
            <Button disabled={!selected.size} onClick={() => setSelected(new Set())} variant="text">清空</Button>
            <Button disabled={!selected.size} onClick={() => openEditor("bulk")} variant="primary">批量设置</Button>
          </div>
        </div>
        <p className="product-types-hint">待完善默认按“未配置 → 部分配置”排列；默认每页 50 条。筛选和翻页不会清除已勾选 SKU。</p>
        <DataTable columns={columns} emptyText={viewMode === "pending" ? "当前筛选下没有待完善 SKU。" : "当前筛选下没有已配置 SKU。"} loadingText="正在加载商品口径…" mobileCard={false} rows={rows} state={loading ? "loading" : notice && !rows.length ? "error" : "ready"} />
        <TablePagination loading={loading} onPageChange={setPage} page={page} pageSize={PAGE_SIZE} rowsOnPage={rows.length} total={total} totalPages={Math.max(1, Math.ceil(total / PAGE_SIZE))} />
      </section>

      <Dialog actions={<><Button disabled={saving} onClick={() => setEditorMode(null)} variant="secondary">取消</Button><Button disabled={saving} onClick={() => void saveEditor()} variant="primary">确认设置</Button></>} description={editorMode === "bulk" ? `将修改已跨页选择的 ${selected.size} 个 SKU；未选择设置的字段保持原值。` : `SKU ${editingRow?.skuId ?? ""}；未选择设置的字段保持原值。`} onClose={() => setEditorMode(null)} open={editorMode !== null} panelClassName="product-types-drawer" title={editorMode === "bulk" ? "批量设置商品口径" : "设置商品口径"}>
        <div className="product-types-editor-field">
          <SelectField label="产品范围处理方式" onChange={(value) => setScopeMode(value as FieldMode)} options={[{ label: "保持原值", value: "keep" }, { label: "设置新值", value: "set" }]} value={scopeMode} />
          {scopeMode === "set" ? <><TextField helperText="可输入新值，也可选择已有建议。" label="产品范围" list="product-scope-suggestions" onChange={(event) => setScopeValue(event.target.value)} placeholder="输入或选择产品范围" value={scopeValue} /><datalist id="product-scope-suggestions">{productScopes.map((value) => <option key={value} value={value} />)}</datalist></> : null}
        </div>
        <div className="product-types-editor-field">
          <SelectField label="商品类型处理方式" onChange={(value) => setTypeMode(value as FieldMode)} options={[{ label: "保持原值", value: "keep" }, { label: "设置新值", value: "set" }]} value={typeMode} />
          {typeMode === "set" ? <><TextField helperText="可输入新值，也可选择已有建议。" label="商品类型" list="product-type-suggestions" onChange={(event) => setTypeValue(event.target.value)} placeholder="输入或选择商品类型" value={typeValue} /><datalist id="product-type-suggestions">{(scopeMode === "set" && scopeValue ? scopeTypeMap[scopeValue] ?? filteredProductTypes : filteredProductTypes).map((value) => <option key={value} value={value} />)}</datalist></> : null}
        </div>
      </Dialog>

      <Dialog actions={<><Button disabled={saving} onClick={() => setImportOpen(false)} variant="secondary">取消</Button>{importPreview?.batch.batchStatus === "PENDING_COMMIT" ? <Button disabled={saving} onClick={() => void commitImport()} variant="primary">确认写入 {importPreview.batch.validCount} 条</Button> : <Button disabled={saving || !importFile} onClick={() => void uploadImport()} variant="primary">上传并预校验</Button>}</>} description="支持 UTF-8 CSV 或 XLSX。字段为 skuId、productScope、productType；单项不修改请填写 KEEP，空白和两个 KEEP 都会阻止整批写入。" onClose={() => setImportOpen(false)} open={importOpen} panelClassName="product-types-drawer" title="批量导入商品口径">
        <div className="product-types-import-actions"><Button onClick={() => void downloadSkuProductImportTemplate()} variant="secondary">下载模板</Button><FieldInput accept=".csv,.xlsx" aria-label="选择商品口径导入文件" onChange={(event) => { setImportFile(event.target.files?.[0] ?? null); setImportPreview(null); }} type="file" /></div>
        {importPreview ? <div className="product-types-import-summary"><strong>{importPreview.batch.batchStatus === "PENDING_COMMIT" ? "预校验通过" : "预校验未通过"}</strong><span>总计 {importPreview.batch.totalCount} / 有效 {importPreview.batch.validCount} / 错误 {importPreview.batch.failedCount}</span>{importPreview.errorPreview.slice(0, 10).map((row) => <p key={row.rowNumber}>第 {row.rowNumber} 行：{row.errors.map(({ message }) => message).join("；")}</p>)}</div> : null}
      </Dialog>
    </div>
  );
}
