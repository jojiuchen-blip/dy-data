import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiRequestError,
  createIdempotencyKey,
  fetchAdminSession,
  fetchNonCommissionOwnerAccounts,
  fetchSkuFeeRuleImports,
  fetchSkuFeeRules,
  fetchSkuRules,
  loginAdmin,
  lookupSkuRules,
  publishSkuFeeRule,
  saveNonCommissionOwnerAccounts,
} from "../api/client";
import { AdminSkuRuleImportDrawer } from "../components/AdminSkuRuleImportDrawer";
import { Button } from "../components/Button";
import { StatusChip, type ChipTone } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { FieldInput, FieldTextarea, SelectField } from "../components/FormControls";
import { SegmentedControl, Tabs } from "../components/SelectionControls";
import type {
  ImportBatchItem,
  SkuFeeRuleItem,
  SkuProductCommissionRule,
} from "../types/dashboard";
import { apiErrorText } from "../utils/apiErrors";
import { formatDateTime, formatInteger } from "../utils/format";
import {
  displayFeeRuleStatus,
  displayImportBatchStatus,
} from "../utils/userFacingLabels";

const PAGE_SIZE = 500;
const MAX_LOOKUP_SKUS = 500;
const FIRST_EFFECTIVE_DATE = "2026-08-01";

type RulesTab = "settings" | "history" | "exceptions";
type SkuListTab = "enabled" | "disabled";
type HistorySource = "all" | "manual" | "import";

interface HistoryRow {
  effectiveDate: string;
  id: string;
  operator: string;
  publishedAt: string;
  rates: string;
  skuCount: number;
  source: "manual" | "import";
  status: string;
}

type SkuRow = Required<
  Pick<
    SkuProductCommissionRule,
    | "sku_id"
    | "product_name"
    | "product_scope"
    | "product_type"
    | "commission_rate"
    | "is_service_product"
    | "order_count"
    | "verified_coupon_count"
  >
>;

function normalizeRule(row: SkuProductCommissionRule): SkuRow {
  return {
    sku_id: row.sku_id,
    product_name: row.product_name ?? "",
    product_scope: row.product_scope ?? "",
    product_type: row.product_type ?? "",
    commission_rate: row.commission_rate ?? 0,
    is_service_product: row.is_service_product ?? true,
    order_count: row.order_count ?? 0,
    verified_coupon_count: row.verified_coupon_count ?? 0,
  };
}

function parseSkuInput(value: string): string[] {
  return Array.from(
    new Set(value.split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean)),
  );
}

function parseOwnerAccountInput(value: string): string[] {
  return Array.from(
    new Set(value.split(/[\n,，;；]+/).map((item) => item.trim()).filter(Boolean)),
  );
}

function percentInputToRate(value: string): string | null {
  if (!value.trim()) return null;
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
  if (["ACTIVE", "COMPLETED"].includes(value)) return "success";
  if (["FAILED", "VALIDATION_FAILED"].includes(value)) return "danger";
  if (["PENDING_COMMIT", "COMMITTING"].includes(value)) return "warning";
  return "neutral";
}

function latestEffectiveRules(rules: SkuFeeRuleItem[]): Map<string, SkuFeeRuleItem> {
  const today = new Date().toISOString().slice(0, 10);
  const latestBySku = new Map<string, SkuFeeRuleItem>();
  for (const rule of rules) {
    if (rule.effectiveDate > today) continue;
    const current = latestBySku.get(rule.skuId);
    if (!current || rule.effectiveDate > current.effectiveDate || (rule.effectiveDate === current.effectiveDate && rule.publishedAt > current.publishedAt)) {
      latestBySku.set(rule.skuId, rule);
    }
  }
  return new Map(Array.from(latestBySku).filter(([, rule]) => rule.ruleStatus === "ACTIVE"));
}

export function AdminSkuRulesPage() {
  const publishIntent = useRef<Map<string, string>>(new Map());
  const previewRef = useRef<HTMLElement | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [activeTab, setActiveTab] = useState<RulesTab>("settings");
  const [skuListTab, setSkuListTab] = useState<SkuListTab>("enabled");
  const [historySource, setHistorySource] = useState<HistorySource>("all");
  const [rows, setRows] = useState<SkuRow[]>([]);
  const [feeRules, setFeeRules] = useState<SkuFeeRuleItem[]>([]);
  const [batches, setBatches] = useState<ImportBatchItem[]>([]);
  const [selectedSkuMap, setSelectedSkuMap] = useState<Map<string, SkuRow>>(new Map());
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [lookupInput, setLookupInput] = useState("");
  const [query, setQuery] = useState("");
  const [productScope, setProductScope] = useState("");
  const [promotionRate, setPromotionRate] = useState("8");
  const [managementRate, setManagementRate] = useState("2");
  const [sameRate, setSameRate] = useState(false);
  const [effectiveDate, setEffectiveDate] = useState(FIRST_EFFECTIVE_DATE);
  const [ruleStatus, setRuleStatus] = useState<"ACTIVE" | "INACTIVE">("ACTIVE");
  const [changeReason, setChangeReason] = useState("");
  const [rateApplied, setRateApplied] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [importDrawerOpen, setImportDrawerOpen] = useState(false);
  const [nonCommissionAccountText, setNonCommissionAccountText] = useState("");
  const [nonCommissionAccountCount, setNonCommissionAccountCount] = useState(0);
  const [working, setWorking] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  const handleAuthError = (error: unknown): boolean => {
    if (error instanceof ApiRequestError && error.status === 401) {
      setAuthenticated(false);
      setNotice("登录已过期，请重新输入管理密码。");
      return true;
    }
    return false;
  };

  const loadFeeData = async () => {
    const [rulesResponse, batchesResponse] = await Promise.all([
      fetchSkuFeeRules({ page: 1, pageSize: 200 }),
      fetchSkuFeeRuleImports({ page: 1, pageSize: 200 }),
    ]);
    setFeeRules(rulesResponse.data.list);
    setBatches(batchesResponse.data.list);
  };

  const loadSkuRows = async () => {
    setLoading(true);
    try {
      const response = await fetchSkuRules({
        page: 1,
        pageSize: PAGE_SIZE,
        productScope: productScope.trim(),
        q: query.trim(),
      });
      setRows(response.data.rows.map(normalizeRule));
      setCheckedIds(new Set());
    } catch (error) {
      if (!handleAuthError(error)) setNotice("SKU 商品列表暂时无法读取。");
    } finally {
      setLoading(false);
    }
  };

  const loadExceptions = async () => {
    const response = await fetchNonCommissionOwnerAccounts();
    const names = response.data.rows.map((row) => row.owner_account_name);
    setNonCommissionAccountText(names.join("\n"));
    setNonCommissionAccountCount(names.length);
  };

  useEffect(() => {
    let cancelled = false;
    fetchAdminSession()
      .then(() => !cancelled && setAuthenticated(true))
      .catch(() => !cancelled && setAuthenticated(false))
      .finally(() => !cancelled && setCheckingSession(false));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    Promise.all([loadSkuRows(), loadFeeData(), loadExceptions()]).catch((error) => {
      if (!handleAuthError(error)) setNotice("分佣规则数据暂时无法读取。");
    });
  }, [authenticated]);

  const effectiveRuleMap = useMemo(() => latestEffectiveRules(feeRules), [feeRules]);
  const enabledSkuIds = useMemo(() => new Set(effectiveRuleMap.keys()), [effectiveRuleMap]);
  const visibleSkuRows = useMemo(
    () => rows.filter((row) => skuListTab === "enabled" ? enabledSkuIds.has(row.sku_id) : !enabledSkuIds.has(row.sku_id)),
    [enabledSkuIds, rows, skuListTab],
  );
  const selectedRows = useMemo(() => Array.from(selectedSkuMap.values()), [selectedSkuMap]);
  const historyRows = useMemo<HistoryRow[]>(() => {
    const manualRows = feeRules.map((rule) => ({
      effectiveDate: rule.effectiveDate,
      id: rule.ruleVersion,
      operator: rule.createdBy,
      publishedAt: rule.publishedAt,
      rates: `推广 ${formatRate(rule.promotionServiceFeeRate)} / 管理 ${formatRate(rule.managementServiceFeeRate)}`,
      skuCount: 1,
      source: "manual" as const,
      status: rule.ruleStatus,
    }));
    const importRows = batches.map((batch) => ({
      effectiveDate: batch.effectiveDate,
      id: batch.batchId,
      operator: batch.uploadedBy,
      publishedAt: batch.committedAt ?? batch.validatedAt ?? "",
      rates: "-",
      skuCount: batch.totalCount,
      source: "import" as const,
      status: batch.batchStatus,
    }));
    return [...manualRows, ...importRows].filter((row) => historySource === "all" || row.source === historySource);
  }, [batches, feeRules, historySource]);
  const allVisibleChecked = visibleSkuRows.length > 0 && visibleSkuRows.every((row) => checkedIds.has(row.sku_id));

  const addSelection = (items: SkuRow[]) => {
    setSelectedSkuMap((current) => {
      const next = new Map(current);
      items.forEach((item) => next.set(item.sku_id, item));
      return next;
    });
    setRateApplied(false);
    setNotice(`已选择 ${formatInteger(items.length)} 个 SKU。`);
  };

  const lookupAndSelect = async () => {
    const skuIds = parseSkuInput(lookupInput);
    if (!skuIds.length) return setNotice("请先输入 SKU ID。");
    if (skuIds.length > MAX_LOOKUP_SKUS) return setNotice(`一次最多选择 ${MAX_LOOKUP_SKUS} 个 SKU。`);
    setWorking(true);
    try {
      const response = await lookupSkuRules(skuIds);
      addSelection(response.data.rows.map(normalizeRule));
      setNotice(`已选择 ${response.data.rows.length} 个 SKU，未匹配 ${response.data.missing_sku_ids.length} 个，重复输入已自动去除。`);
    } catch (error) {
      if (!handleAuthError(error)) setNotice("批量 SKU 查询失败，请稍后重试。");
    } finally {
      setWorking(false);
    }
  };

  const applyRateAndReview = () => {
    const promotion = percentInputToRate(promotionRate);
    const management = percentInputToRate(managementRate);
    if (!selectedRows.length) return setNotice("请先选择至少一个 SKU。");
    if (!promotion || !management || !effectiveDate || !changeReason.trim()) {
      return setNotice("请完整填写两项分佣比例、生效日期和变更原因。");
    }
    setRateApplied(true);
    window.requestAnimationFrame(() => previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const publishSelectedRules = async () => {
    const promotion = percentInputToRate(promotionRate);
    const management = percentInputToRate(managementRate);
    if (!promotion || !management || !selectedRows.length) return;
    setWorking(true);
    let completed = 0;
    try {
      for (const row of selectedRows) {
        const payload = {
          skuId: row.sku_id,
          promotionServiceFeeRate: promotion,
          managementServiceFeeRate: management,
          effectiveDate,
          ruleStatus,
          changeReason: changeReason.trim(),
        };
        const fingerprint = JSON.stringify(payload);
        const idempotencyKey = publishIntent.current.get(fingerprint) ?? createIdempotencyKey("sku-fee-rule");
        publishIntent.current.set(fingerprint, idempotencyKey);
        await publishSkuFeeRule(payload, idempotencyKey);
        completed += 1;
      }
      publishIntent.current.clear();
      setConfirmOpen(false);
      setSelectedSkuMap(new Map());
      setRateApplied(false);
      setChangeReason("");
      await loadFeeData();
      setNotice(`已发布 ${completed} 个 SKU 的双费率版本。`);
    } catch (error) {
      setNotice(apiErrorText(error, `发布中断，已完成 ${completed} 个 SKU；可使用相同内容重试。`, {
        403: "当前账号不是最高管理员，不能发布费率版本。",
        409: "所选 SKU 在该生效日期已存在版本。",
      }));
    } finally {
      setWorking(false);
    }
  };

  const saveExceptions = async () => {
    const accounts = parseOwnerAccountInput(nonCommissionAccountText);
    setWorking(true);
    try {
      const response = await saveNonCommissionOwnerAccounts(accounts);
      setNonCommissionAccountCount(response.data.rows.length);
      setNotice(`已保存 ${response.data.updated_count} 个例外账号，结算重建任务已启动。`);
    } catch (error) {
      if (!handleAuthError(error)) setNotice("例外账号保存失败，请稍后重试。");
    } finally {
      setWorking(false);
    }
  };

  const skuColumns: Column<SkuRow>[] = [
    { key: "select", title: <FieldInput aria-label="选择当前页全部 SKU" checked={allVisibleChecked} onChange={() => setCheckedIds(allVisibleChecked ? new Set() : new Set(visibleSkuRows.map((row) => row.sku_id)))} type="checkbox" />, render: (row) => <FieldInput aria-label={`选择 SKU ${row.sku_id}`} checked={checkedIds.has(row.sku_id)} onChange={() => setCheckedIds((current) => { const next = new Set(current); next.has(row.sku_id) ? next.delete(row.sku_id) : next.add(row.sku_id); return next; })} type="checkbox" /> },
    { key: "sku", title: "SKU ID", align: "left", render: (row) => <span className="mono-cell">{row.sku_id}</span> },
    { key: "name", title: "商品名称", align: "left", render: (row) => row.product_name || "-" },
    { key: "scope", title: "产品范围", render: (row) => row.product_scope || "-" },
    { key: "type", title: "商品类型", render: (row) => row.product_type || "未配置" },
    { key: "rate", title: "分账比例", render: (row) => { const rule = effectiveRuleMap.get(row.sku_id); return rule ? `推广 ${formatRate(rule.promotionServiceFeeRate)} / 管理 ${formatRate(rule.managementServiceFeeRate)}` : "-"; } },
    { key: "commission", title: "参与分账", render: (row) => enabledSkuIds.has(row.sku_id) ? "是" : "否" },
    { key: "orders", title: "订单数", align: "right", render: (row) => formatInteger(row.order_count) },
    { key: "verified", title: "核销券数", align: "right", render: (row) => formatInteger(row.verified_coupon_count) },
    { key: "status", title: "状态", render: (row) => <StatusChip tone={enabledSkuIds.has(row.sku_id) ? "success" : "neutral"}>{enabledSkuIds.has(row.sku_id) ? "已启用" : "未启用"}</StatusChip> },
  ];

  const historyColumns: Column<HistoryRow>[] = [
    { key: "id", title: "版本 / 批次", align: "left", render: (row) => <span className="mono-cell">{row.id}</span> },
    { key: "source", title: "发布来源", render: (row) => row.source === "manual" ? "手工发布" : "批量导入" },
    { key: "count", title: "SKU 数量", align: "right", render: (row) => formatInteger(row.skuCount) },
    { key: "rates", title: "分佣比例", render: (row) => row.rates },
    { key: "date", title: "生效日期", render: (row) => row.effectiveDate },
    { key: "status", title: "状态", render: (row) => <StatusChip tone={statusTone(row.status)}>{row.source === "manual" ? displayFeeRuleStatus(row.status) : displayImportBatchStatus(row.status)}</StatusChip> },
    { key: "audit", title: "操作人 / 时间", align: "left", render: (row) => `${row.operator} / ${formatDateTime(row.publishedAt)}` },
  ];

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try { await loginAdmin(password); setAuthenticated(true); setPassword(""); setNotice(""); }
    catch { setNotice("密码不正确，或后端未配置管理密码。"); }
  };

  if (checkingSession) return <div className="admin-page"><section className="admin-login-panel">正在检查管理权限...</section></div>;
  if (!authenticated) return (
    <div className="admin-page admin-page--centered">
      <form className="admin-login-panel" onSubmit={handleLogin}>
        <div><h1>商品分账规则管理</h1><p className="admin-muted">输入管理密码后进入。</p></div>
        <label className="filter-field"><span>管理密码</span><FieldInput autoFocus onChange={(event) => setPassword(event.target.value)} type="password" value={password} /></label>
        {notice ? <p className="admin-error" role="alert">{notice}</p> : null}
        <Button type="submit" variant="primary">进入管理页</Button>
      </form>
    </div>
  );

  return (
    <div className="admin-page commission-rules-page">
      <section className="admin-header">
        <div><h1>商品分账规则管理</h1><p className="admin-muted">先批量选择商品规格（SKU），再确认分佣比例，检查预选后发布不可变规则版本。</p></div>
      </section>
      {notice ? <div aria-live="polite" className="resource-notice" role="status">{notice}</div> : null}

      <Tabs<RulesTab> ariaLabel="分佣规则页面" onChange={setActiveTab} options={[
        { label: "规则设置", value: "settings" },
        { label: "发布记录", value: "history" },
        { label: `例外账号（${nonCommissionAccountCount}）`, value: "exceptions" },
      ]} value={activeTab} />

      {activeTab === "settings" ? (
        <>
          <ol className="commission-stepper" aria-label="规则发布步骤">
            <li>1 批量选择 SKU</li><li>2 确认分佣比例</li><li>3 检查预选</li><li>4 确认发布</li>
          </ol>
          <div className="commission-workspace">
            <main className="commission-workspace__main">
              <section className="content-section commission-step-card">
                <div className="section-title"><div><h2>1. SKU 查询与批量选择</h2><p>支持单个、批量选择；批量 SKU ID 可使用换行、空格、中英文逗号或分号分隔，自动去重。</p></div><StatusChip tone="brand">已选 {selectedRows.length}</StatusChip></div>
                <div className="admin-tools commission-query-tools">
                  <label className="filter-field commission-query-tools__input"><span>SKU ID 或商品名称</span><FieldTextarea onChange={(event) => setLookupInput(event.target.value)} placeholder="SKU-10231，SKU-10246；SKU-10302" rows={3} value={lookupInput} /></label>
                  <Button disabled={working} onClick={() => void lookupAndSelect()} type="button" variant="primary">查询并选择</Button>
                </div>
                <div className="admin-tools">
                  <label className="filter-field"><span>浏览搜索</span><FieldInput onChange={(event) => setQuery(event.target.value)} placeholder="SKU ID 或商品名称" value={query} /></label>
                  <label className="filter-field"><span>产品范围</span><FieldInput onChange={(event) => setProductScope(event.target.value)} value={productScope} /></label>
                  <Button disabled={loading} onClick={() => void loadSkuRows()} type="button">查询</Button>
                  <Button disabled={!checkedIds.size} onClick={() => addSelection(rows.filter((row) => checkedIds.has(row.sku_id)))} type="button">选择当前勾选</Button>
                </div>
              </section>

              <section className="content-section commission-step-card">
                <div className="section-title"><div><h2>2. SKU-ID分佣比例确认</h2><p>手工发布与批量导入使用同一套双费率规则。</p></div><Button onClick={() => setImportDrawerOpen(true)} type="button">批量导入设置</Button></div>
                <div className="admin-form-grid">
                  <label className="filter-field checkbox-field"><span>两项费率一致</span><FieldInput checked={sameRate} onChange={(event) => { setSameRate(event.target.checked); if (event.target.checked) setManagementRate(promotionRate); }} type="checkbox" /></label>
                  <label className="filter-field"><span>推广服务费比例（%）</span><FieldInput inputMode="decimal" onChange={(event) => { setPromotionRate(event.target.value); if (sameRate) setManagementRate(event.target.value); }} value={promotionRate} /></label>
                  <label className="filter-field"><span>管理服务费比例（%）</span><FieldInput disabled={sameRate} inputMode="decimal" onChange={(event) => setManagementRate(event.target.value)} value={managementRate} /></label>
                  <label className="filter-field"><span>生效日期</span><FieldInput min={FIRST_EFFECTIVE_DATE} onChange={(event) => setEffectiveDate(event.target.value)} type="date" value={effectiveDate} /></label>
                  <SelectField label="规则状态" onChange={(value) => setRuleStatus(value as "ACTIVE" | "INACTIVE")} options={[{ label: "启用", value: "ACTIVE" }, { label: "停用", value: "INACTIVE" }]} value={ruleStatus} />
                  <label className="filter-field admin-form-grid__wide"><span>变更原因</span><FieldTextarea maxLength={512} onChange={(event) => setChangeReason(event.target.value)} rows={3} value={changeReason} /></label>
                </div>
                <div className="commission-card-actions"><span>将应用到 {selectedRows.length} 个已选 SKU</span><Button onClick={applyRateAndReview} type="button" variant="primary">应用比例并检查预选</Button></div>
              </section>

              <section className="content-section commission-step-card" ref={previewRef} tabIndex={-1}>
                <div className="section-title"><div><h2>3. 检查预选</h2><p>核对 SKU 范围和待发布比例。</p></div></div>
                {rateApplied ? <div className="commission-preview-summary"><strong>已选 SKU：{selectedRows.length} 个</strong><span>推广 {promotionRate}% · 管理 {managementRate}%</span><span>{effectiveDate} 生效 · {ruleStatus === "ACTIVE" ? "启用" : "停用"}</span></div> : <div className="resource-panel">请先完成第 2 步并应用比例。</div>}
                <div className="commission-selected-list">{selectedRows.map((row) => <div key={row.sku_id}><span className="mono-cell">{row.sku_id}</span><span>{row.product_name || "-"}</span><Button onClick={() => setSelectedSkuMap((current) => { const next = new Map(current); next.delete(row.sku_id); return next; })} size="sm">移除</Button></div>)}</div>
              </section>

              <section className="content-section commission-step-card">
                <div className="section-title"><div><h2>4. 发布确认</h2><p>手工多 SKU 发布会逐个创建不可变版本；文件批量导入才使用原子提交。</p></div><Button disabled={!rateApplied || working} onClick={() => setConfirmOpen(true)} type="button" variant="primary">确认发布</Button></div>
              </section>
            </main>
            <aside className="content-section commission-preselection"><h2>预选窗口</h2><p className="admin-muted">持续汇总当前选择。</p><strong>{selectedRows.length} 个 SKU</strong><span>推广 {promotionRate}%</span><span>管理 {managementRate}%</span></aside>
          </div>

          <section className="content-section commission-sku-catalog">
            <div className="section-title"><div><h2>全部 SKU 列表</h2><p>启用状态按当前已生效且状态为启用的双费率规则判断。</p></div></div>
            <SegmentedControl<SkuListTab> ariaLabel="SKU 分佣状态" onChange={setSkuListTab} options={[{ count: rows.filter((row) => enabledSkuIds.has(row.sku_id)).length, label: "已启用分佣商品列表", value: "enabled" }, { count: rows.filter((row) => !enabledSkuIds.has(row.sku_id)).length, label: "未启用分佣商品列表", value: "disabled" }]} value={skuListTab} />
            <DataTable columns={skuColumns} emptyText={loading ? "正在加载 SKU 数据..." : "当前分类暂无 SKU"} rows={visibleSkuRows} state={loading ? "loading" : "ready"} tableClassName="admin-rule-table" />
          </section>
        </>
      ) : null}

      {activeTab === "history" ? (
        <section className="content-section">
          <div className="section-title"><div><h2>发布记录</h2><p>手工发布与批量导入统一展示。</p></div><SelectField label="发布来源" onChange={(value) => setHistorySource(value as HistorySource)} options={[{ label: "全部来源", value: "all" }, { label: "手工发布", value: "manual" }, { label: "批量导入", value: "import" }]} value={historySource} /></div>
          <DataTable columns={historyColumns} emptyText="暂无发布记录" rows={historyRows} tableClassName="admin-rule-table" />
        </section>
      ) : null}

      {activeTab === "exceptions" ? (
        <section className="content-section non-commission-rule-panel"><div className="section-title"><div><h2>订单归属账号不分佣</h2><p>每行填写一个订单归属账号，保存后会触发后台重建结算结果。</p></div><StatusChip tone="neutral">当前 {nonCommissionAccountCount} 个</StatusChip></div><label className="filter-field"><span>不分佣账号列表</span><FieldTextarea onChange={(event) => setNonCommissionAccountText(event.target.value)} rows={8} value={nonCommissionAccountText} /></label><div className="commission-card-actions"><Button disabled={working} onClick={() => void saveExceptions()} type="button" variant="primary">保存账号规则并重建</Button></div></section>
      ) : null}

      <Dialog actions={<><Button disabled={working} onClick={() => setConfirmOpen(false)} type="button">返回修改</Button><Button disabled={working} onClick={() => void publishSelectedRules()} type="button" variant="primary">{working ? "正在发布..." : "确认发布"}</Button></>} closeDisabled={working} description="确认后将为每个选中 SKU 创建新的不可变规则版本。" onClose={() => setConfirmOpen(false)} open={confirmOpen} title="分佣规则发布确认">
        <dl className="commission-confirmation-list"><div><dt>SKU 数量</dt><dd>{selectedRows.length} 个</dd></div><div><dt>推广服务费比例</dt><dd>{promotionRate}%</dd></div><div><dt>管理服务费比例</dt><dd>{managementRate}%</dd></div><div><dt>生效日期</dt><dd>{effectiveDate}</dd></div><div><dt>规则状态</dt><dd>{ruleStatus === "ACTIVE" ? "启用" : "停用"}</dd></div><div><dt>变更原因</dt><dd>{changeReason}</dd></div></dl>
      </Dialog>
      <AdminSkuRuleImportDrawer batches={batches} initialBatch={null} onChanged={loadFeeData} onClose={() => setImportDrawerOpen(false)} open={importDrawerOpen} />
    </div>
  );
}
