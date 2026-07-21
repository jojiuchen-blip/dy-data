# Agent-first 严格只读 CLI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 交付 `dydata` 只读 CLI，使当前系统用户可在自身实时门店权限范围内查询门店列表和按北京时间统计的线索跟进指标，并让 Agent 通过机器可读命令目录安全发现和调用这些能力。

**Architecture:** 保留现有 Web Cookie 认证链路不变，新增只被白名单 GET 接口接受的 `cli:read` Bearer 令牌。浏览器中的现有用户通过设备授权流程批准 CLI，服务端在每次业务请求时重新读取账号状态和门店范围。线索统计由服务端一次分组聚合并复用当前 `store_display_status`、`is_followed`、`is_follow_success` 口径；CLI 只负责认证、请求、Schema 校验和渲染，不下载明细、不本地重算。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL/SQLite 测试、argparse、httpx、keyring、React 19、TypeScript、pytest。

**Authority:** Linear `DYDATA-40`；确认设计 `docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md`。DYDATA-40 已获单事项治理例外：不得伪造页面交付物或整套 Foundation/PRD；仍须遵守 Linear、TDD、安全和验证门禁。

---

## 全局约束

- 统计单位固定为 `clue_assignment_rounds` 分配轮次，时间字段固定为 `assigned_at`，日期按 `Asia/Shanghai` 自然日解释。
- `system_follow_up_rate = effective_followed_count / total_count`，必须与现有 Web `follow_success_rate` 一致；`action_follow_rate = action_followed_count / total_count`，必须与现有 Web `follow_rate` 一致。
- `pending_count + followed_count + other_status_count = total_count`；比例四舍五入到 4 位；零分母为 `0`；总计先求和分子分母再算比例。
- 用户未指定门店时返回全部实时授权门店；任何一个请求门店越权时整次返回 `SCOPE_DENIED`，不返回部分数据；零数据授权门店仍返回零值行。
- `get_current_user` 继续只接受 Web Session Cookie。CLI Bearer 令牌只能由新的 `get_current_cli_user` 使用，绝不挂到既有写接口。
- CLI 不注册通用 HTTP、SQL、Python、Shell 或任意脚本入口，不返回线索明细、手机号、姓名、订单和备注。
- JSON 模式的 stdout 只包含一个 JSON 文档；日志、浏览器提示和进度只能用于人工登录流程或 stderr。
- 不修改 `.agent/project-manager-suite/`；不修改、暂存或提交用户的 `docs/brd/brd-ledger-clue-center.md` 和 `docs/brd/ledger-state-clue-center.json`。
- 每个任务遵循 Red → Green → Refactor，并在任务完成后做小提交。预期分支：`feature/dydata-40-agent-first-read-only-cli`。

## 契约常量

```python
CLI_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"
METRIC_VERSION = "clue-follow-up-v1"
CLI_SCOPE = "cli:read"
ACCESS_TOKEN_TTL_SECONDS = 30 * 60
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
DEVICE_CODE_TTL_SECONDS = 10 * 60
DEVICE_POLL_INTERVAL_SECONDS = 3
```

成功信封必须保持：

```json
{
  "ok": true,
  "command": "clues.follow-up-stats",
  "schema_version": "1.0",
  "metric_version": "clue-follow-up-v1",
  "scope": {
    "user_id": "user-001",
    "requested_store_ids": [],
    "effective_store_ids": ["store-001"]
  },
  "filters": {
    "assigned_date_start": "2026-07-14",
    "assigned_date_end": "2026-07-20",
    "timezone": "Asia/Shanghai"
  },
  "data": {"stores": [], "totals": {}},
  "meta": {
    "generated_at": "2026-07-21T16:00:00+08:00",
    "data_as_of": "2026-07-21T16:00:00+08:00",
    "source": "postgres",
    "partial": false,
    "request_id": "req_123"
  }
}
```

失败信封和进程退出码固定为：

```python
EXIT_CODES = {
    "INVALID_ARGUMENT": 2,
    "AUTH_REQUIRED": 3,
    "AUTH_EXPIRED": 3,
    "SCOPE_DENIED": 4,
    "API_UNAVAILABLE": 5,
    "RATE_LIMITED": 5,
    "SCHEMA_MISMATCH": 6,
    "INTERNAL_ERROR": 6,
}
```

---

### Task 1: 建立 CLI 设备授权和刷新凭据的数据模型

**Files:**
- Modify: `apps/api/dy_api/models.py`
- Create: `alembic/versions/20260721_0018_add_cli_authorizations.py`
- Modify: `tests/test_alembic_migrations.py`
- Create: `tests/test_cli_auth_models.py`

**Step 1: 写失败的模型测试**

在 `tests/test_cli_auth_models.py` 验证设备码和刷新令牌可持久化、哈希字段唯一、用户外键允许为空以兼容环境最高管理员：

```python
def test_cli_device_authorization_and_refresh_token_persist(db_session):
    grant = CliDeviceAuthorization(
        device_authorization_id="device-1",
        device_code_hash="device-hash",
        user_code_hash="user-hash",
        status="pending",
        scope="cli:read",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db_session.add(grant)
    db_session.commit()
    assert db_session.get(CliDeviceAuthorization, "device-1").status == "pending"
```

运行：

```powershell
python -m pytest tests/test_cli_auth_models.py -q
```

预期：导入 `CliDeviceAuthorization` 失败。

**Step 2: 增加 ORM 模型**

在 `models.py` 增加：

```python
class CliDeviceAuthorization(Base):
    __tablename__ = "cli_device_authorizations"
    device_authorization_id: Mapped[str] = mapped_column(Text, primary_key=True)
    device_code_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    user_code_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scope: Mapped[str] = mapped_column(Text, default="cli:read")
    user_id: Mapped[str | None] = mapped_column(Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    username: Mapped[str | None] = mapped_column(Text)
    auth_type: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CliRefreshToken(Base):
    __tablename__ = "cli_refresh_tokens"
    refresh_token_id: Mapped[str] = mapped_column(Text, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(Text)
    auth_type: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(Text, default="cli:read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    replaced_by_token_id: Mapped[str | None] = mapped_column(Text)
```

**Step 3: 增加可重复执行的 Alembic 迁移**

创建 revision `20260721_0018`，`down_revision = "20260713_0017"`。`upgrade()` 创建两个表及索引；`downgrade()` 先删 refresh 表再删 device 表；使用 `inspect(op.get_bind()).has_table(table_name)` 保护重复执行。

**Step 4: 扩展迁移测试并运行**

```powershell
python -m pytest tests/test_cli_auth_models.py tests/test_alembic_migrations.py -q
```

预期：全部通过。

**Step 5: 提交**

```powershell
git add apps/api/dy_api/models.py alembic/versions/20260721_0018_add_cli_authorizations.py tests/test_cli_auth_models.py tests/test_alembic_migrations.py
git commit -m "feat(cli): add device authorization persistence"
```

---

### Task 2: 实现专用 `cli:read` 令牌和设备授权 API

**Files:**
- Create: `apps/api/dy_api/cli_auth.py`
- Create: `apps/api/dy_api/routes/cli_auth.py`
- Modify: `apps/api/dy_api/main.py`
- Modify: `apps/api/dy_api/schemas.py`
- Create: `tests/test_cli_auth_tokens.py`
- Create: `tests/test_api_cli_auth.py`

**Step 1: 写访问令牌隔离测试**

覆盖以下行为：

测试函数精确命名为 `test_cli_access_token_reloads_current_user_scope`、`test_disabled_user_cli_token_is_rejected`、`test_web_session_dependency_rejects_cli_bearer` 和 `test_cli_dependency_rejects_web_cookie`；每个测试建立自己的账号、门店范围和认证输入，并断言 HTTP 状态及最终 `AuthContext`。

运行：

```powershell
python -m pytest tests/test_cli_auth_tokens.py -q
```

预期：模块不存在。

**Step 2: 实现令牌原语和专用依赖**

`cli_auth.py` 提供七个公开接口：`hash_cli_secret(value: str) -> str`、`create_cli_access_token(auth: AuthContext, *, now: datetime | None = None) -> tuple[str, datetime]`、`verify_cli_access_payload(token: str | None, *, now: datetime | None = None) -> dict[str, Any] | None`、`issue_refresh_token(session: Session, auth: AuthContext, *, now: datetime | None = None) -> tuple[str, CliRefreshToken]`、`rotate_refresh_token(session: Session, raw_token: str, *, now: datetime | None = None) -> tuple[str, str, datetime]`、`revoke_refresh_token(session: Session, raw_token: str) -> None` 和 `get_current_cli_user(request: Request, session=Depends(get_session_dependency)) -> AuthContext`。

访问令牌使用现有 `DY_SESSION_SECRET` HMAC，但 payload 必须带 `typ="cli_access"`、`scope="cli:read"`、`exp` 和随机 `jti`。`get_current_cli_user` 只读 `Authorization: Bearer`，验证后重新查询 `User` 和 `UserStoreScope`；环境管理员则重新检查当前环境管理员配置。它不得替换或扩展 `get_current_user`。

**Step 3: 写设备流程 API 失败测试**

`tests/test_api_cli_auth.py` 使用依赖覆盖注入 SQLite session，验证：

- `POST /api/v1/auth/cli/device/start` 返回原始 device code、一次性 user code、完整浏览器 URL、600 秒和 3 秒轮询间隔。
- 未批准时 `POST /api/v1/auth/cli/device/token` 返回 `202 authorization_pending`。
- 已登录 Web 用户调用 `POST /api/v1/auth/cli/device/approve` 后，轮询一次性返回访问/刷新令牌并把 grant 标记 consumed。
- 第二次消费、过期 code、错误 code 均不签发令牌。
- `POST /api/v1/auth/cli/token/refresh` 轮换 refresh token，旧 token 立即失效。
- 用户停用后 refresh 失败。
- `POST /api/v1/auth/cli/revoke` 撤销凭据且响应中不回显 token。

**Step 4: 实现认证生命周期路由**

路由固定为：

```text
POST /api/v1/auth/cli/device/start
POST /api/v1/auth/cli/device/approve   # Web Cookie required
POST /api/v1/auth/cli/device/token
POST /api/v1/auth/cli/token/refresh
POST /api/v1/auth/cli/revoke
```

设备码和刷新码只以 SHA-256 哈希落库。批准接口把 `AuthContext.user_id/username/auth_type` 写入 grant；消费和轮换在同一事务中完成。响应模型不得包含哈希、数据库 ID 或账号门店历史范围。

**Step 5: 注册路由并运行测试**

在 `main.py`：

```python
app.include_router(cli_auth.router, prefix="/api/v1/auth/cli", tags=["cli-auth"])
```

运行：

```powershell
python -m pytest tests/test_cli_auth_tokens.py tests/test_api_cli_auth.py tests/test_api_auth.py -q
```

预期：全部通过，现有 Web 认证无回归。

**Step 6: 提交**

```powershell
git add apps/api/dy_api/cli_auth.py apps/api/dy_api/routes/cli_auth.py apps/api/dy_api/main.py apps/api/dy_api/schemas.py tests/test_cli_auth_tokens.py tests/test_api_cli_auth.py
git commit -m "feat(cli): add isolated read-only device authorization"
```

---

### Task 3: 抽取并验证按门店线索跟进统计服务

**Files:**
- Modify: `apps/api/dy_api/routes/_data.py`
- Create: `tests/test_clue_store_follow_up_summary.py`
- Modify: `tests/test_api_clues.py`

**Step 1: 写失败的指标测试**

测试数据必须包含：待跟进、已跟进、已发生但未有效、有效跟进、其他状态、跨北京时间边界和零数据门店。核心断言：

```python
assert row["pending_count"] + row["followed_count"] + row["other_status_count"] == row["total_count"]
assert row["system_follow_up_rate"] == round(row["effective_followed_count"] / row["total_count"], 4)
assert row["action_follow_rate"] == round(row["action_followed_count"] / row["total_count"], 4)
```

运行：

```powershell
python -m pytest tests/test_clue_store_follow_up_summary.py -q
```

预期：`DashboardDataStore.clue_store_follow_up_summary` 不存在。

**Step 2: 增加共享聚合方法**

在 `DashboardDataStore` 增加：

```python
def clue_store_follow_up_summary(
    self,
    *,
    store_ids: Sequence[str],
    assigned_date_start: str,
    assigned_date_end: str,
) -> list[dict[str, Any]]:
    """Return stable per-store assignment-round metrics for an inclusive Shanghai date range."""
```

查询必须调用现有 `self._store_display_status_sql(include_round=True)`，并按以下 SQL 形态一次聚合：

```sql
SELECT r.assigned_store_id,
       COUNT(*) AS total_count,
       SUM(CASE WHEN <shared-status-sql> = '待跟进' THEN 1 ELSE 0 END) AS pending_count,
       SUM(CASE WHEN <shared-status-sql> = '已跟进' THEN 1 ELSE 0 END) AS followed_count,
       SUM(CASE WHEN r.is_followed = true THEN 1 ELSE 0 END) AS action_followed_count,
       SUM(CASE WHEN r.is_follow_success = true THEN 1 ELSE 0 END) AS effective_followed_count
FROM clue_assignment_rounds r
JOIN clue_center_orders c ON c.order_id = r.order_id
WHERE r.assigned_store_id IN (:store_0, :store_1)
  AND r.assigned_at >= :assigned_date_start
  AND r.assigned_at < :assigned_date_end_exclusive
GROUP BY r.assigned_store_id
```

Python 层用 `list_stores(store_ids)` 补齐零数据门店、计算 `other_status_count` 和两个 rate，并按 `store_name, store_id` 排序。结束日期复用 `_parse_filter_date_end` 转为次日零点排他边界。

**Step 3: 增加与 overview 的逐店一致性测试**

同一数据、同一门店和日期范围分别调用 `clue_overview` 与新方法：

```python
assert summary["system_follow_up_rate"] == overview["follow_success_rate"]
assert summary["action_follow_rate"] == overview["follow_rate"]
```

**Step 4: 运行指标回归**

```powershell
python -m pytest tests/test_clue_store_follow_up_summary.py tests/test_api_clues.py -q
```

预期：全部通过。

**Step 5: 提交**

```powershell
git add apps/api/dy_api/routes/_data.py tests/test_clue_store_follow_up_summary.py tests/test_api_clues.py
git commit -m "feat(clues): add shared store follow-up aggregation"
```

---

### Task 4: 建立 CLI 白名单 GET API、错误信封和结构化审计

**Files:**
- Create: `apps/api/dy_api/cli_contract.py`
- Create: `apps/api/dy_api/cli_audit.py`
- Create: `apps/api/dy_api/routes/cli.py`
- Modify: `apps/api/dy_api/main.py`
- Modify: `apps/api/dy_api/schemas.py`
- Create: `tests/test_api_cli_readonly.py`
- Create: `tests/test_cli_audit.py`

**Step 1: 写 API 权限和日期失败测试**

覆盖：单门店、多门店、全局账号、请求授权子集、混入越权门店整体 403、零数据门店、默认北京时间最近 7 天、只传日期一端、from > to、超过 366 天、稳定排序和指标信封。

错误响应统一调用：

```python
def cli_error(code: str, message: str, *, command: str, request_id: str, status_code: int):
    raise HTTPException(status_code=status_code, detail={
        "ok": False,
        "command": command,
        "schema_version": "1.0",
        "error": {"code": code, "message": message, "retryable": code in {"API_UNAVAILABLE", "RATE_LIMITED"}, "request_id": request_id},
    })
```

**Step 2: 实现三个白名单 GET 接口**

```text
GET /api/v1/cli/auth/status
GET /api/v1/cli/stores
GET /api/v1/clues/store-follow-up-summary
```

全部依赖 `get_current_cli_user`。汇总参数名保持设计契约：`assigned_date_start`、`assigned_date_end`、可重复 `store_id`。服务端验证日期并从当前 `AuthContext` 重新计算授权门店；客户端值只能缩小范围。

**Step 3: 增加结构化审计中间件**

`CliAuditMiddleware` 仅匹配 `/api/v1/cli/*` 和 `/api/v1/clues/store-follow-up-summary`：

```python
event = {
    "event": "cli_request",
    "request_id": request_id,
    "user_id": getattr(request.state, "cli_user_id", None),
    "auth_type": getattr(request.state, "cli_auth_type", None),
    "cli_version": request.headers.get("x-dydata-cli-version"),
    "command": request.headers.get("x-dydata-command"),
    "schema_version": request.headers.get("x-dydata-schema-version"),
    "date_range": getattr(request.state, "cli_date_range", None),
    "requested_store_ids": getattr(request.state, "cli_requested_store_ids", []),
    "effective_store_ids": getattr(request.state, "cli_effective_store_ids", []),
    "returned_store_count": getattr(request.state, "cli_returned_store_count", 0),
    "result": response.status_code,
    "duration_ms": round((perf_counter() - started) * 1000, 2),
}
```

用 JSON logger 记录上述摘要，并在响应加 `X-Request-ID`；不得记录 Authorization、Cookie、刷新令牌或完整响应。

**Step 4: 写安全负向测试**

用真实 CLI access token 请求已有业务写接口，例如 `POST /api/v1/clues/orders/{id}/follow-up`，断言 401；检查 OpenAPI 和 CLI 路由不存在 POST/PUT/PATCH/DELETE 业务路由；递归检查聚合 JSON 不含 `phone/name/order/note/token` 等明细字段。

**Step 5: 运行 API 与审计测试**

```powershell
python -m pytest tests/test_api_cli_readonly.py tests/test_cli_audit.py tests/test_api_auth.py tests/test_api_clues.py -q
```

预期：全部通过。

**Step 6: 提交**

```powershell
git add apps/api/dy_api/cli_contract.py apps/api/dy_api/cli_audit.py apps/api/dy_api/routes/cli.py apps/api/dy_api/main.py apps/api/dy_api/schemas.py tests/test_api_cli_readonly.py tests/test_cli_audit.py
git commit -m "feat(cli): expose audited read-only data whitelist"
```

---

### Task 5: 增加浏览器设备授权确认页

**Files:**
- Create: `apps/web/src/pages/CliAuthorizePage.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/types/dashboard.ts`
- Modify: `apps/web/src/styles.css`

**Step 1: 先让 TypeScript 引用尚不存在的页面并确认构建失败**

在 `App.tsx` 引入 `CliAuthorizePage` 并为 `/auth/cli/authorize` 预留分支，然后运行：

```powershell
Set-Location apps/web
npm run build
```

预期：模块不存在或类型缺失。

**Step 2: 实现授权 API 客户端**

增加类型：

```typescript
export interface CliAuthorizationApproval {
  user_code: string;
  status: "approved";
  expires_at: string;
}
```

增加客户端：

```typescript
export async function approveCliAuthorization(userCode: string) {
  return sendJson<CliAuthorizationApproval>("/auth/cli/device/approve", {
    body: { user_code: userCode },
  });
}
```

**Step 3: 实现确认页和路由保留**

`CliAuthorizePage` 从 `URLSearchParams` 读取 `user_code`，展示当前账号、一次性验证码、只读范围和“允许此 CLI 读取门店线索汇总”按钮。成功后显示可关闭页面；缺码、过期和已消费显示明确错误，不显示令牌。

修改 `AuthGate.handleAuthenticated`：登录来源是 `/auth/cli/authorize` 时保留当前 URL，不重定向 `/ranking`；其他登录/激活路径保持原行为。已登录用户访问该路径时直接渲染授权页。

**Step 4: 添加最小样式并构建**

```powershell
npm run build
```

预期：`tsc --noEmit` 与 Vite build 通过。

**Step 5: 提交**

```powershell
git add apps/web/src/pages/CliAuthorizePage.tsx apps/web/src/App.tsx apps/web/src/api/client.ts apps/web/src/types/dashboard.ts apps/web/src/styles.css
git commit -m "feat(cli): add browser authorization confirmation"
```

---

### Task 6: 建立 Agent-first CLI 包、命令注册表和文档生成器

**Files:**
- Create: `apps/cli/pyproject.toml`
- Create: `apps/cli/src/dydata_cli/__init__.py`
- Create: `apps/cli/src/dydata_cli/constants.py`
- Create: `apps/cli/src/dydata_cli/registry.py`
- Create: `apps/cli/src/dydata_cli/output.py`
- Create: `apps/cli/src/dydata_cli/parser.py`
- Create: `apps/cli/src/dydata_cli/docs.py`
- Create: `tests/cli/conftest.py`
- Create: `tests/cli/test_registry.py`
- Create: `tests/cli/test_parser.py`
- Create: `tests/cli/test_output.py`

**Step 1: 写命令目录契约测试**

测试精确命令集合：

```python
EXPECTED = {
    "commands", "auth.login", "auth.logout", "auth.status",
    "stores.list", "clues.follow-up-stats", "version",
}
assert {item["command"] for item in command_catalog()} == EXPECTED
```

每个条目必须具备 `command/purpose/parameters/roles/data_scope/side_effect/risk_level/agent_callable/confirmation/output_schema/sensitive_data/examples/errors`。断言只有 `auth.login`、`auth.logout` 不是 Agent 可调用；所有业务命令 `side_effect == "none"`；注册表中不存在 http/sql/shell/script。

**Step 2: 创建可安装包**

`apps/cli/pyproject.toml`：

```toml
[project]
name = "dydata-cli"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27,<1", "keyring>=25,<26"]

[project.scripts]
dydata = "dydata_cli.main:main"

[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"
```

**Step 3: 实现注册表和 argparse**

注册表是唯一命令事实源；parser 的命令树只允许：

```text
commands --json
auth login
auth logout
auth status --json
stores list --json
clues follow-up-stats [--from YYYY-MM-DD --to YYYY-MM-DD] [--store-id ID] [--store-id ID] [--output json|table]
version --json
```

日期预校验要求 from/to 同时出现、from <= to、跨度 <= 366；未传日期时由 CLI 计算北京时间今天及前 6 天，但服务端仍独立重复校验。

**Step 4: 实现稳定 JSON/表格输出**

`emit_json` 使用 `ensure_ascii=False`、确定性 key 顺序和单次 stdout 写入。表格只渲染门店名、总数、待跟进、已跟进、其他、系统跟进率、行为跟进率。错误信封始终输出 JSON 并按固定退出码返回。

**Step 5: 实现文档生成器**

`dydata_cli.docs.render_command_reference()` 从 registry 生成 Markdown 命令表、参数、Schema、错误码和示例。不得在生成器内复制第二份命令列表。

**Step 6: 运行 CLI 基础测试**

```powershell
python -m pip install -e apps/cli
python -m pytest tests/cli/test_registry.py tests/cli/test_parser.py tests/cli/test_output.py -q
dydata commands --json
```

预期：测试通过；最后一条只输出合法 JSON，目录含 7 个命令。

**Step 7: 提交**

```powershell
git add apps/cli tests/cli
git commit -m "feat(cli): add agent-discoverable command shell"
```

---

### Task 7: 实现凭据库、HTTP 客户端和全部命令执行

**Files:**
- Create: `apps/cli/src/dydata_cli/credentials.py`
- Create: `apps/cli/src/dydata_cli/client.py`
- Create: `apps/cli/src/dydata_cli/commands.py`
- Create: `apps/cli/src/dydata_cli/main.py`
- Create: `tests/cli/test_credentials.py`
- Create: `tests/cli/test_client.py`
- Create: `tests/cli/test_commands.py`
- Create: `tests/cli/test_cli_security.py`

**Step 1: 写凭据和 HTTP 失败测试**

覆盖：keyring 保存的是 JSON credential state 且不写磁盘文件；access token 未过期直接使用；过期时用 refresh token 轮换并原子覆盖；轮换失败清理凭据；请求带 CLI/命令/Schema/request-id headers；超时、429、401、403、5xx、Schema 不一致映射为固定错误码。

**Step 2: 实现 OS 凭据库封装**

`CredentialStore` 固定 `service = "dydata-cli"`、`account = "default"`，公开 `load() -> CredentialState | None`、`save(state: CredentialState) -> None` 和 `clear() -> None` 三个方法。

只使用 `keyring.get_password/set_password/delete_password`。不得回显或记录 credential state。

**Step 3: 实现严格 API 客户端**

基础 URL 来自 `DYDATA_API_URL`，默认 `http://127.0.0.1:8000/api/v1`。客户端只暴露显式方法：

`DyDataClient` 只公开 `start_device_authorization() -> dict`、`poll_device_token(device_code: str) -> dict`、`refresh(refresh_token: str) -> dict`、`revoke(refresh_token: str) -> None`、`auth_status(access_token: str) -> dict`、`list_stores(access_token: str) -> dict` 和 `follow_up_stats(access_token: str, *, date_from: date, date_to: date, store_ids: list[str]) -> dict`。

禁止暴露 `request(method, path)` 之类公共通用入口。成功响应必须检查 `schema_version == "1.0"` 和 `ok is True`。

**Step 4: 实现人工登录和安全退出**

`auth login` 启动 device flow，打印 URL/code，调用 `webbrowser.open`，按服务端 interval 轮询，成功后将 access/refresh 凭据写入 keyring。`auth logout` 尽力服务端 revoke，无论网络结果都清理本地凭据；两者都不得打印 token。

**Step 5: 实现 Agent 可调用命令**

- `auth status --json`：返回用户 ID、用户名、角色、当前门店范围和过期时间，不返回 token。
- `stores list --json`：转发服务端白名单响应。
- `clues follow-up-stats`：传递日期/门店，JSON 模式原样输出版本化业务信封；table 模式只渲染聚合列。
- `commands --json`、`version --json`：完全离线，不读取凭据、不访问网络。

**Step 6: 安全和 stdout 测试**

断言所有 JSON 命令 stdout 可直接 `json.loads`；stderr/日志不混入 stdout；任何输出和异常文本不含测试 token；命令 parser 拒绝未知子命令；客户端公开方法中不存在任意 method/path；未登录返回 `AUTH_REQUIRED`/exit 3。

**Step 7: 运行 CLI 测试**

```powershell
python -m pytest tests/cli -q
```

预期：全部通过。

**Step 8: 提交**

```powershell
git add apps/cli/src/dydata_cli tests/cli
git commit -m "feat(cli): implement secure read-only command execution"
```

---

### Task 8: 生成 Agent 文档并建立文档漂移门禁

**Files:**
- Create: `docs/cli-agent-guide.md`
- Create: `docs/cli-command-reference.md`
- Create: `scripts/generate_cli_docs.py`
- Create: `tests/cli/test_docs.py`
- Modify: `README.md`

**Step 1: 写文档一致性失败测试**

```python
def test_command_reference_matches_registry():
    expected = render_command_reference()
    actual = (ROOT / "docs/cli-command-reference.md").read_text(encoding="utf-8")
    assert actual == expected
```

再断言 Agent 指南明确写出：先 `commands --json`、人工登录、实时权限、两个跟进率差异、全成全败、错误/退出码处理、不自动扩大门店范围、不处理凭据。

**Step 2: 增加生成脚本**

`scripts/generate_cli_docs.py --check` 仅比较并非零退出；无 `--check` 时把 registry 渲染结果写入 `docs/cli-command-reference.md`。脚本把 `apps/cli/src` 加入 `sys.path`，无需先安装包。

**Step 3: 写 Agent 指南**

指南包含安全调用顺序：

```powershell
dydata commands --json
dydata auth status --json
dydata stores list --json
dydata clues follow-up-stats --from 2026-07-14 --to 2026-07-20 --output json
```

并解释 `system_follow_up_rate` 是默认对外指标，`action_follow_rate` 仅用于“是否联系过”与差异解释；任何错误都不得伪造、补全或跨门店重试。

**Step 4: 生成命令参考并更新 README**

```powershell
python scripts/generate_cli_docs.py
python scripts/generate_cli_docs.py --check
```

README 只增加 CLI 安装入口、两份文档链接和 `commands --json` 权威性说明，不复制完整命令列表。

**Step 5: 运行文档测试并提交**

```powershell
python -m pytest tests/cli/test_docs.py -q
git add docs/cli-agent-guide.md docs/cli-command-reference.md scripts/generate_cli_docs.py tests/cli/test_docs.py README.md
git commit -m "docs(cli): publish agent guide and generated command reference"
```

---

### Task 9: 端到端验收、安全回归和交付写回

**Files:**
- Modify: `docs/superpowers/plans/2026-07-21-agent-first-read-only-cli-implementation.md`（仅勾验收记录，不改变契约）
- Linear: `DYDATA-40`

**Step 1: 运行完整后端测试**

```powershell
python -m pytest -q
```

预期：全部通过；只允许已有且已记录的 warning，不允许新失败。

**Step 2: 运行 Web 构建**

```powershell
Set-Location apps/web
npm run build
Set-Location ../..
```

预期：TypeScript 和 Vite build 通过。

**Step 3: 运行 CLI 安装与离线 smoke**

```powershell
python -m pip install -e apps/cli
dydata version --json
dydata commands --json
python scripts/generate_cli_docs.py --check
```

预期：三个 JSON/检查命令均为 exit 0；版本为 `0.1.0`，Schema 为 `1.0`。

**Step 4: 运行敏感信息和命令面扫描**

```powershell
rg -n "(access_token|refresh_token|Authorization: Bearer)" docs apps/cli -g "*.md" -g "*.py"
rg -n "(shell|sql|arbitrary|generic.*http)" apps/cli/src tests/cli
```

预期：第一条只命中字段名/防泄露说明，不出现真实 token；第二条只命中负向测试或安全说明，不存在可调用入口。

**Step 5: 运行差异和仓库卫生检查**

```powershell
git diff --check
git status --short
git diff --stat HEAD~8..HEAD
```

预期：无空白错误；只出现 DYDATA-40 文件和用户原有两份未跟踪 BRD 台账，台账未被暂存。

**Step 6: 重新运行治理工具**

```powershell
node .agent/project-manager-suite/tools/validate-global-files.mjs . --json
node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S3 --json
```

预期：全局文件校验 0 error；route-check 仍可能报告页面型 Foundation/PRD 缺失，按 DYDATA-40 已批准的单事项例外记录，不伪造产物。读取并执行所有 `companionActions`；如索引器把用户未跟踪台账写入生成索引，只还原本轮生成的 `docs/index/*` 变更。

**Step 7: Linear 写回**

在 DYDATA-40 评论中写入：实现提交、测试数量、Web build、CLI smoke、已验证的只读隔离、已知非阻断项。只有全部验收通过才把 issue 改为 Done；否则保持 In Progress 并记录具体失败。

**Step 8: 最终提交（仅当验收记录产生文件变化）**

```powershell
git add docs/superpowers/plans/2026-07-21-agent-first-read-only-cli-implementation.md
git commit -m "chore(cli): record DYDATA-40 verification"
```

---

## 计划自检清单

- [ ] 设计第 3 节全部首版范围均映射到 Task 2–8。
- [ ] 设计第 7 节 7 个命令与 registry 测试精确一致。
- [ ] 设计第 9 节成功信封、统计公式、排序、零数据门店和全成全败均有测试。
- [ ] 设计第 10 节 30 分钟 access、30 天 refresh、轮换、实时权限重算均有实现步骤。
- [ ] 设计第 11 节 Bearer 与 Web Cookie 写接口隔离有负向测试。
- [ ] 设计第 12 节审计字段、错误码、退出码均有单一常量和测试。
- [ ] `docs/cli-command-reference.md` 由 registry 生成并有 `--check` 门禁。
- [ ] 没有 TBD、TODO、伪代码占位符、未命名的“相关文件”或“类似实现”。
- [ ] 所有新增 API、CLI 方法、模型字段和测试引用的名称一致。
- [ ] 用户未跟踪的两份线索中心台账未修改、未暂存、未提交。
