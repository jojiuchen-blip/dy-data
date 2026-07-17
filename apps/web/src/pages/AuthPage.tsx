import { useEffect, useMemo, useState } from "react";
import {
  checkAccountActivationStatus,
  initializeAccount,
  loginAdmin,
  resetAccountPassword,
} from "../api/client";
import { Button, IconButton } from "../components/Button";
import { SolarIcon } from "../components/SolarIcon";
import type {
  AccountActivationCheckPayload,
  AccountActivationPayload,
  AccountPasswordResetPayload,
  AdminUser,
} from "../types/dashboard";

export type AuthMode = "login" | "activate" | "reset";

interface AuthPageProps {
  initialMode?: AuthMode;
  onAuthenticated: (user: AdminUser) => void;
}

type ActivationStep = "identity" | "credentials";
type ResetStep = "identity" | "credentials";
type ActivationCheckState = "idle" | "invalid" | "activated";
type ResetCheckState = "idle" | "invalid" | "unactivated";
type ActivationHintKey = "external_account_id" | "poi_id";

interface ActivationCredentials {
  username: string;
  password: string;
  password_confirm: string;
}

interface PasswordCredentials {
  password: string;
  password_confirm: string;
}

interface ActivationFieldHint {
  title: string;
}

const USERNAME_PATTERN = /^[A-Za-z0-9]+$/;

const modeLabels: Record<AuthMode, string> = {
  login: "账号登录",
  activate: "账号激活",
  reset: "重置密码",
};

const activationFieldHints: Record<ActivationHintKey, ActivationFieldHint> = {
  external_account_id: {
    title: "如何获取账户所属ID",
  },
  poi_id: {
    title: "如何获取关联 POI ID",
  },
};

function emptyActivationIdentity(): AccountActivationCheckPayload {
  return {
    external_account_id: "",
    poi_id: "",
  };
}

function emptyActivationCredentials(): ActivationCredentials {
  return {
    username: "",
    password: "",
    password_confirm: "",
  };
}

function emptyPasswordCredentials(): PasswordCredentials {
  return {
    password: "",
    password_confirm: "",
  };
}

export function AuthPage({ initialMode = "login", onAuthenticated }: AuthPageProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [identifier, setIdentifier] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [activationStep, setActivationStep] =
    useState<ActivationStep>("identity");
  const [activationIdentity, setActivationIdentity] =
    useState<AccountActivationCheckPayload>(emptyActivationIdentity);
  const [activationCredentials, setActivationCredentials] =
    useState<ActivationCredentials>(emptyActivationCredentials);
  const [activationCheckState, setActivationCheckState] =
    useState<ActivationCheckState>("idle");
  const [resetStep, setResetStep] = useState<ResetStep>("identity");
  const [resetIdentity, setResetIdentity] =
    useState<AccountActivationCheckPayload>(emptyActivationIdentity);
  const [resetCredentials, setResetCredentials] =
    useState<PasswordCredentials>(emptyPasswordCredentials);
  const [resetCheckState, setResetCheckState] =
    useState<ResetCheckState>("idle");
  const [activeActivationHint, setActiveActivationHint] =
    useState<ActivationHintKey | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const title = useMemo(() => modeLabels[mode], [mode]);
  const activeActivationHintDetail =
    mode !== "login" && activeActivationHint
      ? activationFieldHints[activeActivationHint]
      : null;
  const authShellClassName = [
    "auth-shell",
    mode !== "login" ? "auth-shell--with-help" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const activationIdentityComplete = Boolean(
    activationIdentity.external_account_id.trim() && activationIdentity.poi_id.trim(),
  );
  const trimmedUsername = activationCredentials.username.trim();
  const usernameHasInvalidCharacters = Boolean(
    trimmedUsername && !USERNAME_PATTERN.test(trimmedUsername),
  );
  const activationCredentialsComplete = Boolean(
    trimmedUsername &&
      !usernameHasInvalidCharacters &&
      activationCredentials.password &&
      activationCredentials.password_confirm,
  );
  const resetIdentityComplete = Boolean(
    resetIdentity.external_account_id.trim() && resetIdentity.poi_id.trim(),
  );
  const resetCredentialsComplete = Boolean(
    resetCredentials.password && resetCredentials.password_confirm,
  );

  useEffect(() => {
    setMode(initialMode);
    setMessage("");
    setActiveActivationHint(null);
    setActivationStep("identity");
    setActivationCheckState("idle");
    setActivationCredentials(emptyActivationCredentials());
    setResetStep("identity");
    setResetIdentity(emptyActivationIdentity());
    setResetCredentials(emptyPasswordCredentials());
    setResetCheckState("idle");
  }, [initialMode]);

  const resetActivationFlow = () => {
    setActivationStep("identity");
    setActivationIdentity(emptyActivationIdentity());
    setActivationCredentials(emptyActivationCredentials());
    setActivationCheckState("idle");
    setActiveActivationHint(null);
  };

  const resetPasswordFlow = () => {
    setResetStep("identity");
    setResetIdentity(emptyActivationIdentity());
    setResetCredentials(emptyPasswordCredentials());
    setResetCheckState("idle");
    setActiveActivationHint(null);
  };

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setMessage("");
    resetActivationFlow();
    resetPasswordFlow();
  };

  const setActivationIdentityField = (
    field: keyof AccountActivationCheckPayload,
    value: string,
  ) => {
    setActivationIdentity((current) => ({ ...current, [field]: value }));
    setActivationCheckState("idle");
    setMessage("");
  };

  const setActivationCredentialField = (
    field: keyof ActivationCredentials,
    value: string,
  ) => {
    setActivationCredentials((current) => ({ ...current, [field]: value }));
    setMessage("");
  };

  const setResetIdentityField = (
    field: keyof AccountActivationCheckPayload,
    value: string,
  ) => {
    setResetIdentity((current) => ({ ...current, [field]: value }));
    setResetCheckState("idle");
    setMessage("");
  };

  const setResetCredentialField = (
    field: keyof PasswordCredentials,
    value: string,
  ) => {
    setResetCredentials((current) => ({ ...current, [field]: value }));
    setMessage("");
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

  const handleActivationCheck = async (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    if (!activationIdentityComplete) {
      return;
    }
    setSubmitting(true);
    setMessage("");
    setActivationCheckState("idle");
    try {
      const result = await checkAccountActivationStatus({
        external_account_id: activationIdentity.external_account_id.trim(),
        poi_id: activationIdentity.poi_id.trim(),
      });
      if (result.data.status === "ready") {
        setActivationCredentials(emptyActivationCredentials());
        setActivationStep("credentials");
        setActiveActivationHint(null);
        return;
      }
      if (result.data.status === "activated") {
        setActivationCheckState("activated");
        setMessage("账户已激活过，需要前往账户登录");
        return;
      }
      setActivationCheckState("invalid");
      setMessage("账户所属ID和所属账户关联POI ID不正确");
    } catch {
      setActivationCheckState("invalid");
      setMessage("暂时无法核验激活状态，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleActivationSubmit = async (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    if (!activationCredentialsComplete) {
      if (usernameHasInvalidCharacters) {
        setMessage("账号名只能使用数字和英文字母。");
      }
      return;
    }
    if (
      activationCredentials.password !== activationCredentials.password_confirm
    ) {
      setMessage("两次输入的密码不一致。");
      return;
    }
    setSubmitting(true);
    setMessage("");
    try {
      const payload: AccountActivationPayload = {
        external_account_id: activationIdentity.external_account_id.trim(),
        poi_id: activationIdentity.poi_id.trim(),
        username: trimmedUsername,
        password: activationCredentials.password,
        password_confirm: activationCredentials.password_confirm,
      };
      const result = await initializeAccount(payload);
      resetActivationFlow();
      onAuthenticated(result.data);
    } catch {
      setMessage("账号激活失败，请重新核验门店信息后再试。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleActivationBack = () => {
    setActivationStep("identity");
    setActivationCredentials(emptyActivationCredentials());
    setMessage("");
  };

  const handleResetIdentityCheck = async (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    if (!resetIdentityComplete) {
      return;
    }
    setSubmitting(true);
    setMessage("");
    setResetCheckState("idle");
    try {
      const result = await checkAccountActivationStatus({
        external_account_id: resetIdentity.external_account_id.trim(),
        poi_id: resetIdentity.poi_id.trim(),
      });
      if (result.data.status === "activated") {
        setResetCredentials(emptyPasswordCredentials());
        setResetStep("credentials");
        setActiveActivationHint(null);
        return;
      }
      if (result.data.status === "ready") {
        setResetCheckState("unactivated");
        setMessage("账户尚未激活，请先完成账号激活");
        return;
      }
      setResetCheckState("invalid");
      setMessage("账户所属ID和所属账户关联POI ID不正确");
    } catch {
      setResetCheckState("invalid");
      setMessage("暂时无法核验账户信息，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleResetPassword = async (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    if (!resetCredentialsComplete) {
      return;
    }
    if (resetCredentials.password !== resetCredentials.password_confirm) {
      setMessage("两次输入的密码不一致。");
      return;
    }
    setSubmitting(true);
    setMessage("");
    try {
      const payload: AccountPasswordResetPayload = {
        external_account_id: resetIdentity.external_account_id.trim(),
        poi_id: resetIdentity.poi_id.trim(),
        password: resetCredentials.password,
        password_confirm: resetCredentials.password_confirm,
      };
      const result = await resetAccountPassword(payload);
      resetPasswordFlow();
      onAuthenticated(result.data);
    } catch {
      setMessage("密码重置失败，请重新核验门店信息后再试。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleResetBack = () => {
    setResetStep("identity");
    setResetCredentials(emptyPasswordCredentials());
    setMessage("");
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
            <a href="/login">返回账号登录</a>
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
              <span>账号名、所属账户编号或门店位置编号（POI ID）</span>
              <input
                autoFocus
                autoComplete="username"
                onChange={(event) => setIdentifier(event.target.value)}
                placeholder="输入账号名、所属账户编号或门店位置编号"
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
              <Button loading={submitting} type="submit" variant="primary">
                登录
              </Button>
              <a href="/auth/reset-password">忘记密码</a>
            </div>
          </form>
        ) : mode === "reset" ? (
          resetStep === "identity" ? (
            <form className="auth-form" onSubmit={handleResetIdentityCheck}>
              <div className="filter-field">
                <div className="auth-field-label">
                  <label htmlFor="reset-external-account-id">账户所属ID</label>
                  <IconButton
                    aria-pressed={activeActivationHint === "external_account_id"}
                    className="auth-help-trigger"
                    icon="question"
                    label="查看账户所属ID获取方式"
                    onClick={() => setActiveActivationHint("external_account_id")}
                    size="sm"
                    variant="soft"
                  />
                </div>
                <input
                  autoComplete="off"
                  id="reset-external-account-id"
                  onChange={(event) =>
                    setResetIdentityField("external_account_id", event.target.value)
                  }
                  placeholder="输入导出数据中的账户所属ID"
                  value={resetIdentity.external_account_id}
                />
              </div>
              <div className="filter-field">
                <div className="auth-field-label">
                  <label htmlFor="reset-poi-id">所属账户关联 POI ID</label>
                  <IconButton
                    aria-pressed={activeActivationHint === "poi_id"}
                    className="auth-help-trigger"
                    icon="question"
                    label="查看所属账户关联 POI ID 获取方式"
                    onClick={() => setActiveActivationHint("poi_id")}
                    size="sm"
                    variant="soft"
                  />
                </div>
                <input
                  autoComplete="off"
                  id="reset-poi-id"
                  onChange={(event) =>
                    setResetIdentityField("poi_id", event.target.value)
                  }
                  placeholder="输入导出数据中的所属账户关联 POI ID"
                  value={resetIdentity.poi_id}
                />
              </div>
              {message ? (
                <div
                  className={`auth-check-result auth-check-result--${resetCheckState}`}
                  role="status"
                >
                  <p>{message}</p>
                  {resetCheckState === "unactivated" ? (
                    <Button onClick={() => switchMode("activate")} size="sm" variant="soft">
                      前往账号激活
                    </Button>
                  ) : null}
                </div>
              ) : null}
              <Button
                disabled={!resetIdentityComplete}
                loading={submitting}
                type="submit"
                variant="primary"
              >
                验证账户信息
              </Button>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleResetPassword}>
              <div className="auth-verified-summary">
                <SolarIcon name="check" size={18} />
                <div>
                  <strong>账户信息已核验</strong>
                  <span>请设置新的登录密码。</span>
                </div>
              </div>
              <label className="filter-field">
                <span>新密码</span>
                <input
                  autoComplete="new-password"
                  onChange={(event) =>
                    setResetCredentialField("password", event.target.value)
                  }
                  placeholder="设置新密码"
                  type="password"
                  value={resetCredentials.password}
                />
              </label>
              <label className="filter-field">
                <span>确认密码</span>
                <input
                  autoComplete="new-password"
                  onChange={(event) =>
                    setResetCredentialField("password_confirm", event.target.value)
                  }
                  placeholder="再次输入新密码"
                  type="password"
                  value={resetCredentials.password_confirm}
                />
              </label>
              {message ? <p className="admin-error">{message}</p> : null}
              <div className="auth-activation-submit-row">
                <Button onClick={handleResetBack} variant="soft">
                  返回修改门店信息
                </Button>
                <Button
                  disabled={!resetCredentialsComplete}
                  loading={submitting}
                  type="submit"
                  variant="primary"
                >
                  重置密码
                </Button>
              </div>
            </form>
          )
        ) : activationStep === "identity" ? (
          <form className="auth-form" onSubmit={handleActivationCheck}>
            <div className="filter-field">
              <div className="auth-field-label">
                <label htmlFor="activation-external-account-id">账户所属ID</label>
                <IconButton
                  aria-pressed={activeActivationHint === "external_account_id"}
                  className="auth-help-trigger"
                  icon="question"
                  label="查看账户所属ID获取方式"
                  onClick={() => setActiveActivationHint("external_account_id")}
                  size="sm"
                  variant="soft"
                />
              </div>
              <input
                autoComplete="off"
                id="activation-external-account-id"
                onChange={(event) =>
                  setActivationIdentityField("external_account_id", event.target.value)
                }
                placeholder="输入导出数据中的账户所属ID"
                value={activationIdentity.external_account_id}
              />
            </div>
            <div className="filter-field">
              <div className="auth-field-label">
                <label htmlFor="activation-poi-id">所属账户关联 POI ID</label>
                <IconButton
                  aria-pressed={activeActivationHint === "poi_id"}
                  className="auth-help-trigger"
                  icon="question"
                  label="查看所属账户关联 POI ID 获取方式"
                  onClick={() => setActiveActivationHint("poi_id")}
                  size="sm"
                  variant="soft"
                />
              </div>
              <input
                autoComplete="off"
                id="activation-poi-id"
                onChange={(event) =>
                  setActivationIdentityField("poi_id", event.target.value)
                }
                placeholder="输入导出数据中的所属账户关联 POI ID"
                value={activationIdentity.poi_id}
              />
            </div>
            {message ? (
              <div
                className={`auth-check-result auth-check-result--${activationCheckState}`}
                role="status"
              >
                <p>{message}</p>
                {activationCheckState === "activated" ? (
                  <Button onClick={() => switchMode("login")} size="sm" variant="soft">
                    前往账户登录
                  </Button>
                ) : null}
              </div>
            ) : null}
            <div className="auth-activation-actions">
              <Button
                disabled={!activationIdentityComplete}
                loading={submitting}
                type="submit"
                variant="primary"
              >
                激活状态核验
              </Button>
              <a
                className="auth-guide-link"
                href="/account-activation-guide/index.html"
                rel="noreferrer"
                target="_blank"
              >
                查看账号激活指引
              </a>
            </div>
          </form>
        ) : (
          <form className="auth-form" onSubmit={handleActivationSubmit}>
            <div className="auth-verified-summary">
              <SolarIcon name="check" size={18} />
              <div>
                <strong>门店信息已核验</strong>
                <span>请设置后续登录使用的账号名和密码。</span>
              </div>
            </div>
            <label className="filter-field">
              <span>账号名</span>
              <input
                aria-describedby="activation-username-help activation-username-error"
                aria-invalid={usernameHasInvalidCharacters || undefined}
                autoComplete="username"
                onChange={(event) =>
                  setActivationCredentialField("username", event.target.value)
                }
                placeholder="仅输入数字和英文字母"
                value={activationCredentials.username}
              />
              <small className="auth-field-help" id="activation-username-help">
                只能使用数字和英文字母。
              </small>
              {usernameHasInvalidCharacters ? (
                <small className="auth-field-error" id="activation-username-error" role="alert">
                  账号名只能使用数字和英文字母。
                </small>
              ) : null}
            </label>
            <label className="filter-field">
              <span>密码</span>
              <input
                autoComplete="new-password"
                onChange={(event) =>
                  setActivationCredentialField("password", event.target.value)
                }
                placeholder="设置密码"
                type="password"
                value={activationCredentials.password}
              />
            </label>
            <label className="filter-field">
              <span>确认密码</span>
              <input
                autoComplete="new-password"
                onChange={(event) =>
                  setActivationCredentialField("password_confirm", event.target.value)
                }
                placeholder="再次输入密码"
                type="password"
                value={activationCredentials.password_confirm}
              />
            </label>
            {message ? <p className="admin-error">{message}</p> : null}
            <div className="auth-activation-submit-row">
              <Button onClick={handleActivationBack} variant="soft">
                返回修改门店信息
              </Button>
              <Button
                disabled={!activationCredentialsComplete}
                loading={submitting}
                type="submit"
                variant="primary"
              >
                设置账号并完成激活
              </Button>
            </div>
            <a
              className="auth-guide-link"
              href="/account-activation-guide/index.html"
              rel="noreferrer"
              target="_blank"
            >
              查看账号激活指引
            </a>
          </form>
        )}
      </section>
      {activeActivationHintDetail ? (
        <aside className="auth-help-card" aria-live="polite">
          <p className="auth-help-card__eyebrow">字段来源</p>
          <h2>{activeActivationHintDetail.title}</h2>
          <p>请从同一条认证成功的子机构经营号记录中获取这两个字段。</p>
          <ol>
            <li>进入抖音来客的【店铺管理】-【抖音号管理】-【子机构经营号】。</li>
            <li>若没有子机构经营号，先创建新账号并完成认证。</li>
            <li>
              点击【导出数据】，在对应记录中查看【账户所属id】和【所属账户关联poi_id】。
            </li>
          </ol>
          <a href="/account-activation-guide/index.html" rel="noreferrer" target="_blank">
            查看完整账号激活指引
          </a>
        </aside>
      ) : null}
    </main>
  );
}
