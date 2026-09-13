import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiRequestError,
  fetchAdminSession,
  fetchSyncAdmin,
  loginAdmin,
  runManualSync,
  saveSyncConfig,
} from "../api/client";
import { Button } from "../components/Button";
import { AdminProductSyncPanel } from "../components/AdminProductSyncPanel";
import { DouyinStoreOrgMappingPanel } from "../components/DouyinStoreOrgMappingPanel";
import { ComponentRoom } from "../components/admin-sync/ComponentRoom";
import { StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput, SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import type {
  JobRun,
  ManualSyncTarget,
  SyncAdminData,
  SyncConfigData,
  SyncDailyBatchData,
  SyncResourceGuardData,
} from "../types/dashboard";
import { formatDateTime, formatInteger } from "../utils/format";
import {
  displaySyncFailureReason,
  displaySyncJobName,
  displaySyncPhaseName,
  displayWorkerMode,
} from "../utils/userFacingLabels";

const targetOptions: { value: ManualSyncTarget; label: string }[] = [
  { value: "all", label: "全部开放接口数据" },
  { value: "orders", label: "订单数据" },
  { value: "verify_records", label: "核销数据" },
  { value: "shop_pois", label: "门店位置数据（POI）" },
  { value: "aweme_bindings", label: "子机构号开放接口" },
  { value: "backend_aweme_export", label: "子机构号浏览器导出" },
  { value: "settlement", label: "仅重建结算结果" },
];

const intervalOptions = [
  { value: "1800", label: "半小时" },
  { value: "3600", label: "1 小时" },
  { value: "7200", label: "2 小时" },
  { value: "21600", label: "6 小时" },
  { value: "86400", label: "每天" },
];

function configToDraft(config: SyncConfigData) {
  return {
    history_start: config.history_start,
    history_end: config.history_end,
    history_chunk_days: String(config.history_chunk_days),
    rolling_days: String(config.rolling_days),
    interval_seconds: String(config.interval_seconds),
    auto_sync_enabled: config.auto_sync_enabled,
    backfill_skip_completed: config.backfill_skip_completed,
  };
}

function draftSignature(draft: ReturnType<typeof configToDraft>): string {
  return JSON.stringify(draft);
}

function statusLabel(status: JobRun["status"]): string {
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  if (status === "partial") return "部分完成";
  if (status === "cancelled") return "已取消";
  if (status === "retry_wait") return "等待重试";
  return "已排队";
}

function statusTone(status: JobRun["status"]): "warning" | "info" | "danger" | "success" {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  return "warning";
}

function phaseSummary(job: JobRun): string {
  const phases = job.metadata_json?.phases ?? {};
  const parts = Object.values(phases).map((phase) => {
    const fetched = formatInteger(Number(phase.fetched ?? 0));
    const upserted = formatInteger(Number(phase.upserted ?? 0));
    return `${displaySyncPhaseName(phase.name)}：拉取 ${fetched} / 写入 ${upserted}`;
  });
  return parts.length ? parts.join("；") : "-";
}

function intervalText(seconds: number): string {
  if (seconds % 3600 === 0) {
    return `${formatInteger(seconds / 3600)} 小时`;
  }
  if (seconds % 60 === 0) {
    return `${formatInteger(seconds / 60)} 分钟`;
  }
  return `${formatInteger(seconds)} 秒`;
}

function yesNo(value: boolean): string {
  return value ? "是" : "否";
}

function jobWindowText(job: JobRun | null | undefined): string {
  const window = job?.metadata_json?.source_window;
  if (!window) return "-";
  return `${formatDateTime(window.start)} 至 ${formatDateTime(window.end)}`;
}

function jobStatusLine(job: JobRun | null | undefined): string {
  if (!job) return "暂无记录";
  const finishedAt = job.finished_at
    ? `完成于 ${formatDateTime(job.finished_at)}`
    : `开始于 ${formatDateTime(job.started_at)}`;
  return `${statusLabel(job.status)}，${finishedAt}`;
}

const resourceGuardLabels: Record<SyncResourceGuardData["state"], string> = {
  normal: "正常放行",
  constrained: "资源收紧",
  protected: "保护暂停",
  recovering: "恢复观察",
  unknown: "状态未知",
  disabled: "监控未启用",
};

const resourceGuardReasonLabels: Record<string, string> = {
  host_available_low: "主机可用内存偏低",
  cgroup_used_high: "工作进程内存使用率偏高",
  pressure_sustained: "内存压力持续超过阈值",
  recovery_observation: "正在观察资源恢复稳定性",
  swap_used: "检测到交换内存占用",
  resource_guard_heartbeat_missing: "尚未收到采集服务的资源状态",
  resource_guard_heartbeat_stale: "采集服务的资源状态已超过 30 秒未更新",
  resource_guard_sampled_at_missing: "采集服务的资源采样时间缺失",
  resource_guard_sampled_at_stale: "采集服务的资源采样已超过 30 秒未更新",
  resource_guard_payload_missing: "采集服务尚未报告资源保护状态",
  resource_guard_state_invalid: "采集服务报告的保护状态无法识别",
  host_available_below_protected_threshold: "主机可用内存低于保护阈值",
  host_available_below_constrained_threshold: "主机可用内存低于限流阈值",
  cgroup_usage_above_protected_ratio: "采集服务内存使用率超过保护阈值",
  cgroup_usage_above_constrained_ratio: "采集服务内存使用率超过限流阈值",
  host_memory_unavailable: "暂时无法读取主机内存",
  cgroup_memory_ratio_unavailable: "暂时无法读取采集服务内存使用率",
  swap_activity_above_threshold: "内存不足且交换读写持续偏高",
  process_tree_rss_hard_limit: "采集进程内存达到硬上限",
  cgroup_memory_hard_limit: "采集服务内存达到硬上限",
  awaiting_recovery_window: "资源已回落，正在等待连续健康观察完成",
  recovery_window_complete: "健康观察已完成，优先恢复日批",
  pressure_reappeared: "恢复期间再次出现内存压力",
  awaiting_healthy_window: "恢复条件未持续满足，重新观察",
  stabilizing_after_recovery: "日批已放行，历史补拉等待稳定观察完成",
  resource_sample_unavailable: "暂时无法采集资源状态",
  resource_monitor_unavailable: "资源监控尚未就绪",
  resource_monitor_stale: "资源监控数据已过期",
};

const syncTaskTypeLabels: Record<string, string> = {
  range_sync: "日批总任务",
  parent_sync: "维度采集",
  date_sync: "业务日采集",
  finalize: "日批发布",
};

const dailyBatchLabels: Record<SyncDailyBatchData["status"], string> = {
  not_applicable: "不适用",
  missing: "尚未创建",
  incomplete: "未完成",
  pending: "等待执行",
  queued: "已排队",
  running: "运行中",
  retry_wait: "等待重试",
  success: "已完成",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
  unknown: "状态未知",
};

function resourceGuardTone(
  state: SyncResourceGuardData["state"],
): "neutral" | "info" | "warning" | "danger" | "success" {
  if (state === "normal") return "success";
  if (state === "recovering") return "info";
  if (state === "protected") return "danger";
  if (state === "constrained" || state === "unknown") return "warning";
  return "neutral";
}

function resourceReasonText(reasons: string[]): string {
  if (!reasons.length) return "暂无保护原因";
  return reasons
    .map((reason) => resourceGuardReasonLabels[reason] ?? "资源状态异常，等待重新检查")
    .filter((label, index, labels) => labels.indexOf(label) === index)
    .join("、");
}

function resourceDurationText(seconds: number): string {
  const duration = Math.max(0, Math.floor(seconds));
  if (duration < 60) return `${formatInteger(duration)} 秒`;
  const minutes = Math.floor(duration / 60);
  const remain = duration % 60;
  if (minutes < 60) return `${formatInteger(minutes)} 分 ${formatInteger(remain)} 秒`;
  return `${formatInteger(Math.floor(minutes / 60))} 小时 ${formatInteger(minutes % 60)} 分`;
}

function resourceAffectedTasks(guard: SyncResourceGuardData): string {
  const affected = [
    !guard.allow_daily ? "当日日批" : null,
    !guard.allow_history ? "历史补拉" : null,
  ].filter(Boolean);
  return affected.length ? affected.join("、") : "无（当前任务类型均放行）";
}

function bytesText(value: number | null): string {
  if (value === null) return "-";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value >= 1024 ** 2) return `${Math.round(value / 1024 ** 2)} MB`;
  return `${formatInteger(value)} B`;
}

function byteRateText(value: number | null): string {
  return value === null ? "-" : `${bytesText(value)}/秒`;
}

function dailyTaskTypesText(types: string[]): string {
  if (!types.length) return "暂无待完成任务";
  return types.map((type) => syncTaskTypeLabels[type] ?? "日批任务").filter((label, index, labels) => labels.indexOf(label) === index).join("、");
}

function syncBatchScopeText(freshness: SyncAdminData["sync_freshness"]): string {
  if (!freshness) return "没有可用的成功批次记录";
  if (freshness.latest_successful_sync_window_start && freshness.latest_successful_sync_window_end) {
    return `批次窗口：${formatDateTime(freshness.latest_successful_sync_window_start)} 至 ${formatDateTime(freshness.latest_successful_sync_window_end)}`;
  }
  if (freshness.latest_successful_sync_business_date) {
    return `业务日：${freshness.latest_successful_sync_business_date}`;
  }
  return "业务日或批次窗口未知";
}

function ResourceGuardPanel({
  guard,
  freshness,
}: {
  guard?: SyncResourceGuardData | null;
  freshness?: SyncAdminData["sync_freshness"];
}) {
  const daily = freshness?.daily_batch ?? null;
  return (
    <section className="content-section" aria-labelledby="resource-guard-title">
      <div className="section-title">
        <div>
          <h2 id="resource-guard-title">资源保护与同步时效</h2>
          <p>
            资源状态来自采集服务的持续监测；超过 30 秒未更新时显示为未知。满足恢复条件后自动继续同步。
          </p>
        </div>
        {guard ? (
          <StatusChip tone={resourceGuardTone(guard.state)}>
            {resourceGuardLabels[guard.state]}
          </StatusChip>
        ) : null}
      </div>
      {guard ? (
        <dl className="worker-status-grid">
          <div className="worker-status-item">
            <dt>保护等级</dt>
            <dd>{resourceGuardLabels[guard.state]}</dd>
            <small>监控采样：{formatDateTime(guard.sampled_at)}</small>
          </div>
          <div className="worker-status-item">
            <dt>保护原因</dt>
            <dd>{resourceReasonText(guard.reasons)}</dd>
            <small>
              主机可用内存 {bytesText(guard.host_available_bytes)}；交换内存 {bytesText(guard.swap_used_bytes)}；交换活动速率 {byteRateText(guard.swap_activity_bytes_per_second)}
            </small>
          </div>
          <div className="worker-status-item">
            <dt>持续时长</dt>
            <dd>{resourceDurationText(guard.duration_seconds)}</dd>
            <small>状态开始：{formatDateTime(guard.since)}</small>
          </div>
          <div className="worker-status-item">
            <dt>恢复条件</dt>
            <dd>{guard.recovery_condition || "暂无恢复条件"}</dd>
            <small>
              工作进程内存使用率 {guard.cgroup_used_ratio === null ? "-" : `${Math.round(guard.cgroup_used_ratio * 100)}%`}
            </small>
          </div>
          <div className="worker-status-item">
            <dt>受影响任务类型</dt>
            <dd>{resourceAffectedTasks(guard)}</dd>
            <small>
              当日日批：{yesNo(guard.allow_daily)}；历史补拉：{yesNo(guard.allow_history)}
            </small>
          </div>
          <div className="worker-status-item">
            <dt>最后成功批次</dt>
            <dd>{formatDateTime(freshness?.latest_successful_sync_at)}</dd>
            <small>
              {syncBatchScopeText(freshness)}；
              {freshness?.latest_successful_sync_job_name
                ? `任务类型：${syncTaskTypeLabels[freshness.latest_successful_sync_job_name] ?? "同步任务"}`
                : "任务类型未知"}
            </small>
          </div>
          <div className="worker-status-item">
            <dt>最近完成业务日</dt>
            <dd>{freshness?.latest_completed_business_date ?? "-"}</dd>
            <small>按成功 date_sync 的业务日期统计，不代表昨日批次一定已发布。</small>
          </div>
        </dl>
      ) : (
        <div className="resource-panel">资源监控状态暂不可用，等待采集服务更新。</div>
      )}
      {daily ? (
        <div className={`resource-notice ${daily.is_overdue ? "resource-notice--warning" : daily.status === "failed" ? "resource-notice--error" : ""}`}>
          <strong>
            目标业务日（{daily.business_date ?? "-"}）02:00 日批：{dailyBatchLabels[daily.status]}
          </strong>
          <span>
            目标截止 {formatDateTime(daily.deadline_at)}（上海时间，可配置）；
            {daily.status === "success" ? `完成于 ${formatDateTime(daily.completed_at)}` : daily.is_overdue ? "已超过目标截止时间" : `待完成：${dailyTaskTypesText(daily.incomplete_task_types)}`}
          </span>
        </div>
      ) : freshness ? (
        <div className="resource-notice">当前调度模式没有优先日批状态。</div>
      ) : null}
    </section>
  );
}

interface AdminSyncPageProps {
  isHighestAdmin: boolean;
}

export function AdminSyncPage({ isHighestAdmin }: AdminSyncPageProps) {
  const [checkingSession, setCheckingSession] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [data, setData] = useState<SyncAdminData | null>(null);
  const [draft, setDraft] = useState<ReturnType<typeof configToDraft> | null>(
    null,
  );
  const [draftDirty, setDraftDirty] = useState(false);
  const [remoteConfigChanged, setRemoteConfigChanged] = useState(false);
  const [target, setTarget] = useState<ManualSyncTarget>("orders");
  const [manualDays, setManualDays] = useState("30");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [runningManual, setRunningManual] = useState(false);
  const [statusText, setStatusText] = useState("");
  const draftDirtyRef = useRef(false);
  const configBaselineRef = useRef("");
  const manualTaskRef = useRef<HTMLElement | null>(null);

  const loadData = () => {
    setLoading(true);
    fetchSyncAdmin()
      .then((response) => {
        const nextDraft = configToDraft(response.data.config);
        const nextSignature = draftSignature(nextDraft);
        setData(response.data);
        if (!draftDirtyRef.current) {
          setDraft(nextDraft);
          setDraftDirty(false);
          configBaselineRef.current = nextSignature;
          setRemoteConfigChanged(false);
          return;
        }
        if (
          configBaselineRef.current &&
          configBaselineRef.current !== nextSignature
        ) {
          setRemoteConfigChanged(true);
        }
      })
      .catch((error) => {
        if (error instanceof ApiRequestError && error.status === 401) {
          setAuthenticated(false);
          setStatusText("登录已过期，请重新输入管理密码。");
          return;
        }
        setStatusText("同步配置暂时无法读取。");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!isHighestAdmin) {
      setAuthenticated(false);
      setCheckingSession(false);
      return undefined;
    }
    let cancelled = false;
    setCheckingSession(true);
    fetchAdminSession()
      .then(() => {
        if (!cancelled) {
          setAuthenticated(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuthenticated(false);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingSession(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isHighestAdmin]);

  useEffect(() => {
    if (!isHighestAdmin || !authenticated) return undefined;
    loadData();
    const timer = window.setInterval(loadData, 30000);
    return () => window.clearInterval(timer);
  }, [authenticated, isHighestAdmin]);

  const updateDraft = (patch: Partial<ReturnType<typeof configToDraft>>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setDraftDirty(true);
    draftDirtyRef.current = true;
  };

  const discardDraftAndRefresh = () => {
    if (!data) return;
    const nextDraft = configToDraft(data.config);
    setDraft(nextDraft);
    setDraftDirty(false);
    draftDirtyRef.current = false;
    configBaselineRef.current = draftSignature(nextDraft);
    setRemoteConfigChanged(false);
    setStatusText("已放弃本地草稿，并刷新为服务器最新配置。");
  };

  const progressPercent = useMemo(() => {
    if (!data?.progress.total_windows) return 0;
    return Math.round(
      (data.progress.completed_windows / data.progress.total_windows) * 100,
    );
  }, [data]);
  const workerStatus = data?.worker_status ?? null;
  const priorityMode = workerStatus?.mode === "priority_daily";
  const jobColumns: Column<JobRun>[] = [
    {
      key: "job_id",
      title: "任务编号",
      align: "left",
      render: (job) => <span className="mono-cell">{job.job_id}</span>,
    },
    {
      key: "type",
      title: "类型",
      align: "left",
      render: (job) => displaySyncJobName(job.job_name),
    },
    {
      key: "status",
      title: "状态",
      render: (job) => (
        <StatusChip tone={statusTone(job.status)}>{statusLabel(job.status)}</StatusChip>
      ),
    },
    {
      key: "window",
      title: "数据窗口",
      render: (job) => {
        const window = job.metadata_json?.source_window;
        return window
          ? `${formatDateTime(window.start)} 至 ${formatDateTime(window.end)}`
          : "-";
      },
    },
    {
      key: "started",
      title: "开始时间",
      render: (job) => formatDateTime(job.started_at),
    },
    {
      key: "finished",
      title: "结束时间",
      render: (job) => formatDateTime(job.finished_at),
    },
    {
      align: "right",
      key: "success",
      title: "成功数",
      render: (job) => formatInteger(job.success_count),
    },
    {
      key: "detail",
      title: "明细",
      align: "left",
      render: (job) =>
        job.error_message ? displaySyncFailureReason(job.error_message) : phaseSummary(job),
    },
  ];

  if (!isHighestAdmin) {
    return null;
  }

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginError("");
    try {
      await loginAdmin(password);
      setPassword("");
      setAuthenticated(true);
      setStatusText("");
    } catch {
      setLoginError("密码不正确，或后端未配置管理密码。");
    }
  };

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setStatusText("正在保存同步配置...");
    try {
      const response = await saveSyncConfig({
        history_start: draft.history_start,
        history_end: draft.history_end,
        history_chunk_days: Number(draft.history_chunk_days),
        rolling_days: Number(draft.rolling_days),
        interval_seconds: Number(draft.interval_seconds),
        auto_sync_enabled: draft.auto_sync_enabled,
        backfill_skip_completed: draft.backfill_skip_completed,
      });
      const nextDraft = configToDraft(response.data.config);
      setData(response.data);
      setDraft(nextDraft);
      setDraftDirty(false);
      draftDirtyRef.current = false;
      configBaselineRef.current = draftSignature(nextDraft);
      setRemoteConfigChanged(false);
      setStatusText("同步配置已保存，后台同步程序下一轮会读取新配置。");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) {
        setAuthenticated(false);
        setStatusText("登录已过期，请重新输入管理密码。");
      } else {
        setStatusText("保存失败，请检查配置值。");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleManualRun = async () => {
    setRunningManual(true);
    setStatusText("正在提交手动同步任务...");
    try {
      const response = await runManualSync({
        target,
        days: Number(manualDays),
      });
      setStatusText(`已提交任务 ${response.data.job_id}。`);
      loadData();
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) {
        setAuthenticated(false);
        setStatusText("登录已过期，请重新输入管理密码。");
      } else {
        setStatusText("手动同步任务提交失败。");
      }
    } finally {
      setRunningManual(false);
    }
  };

  if (checkingSession) {
    return (
      <div className="admin-page">
        <section className="admin-login-panel">正在检查管理权限...</section>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="admin-page admin-page--centered">
        <form className="admin-login-panel" onSubmit={handleLogin}>
          <div>
            <h1>数据同步管理</h1>
            <p className="admin-muted">输入管理密码后进入。</p>
          </div>
          <label className="filter-field">
            <span>管理密码</span>
            <FieldInput
              autoFocus
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入管理密码"
              type="password"
              value={password}
            />
          </label>
          {loginError ? (
            <p className="admin-error" role="alert">
              {loginError}
            </p>
          ) : null}
          <Button type="submit" variant="primary">
            进入管理页
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <h1>数据同步管理</h1>
          <p className="admin-muted">
            配置后台采集节奏，查看任务执行情况，并按需手动补拉数据。
          </p>
        </div>
      </section>

      {statusText ? (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="resource-notice"
          role="status"
        >
          {statusText}
        </div>
      ) : null}
      <ComponentRoom
        onCreateTask={() =>
          manualTaskRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
        }
      />
      <ResourceGuardPanel
        guard={data?.resource_guard}
        freshness={data?.sync_freshness}
      />
      <AdminProductSyncPanel />
      <DouyinStoreOrgMappingPanel />
      {remoteConfigChanged ? (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="resource-notice resource-notice--warning"
          role="status"
        >
          <span>服务器配置已更新，本地草稿暂未覆盖。</span>
          <Button onClick={discardDraftAndRefresh} type="button">
            放弃草稿并刷新
          </Button>
        </div>
      ) : null}

      <section className="metric-grid metric-grid--four">
        <MetricCard
          label="历史回填进度"
          value={`${progressPercent}%`}
          meta={
            <>
              已完成 {formatInteger(data?.progress.completed_windows ?? 0)} /{" "}
              {formatInteger(data?.progress.total_windows ?? 0)} 个时间片
            </>
          }
        />
        <MetricCard
          label="当前运行任务"
          value={formatInteger(data?.progress.running_jobs ?? 0)}
          meta="正在写入数据库的任务数"
        />
        <MetricCard
          label="自动同步"
          value={data ? (data.schedule.auto_sync_enabled ? "开启" : "暂停") : "-"}
          meta={
            <>
              最近 {formatDateTime(data?.schedule.latest_successful_sync_at)} / 下次{" "}
              {formatDateTime(data?.schedule.next_scheduled_sync_at)}
            </>
          }
        />
        <MetricCard
          label="同步间隔"
          value={priorityMode ? "每日 02:00" : data ? intervalText(data.config.interval_seconds) : "-"}
          meta={
            <>
              {priorityMode ? "先完成昨日数据，剩余额度补历史；门店与职人每两小时刷新" : `日常同步每次回看 ${formatInteger(data?.config.rolling_days ?? 0)} 天`}
            </>
          }
        />
      </section>

      <section className="content-section" id="manual-sync-task" ref={manualTaskRef}>
        <div className="section-title">
          <div>
            <h2>后台同步状态</h2>
            <p>
              根据后台配置和最近任务日志判断采集进度，用于确认是否正在跑、跑到哪段、失败原因是什么。
            </p>
          </div>
          <Button onClick={loadData} type="button">
            刷新状态
          </Button>
        </div>
        {workerStatus ? (
          <dl className="worker-status-grid">
            <div className="worker-status-item">
              <dt>自动同步</dt>
              <dd>{workerStatus.auto_sync_enabled ? "开启" : "暂停"}</dd>
              <small>
                下次调度 {formatDateTime(workerStatus.next_scheduled_sync_at)}
              </small>
            </div>
            <div className="worker-status-item">
              <dt>运行模式</dt>
              <dd>{displayWorkerMode(workerStatus.mode)}</dd>
              <small>
                启动后立即同步：{yesNo(workerStatus.run_on_start)}；单次运行：
                {yesNo(workerStatus.run_once)}
              </small>
            </div>
            <div className="worker-status-item">
              <dt>日常刷新范围</dt>
              <dd>最近 {formatInteger(workerStatus.rolling_days)} 天</dd>
              <small>
                每 {intervalText(workerStatus.interval_seconds)} 触发；每片{" "}
                {formatInteger(workerStatus.history_chunk_days)} 天；失败最多重试{" "}
                {formatInteger(workerStatus.chunk_max_attempts)} 次
              </small>
            </div>
            <div className="worker-status-item">
              <dt>当前运行任务</dt>
              <dd>
                {workerStatus.active_job
                  ? statusLabel(workerStatus.active_job.status)
                  : "暂无运行中任务"}
              </dd>
              <small>
                {workerStatus.active_job
                  ? `${workerStatus.active_job.job_id}，${jobWindowText(workerStatus.active_job)}`
                  : "如果后台同步程序正在写入大量数据，任务记录可能会在提交后才显示。"}
              </small>
            </div>
            <div className="worker-status-item">
              <dt>最近成功窗口</dt>
              <dd>{jobWindowText(workerStatus.latest_success)}</dd>
              <small>{jobStatusLine(workerStatus.latest_success)}</small>
            </div>
            <div className="worker-status-item">
              <dt>最近失败原因</dt>
              <dd>
                {workerStatus.latest_failure
                  ? displaySyncFailureReason(workerStatus.latest_failure.error_message)
                  : "暂无失败记录"}
              </dd>
              <small>
                {workerStatus.latest_failure
                  ? `${jobWindowText(workerStatus.latest_failure)}，${jobStatusLine(
                      workerStatus.latest_failure,
                    )}`
                  : "最近没有失败的采集任务。"}
              </small>
            </div>
          </dl>
        ) : (
          <div className="resource-panel">暂无后台同步状态数据</div>
        )}
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>同步配置</h2>
            <p>历史回填用于补齐旧数据；日常同步用于滚动刷新最近可能变化的数据。</p>
          </div>
          {draftDirty ? (
            <span className="source-pill">有未保存草稿</span>
          ) : loading ? (
            <span className="source-pill">刷新中</span>
          ) : null}
        </div>

        {draft ? (
          <div className="sync-config-grid">
            {priorityMode && <p>当前使用昨日优先调度。旧自动同步开关、滚动天数和间隔不参与调度；历史日期范围仍生效。</p>}
            <label className="filter-field checkbox-field">
              <span>自动同步</span>
              <FieldInput
                checked={draft.auto_sync_enabled}
                disabled={priorityMode}
                onChange={(event) =>
                  updateDraft({
                    auto_sync_enabled: event.target.checked,
                  })
                }
                type="checkbox"
              />
            </label>
            <label className="filter-field">
              <span>历史回填开始日期</span>
              <FieldInput
                onChange={(event) =>
                  updateDraft({ history_start: event.target.value })
                }
                type="date"
                value={draft.history_start}
              />
            </label>
            <label className="filter-field">
              <span>历史回填结束日期</span>
              <FieldInput
                onChange={(event) =>
                  updateDraft({ history_end: event.target.value })
                }
                type="date"
                value={draft.history_end}
              />
            </label>
            <label className="filter-field">
              <span>每个历史分片天数</span>
              <FieldInput
                min="1"
                max="31"
                onChange={(event) =>
                  updateDraft({ history_chunk_days: event.target.value })
                }
                type="number"
                value={draft.history_chunk_days}
                disabled={priorityMode}
              />
            </label>
            <label className="filter-field">
              <span>日常滚动刷新天数</span>
              <FieldInput
                min="1"
                max="180"
                onChange={(event) =>
                  updateDraft({ rolling_days: event.target.value })
                }
                type="number"
                value={draft.rolling_days}
                disabled={priorityMode}
              />
            </label>
            <SelectField
              label="同步间隔"
              onChange={(value) => updateDraft({ interval_seconds: value })}
              options={intervalOptions}
              value={draft.interval_seconds}
              disabled={priorityMode}
            />
            <label className="filter-field checkbox-field">
              <span>历史回填断点续跑</span>
              <FieldInput
                checked={draft.backfill_skip_completed}
                disabled={priorityMode}
                onChange={(event) =>
                  updateDraft({
                    backfill_skip_completed: event.target.checked,
                  })
                }
                type="checkbox"
              />
            </label>
            <Button
              disabled={saving}
              onClick={handleSave}
              type="button"
              variant="primary"
            >
              保存配置
            </Button>
          </div>
        ) : (
          <div className="resource-panel">暂无配置数据</div>
        )}
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>手动补拉</h2>
            <p>用于重新拉取某类源数据，完成后会刷新结算结果。</p>
          </div>
        </div>
        <div className="manual-sync-grid">
          <SelectField
            label="数据表 / 任务类型"
            onChange={(value) => setTarget(value as ManualSyncTarget)}
            options={targetOptions}
            value={target}
          />
          <label className="filter-field">
            <span>回看天数</span>
            <FieldInput
              min="1"
              max="180"
              onChange={(event) => setManualDays(event.target.value)}
              type="number"
              value={manualDays}
            />
          </label>
          <Button
            disabled={runningManual}
            onClick={handleManualRun}
            type="button"
            variant="primary"
          >
            立即补拉
          </Button>
          <Button onClick={loadData} type="button">
            刷新日志
          </Button>
        </div>
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>同步日志</h2>
            <p>最近 20 个任务，包含后台自动任务和手动任务。</p>
          </div>
        </div>
        <DataTable
          columns={jobColumns}
          emptyText="暂无同步日志"
          rows={data?.jobs ?? []}
          tableClassName="admin-sync-table"
        />
      </section>
    </div>
  );
}
