# Agent-first 严格只读 CLI：门店线索跟进统计设计

- 日期：2026-07-21
- 状态：已确认
- 首版业务域：线索管理
- 首版主要调用方：Agent
- 业务数据权限：继承当前系统用户的角色、组织和门店范围
- 业务副作用：无

## 1. 背景与目标

项目已经在 [项目级 BRD](../../brd/BRD-dy-data-20260716-1255.md) 和
[项目画像](../../../project-profile.md) 中确认 CLI / Agent 接入属于项目范围：全部已授权系统用户均可使用，CLI 继承账号的数据权限，但渠道始终严格只读。

首版不追求覆盖所有业务模块，而是先完成一条可验证、可被 Agent 稳定调用的线索统计闭环：

1. 识别当前账号以及账号可访问的一个或多个门店。
2. 按北京时间日期范围统计每家门店的线索跟进情况。
3. 返回待跟进、已跟进、其他状态、系统跟进率和行为跟进率。
4. 保证 CLI 结果与现有 Web 系统口径一致。
5. 让 Agent 能通过机器可读的命令目录理解有哪些命令、命令能做什么、权限边界是什么以及返回值如何解释。

本设计只定义产品和技术契约，不是实现计划，也不授权进入业务代码开发。

## 2. 已确认决策

| 决策项 | 结论 |
| --- | --- |
| 使用模式 | Agent-first；JSON 和机器可发现性优先 |
| 调用身份 | 使用当前用户的独立身份，不使用门店共享账号或全局 Agent 账号 |
| 首版业务域 | 线索管理，不同时扩展结算、订单和经营看板 |
| 首版任务 | 查看账号门店范围以及各门店线索跟进统计 |
| 时间口径 | 按现有系统的 `assigned_at` 统计，使用北京时间自然日 |
| 指标口径 | 页面口径为主，同时返回行为跟进率，避免把“发生过跟进”和“有效跟进”混为一谈 |
| 技术路线 | 新增服务端按门店聚合的只读 API；CLI 不拉取明细后本地计算 |
| 只读边界 | CLI 命令白名单与服务端 `cli:read` 令牌双重强制 |
| 命令发现 | `dydata commands --json` 是运行时权威命令目录 |
| 文档 | Agent 使用指南与命令参考必须和 CLI 同版本发布 |

## 3. 范围

### 3.1 首版包含

- 用户完成 CLI 身份授权。
- 查询当前账号信息和认证状态。
- 查询当前账号可访问的门店列表。
- 查询全部授权门店或指定授权门店的线索跟进统计。
- JSON 和基础表格输出。
- 版本化命令目录、输出 Schema、错误码和 Agent 文档。
- 服务端权限校验、只读限制和调用审计。

### 3.2 首版不包含

- 新增、修改、分配、跟进、删除或重新分配线索。
- 调用同步、审批、任务或其他会改变业务状态的能力。
- 线索明细、手机号、客户姓名、订单明细或跟进备注。
- CSV 或 Excel 导出。
- CLI 内部的自然语言理解；自然语言由上层 Agent 处理。
- 结算、订单、经营看板和后台管理命令。
- 任意 HTTP、SQL 或脚本执行入口。

## 4. 用户场景与成功结果

首版必须支持 Agent 回答以下问题：

- “我能查看哪些门店？”
- “最近 7 天各门店有多少待跟进和已跟进线索？”
- “各门店的系统跟进率是多少？”
- “哪个门店的系统跟进率最低？”
- “为什么已发生跟进的数量和系统跟进率的分子不一样？”

成功结果不是让 Agent 拥有新的业务权限，而是让 Agent 在当前用户权限范围内，稳定取得与 Web 一致的结构化统计，并准确解释指标。

## 5. 架构

```text
Agent
  ↓
dydata 只读命令白名单
  ↓
用户认证与 HTTP 客户端
  ↓
GET /api/v1/clues/store-follow-up-summary
  ↓
现有账号权限 + 共享指标计算服务
  ↓
PostgreSQL
```

禁止以下链路：

```text
Agent → PostgreSQL
Agent → worker 脚本
Agent → 任意业务 API
CLI → 本地下载线索明细后重新计算指标
```

## 6. 组件边界

### 6.1 命令注册层

命令注册层是 CLI 能力白名单的唯一来源。每个命令必须声明名称、用途、参数、允许角色、数据范围、副作用、风险等级、是否允许 Agent 调用、输出 Schema、错误码和安全示例。

不得通过隐藏参数、调试参数或通用请求命令绕过白名单。

### 6.2 认证层

认证层负责人工授权、令牌刷新和本地安全存储。它只向业务命令提供可用的短期访问令牌，不向 Agent、标准输出或日志暴露凭据。

### 6.3 HTTP 客户端

HTTP 客户端负责基础地址、超时、重试、请求 ID、Schema 版本检查和错误标准化。它不包含线索指标计算逻辑。

### 6.4 汇总 API

新增 `GET /api/v1/clues/store-follow-up-summary`。接口在一次请求中返回当前账号实际可见的所有目标门店及汇总结果，避免 CLI 逐店发起 N+1 请求。

### 6.5 指标计算服务

指标计算服务复用现有线索过滤、门店权限和跟进状态定义。现有实现依据包括：

- [线索路由和账号门店范围](../../../apps/api/dy_api/routes/clues.py)
- [线索过滤与 overview 指标计算](../../../apps/api/dy_api/routes/_data.py)
- [Web 页面展示的系统跟进率](../../../apps/web/src/pages/ClueCenterPage.tsx)
- [跟进行为和有效跟进状态](../../../apps/worker/clue_follow_up_state.py)

Web 页面和 CLI 不得分别维护两套公式。新接口应调用共享指标函数或共享查询构造器。

### 6.6 输出与审计层

输出层只负责把已计算结果渲染为版本化 JSON 或基础表格。审计层记录调用主体、有效范围、过滤条件和执行状态，不记录令牌或完整业务结果。

## 7. CLI 命令契约

### 7.1 首版命令

| 命令 | 用途 | Agent 可调用 | 业务副作用 |
| --- | --- | --- | --- |
| `dydata commands --json` | 获取命令和契约目录 | 是 | 无 |
| `dydata auth login` | 用户通过浏览器完成身份授权 | 否，必须人工执行 | 无业务副作用 |
| `dydata auth logout` | 撤销刷新凭据并清理本地认证信息 | 否，必须人工执行 | 无业务副作用 |
| `dydata auth status --json` | 查看当前用户和认证状态，不返回令牌 | 是 | 无 |
| `dydata stores list --json` | 获取当前账号可见门店 | 是 | 无 |
| `dydata clues follow-up-stats` | 获取门店线索跟进统计 | 是 | 无 |
| `dydata version --json` | 获取 CLI 和契约版本 | 是 | 无 |

### 7.2 核心命令

```powershell
dydata clues follow-up-stats `
  --from 2026-07-14 `
  --to 2026-07-20 `
  --output json
```

参数规则：

- 不传 `--from` 和 `--to` 时，查询包含当天在内的最近 7 个北京时间自然日。
- 必须同时传入 `--from` 和 `--to`，不接受只传一端。
- `--from` 和 `--to` 均包含当天；服务端内部可把结束日转换为下一日零点的排他边界。
- 单次查询最长 366 个自然日。
- `--store-id` 可重复使用。
- 不传 `--store-id` 时返回当前账号可见的全部门店。
- 请求列表中只要包含一个无权访问的门店，整个请求返回 `SCOPE_DENIED`，不返回部分结果。
- Agent 默认使用 `--output json`；人工可使用 `--output table`。
- JSON 模式不发起交互式提问，不向标准输出写日志、提示语或进度动画。

## 8. 命令发现与文档

### 8.1 运行时权威来源

`dydata commands --json` 从命令注册层生成，至少返回：

- `command`
- `purpose`
- `parameters`
- `roles`
- `data_scope`
- `side_effect`
- `risk_level`
- `agent_callable`
- `confirmation`
- `output_schema`
- `sensitive_data`
- `examples`
- `errors`

Agent 应先读取命令目录，再决定是否调用业务命令。

### 8.2 文档交付

首版必须同步交付：

- `docs/cli-agent-guide.md`：认证、安全边界、Agent 调用流程、典型问题和安全示例。
- `docs/cli-command-reference.md`：完整命令、参数、字段、退出码、错误码和示例。

命令参考必须由命令注册信息生成，或由 CI 校验与命令注册信息完全一致。手写文档不得成为独立的命令事实来源。

## 9. 汇总 API 契约

### 9.1 请求

```http
GET /api/v1/clues/store-follow-up-summary
    ?assigned_date_start=2026-07-14
    &assigned_date_end=2026-07-20
    &store_id=store-001
    &store_id=store-002
```

服务端从认证主体重新取得当前角色、账号状态和门店权限。客户端提交的门店 ID 只能缩小范围，不能扩大权限。

### 9.2 成功响应

```json
{
  "ok": true,
  "command": "clues.follow-up-stats",
  "schema_version": "1.0",
  "metric_version": "clue-follow-up-v1",
  "scope": {
    "user_id": "user-001",
    "requested_store_ids": [],
    "effective_store_ids": ["store-001", "store-002"]
  },
  "filters": {
    "assigned_date_start": "2026-07-14",
    "assigned_date_end": "2026-07-20",
    "timezone": "Asia/Shanghai"
  },
  "data": {
    "stores": [
      {
        "store_id": "store-001",
        "store_name": "上海一店",
        "total_count": 120,
        "pending_count": 30,
        "followed_count": 70,
        "other_status_count": 20,
        "action_followed_count": 90,
        "effective_followed_count": 82,
        "system_follow_up_rate": 0.6833,
        "action_follow_rate": 0.75
      }
    ],
    "totals": {
      "total_count": 120,
      "pending_count": 30,
      "followed_count": 70,
      "other_status_count": 20,
      "action_followed_count": 90,
      "effective_followed_count": 82,
      "system_follow_up_rate": 0.6833,
      "action_follow_rate": 0.75
    }
  },
  "meta": {
    "generated_at": "2026-07-21T16:00:00+08:00",
    "data_as_of": "2026-07-21T15:58:00+08:00",
    "source": "postgres",
    "partial": false,
    "request_id": "req_123"
  }
}
```

返回顺序按 `store_name`、`store_id` 稳定排序。当前账号可见但没有匹配数据的门店仍必须返回，全部指标为 `0`。

### 9.3 统计单位和公式

首版沿用当前 API 的真实实现，以匹配过滤条件的 `clue_assignment_rounds` 分配轮次为统计单位，不改成唯一订单数或唯一客户数。

| 字段 | 公式或语义 |
| --- | --- |
| `total_count` | 时间范围内分配给该门店的全部匹配轮次 |
| `pending_count` | `store_display_status = 待跟进` |
| `followed_count` | `store_display_status = 已跟进` |
| `other_status_count` | 已核销、已退款、超期、战败、换门店和不可跟进等其他状态 |
| `action_followed_count` | `is_followed = true` |
| `effective_followed_count` | `is_follow_success = true` |
| `system_follow_up_rate` | `effective_followed_count / total_count`，与当前 Web 页面一致 |
| `action_follow_rate` | `action_followed_count / total_count`，与现有 API 的 `follow_rate` 一致 |

必须满足：

```text
pending_count + followed_count + other_status_count = total_count
```

比例保留四位小数。分母为零时返回 `0`。账号总计必须先汇总各门店分子和分母再计算，禁止取各门店比例的算术平均值。

Agent 默认向用户展示 `system_follow_up_rate`。只有当用户询问“是否联系过”或要求解释差异时，才使用 `action_follow_rate`。

## 10. 认证设计

### 10.1 登录流程

1. 用户人工执行 `dydata auth login`。
2. CLI 显示登录地址和一次性验证码。
3. 用户在浏览器中使用现有系统账号完成认证和授权。
4. 服务端签发限定为 `cli:read` 的用户访问令牌和可撤销刷新凭据。
5. CLI 将刷新凭据写入操作系统凭据库。
6. 后续业务命令在访问令牌过期前自动刷新，不要求 Agent 接触凭据。

访问令牌有效期为 30 分钟；刷新凭据有效期为 30 天，并在每次使用后轮换。账号停用、权限变更、主动退出或服务端撤销后，旧刷新凭据不可继续使用。

### 10.2 权限求值

令牌只证明调用者身份和 `cli:read` 授权。服务端每次请求都从当前账号数据重新求值角色、组织范围和门店范围，令牌内的历史范围不得作为最终权限来源。

## 11. 严格只读与敏感数据保护

只读边界采用双重强制：

1. CLI 只注册批准的只读业务命令。
2. 服务端 CLI 令牌只能访问专用白名单中的只读业务接口。

登录、刷新和退出认证接口是认证生命周期所需的例外，但不能修改业务数据。即使用户在 Web 端拥有管理员写权限，`cli:read` 令牌也不得访问业务 POST、PUT、PATCH 或 DELETE 接口。

首版汇总接口只返回门店标识和聚合指标，不返回手机号、姓名、订单、备注或其他线索明细。令牌不得出现在命令参数、标准输出、错误消息、审计日志或文档示例中。

## 12. 审计与错误处理

### 12.1 服务端审计字段

- `request_id`
- 用户 ID 和认证类型
- CLI 版本、命令名称和 Schema 版本
- 查询日期范围
- 请求门店和实际生效门店
- 返回门店数量
- 成功状态或错误码
- 执行耗时

审计不记录令牌、完整响应或敏感线索数据。

### 12.2 错误信封

```json
{
  "ok": false,
  "command": "clues.follow-up-stats",
  "schema_version": "1.0",
  "error": {
    "code": "SCOPE_DENIED",
    "message": "请求的门店不在当前账号权限范围内",
    "retryable": false,
    "request_id": "req_123"
  }
}
```

首版错误码：

- `INVALID_ARGUMENT`
- `AUTH_REQUIRED`
- `AUTH_EXPIRED`
- `SCOPE_DENIED`
- `API_UNAVAILABLE`
- `RATE_LIMITED`
- `SCHEMA_MISMATCH`
- `INTERNAL_ERROR`

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `2` | 参数错误 |
| `3` | 未认证或认证过期 |
| `4` | 权限范围错误 |
| `5` | 网络、限流或服务不可用 |
| `6` | Schema 不兼容或内部错误 |

一次汇总请求全成全败。任何门店查询失败时不返回部分统计，也不把不完整结果标记为成功。网络和限流错误可按退避策略重试；参数、认证、权限和 Schema 错误不可盲目重试。

## 13. 测试与验收

### 13.1 指标单元测试

- 零分母返回 `0`。
- 待跟进、已跟进和其他状态之和等于总数。
- 任意跟进行为和有效跟进分别进入正确分子。
- 比例保留四位小数。
- 总计由汇总分子和分母重新计算。

### 13.2 API 集成测试

- 单门店账号只能看到授权门店。
- 多门店账号返回全部授权门店。
- 零数据授权门店仍返回零值行。
- 指定部分授权门店时只返回请求范围。
- 请求包含越权门店时整体返回 `SCOPE_DENIED`。
- 日期使用北京时间自然日且首尾日期均包含。

### 13.3 口径一致性测试

对同一账号、门店和日期范围逐店比较：

- 新接口 `system_follow_up_rate` 等于现有 `/clues/overview` 的 `follow_success_rate`。
- 新接口 `action_follow_rate` 等于现有 `/clues/overview` 的 `follow_rate`。

### 13.4 CLI 契约测试

- 参数默认值、互斥关系和最长日期范围。
- JSON Schema、字段类型、稳定排序和退出码。
- JSON 标准输出中没有日志、提示语或动画。
- 表格输出不改变 JSON 契约。
- `commands --json` 与实际命令注册一致。

### 13.5 安全负向测试

- `cli:read` 令牌不能访问业务 POST、PUT、PATCH 和 DELETE 接口。
- 不存在通用 HTTP、SQL 或脚本执行命令。
- 认证状态、日志、错误和审计均不泄露令牌。
- 聚合响应不包含线索级敏感字段。

### 13.6 Agent 场景测试

- Agent 能先发现命令，再查询账号门店范围。
- Agent 能查询最近 7 天全部授权门店统计。
- Agent 能根据返回结果找出系统跟进率最低的门店。
- Agent 能准确解释系统跟进率与行为跟进率的差异。
- Agent 面对权限、认证和服务错误时不会伪造数据或自动扩大范围。

## 14. 发布策略

1. 抽取共享指标计算服务并建立按门店汇总 API。
2. 在测试环境将新接口与现有 overview 逐店做影子比对。
3. 完成用户授权、CLI 主命令、命令发现和文档。
4. 使用单门店、多门店和全局权限测试账号完成验收。
5. 面向全部授权用户开放只读能力。
6. 持续监控认证失败率、接口错误率、响应耗时和 Schema 不匹配。

灰度只控制可用用户范围，不扩大任何用户的数据权限或 CLI 能力范围。

## 15. 风险与控制

| 风险 | 控制 |
| --- | --- |
| CLI 与 Web 指标漂移 | 使用共享指标服务并增加逐店一致性测试 |
| 多门店逐店请求导致慢或部分失败 | 使用单次服务端分组汇总，不在 CLI 中 N+1 调用 |
| 管理员令牌被用于写操作 | 使用独立 `cli:read` scope 和服务端接口白名单 |
| Agent 不知道命令或误解参数 | 提供版本化 `commands --json` 和同步文档 |
| 门店权限变更后令牌范围过期 | 每次请求从当前账号数据重新求值权限 |
| 统计字段无法相互核对 | 返回其他状态数量、两类分子和两类比例 |
| 部分结果被误认为完整结果 | 聚合请求全成全败，成功响应固定 `partial: false` |

## 16. 后续交接

本设计经用户复核后，下一步才进入正式实施计划。实施计划需要把工作拆分为认证、共享指标服务、汇总 API、CLI 基础设施、命令发现、文档和测试等可独立验收任务，并遵守项目的 Linear 和开发门禁。
