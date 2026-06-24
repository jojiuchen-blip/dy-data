import { useCallback, useEffect, useState } from "react";
import {
  ApiRequestError,
  fetchAdminSession,
  fetchClueReassignRule,
  loginAdmin,
  rebuildClues,
  saveClueReassignRule,
} from "../api/client";
import type { ClueReassignRuleData } from "../types/dashboard";
import { formatDateTime, formatInteger } from "../utils/format";

function slaToInput(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function validateSla(value: string): number | null | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 168) {
    return undefined;
  }
  return parsed;
}

function displayOperator(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return value.includes("mock") ? "演示管理员" : value;
}

export function AdminClueRulePage() {
  const [checkingSession, setCheckingSession] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [rule, setRule] = useState<ClueReassignRuleData | null>(null);
  const [slaInput, setSlaInput] = useState("");
  const [statusText, setStatusText] = useState("");
  const [loadingRule, setLoadingRule] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const handleAuthError = useCallback((error: unknown): boolean => {
    if (error instanceof ApiRequestError && error.status === 401) {
      setAuthenticated(false);
      setStatusText("登录已过期，请重新输入管理密码。");
      return true;
    }
    return false;
  }, []);

  const loadRule = useCallback(() => {
    setLoadingRule(true);
    fetchClueReassignRule()
      .then((response) => {
        setRule(response.data);
        setSlaInput(slaToInput(response.data.reassign_sla_hours));
        setStatusText(response.usingMock ? response.fallbackReason ?? "" : "");
      })
      .catch((error) => {
        if (!handleAuthError(error)) {
          setStatusText("线索再分配规则暂时无法读取。");
        }
      })
      .finally(() => {
        setLoadingRule(false);
      });
  }, [handleAuthError]);

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
    if (authenticated) {
      loadRule();
    }
  }, [authenticated, loadRule]);

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
    const parsed = validateSla(slaInput);
    if (parsed === undefined) {
      setStatusText("SLA 必须留空，或填写 1 到 168 之间的整数小时。");
      return;
    }

    setSaving(true);
    setStatusText("正在保存线索再分配规则...");
    try {
      const response = await saveClueReassignRule({
        reassign_sla_hours: parsed,
      });
      setRule(response.data);
      setSlaInput(slaToInput(response.data.reassign_sla_hours));
      setStatusText(
        response.usingMock
          ? response.fallbackReason ?? "规则已保存到演示数据。"
          : "线索再分配规则已保存。",
      );
    } catch (error) {
      if (!handleAuthError(error)) {
        setStatusText("规则保存失败，请稍后重试。");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleRebuild = async () => {
    setRebuilding(true);
    setStatusText("正在触发线索中心重建...");
    try {
      const response = await rebuildClues();
      const result = response.data;
      const countText =
        result.rebuilt_order_count !== undefined &&
        result.rebuilt_order_count !== null
          ? `，订单 ${formatInteger(result.rebuilt_order_count)} 条`
          : "";
      const jobText = result.job_id ? `，任务 ${result.job_id}` : "";
      setStatusText(
        `线索中心重建完成${jobText}${countText}${
          result.status ? `，状态 ${result.status}` : ""
        }。`,
      );
    } catch (error) {
      if (!handleAuthError(error)) {
        setStatusText("线索中心重建触发失败，请稍后重试。");
      }
    } finally {
      setRebuilding(false);
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
            <h1>线索再分配规则</h1>
            <p className="admin-muted">规则配置页</p>
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
          <h1>线索再分配规则</h1>
          <p className="admin-muted">
            全局 SLA 小时数；留空时不启用自动超时待再分配。
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

      <section className="content-section clue-rule-panel">
        <div className="section-title">
          <div>
            <h2>再分配 SLA</h2>
            <p>未配置时，距离再分配剩余时间为空。</p>
          </div>
          {loadingRule ? <span className="source-pill">加载中</span> : null}
        </div>

        <div className="clue-rule-grid">
          <label className="filter-field">
            <span>SLA 小时数</span>
            <input
              inputMode="numeric"
              max={168}
              min={1}
              onChange={(event) => setSlaInput(event.target.value)}
              placeholder="留空表示不配置"
              value={slaInput}
            />
          </label>
          <div className="clue-rule-current">
            <span>当前值</span>
            <strong>
              {rule?.reassign_sla_hours == null
                ? "未配置"
                : `${rule.reassign_sla_hours} 小时`}
            </strong>
            <small>
              更新人 {displayOperator(rule?.updated_by)} · 更新时间{" "}
              {formatDateTime(rule?.updated_at)}
            </small>
          </div>
          <button
            className="primary-button"
            disabled={saving || loadingRule}
            onClick={handleSave}
            type="button"
          >
            保存规则
          </button>
          <button
            className="ghost-button"
            disabled={rebuilding}
            onClick={handleRebuild}
            type="button"
          >
            重建线索中心
          </button>
        </div>
      </section>
    </div>
  );
}
