import { useEffect, useMemo, useRef, useState } from "react";
import {
  createIdempotencyKey,
  fetchProductSyncRunDetail,
  fetchProductSyncRuns,
  fetchSkuSyncHistory,
  triggerProductSync,
} from "../api/client";
import type {
  ProductSyncMode,
  ProductSyncRunDetailData,
  ProductSyncRunItem,
  SkuSyncHistoryItem,
} from "../types/dashboard";
import { apiErrorText } from "../utils/apiErrors";
import { formatDateTime, formatInteger } from "../utils/format";
import {
  displayProductStatus,
  displayProductSyncMode,
  displayProductSyncStatus,
} from "../utils/userFacingLabels";
import { Button } from "./Button";
import { StatusChip, type ChipTone } from "./Chips";
import { DataTable, type Column } from "./DataTable";
import { SelectField } from "./FormControls";

function syncTone(status: ProductSyncRunItem["status"]): ChipTone {
  if (status === "SUCCESS") return "success";
  if (status === "FAILED") return "danger";
  if (status === "PARTIAL") return "warning";
  return "info";
}

export function AdminProductSyncPanel() {
  const triggerIntent = useRef<{ fingerprint: string; key: string } | null>(null);
  const [runs, setRuns] = useState<ProductSyncRunItem[]>([]);
  const [detail, setDetail] = useState<ProductSyncRunDetailData | null>(null);
  const [history, setHistory] = useState<SkuSyncHistoryItem[]>([]);
  const [mode, setMode] = useState<ProductSyncMode>("INCREMENTAL");
  const [reason, setReason] = useState("");
  const [historySkuId, setHistorySkuId] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");
  const [detailRequestId, setDetailRequestId] = useState("");

  const loadRuns = async () => {
    const response = await fetchProductSyncRuns({ page: 1, pageSize: 20 });
    setRuns(response.data.list);
    return response.data.list;
  };

  const openDetail = async (syncRunId: string) => {
    try {
      const response = await fetchProductSyncRunDetail(syncRunId);
      setDetail(response.data);
      setDetailRequestId(response.meta.requestId ?? "");
    } catch (error) {
      setNotice(apiErrorText(error, "商品同步详情暂时无法读取。"));
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadRuns()
      .catch((error) => {
        if (!cancelled) setNotice(apiErrorText(error, "商品同步运行记录暂时无法读取。"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const active = runs.some((run) => run.status === "QUEUED" || run.status === "RUNNING");
    if (!active) return undefined;
    const timer = window.setInterval(() => {
      loadRuns()
        .then((nextRuns) => {
          if (detail) {
            const current = nextRuns.find((run) => run.syncRunId === detail.run.syncRunId);
            if (current) void openDetail(current.syncRunId);
          }
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [detail, runs]);

  const trigger = async () => {
    if (!reason.trim()) {
      setNotice("请填写本次商品同步的触发原因。");
      return;
    }
    const normalizedReason = reason.trim();
    const fingerprint = JSON.stringify({ mode, reason: normalizedReason });
    if (triggerIntent.current?.fingerprint !== fingerprint) {
      triggerIntent.current = {
        fingerprint,
        key: createIdempotencyKey("product-sync"),
      };
    }
    setWorking(true);
    try {
      const response = await triggerProductSync(
        mode,
        normalizedReason,
        triggerIntent.current.key,
      );
      triggerIntent.current = null;
      setNotice(`任务 ${response.data.syncRunId} 已入队；触发成功只表示任务已入队，不代表同步完成。`);
      setReason("");
      await loadRuns();
      await openDetail(response.data.syncRunId);
    } catch (error) {
      setNotice(apiErrorText(error, "商品同步触发失败。", {
        409: "已有商品同步任务正在排队或运行，请等待完成后再试。",
        422: "同步方式或触发原因不合法。",
      }));
    } finally {
      setWorking(false);
    }
  };

  const loadHistory = async () => {
    if (!historySkuId.trim()) {
      setNotice("请先输入要查询的 SKU ID。");
      return;
    }
    setWorking(true);
    try {
      const response = await fetchSkuSyncHistory(historySkuId.trim());
      setHistory(response.data.list);
      setNotice(`已读取 SKU ${historySkuId.trim()} 的 ${formatInteger(response.data.list.length)} 条同步历史。`);
    } catch (error) {
      setNotice(apiErrorText(error, "SKU 同步历史暂时无法读取。"));
    } finally {
      setWorking(false);
    }
  };

  const runColumns: Column<ProductSyncRunItem>[] = useMemo(() => [
    { key: "id", title: "运行 ID", align: "left", render: (row) => <span className="mono-cell">{row.syncRunId}</span> },
    { key: "mode", title: "同步方式", render: (row) => displayProductSyncMode(row.mode) },
    { key: "status", title: "状态", render: (row) => <StatusChip tone={syncTone(row.status)}>{displayProductSyncStatus(row.status)}</StatusChip> },
    { key: "counts", title: "观察 / 新增 / 更新 / 失败", align: "right", render: (row) => `${formatInteger(row.observedCount)} / ${formatInteger(row.insertedCount)} / ${formatInteger(row.updatedCount)} / ${formatInteger(row.failedCount)}` },
    { key: "latest", title: "最近成功同步", render: (row) => formatDateTime(row.latestSuccessfulSyncedAt) },
    { key: "time", title: "开始 / 完成", render: (row) => `${formatDateTime(row.startedAt)} / ${formatDateTime(row.finishedAt)}` },
    { key: "action", title: "操作", render: (row) => <Button onClick={() => void openDetail(row.syncRunId)} size="sm">查看详情</Button> },
  ], []);

  const historyColumns: Column<SkuSyncHistoryItem>[] = [
    { key: "time", title: "观测时间", render: (row) => formatDateTime(row.observedAt) },
    { key: "run", title: "运行 ID", align: "left", render: (row) => <span className="mono-cell">{row.syncRunId}</span> },
    { key: "name", title: "商品 / SKU 名称", align: "left", render: (row) => row.productName || row.skuName || "-" },
    { key: "owner", title: "归属账号", render: (row) => row.ownerAccountName || row.ownerAccountId || "未返回" },
    { key: "creator", title: "创建账号", render: (row) => row.creatorAccountName || row.creatorAccountId || "未返回" },
    { key: "status", title: "商品状态", render: (row) => displayProductStatus(row.productStatus) },
    { key: "digest", title: "载荷摘要", align: "left", render: (row) => <span className="mono-cell">{row.payloadSha256.slice(0, 12)}…</span> },
  ];

  return (
    <section className="content-section admin-product-sync">
      <div className="section-title"><div><h2>商品主数据同步</h2><p>支持增量或全量同步；触发成功只表示任务已入队，页面会继续轮询最终状态。</p></div><Button disabled={loading} onClick={() => void loadRuns()} type="button">刷新商品任务</Button></div>
      {notice ? <div aria-live="polite" className="resource-notice" role="status">{notice}</div> : null}
      <div className="admin-form-grid">
        <SelectField label="同步方式" onChange={(value) => setMode(value as ProductSyncMode)} options={[{ value: "INCREMENTAL", label: "增量同步" }, { value: "FULL", label: "全量同步" }]} value={mode} />
        <label className="filter-field admin-form-grid__wide"><span>触发原因</span><input maxLength={512} onChange={(event) => setReason(event.target.value)} placeholder="说明本次同步目的" value={reason} /></label>
        <Button disabled={working} onClick={() => void trigger()} type="button" variant="primary">触发商品同步</Button>
      </div>
      <DataTable columns={runColumns} emptyText="暂无商品同步运行记录" rows={runs} state={loading ? "loading" : "ready"} tableClassName="admin-sync-table" />

      {detail ? (
        <div className="resource-panel admin-sync-detail">
          <div className="section-title"><div><h3>运行详情</h3><p className="mono-cell">{detail.run.syncRunId}</p></div><StatusChip tone={syncTone(detail.run.status)}>{displayProductSyncStatus(detail.run.status)}</StatusChip></div>
          <dl className="worker-status-grid">
            <div className="worker-status-item"><dt>最近成功同步</dt><dd>{formatDateTime(detail.run.latestSuccessfulSyncedAt)}</dd><small>失败任务不会覆盖该时间</small></div>
            <div className="worker-status-item"><dt>数据质量问题</dt><dd>{formatInteger(detail.dataQualityIssueCount)}</dd><small>{detail.retryable ? "允许安全重试" : "需先核对失败原因"}</small></div>
            <div className="worker-status-item"><dt>受影响 SKU 样例</dt><dd>{detail.affectedSkuSample.length ? detail.affectedSkuSample.join("、") : "暂无"}</dd><small>最多展示 20 个授权内 SKU ID</small></div>
            <div className="worker-status-item"><dt>错误摘要</dt><dd>{detail.run.errorCode ?? "暂无错误"}</dd><small>{detail.run.errorMessage ?? "不展示外部认证信息、原始游标或完整载荷"}</small>{detailRequestId ? <small>请求编号：{detailRequestId}</small> : null}</div>
          </dl>
        </div>
      ) : null}

      <div className="admin-history-block">
        <div className="section-title"><div><h3>SKU 同步历史</h3><p>查看当前商品名称、归属、创建账号和状态的历史快照，不返回原始载荷。</p></div></div>
        <div className="admin-tools"><label className="filter-field"><span>SKU ID</span><input onChange={(event) => setHistorySkuId(event.target.value)} value={historySkuId} /></label><Button disabled={working} onClick={() => void loadHistory()} type="button">查询历史</Button></div>
        <DataTable columns={historyColumns} emptyText="输入 SKU ID 查询同步历史" rows={history} tableClassName="admin-sync-table" />
      </div>
    </section>
  );
}
