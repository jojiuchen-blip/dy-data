import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiRequestError,
  decideMcpAuthorization,
  fetchMcpAuthorizationRequest,
} from "../api/client";
import { Button } from "../components/Button";
import type {
  AdminUser,
  McpAuthorizationRequestDetails,
} from "../types/dashboard";

interface McpAuthorizePageProps {
  currentUser: AdminUser;
  search: string;
}

type PageState = "loading" | "ready" | "invalid";

function readRequestId(search: string): string {
  return new URLSearchParams(search).get("request_id")?.trim() ?? "";
}

function failureMessage(error: unknown): string {
  if (error instanceof ApiRequestError && error.status === 401) {
    return "登录状态已失效，请重新登录后再确认授权。";
  }
  if (error instanceof ApiRequestError && error.status === 400) {
    return "这次 Agent 授权请求无效、已过期或已经处理。请返回 Agent 重新连接。";
  }
  return "暂时无法读取授权信息，请稍后从 Agent 重新发起连接。";
}

export function McpAuthorizePage({
  currentUser,
  search,
}: McpAuthorizePageProps) {
  const requestId = useMemo(() => readRequestId(search), [search]);
  const [pageState, setPageState] = useState<PageState>("loading");
  const [details, setDetails] = useState<McpAuthorizationRequestDetails | null>(
    null,
  );
  const [message, setMessage] = useState("");
  const [decision, setDecision] = useState<"approve" | "deny" | null>(null);
  const requestGenerationRef = useRef(0);

  useEffect(() => {
    requestGenerationRef.current += 1;
    const generation = requestGenerationRef.current;
    setDetails(null);
    setMessage("");
    setDecision(null);

    if (!requestId) {
      setPageState("invalid");
      setMessage("缺少 Agent 授权请求，请返回 Agent 重新连接。");
      return;
    }

    setPageState("loading");
    fetchMcpAuthorizationRequest(requestId)
      .then((response) => {
        if (requestGenerationRef.current !== generation) {
          return;
        }
        setDetails(response.data);
        setPageState("ready");
      })
      .catch((error: unknown) => {
        if (requestGenerationRef.current !== generation) {
          return;
        }
        setPageState("invalid");
        setMessage(failureMessage(error));
      });
  }, [requestId]);

  const submitDecision = async (nextDecision: "approve" | "deny") => {
    if (!details || decision) {
      return;
    }
    setDecision(nextDecision);
    setMessage("");
    try {
      const response = await decideMcpAuthorization(
        details.request_id,
        nextDecision,
      );
      window.location.assign(response.redirect_uri);
    } catch (error) {
      setDecision(null);
      setPageState("invalid");
      setMessage(failureMessage(error));
    }
  };

  if (pageState !== "ready" || !details) {
    return (
      <main className="auth-shell cli-authorize-shell">
        <section
          className="auth-panel cli-authorize-panel"
          aria-labelledby="mcp-authorize-title"
        >
          <p className="cli-authorize-eyebrow">Agent 安全授权</p>
          <h1 id="mcp-authorize-title">
            {pageState === "loading" ? "正在读取授权信息" : "无法继续授权"}
          </h1>
          <p className="cli-authorize-copy">
            {pageState === "loading"
              ? `正在确认 ${currentUser.display_name || currentUser.username} 的账号范围…`
              : message}
          </p>
        </section>
      </main>
    );
  }

  const stores = details.data_scope.stores;
  return (
    <main className="auth-shell cli-authorize-shell">
      <section
        className="auth-panel cli-authorize-panel"
        aria-labelledby="mcp-authorize-title"
      >
        <p className="cli-authorize-eyebrow">Agent 安全授权</p>
        <h1 id="mcp-authorize-title">允许这个 Agent 读取门店数据？</h1>
        <p className="cli-authorize-copy">
          授权后只可查询当前账号有权访问的门店和线索跟进统计，不能新增、修改或删除数据。
        </p>

        <dl className="cli-authorize-details">
          <div>
            <dt>Agent 名称</dt>
            <dd><strong>{details.agent_name}</strong></dd>
          </div>
          <div>
            <dt>当前账号</dt>
            <dd>
              <strong>{details.account.display_name}</strong>
              <span>用户名：{details.account.username}</span>
            </dd>
          </div>
          <div>
            <dt>测试环境</dt>
            <dd>{details.environment}</dd>
          </div>
          <div>
            <dt>授权范围</dt>
            <dd>{details.scopes.join("、")}（只读）</dd>
          </div>
          <div>
            <dt>可读取门店</dt>
            <dd>
              <strong>{stores.length} 家</strong>
              <span>{stores.map((store) => store.store_name).join("、") || "无"}</span>
            </dd>
          </div>
          <div>
            <dt>回调地址</dt>
            <dd className="mcp-authorize-uri">{details.redirect_uri}</dd>
          </div>
        </dl>

        {message ? <p className="auth-field-error" role="alert">{message}</p> : null}
        <div className="mcp-authorize-actions">
          <Button
            disabled={decision !== null}
            onClick={() => void submitDecision("deny")}
            variant="secondary"
          >
            拒绝
          </Button>
          <Button
            loading={decision === "approve"}
            disabled={decision !== null}
            onClick={() => void submitDecision("approve")}
            variant="primary"
          >
            允许只读访问
          </Button>
        </div>
      </section>
    </main>
  );
}
