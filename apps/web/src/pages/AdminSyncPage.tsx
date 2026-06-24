import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiRequestError,
  fetchAdminSession,
  fetchSyncAdmin,
  loginAdmin,
  logoutAdmin,
  runManualSync,
  saveSyncConfig,
} from "../api/client";
import type {
  JobRun,
  ManualSyncTarget,
  SyncAdminData,
  SyncConfigData,
} from "../types/dashboard";
import { formatDateTime, formatInteger } from "../utils/format";

const targetOptions: { value: ManualSyncTarget; label: string }[] = [
  { value: "all", label: "全部开放接口数据" },
  { value: "orders", label: "订单数据" },
  { value: "verify_records", label: "核销数据" },
  { value: "shop_pois", label: "门店 POI 数据" },
  { value: "aweme_bindings", label: "子机构号开放接口" },
  { value: "backend_aweme_export", label: "子机构号浏览器导出" },
  { value: "settlement", label: "仅重建结算结果" },
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
  return "已排队";
}

function phaseSummary(job: JobRun): string {
  const phases = job.metadata_json?.phases ?? {};
  const parts = Object.values(phases).map((phase) => {
    const fetched = formatInteger(Number(phase.fetched ?? 0));
    const upserted = formatInteger(Number(phase.upserted ?? 0));
    return `${phase.name} 拉取 ${fetched} / 写入 ${upserted}`;
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

function workerModeLabel(mode: string): string {
  if (mode === "collect_and_settle") return "接口采集并重建结算";
  if (mode === "settlement_only") return "只重建结算";
  if (mode === "backfill") return "历史数据回填";
  if (mode === "browser_export_only") return "只执行浏览器导出";
  return mode || "-";
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

export function AdminSyncPage() {
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
    let cancelled = false;
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
  }, []);

  useEffect(() => {
    if (!authenticated) return undefined;
    loadData();
    const timer = window.setInterval(loadData, 30000);
    return () => window.clearInterval(timer);
  }, [authenticated]);

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

  const handleLogout = async () => {
    await logoutAdmin().catch(() => undefined);
    setAuthenticated(false);
    setData(null);
    setDraft(null);
    setDraftDirty(false);
    draftDirtyRef.current = false;
    configBaselineRef.current = "";
    setRemoteConfigChanged(false);
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
      setStatusText("同步配置已保存，worker 下一轮会读取新配置。");
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
            <p className="source-pill">系统管理后台</p>
            <h1>数据同步管理</h1>
            <p className="admin-muted">输入管理密码后进入。</p>
          </div>
          <label className="filter-field">
            <span>管理密码</span>
            <input
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
          <button className="primary-button" type="submit">
            进入管理页
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <p className="source-pill">系统管理后台</p>
          <h1>数据同步管理</h1>
          <p className="admin-muted">
            配置后台采集节奏，查看任务执行情况，并按需手动补拉数据。
          </p>
        </div>
        <div className="admin-header-actions">
          <a className="ghost-button admin-link-button" href="/">
            返回看板主页
          </a>
          <a className="ghost-button admin-link-button" href="/admin">
            返回后台首页
          </a>
          <button className="ghost-button" onClick={handleLogout} type="button">
            退出
          </button>
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
      {remoteConfigChanged ? (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="resource-notice resource-notice--warning"
          role="status"
        >
          <span>服务器配置已更新，本地草稿暂未覆盖。</span>
          <button className="ghost-button" onClick={discardDraftAndRefresh} type="button">
            放弃草稿并刷新
          </button>
        </div>
      ) : null}

      <section className="metric-grid metric-grid--four">
        <div className="metric-card">
          <div className="metric-card__label">历史回填进度</div>
          <div className="metric-card__value">{progressPercent}%</div>
          <div className="metric-card__meta">
            已完成 {formatInteger(data?.progress.completed_windows ?? 0)} /{" "}
            {formatInteger(data?.progress.total_windows ?? 0)} 个时间片
          </div>
        </div>
        <div className="metric-card metric-card--blue">
          <div className="metric-card__label">当前运行任务</div>
          <div className="metric-card__value">
            {formatInteger(data?.progress.running_jobs ?? 0)}
          </div>
          <div className="metric-card__meta">正在写入数据库的任务数</div>
        </div>
        <div className="metric-card">
          <div className="metric-card__label">自动同步</div>
          <div className="metric-card__value">
            {data ? (data.schedule.auto_sync_enabled ? "开启" : "暂停") : "-"}
          </div>
          <div className="metric-card__meta">
            最近 {formatDateTime(data?.schedule.latest_successful_sync_at)} / 下次{" "}
            {formatDateTime(data?.schedule.next_scheduled_sync_at)}
          </div>
        </div>
        <div className="metric-card metric-card--amber">
          <div className="metric-card__label">同步间隔</div>
          <div className="metric-card__value">
            {data ? intervalText(data.config.interval_seconds) : "-"}
          </div>
          <div className="metric-card__meta">
            日常同步每次回看 {formatInteger(data?.config.rolling_days ?? 0)} 天
          </div>
        </div>
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>Worker 状态</h2>
            <p>
              根据后台配置和最近任务日志判断采集进度，用于确认是否正在跑、跑到哪段、失败原因是什么。
            </p>
          </div>
          <button className="ghost-button" onClick={loadData} type="button">
            刷新状态
          </button>
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
              <dd>{workerModeLabel(workerStatus.mode)}</dd>
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
                  : "如果 worker 正在长事务里写入，任务记录可能会在提交后才显示。"}
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
                {workerStatus.latest_failure?.error_message
                  ? workerStatus.latest_failure.error_message
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
          <div className="resource-panel">暂无 worker 状态数据</div>
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
            <label className="filter-field checkbox-field">
              <span>自动同步</span>
              <input
                checked={draft.auto_sync_enabled}
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
              <input
                onChange={(event) =>
                  updateDraft({ history_start: event.target.value })
                }
                type="date"
                value={draft.history_start}
              />
            </label>
            <label className="filter-field">
              <span>历史回填结束日期</span>
              <input
                onChange={(event) =>
                  updateDraft({ history_end: event.target.value })
                }
                type="date"
                value={draft.history_end}
              />
            </label>
            <label className="filter-field">
              <span>每个历史分片天数</span>
              <input
                min="1"
                max="31"
                onChange={(event) =>
                  updateDraft({ history_chunk_days: event.target.value })
                }
                type="number"
                value={draft.history_chunk_days}
              />
            </label>
            <label className="filter-field">
              <span>日常滚动刷新天数</span>
              <input
                min="1"
                max="180"
                onChange={(event) =>
                  updateDraft({ rolling_days: event.target.value })
                }
                type="number"
                value={draft.rolling_days}
              />
            </label>
            <label className="filter-field">
              <span>同步间隔</span>
              <select
                onChange={(event) =>
                  updateDraft({ interval_seconds: event.target.value })
                }
                value={draft.interval_seconds}
              >
                <option value="1800">半小时</option>
                <option value="3600">1 小时</option>
                <option value="7200">2 小时</option>
                <option value="21600">6 小时</option>
                <option value="86400">每天</option>
              </select>
            </label>
            <label className="filter-field checkbox-field">
              <span>历史回填断点续跑</span>
              <input
                checked={draft.backfill_skip_completed}
                onChange={(event) =>
                  updateDraft({
                    backfill_skip_completed: event.target.checked,
                  })
                }
                type="checkbox"
              />
            </label>
            <button
              className="primary-button"
              disabled={saving}
              onClick={handleSave}
              type="button"
            >
              保存配置
            </button>
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
          <label className="filter-field">
            <span>数据表 / 任务类型</span>
            <select
              onChange={(event) =>
                setTarget(event.target.value as ManualSyncTarget)
              }
              value={target}
            >
              {targetOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>回看天数</span>
            <input
              min="1"
              max="180"
              onChange={(event) => setManualDays(event.target.value)}
              type="number"
              value={manualDays}
            />
          </label>
          <button
            className="primary-button"
            disabled={runningManual}
            onClick={handleManualRun}
            type="button"
          >
            立即补拉
          </button>
          <button className="ghost-button" onClick={loadData} type="button">
            刷新日志
          </button>
        </div>
      </section>

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>同步日志</h2>
            <p>最近 20 个任务，包含后台自动任务和手动任务。</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table admin-sync-table">
            <thead>
              <tr>
                <th>任务 ID</th>
                <th>类型</th>
                <th>状态</th>
                <th>数据窗口</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th className="is-right">成功数</th>
                <th>明细</th>
              </tr>
            </thead>
            <tbody>
              {data?.jobs.length ? (
                data.jobs.map((job) => {
                  const window = job.metadata_json?.source_window;
                  return (
                    <tr key={job.job_id}>
                      <td className="mono-cell">{job.job_id}</td>
                      <td>{job.job_name}</td>
                      <td>
                        <span className="status-chip">{statusLabel(job.status)}</span>
                      </td>
                      <td>
                        {window
                          ? `${formatDateTime(window.start)} 至 ${formatDateTime(window.end)}`
                          : "-"}
                      </td>
                      <td>{formatDateTime(job.started_at)}</td>
                      <td>{formatDateTime(job.finished_at)}</td>
                      <td className="is-right">
                        {formatInteger(job.success_count)}
                      </td>
                      <td>{job.error_message || phaseSummary(job)}</td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td className="empty-cell" colSpan={8}>
                    暂无同步日志
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
