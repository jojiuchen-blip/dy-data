import { useMemo, useState, type FormEvent } from "react";
import { ApiRequestError, approveCliAuthorization } from "../api/client";
import { Button } from "../components/Button";
import type { AdminUser } from "../types/dashboard";

interface CliAuthorizePageProps {
  currentUser: AdminUser;
}

type ApprovalState = "ready" | "approved" | "invalid";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError && error.status === 401) {
    return "登录状态已失效，请重新登录后再确认授权。";
  }
  if (error instanceof ApiRequestError && error.status === 400) {
    return "此验证码无效、已过期或已被使用。请返回 CLI 重新发起授权。";
  }
  return "授权暂时未完成，请稍后重试。";
}

export function CliAuthorizePage({ currentUser }: CliAuthorizePageProps) {
  const [approvalState, setApprovalState] = useState<ApprovalState>("ready");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const userCode = useMemo(
    () => new URLSearchParams(window.location.search).get("user_code")?.trim() ?? "",
    [],
  );
  const accountName = currentUser.display_name || currentUser.username;

  const handleApprove = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!userCode || submitting) {
      return;
    }

    setSubmitting(true);
    setMessage("");
    try {
      await approveCliAuthorization(userCode);
      setApprovalState("approved");
    } catch (error) {
      setApprovalState("invalid");
      setMessage(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  if (!userCode) {
    return (
      <main className="auth-shell cli-authorize-shell">
        <section className="auth-panel cli-authorize-panel" aria-labelledby="cli-authorize-title">
          <p className="cli-authorize-eyebrow">CLI 设备授权</p>
          <h1 id="cli-authorize-title">缺少授权码</h1>
          <p className="cli-authorize-copy">
            请回到 CLI，重新打开其提供的浏览器授权链接。
          </p>
        </section>
      </main>
    );
  }

  if (approvalState === "approved") {
    return (
      <main className="auth-shell cli-authorize-shell">
        <section className="auth-panel cli-authorize-panel" aria-labelledby="cli-authorize-title">
          <p className="cli-authorize-eyebrow">CLI 设备授权</p>
          <h1 id="cli-authorize-title">授权已完成</h1>
          <p className="cli-authorize-copy">
            CLI 将获得门店线索汇总的只读权限。你可以关闭此页面并返回 CLI。
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-shell cli-authorize-shell">
      <section className="auth-panel cli-authorize-panel" aria-labelledby="cli-authorize-title">
        <p className="cli-authorize-eyebrow">CLI 设备授权</p>
        <h1 id="cli-authorize-title">允许 CLI 读取门店线索汇总？</h1>
        <p className="cli-authorize-copy">
          请确认当前账号和授权范围；授权后，CLI 只能读取你有权限访问的数据。
        </p>

        <dl className="cli-authorize-details">
          <div>
            <dt>当前账号</dt>
            <dd>
              <strong>{accountName}</strong>
              <span>用户名：{currentUser.username}</span>
            </dd>
          </div>
          <div>
            <dt>一次性验证码</dt>
            <dd className="cli-authorize-code">{userCode}</dd>
          </div>
          <div>
            <dt>授权范围</dt>
            <dd>只读 · 门店线索汇总</dd>
          </div>
        </dl>

        <form className="cli-authorize-form" onSubmit={handleApprove}>
          {approvalState === "invalid" ? (
            <p className="auth-field-error" role="alert">{message}</p>
          ) : null}
          <Button loading={submitting} type="submit" variant="primary">
            允许此 CLI 读取门店线索汇总
          </Button>
        </form>
      </section>
    </main>
  );
}
