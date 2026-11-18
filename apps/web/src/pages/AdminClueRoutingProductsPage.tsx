import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  clueRoutingFailureMessage, clueRoutingRequestError, fetchClueRoutingProducts, submitClueRoutingBatch,
  type ClueRoutingAction, type ClueRoutingBatchWrite, type ClueRoutingFilters,
  type ClueRoutingProduct, type ClueRoutingProductList, type ClueRoutingResult,
} from "../api/clueRouting";
import { Button } from "../components/Button";
import { StatusChip } from "../components/Chips";
import { ClueRoutingGrantsDialog, SharedClueRoutingRuleDialog } from "../components/ClueRoutingManagementDialogs";
import {
  ClueRoutingRuleEditor, ClueRoutingRuleSummary, createClueRoutingRuleDraft, readClueRoutingRuleDraft,
} from "../components/ClueRoutingRuleEditor";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import { CheckboxField, FieldInput, FieldTextarea, SelectField } from "../components/FormControls";
import { SegmentedControl } from "../components/SelectionControls";
import { TablePagination } from "../components/TablePagination";
import { clueRoutingBodyForResults, parseClueRoutingProductLists, parseClueRoutingStoreIds } from "../utils/clueRoutingDraft";
import "./AdminClueRoutingProductsPage.css";

const actionLabels: Record<ClueRoutingAction, string> = {
  publish_list: "发布适用门店名单", publish_rule: "发布商品规则", enable: "正式开启 / 重新开启流转", disable: "关闭商品流转",
};
const emptyProducts: ClueRoutingProductList = { rows: [], total: 0, page: 1, page_size: 50, can_manage_grants: false };
const emptyFilters: ClueRoutingFilters = { q: "", product_scope: "all" };
type BatchReview = { body: ClueRoutingBatchWrite; results: ClueRoutingResult[]; phase: "preview" | "complete" };

function scopeLabel(scope: string | undefined) {
  return scope === "jingcheng" ? "精诚养车" : scope === "byd" ? "比亚迪本品" : "全部商品";
}

function ProductStores({ storeIds }: { storeIds?: string[] }) {
  if (!storeIds?.length) return <span className="admin-muted">暂无有效名单</span>;
  return <details className="clue-routing-stores"><summary>{storeIds.length} 家门店，展开编码</summary><p>{storeIds.join("、")}</p></details>;
}

function ProductSnapshot({ snapshot, action, proposed }: { snapshot: Partial<ClueRoutingProduct>; action: ClueRoutingAction; proposed?: boolean }) {
  if (!snapshot.product_id) return <span className="admin-muted">无可查看配置</span>;
  return <div className="clue-routing-snapshot">
    <p><StatusChip tone={snapshot.routing_enabled ? "success" : "neutral"}>{snapshot.routing_enabled ? "流转已开启" : "流转已关闭"}</StatusChip></p>
    {action === "publish_rule" ? <ClueRoutingRuleSummary snapshot={snapshot} /> : null}
    {action === "publish_list" || action === "enable" ? <ProductStores storeIds={snapshot.store_ids} /> : null}
    <p className="clue-routing-version">规则版本：{proposed && action === "publish_rule" ? "正式发布时生成新版本" : snapshot.rule_version_id ?? "尚未独立发布"}</p>
    <p className="clue-routing-version">名单版本：{proposed && action === "publish_list" ? "正式发布时生成新版本" : snapshot.list_version ?? "尚未发布"}</p>
  </div>;
}

export function AdminClueRoutingProductsPage() {
  const [data, setData] = useState(emptyProducts);
  const [filters, setFilters] = useState<ClueRoutingFilters>(emptyFilters);
  const [filterDraft, setFilterDraft] = useState<ClueRoutingFilters>(emptyFilters);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [allMatching, setAllMatching] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [action, setAction] = useState<ClueRoutingAction>("publish_list");
  const [listMode, setListMode] = useState<"shared" | "per_product">("shared");
  const [listText, setListText] = useState("");
  const [importAsScope, setImportAsScope] = useState(true);
  const [fileName, setFileName] = useState("");
  const [fileRevision, setFileRevision] = useState(0);
  const [ruleDraft, setRuleDraft] = useState(() => createClueRoutingRuleDraft());
  const [authorizationNote, setAuthorizationNote] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [review, setReview] = useState<BatchReview | null>(null);
  const [resultPage, setResultPage] = useState(1);
  const [resultPageSize, setResultPageSize] = useState(20);
  const [pendingApply, setPendingApply] = useState<{ body: ClueRoutingBatchWrite; key: string } | null>(null);
  const [busy, setBusy] = useState<"file" | "preview" | "submit" | null>(null);
  const [operationError, setOperationError] = useState("");
  const [notice, setNotice] = useState("");
  const [grantsProduct, setGrantsProduct] = useState<ClueRoutingProduct | null>(null);
  const [sharedOpen, setSharedOpen] = useState(false);
  const requestSequence = useRef(0);

  const load = useCallback(async (signal?: AbortSignal) => {
    const sequence = ++requestSequence.current;
    setLoading(true); setLoadError("");
    try {
      const next = await fetchClueRoutingProducts(filters, page, pageSize, signal);
      if (sequence !== requestSequence.current) return false;
      setData(next);
      return true;
    } catch (failure) {
      if (signal?.aborted || sequence !== requestSequence.current) return false;
      setLoadError(clueRoutingRequestError(failure, "商品配置暂时无法读取，请重试。"));
      setData(emptyProducts);
      return false;
    } finally { if (sequence === requestSequence.current) setLoading(false); }
  }, [filters, page, pageSize]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => { controller.abort(); };
  }, [load]);

  const selectedCount = allMatching ? data.total : selectedIds.length;
  const manageableRows = data.rows.filter((row) => row.can_manage);
  const pageSelected = manageableRows.length > 0 && manageableRows.every((row) => selectedIds.includes(row.product_id));
  const parsedLists = listMode === "per_product" ? parseClueRoutingProductLists(listText) : null;

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    setSelectedIds([]); setAllMatching(false); setPage(1);
    setFilters({ ...filterDraft, q: filterDraft.q.trim() });
  };
  const openAction = (nextAction: ClueRoutingAction) => {
    setAction(nextAction); setDialogOpen(true); setReview(null); setPendingApply(null);
    setOperationError(""); setAuthorizationNote(""); setAuthorized(false);
    setListMode("shared"); setListText(""); setFileName(""); setImportAsScope(true);
    setFileRevision((value) => value + 1);
    const first = data.rows.find((row) => selectedIds.includes(row.product_id));
    setRuleDraft(createClueRoutingRuleDraft(first));
  };
  const toggleProduct = (productId: string, checked: boolean) => {
    setSelectedIds((current) => checked ? [...new Set([...current, productId])] : current.filter((id) => id !== productId));
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    setOperationError("");
    setBusy("file");
    try { setListText(await file.text()); setFileName(file.name); }
    catch (failure) { setOperationError(clueRoutingRequestError(failure, "文件无法读取，请重新选择。")); }
    finally { setBusy(null); }
  };
  const downloadTemplate = () => {
    const content = listMode === "shared" ? "store_id\n001001\n001002\n" : "product_id,store_id\n000001,001001\n000001,001002\n000002,001003\n";
    const url = URL.createObjectURL(new Blob(["\uFEFF", content], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "商品适用门店名单模板.csv"; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const previewBatch = async (body: ClueRoutingBatchWrite) => {
    setBusy("preview"); setOperationError(""); setPendingApply(null);
    try {
      const result = await submitClueRoutingBatch({ ...body, preview: true });
      setResultPage(1);
      setReview({ body: { ...body, preview: true }, results: result.results, phase: "preview" });
    } catch (failure) { setOperationError(clueRoutingRequestError(failure, "本次预览未完成，请重试。")); }
    finally { setBusy(null); }
  };
  const preparePreview = async () => {
    const body: ClueRoutingBatchWrite = { product_ids: selectedIds, all_matching: allMatching, filters, action, preview: true };
    if (action === "publish_list") {
      if (listMode === "shared") {
        body.store_ids = parseClueRoutingStoreIds(listText);
        if (!body.store_ids.length) { setOperationError("请填写或导入至少一个门店编码。"); return; }
      } else {
        if (!parsedLists || parsedLists.error) { setOperationError(parsedLists?.error || "请提供每商品独立名单。"); return; }
        body.lists = parsedLists.lists;
        if (importAsScope) { body.product_ids = parsedLists.lists.map((row) => row.product_id); body.all_matching = false; }
      }
    }
    if (!body.all_matching && !body.product_ids.length) { setOperationError("请先选择商品，或使用文件中的商品 ID 作为发布范围。"); return; }
    if (action === "publish_rule") {
      const parsed = readClueRoutingRuleDraft(ruleDraft);
      if (parsed.error) { setOperationError(parsed.error); return; }
      body.rules = parsed.rules;
    }
    if (action === "enable" && (!authorizationNote.trim() || !authorized)) {
      setOperationError("请填写业务负责人授权依据，并确认已核对发布名单及正式开启授权。"); return;
    }
    if (action === "enable" || action === "disable") body.authorization_note = authorizationNote.trim();
    await previewBatch(body);
  };
  const applyPreview = async () => {
    if (!review || review.phase !== "preview") return;
    const transaction = pendingApply ?? {
      body: {
        ...clueRoutingBodyForResults(review.body, review.results, "preview"), preview: false,
        ...(review.body.action === "enable" ? { expected_list_versions: Object.fromEntries(review.results.filter((row) => row.status === "preview").map((row) => [row.product_id, row.before.list_version ?? null])) } : {}),
      },
      key: crypto.randomUUID(),
    };
    if (!transaction.body.product_ids.length) return;
    setPendingApply(transaction); setBusy("submit"); setOperationError(""); setNotice("");
    try {
      const result = await submitClueRoutingBatch(transaction.body, transaction.key);
      const rows = [...review.results.filter((row) => row.status === "failed"), ...result.results];
      setReview({ body: review.body, results: rows, phase: "complete" }); setPendingApply(null);
      setResultPage(1);
      setSelectedIds([]); setAllMatching(false);
      const succeeded = result.results.filter((row) => row.status === "success").length;
      const refreshed = await load();
      setNotice(`本次已完成 ${succeeded} 个商品的${actionLabels[review.body.action]}。${refreshed ? "已重新读取最新配置。" : "最新列表读取失败，请刷新核对；提交结果保留在本次结果中。"}`);
    } catch (failure) {
      setOperationError(`${clueRoutingRequestError(failure, "提交结果暂时无法确认。")}请重试本次提交，系统会复用同一操作编号避免重复发布。`);
    } finally { setBusy(null); }
  };

  const productColumns: Column<ClueRoutingProduct>[] = [
    { key: "select", width: 66, title: <FieldInput aria-label="选择本页商品" checked={allMatching || pageSelected} disabled={loading || allMatching || !manageableRows.length} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...new Set([...current, ...manageableRows.map((row) => row.product_id)])] : current.filter((id) => !manageableRows.some((row) => row.product_id === id)))} type="checkbox" />,
      render: (row) => <FieldInput aria-label={`选择商品 ${row.product_id}`} checked={allMatching || selectedIds.includes(row.product_id)} disabled={allMatching || !row.can_manage || loading} onChange={(event) => toggleProduct(row.product_id, event.target.checked)} type="checkbox" /> },
    { key: "product", title: "商品", align: "left", minWidth: 240, render: (row) => <div className="clue-routing-product-name"><strong>{row.product_name || "未命名商品"}</strong><span>商品 ID：{row.product_id}</span><span>{scopeLabel(row.product_scope)}</span></div> },
    { key: "enabled", title: "流转状态", minWidth: 115, render: (row) => <StatusChip tone={row.routing_enabled ? "success" : "neutral"}>{row.routing_enabled ? "已开启" : "已关闭"}</StatusChip> },
    { key: "list", title: "有效门店名单", align: "left", minWidth: 180, render: (row) => <div><ProductStores storeIds={row.store_ids} /><p className="clue-routing-version">版本 {row.list_version ?? "尚未发布"}</p></div> },
    { key: "rule", title: "已发布规则", align: "left", minWidth: 240, render: (row) => <div><span>首次跟进 {row.first_follow_up_sla_hours} 小时</span><details className="clue-routing-stores"><summary>查看保护期与到期动作</summary><ClueRoutingRuleSummary snapshot={row} /></details><p className="clue-routing-version">{row.rule_version_id ?? "正式开启时生成独立版本"}</p></div> },
    ...(data.can_manage_grants ? [{ key: "grants", title: "商品负责人", width: 145, render: (row: ClueRoutingProduct) => <Button disabled={loading} onClick={() => setGrantsProduct(row)} size="sm">管理授权</Button> }] : []),
  ];
  const resultColumns: Column<ClueRoutingResult>[] = [
    { key: "product", title: "商品范围", align: "left", minWidth: 185, render: (row) => <div className="clue-routing-product-name"><strong>{row.after.product_name || row.before.product_name || "商品"}</strong><span>{row.product_id}</span></div> },
    { key: "result", title: "逐商品结果", align: "left", minWidth: 180, render: (row) => <div><StatusChip tone={row.status === "failed" ? "danger" : row.status === "success" ? "success" : "info"}>{row.status === "failed" ? "失败，沿用原配置" : row.status === "success" ? "操作成功" : "校验通过"}</StatusChip>{row.status === "failed" ? <p className="clue-routing-result-error">{clueRoutingFailureMessage(row.error)}</p> : null}</div> },
    { key: "before", title: "变更前", align: "left", minWidth: 280, render: (row) => <ProductSnapshot action={review?.body.action ?? action} snapshot={row.before} /> },
    { key: "after", title: review?.phase === "complete" ? "实际结果" : "变更后预览", align: "left", minWidth: 280, render: (row) => row.status === "failed" ? <span className="admin-muted">该商品未变更</span> : <ProductSnapshot action={review?.body.action ?? action} proposed={review?.phase === "preview"} snapshot={row.after} /> },
  ];
  const failedCount = review?.results.filter((row) => row.status === "failed").length ?? 0;
  const previewCount = review?.results.filter((row) => row.status === "preview").length ?? 0;
  const successCount = review?.results.filter((row) => row.status === "success").length ?? 0;

  return <div className="admin-page clue-routing-page">
    <section className="admin-header">
      <div><h1>商品线索流转</h1><p className="admin-muted">按商品发布门店名单、规则并手动启停。只展示当前账号有权管理的商品。</p></div>
      <div className="admin-header-actions">
        {data.can_manage_grants ? <Button onClick={() => setSharedOpen(true)}>精诚养车共享基座</Button> : null}
        <Button disabled={loading} icon="sync" loading={loading} onClick={() => void load()}>刷新</Button>
      </div>
    </section>
    <p className="resource-notice">名单和规则发布后，流转开关保持原状态。精诚养车试点须由业务负责人确认已发布的有效名单并明确授权后，手动正式开启。启停和规则发布只影响之后首次入库的线索；已入库、未分配及在途线索继续按原绑定处理。</p>
    {notice ? <p className="resource-notice" role="status">{notice}</p> : null}
    <section className="content-section">
      <div className="section-title"><div><h2>商品查询与批量选择</h2><p>支持跨分页多选，或全选当前筛选下有管理权限的商品。变更筛选时清空选择。</p></div><StatusChip tone="neutral">{data.total} 个商品</StatusChip></div>
      <form className="filter-bar filter-bar--compact clue-routing-filters" onSubmit={applyFilters}>
        <label className="filter-field"><span>搜索商品</span><FieldInput disabled={loading} onChange={(event) => setFilterDraft((current) => ({ ...current, q: event.target.value }))} placeholder="商品 ID 或名称" type="search" value={filterDraft.q} /></label>
        <SelectField disabled={loading} label="商品范围" onChange={(value) => setFilterDraft((current) => ({ ...current, product_scope: value as ClueRoutingFilters["product_scope"] }))} options={[{ value: "all", label: "全部商品" }, { value: "jingcheng", label: "精诚养车" }, { value: "byd", label: "比亚迪本品" }]} value={filterDraft.product_scope} />
        <Button disabled={loading} icon="filter" type="submit" variant="primary">查询</Button>
        <Button disabled={loading} onClick={() => { setFilters({ ...emptyFilters }); setFilterDraft({ ...emptyFilters }); setSelectedIds([]); setAllMatching(false); setPage(1); }}>清空筛选</Button>
      </form>
      <div className="clue-routing-selection" role="status">
        <strong>{allMatching ? `已全选筛选结果 ${selectedCount} 个商品（跨全部分页）` : `已选择 ${selectedCount} 个商品（跨分页保留）`}</strong>
        <div className="clue-routing-actions"><Button disabled={loading || !data.total || allMatching} onClick={() => { setAllMatching(true); setSelectedIds([]); }} size="sm">全选所有筛选结果</Button><Button disabled={!selectedCount} onClick={() => { setSelectedIds([]); setAllMatching(false); }} size="sm">清除选择</Button></div>
      </div>
      <div className="clue-routing-actions clue-routing-batch-actions">
        <Button disabled={loading || Boolean(loadError)} onClick={() => openAction("publish_list")}>导入 / 发布门店名单</Button>
        <Button disabled={loading || !selectedCount} onClick={() => openAction("publish_rule")}>按字段批量改规则</Button>
        <Button disabled={loading || !selectedCount} onClick={() => openAction("enable")} variant="primary">正式开启 / 重新开启</Button>
        <Button disabled={loading || !selectedCount} onClick={() => openAction("disable")}>关闭流转</Button>
        {review ? <Button onClick={() => setDialogOpen(true)}>查看本次{review.phase === "complete" ? "结果" : "预览"}</Button> : null}
      </div>
      <DataTable columns={productColumns} emptyText="当前没有可管理的匹配商品；商品负责人可联系全国范围管理员授予商品权限。" errorText={loadError} loadingText="正在加载商品配置..." rows={data.rows} state={loading ? "loading" : loadError ? "error" : "ready"} stickyHeader="container"
        mobileCard={(row) => <div className="clue-routing-mobile-product">
          <CheckboxField checked={allMatching || selectedIds.includes(row.product_id)} disabled={allMatching || !row.can_manage || loading} label={`选择商品 ${row.product_id}`} onChange={(event) => toggleProduct(row.product_id, event.target.checked)} />
          <strong>{row.product_name || "未命名商品"}</strong>
          <span className="admin-muted">{scopeLabel(row.product_scope)}</span>
          <StatusChip tone={row.routing_enabled ? "success" : "neutral"}>{row.routing_enabled ? "流转已开启" : "流转已关闭"}</StatusChip>
          <ProductStores storeIds={row.store_ids} />
          <details className="clue-routing-stores"><summary>查看已发布规则</summary><ClueRoutingRuleSummary snapshot={row} /><p className="clue-routing-version">{row.rule_version_id ?? "尚未独立发布"}</p></details>
          {data.can_manage_grants ? <Button onClick={() => setGrantsProduct(row)} size="sm">管理授权</Button> : null}
        </div>}
      />
      <TablePagination loading={loading} onPageChange={setPage} onPageSizeChange={(value) => { setPageSize(value); setPage(1); }} page={data.page} pageSize={data.page_size} pageSizeOptions={[20, 50, 100]} rowsOnPage={data.rows.length} total={data.total} totalPages={Math.ceil(data.total / data.page_size)} />
    </section>
    <Dialog
      actions={<>
        <Button disabled={Boolean(busy)} onClick={review?.phase === "preview" && !pendingApply ? () => { setReview(null); setOperationError(""); } : () => setDialogOpen(false)}>{review?.phase === "preview" && !pendingApply ? "返回修改" : "关闭"}</Button>
        {review && failedCount > 0 && !pendingApply ? <Button disabled={Boolean(busy)} onClick={() => void previewBatch(clueRoutingBodyForResults(review.body, review.results, "failed"))}>仅重试失败商品（{failedCount}）</Button> : null}
        {!review ? <Button disabled={Boolean(busy)} loading={busy === "preview"} onClick={() => void preparePreview()} variant="primary">校验并预览变更</Button> : review.phase === "preview" ? <Button disabled={Boolean(busy) || !previewCount} loading={busy === "submit"} onClick={() => void applyPreview()} variant={review.body.action === "disable" ? "danger" : "primary"}>{pendingApply ? "重试本次提交" : `确认${actionLabels[review.body.action]}（${previewCount} 个）`}</Button> : null}
      </>}
      closeDisabled={Boolean(busy)} description={review ? `本次范围固定为预览返回的商品。成功 ${successCount} 个，${review.phase === "preview" ? `校验通过 ${previewCount} 个，` : ""}失败 ${failedCount} 个。失败商品保留原配置。` : `当前选择 ${selectedCount} 个商品，${allMatching ? `包含“${scopeLabel(filters.product_scope)}”下全部分页筛选结果` : "可在名单导入中改用文件内商品范围"}。`}
      onClose={() => setDialogOpen(false)} open={dialogOpen} panelClassName="clue-routing-dialog" title={review ? `${actionLabels[review.body.action]} · ${review.phase === "preview" ? "确认预览" : "逐商品结果"}` : actionLabels[action]}
    >
      {operationError ? <p className="admin-error" role="alert">{operationError}</p> : null}
      {review ? <>
        {review.phase === "preview" ? <p className="resource-notice">预览不会写入。确认后只提交校验通过的商品，并由服务端再次核验权限与名单。{review.body.action === "publish_list" ? "名单发布在下一次选店时生效，当前门店任务继续处理。" : "规则发布和启停仅影响之后首次入库线索。"}{review.body.action === "enable" ? "正式开启绑定下方确认的名单版本；名单变化时该商品保持关闭，须重新预览并确认最新版本。" : ""}</p> : <p className="resource-notice" role="status">本次操作成功 {successCount} 个，失败 {failedCount} 个。可单独重新校验失败商品。</p>}
        {pendingApply ? <p className="resource-notice">本次提交的范围和操作编号已保留。请重试本次提交以核对最终结果。</p> : null}
        <DataTable columns={resultColumns} rows={review.results.slice((resultPage - 1) * resultPageSize, resultPage * resultPageSize)} emptyText="没有符合本次范围的可管理商品。" stickyHeader="container" />
        <TablePagination loading={Boolean(busy)} onPageChange={setResultPage} onPageSizeChange={(value) => { setResultPageSize(value); setResultPage(1); }} page={resultPage} pageSize={resultPageSize} pageSizeOptions={[20, 50, 100]} rowsOnPage={review.results.slice((resultPage - 1) * resultPageSize, resultPage * resultPageSize).length} total={review.results.length} totalPages={Math.ceil(review.results.length / resultPageSize)} />
      </> : <>
        {action === "publish_list" ? <div className="clue-routing-editor">
          <SegmentedControl ariaLabel="门店名单导入方式" onChange={(value) => { setListMode(value); setListText(""); setFileName(""); setOperationError(""); setFileRevision((current) => current + 1); }} options={[{ value: "shared", label: "同一名单应用多商品" }, { value: "per_product", label: "按商品导入不同名单" }]} value={listMode} />
          <p className="admin-muted">{listMode === "shared" ? "每行一个门店编码，也可用逗号、空格分隔。发布会替换所选商品的完整有效名单。" : "CSV 每行填写商品 ID、门店编码；同一商品可占多行。重复编码自动去重，前导零保留。发布会替换每个商品的完整有效名单。"}</p>
          <div className="clue-routing-file-actions"><Button disabled={Boolean(busy)} onClick={downloadTemplate}>下载名单模板</Button><label className="filter-field"><span>导入 CSV 或文本文件</span><FieldInput accept=".csv,.txt,.tsv" disabled={Boolean(busy)} key={fileRevision} onChange={(event) => void importFile(event.target.files?.[0])} type="file" /></label></div>
          {fileName ? <p className="admin-muted">已读取：{fileName}</p> : null}
          <label className="filter-field"><span>{listMode === "shared" ? "门店编码名单" : "商品与门店名单"}</span><FieldTextarea disabled={Boolean(busy)} onChange={(event) => { setListText(event.target.value); setFileName(""); }} placeholder={listMode === "shared" ? "001001\n001002" : "product_id,store_id\n000001,001001\n000001,001002"} rows={8} spellCheck={false} value={listText} /></label>
          {listMode === "per_product" ? <>
            <CheckboxField checked={importAsScope} disabled={Boolean(busy)} label="以文件中的商品 ID 作为本次发布范围" onChange={(event) => setImportAsScope(event.target.checked)} description="服务端逐商品校验管理权限。未勾选时仅发布当前已选商品，文件外的已选商品会校验失败。" />
            {listText && !parsedLists?.error ? <p className="resource-notice">已识别 {parsedLists?.lists.length} 个商品，{parsedLists?.lists.reduce((sum, row) => sum + row.store_ids.length, 0)} 条商品与门店关系，等待服务端校验。</p> : null}
          </> : null}
        </div> : null}
        {action === "publish_rule" ? <div className="clue-routing-editor"><p className="resource-notice">只发布勾选字段，其余字段各商品保留原值。本品首次开启前继承精诚共享基座，须先按已确认名单开启，之后可发布独立规则。精诚养车可在关闭时预配规则。第 0、1 轮为 10 公里，第 2 轮同城兜底；首次跟进期限不改变看板固定 24 小时跟进率口径。</p><ClueRoutingRuleEditor disabled={Boolean(busy)} draft={ruleDraft} onChange={setRuleDraft} /></div> : null}
        {action === "enable" || action === "disable" ? <div className="clue-routing-editor">
          <p className="resource-notice">{action === "enable" ? "开启前必须已有成功发布且经业务确认的有效门店名单。本品首次开启时采用精诚养车共享基座创建独立规则版本。第 0、1 轮均为 10 公里，第 2 轮同城兜底。" : "关闭后，之后首次入库的线索回到原分配流程。已入库未分配和在途任务继续按原绑定规则完成。"}</p>
          <label className="filter-field"><span>{action === "enable" ? "业务负责人授权依据（必填）" : "关闭原因（选填）"}</span><FieldTextarea disabled={Boolean(busy)} maxLength={2000} onChange={(event) => setAuthorizationNote(event.target.value)} placeholder={action === "enable" ? "填写授权负责人、确认日期和对应商品名单依据" : "填写本次关闭原因"} rows={4} value={authorizationNote} /></label>
          {action === "enable" ? <CheckboxField checked={authorized} disabled={Boolean(busy)} label="已核对发布的有效名单，并获得业务负责人正式开启授权" onChange={(event) => setAuthorized(event.target.checked)} /> : null}
        </div> : null}
      </>}
    </Dialog>
    <ClueRoutingGrantsDialog onClose={() => setGrantsProduct(null)} product={grantsProduct} />
    <SharedClueRoutingRuleDialog onClose={() => setSharedOpen(false)} open={sharedOpen} />
  </div>;
}
