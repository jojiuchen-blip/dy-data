import { useEffect, useMemo, useState } from "react";
import { initializeAccount, loginAdmin, resetAccountPassword } from "../api/client";
import { SolarIcon } from "../components/SolarIcon";
import type { AccountSelfServicePayload, AdminUser } from "../types/dashboard";

export type AuthMode = "login" | "activate" | "reset";

interface AuthPageProps {
  initialMode?: AuthMode;
  onAuthenticated: (user: AdminUser) => void;
}

const modeLabels: Record<AuthMode, string> = {
  login: "账号登录",
  activate: "账号激活",
  reset: "重置密码",
};

const selfServiceSubmitLabels: Record<Exclude<AuthMode, "login">, string> = {
  activate: "完成激活",
  reset: "重置密码",
};

const selfServiceErrorMessages: Record<Exclude<AuthMode, "login">, string> = {
  activate: "账号激活失败，请核对所属账户ID/POI ID、认证主体全称和密码确认。",
  reset: "密码重置失败，请核对所属账户ID/POI ID、认证主体全称和密码确认。",
};

type ActivationHintKey =
  | "external_account_id"
  | "certified_subject_name"
  | "username"
  | "display_name"
  | "password"
  | "password_confirm";

interface ActivationFieldHint {
  title: string;
  body: string;
}

const activationFieldHints: Record<ActivationHintKey, ActivationFieldHint> = {
  external_account_id: {
    title: "所属账户ID/POI ID",
    body:
      "抖音来客电脑端右上角个人头像下方的“账户ID”；手机端“我的-个人中心-我的账户ID”。也可以填写对应门店的POI ID。",
  },
  certified_subject_name: {
    title: "认证主体全称",
    body: "抖音来客账号绑定的公司主体全名。",
  },
  username: {
    title: "账号名",
    body: "自行设置。",
  },
  display_name: {
    title: "显示名称",
    body: "自行设置。",
  },
  password: {
    title: "密码",
    body: "自行设置。",
  },
  password_confirm: {
    title: "确认密码",
    body: "自行设置。",
  },
};

function emptyActivationPayload(): AccountSelfServicePayload {
  return {
    external_account_id: "",
    certified_subject_name: "",
    username: "",
    password: "",
    password_confirm: "",
    display_name: "",
  };
}

export function AuthPage({ initialMode = "login", onAuthenticated }: AuthPageProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [identifier, setIdentifier] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [payload, setPayload] = useState<AccountSelfServicePayload>(
    emptyActivationPayload,
  );
  const [activeActivationHint, setActiveActivationHint] =
    useState<ActivationHintKey | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const title = useMemo(() => modeLabels[mode], [mode]);
  const activeActivationHintDetail =
    mode === "login" || !activeActivationHint
      ? null
      : activationFieldHints[activeActivationHint];
  const authShellClassName = [
    "auth-shell",
    mode === "login" ? "" : "auth-shell--with-help",
  ]
    .filter(Boolean)
    .join(" ");

  useEffect(() => {
    setMode(initialMode);
    setMessage("");
    setActiveActivationHint(null);
  }, [initialMode]);

  const setPayloadField = (
    field: keyof AccountSelfServicePayload,
    value: string,
  ) => {
    setPayload((current) => ({ ...current, [field]: value }));
  };

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setMessage("");
    setActiveActivationHint(null);
  };

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage("");
    try {
      const result = await loginAdmin(identifier.trim(), loginPassword);
      setLoginPassword("");
      onAuthenticated(result.data);
    } catch {
      setMessage("账号或密码不正确。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSelfService = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mode === "login") {
      return;
    }
    setSubmitting(true);
    setMessage("");
    try {
      const submitPayload = {
        ...payload,
        external_account_id: payload.external_account_id.trim(),
        certified_subject_name: payload.certified_subject_name.trim(),
        username: payload.username.trim(),
        display_name: payload.display_name?.trim() || null,
      };
      const request =
        mode === "reset" ? resetAccountPassword : initializeAccount;
      const result = await request(submitPayload);
      setPayload(emptyActivationPayload());
      onAuthenticated(result.data);
    } catch {
      setMessage(selfServiceErrorMessages[mode]);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className={authShellClassName}>
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">
          <SolarIcon className="brand__mark" name="brand" size={44} />
          <div>
            <p className="eyebrow">抖音经营数据引擎</p>
            <h1 id="auth-title">{title}</h1>
          </div>
        </div>

        {mode === "reset" ? (
          <div className="auth-return-row">
            <a className="link-button" href="/login">
              返回账号登录
            </a>
          </div>
        ) : (
          <div className="auth-tabs auth-tabs--two" role="tablist" aria-label="账号入口">
            {(["login", "activate"] as const).map((item) => (
              <button
                aria-selected={mode === item}
                className="auth-tab"
                key={item}
                onClick={() => switchMode(item)}
                role="tab"
                type="button"
              >
                {modeLabels[item]}
              </button>
            ))}
          </div>
        )}

        {mode === "login" ? (
          <form className="auth-form" onSubmit={handleLogin}>
            <label className="filter-field">
              <span>账号名或所属账户ID/POI ID</span>
              <input
                autoFocus
                autoComplete="username"
                onChange={(event) => setIdentifier(event.target.value)}
                placeholder="输入账号名、所属账户ID或POI ID"
                value={identifier}
              />
            </label>
            <label className="filter-field">
              <span>密码</span>
              <input
                autoComplete="current-password"
                onChange={(event) => setLoginPassword(event.target.value)}
                placeholder="输入密码"
                type="password"
                value={loginPassword}
              />
            </label>
            {message ? <p className="admin-error">{message}</p> : null}
            <div className="auth-form-actions">
              <button className="primary-button" disabled={submitting} type="submit">
                登录
              </button>
              <a className="link-button" href="/auth/reset-password">
                忘记密码
              </a>
            </div>
          </form>
        ) : (
          <form className="auth-form" onSubmit={handleSelfService}>
            <label className="filter-field">
              <span>所属账户ID/POI ID</span>
              <input
                autoComplete="off"
                onFocus={() => setActiveActivationHint("external_account_id")}
                onChange={(event) =>
                  setPayloadField("external_account_id", event.target.value)
                }
                placeholder="输入子机构账号所属账户ID或门店POI ID"
                value={payload.external_account_id}
              />
            </label>
            <label className="filter-field">
              <span>认证主体全称</span>
              <input
                autoComplete="organization"
                onFocus={() => setActiveActivationHint("certified_subject_name")}
                onChange={(event) =>
                  setPayloadField("certified_subject_name", event.target.value)
                }
                placeholder="输入门店主数据中的认证主体全称"
                value={payload.certified_subject_name}
              />
            </label>
            <label className="filter-field">
              <span>账号名</span>
              <input
                autoComplete="username"
                onFocus={() => setActiveActivationHint("username")}
                onChange={(event) => setPayloadField("username", event.target.value)}
                placeholder="设置后续登录使用的账号名"
                value={payload.username}
              />
            </label>
            <label className="filter-field">
              <span>显示名称</span>
              <input
                autoComplete="name"
                onFocus={() => setActiveActivationHint("display_name")}
                onChange={(event) =>
                  setPayloadField("display_name", event.target.value)
                }
                placeholder="可选，默认使用门店名称"
                value={payload.display_name ?? ""}
              />
            </label>
            <label className="filter-field">
              <span>密码</span>
              <input
                autoComplete="new-password"
                onFocus={() => setActiveActivationHint("password")}
                onChange={(event) => setPayloadField("password", event.target.value)}
                placeholder="设置密码"
                type="password"
                value={payload.password}
              />
            </label>
            <label className="filter-field">
              <span>确认密码</span>
              <input
                autoComplete="new-password"
                onFocus={() => setActiveActivationHint("password_confirm")}
                onChange={(event) =>
                  setPayloadField("password_confirm", event.target.value)
                }
                placeholder="再次输入密码"
                type="password"
                value={payload.password_confirm}
              />
            </label>
            {message ? <p className="admin-error">{message}</p> : null}
            <button className="primary-button" disabled={submitting} type="submit">
              {selfServiceSubmitLabels[mode]}
            </button>
          </form>
        )}
      </section>
      {activeActivationHintDetail ? (
        <aside className="auth-help-card" aria-live="polite">
          <p className="auth-help-card__eyebrow">字段来源</p>
          <h2>{activeActivationHintDetail.title}</h2>
          {activeActivationHintDetail.body ? (
            <p>{activeActivationHintDetail.body}</p>
          ) : null}
        </aside>
      ) : null}
    </main>
  );
}
