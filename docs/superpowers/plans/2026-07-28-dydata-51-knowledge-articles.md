# DYDATA-51 Knowledge Articles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出四篇可直接复制到公司知识库的中文 Markdown 文章，帮助产品、运营和初级开发完成抖音数据获取，并理解以 Linear 为载体的开发协作流程。

**Architecture:** 四篇文章分别保存在 `docs/knowledge-sharing/`，每篇只解决一个核心问题并可独立阅读。抖音主题以当期官方文档为平台事实源、以当前仓库代码为项目实践源；Linear 主题以官方文档、团队文档和 `AGENTS.md` 为依据。每篇独立撰写、验证和提交，最后统一做交叉链接、术语、脱敏和 Markdown 检查。

**Tech Stack:** Markdown、Mermaid、抖音开放平台官方文档、Linear 官方文档、Linear 团队文档、PowerShell、ripgrep、pytest

## Global Constraints

- Linear 权威事项：`DYDATA-51`；当前状态为 `In Progress`，负责人为 `jiu chen`。
- 设计依据：`docs/superpowers/specs/2026-07-28-dydata-51-knowledge-articles-design.md`。
- 目标读者固定为产品、运营和初级开发。
- 第一、三、四篇控制在 1800—3000 个中文字符附近；第二篇可放宽至 3500 个中文字符以内。
- 每篇采用“场景问题 → 流程图 → 准备清单 → 分步操作 → 常见问题 → 完成检查表”的阅读顺序。
- 正文少代码、多解释；代码只保留完成操作所需的最小示例。
- 平台通用规则与本项目实践必须分别标注，不能把仓库实现写成抖音或 Linear 的通用规定。
- 不写完整分页、补拉、前后端联调、数据口径、质量门禁、Git 分支交接或技术文章写法。
- 不深入讲 FastAPI、React、pytest、Docker 或 CI。
- 示例只使用 `APP_ID_EXAMPLE`、`APP_SECRET_EXAMPLE`、`ACCOUNT_ID_EXAMPLE`、`TOKEN_EXAMPLE`、`DYDEMO-101` 和虚构业务数据。
- 禁止出现真实凭据、Cookie、账号、手机号、客户信息、生产域名、数据库地址、内部绝对路径和原始导出数据。
- 无法从官方资料、当前代码、团队文档或用户确认中验证的菜单名、按钮名、权限名和字段名不得编造。
- 当前工作树中存在其他协作者的未提交改动；每次只暂存本计划明确列出的文章文件。

---

## File Map

| 文件 | 职责 |
| --- | --- |
| `docs/knowledge-sharing/01-douyin-open-api-first-request.md` | 解释准备、凭证、Token 和第一次 API 请求 |
| `docs/knowledge-sharing/02-douyin-data-acquisition-options.md` | 对比开放平台 API 与来客后台导出，并指导跑出一批数据 |
| `docs/knowledge-sharing/03-linear-development-collaboration.md` | 解释 Linear 为什么适合作为开发协作和统一需求池 |
| `docs/knowledge-sharing/04-linear-issue-lifecycle.md` | 用一个虚构需求演示定义、分工、推进和验收 |

四个文件之间只通过相对链接建立导航，不新增第二份需求、流程或状态权威源。

---

### Task 1: 撰写“从零跑通抖音开放平台 API”

**Files:**
- Create: `docs/knowledge-sharing/01-douyin-open-api-first-request.md`
- Read: `docs/superpowers/specs/2026-07-28-dydata-51-knowledge-articles-design.md:65`
- Read: `src/dy_data/douyin_client.py:12`
- Read: `src/dy_data/config.py:178`
- Read: `docs/runbook.md:1`

**Interfaces:**
- Consumes: 抖音开放平台当期认证规则、仓库中的 Token 请求和请求头实现、设计文档第四节。
- Produces: 第一篇独立文章；第二篇通过 `./01-douyin-open-api-first-request.md` 引用完整认证说明。

- [ ] **Step 1: 核对抖音开放平台认证事实**

逐页读取并记录发布日期或当前可见内容：

- `https://open.douyin.com/platform/resource/docs/accession-guide/platform-accession/`
- `https://open.douyin.com/platform/resource/docs/accession-guide/type-and-permission`
- `https://open.douyin.com/platform/resource/docs/openapi/account-permission/client-token/`
- `https://open.douyin.com/platform/resource/docs/develop/common-tools/status-code`

必须确认：

- `client_token` 的用途与用户授权 Token 的区别。
- Token 请求地址、当前要求的请求方式和请求体格式。
- Token 有效期和重复获取的影响。
- 无权限、参数错误、Token 失效对应的官方解释。

如果官方请求格式与 `src/dy_data/douyin_client.py` 的 JSON 封装不一致，正文使用两个明确小标题：

- “抖音开放平台当前文档的请求要求”
- “本项目客户端的封装方式”

不得用其中一方覆盖另一方。

- [ ] **Step 2: 核对项目认证实现和脱敏行为**

Run:

```powershell
rg -n "TOKEN_URL|get_client_token|client_key|client_secret|access-token|Rpc-Transit-Life-Account|\\[redacted\\]" src/dy_data/douyin_client.py src/dy_data/config.py
```

Expected:

- 找到 `TOKEN_URL`、`get_client_token()`、`douyin_headers()` 和敏感值替换逻辑。
- 找到 `DOUYIN_APP_SECRET`、`DOUYIN_ACCOUNT_ID` 的配置读取位置。

- [ ] **Step 3: 创建文章并按固定结构写完正文**

Create `docs/knowledge-sharing/01-douyin-open-api-first-request.md` with these exact top-level sections:

```markdown
# 从零跑通抖音开放平台 API：准备、Token 与第一次请求

> 适合谁：第一次接触抖音开放平台 API 的产品、运营和初级开发。
>
> 读完能做什么：分清应用凭证和账号信息，获取一次 Token，完成一次小范围请求，并判断结果是否成功。

## 先看全流程
## 第一次调用前，需要准备什么
## 四个容易混淆的字段
## 第一步：安全保存应用凭证
## 第二步：获取 client_token
## 第三步：携带 Token 发起业务请求
## 怎样判断接口真的跑通了
## 常见问题
## 完成检查表
## 进阶实践：在项目中安全复用 Token
## 参考资料
```

正文必须包含：

- 一张不超过六个节点的 Mermaid 流程图。
- `app_id`、`app_secret`、`account_id`、`access_token` 四列表格。
- 一段最小 Token 请求示例，示例值全部使用全局约束中的安全值。
- 一段最小业务请求示例；如果接口权限或路径不能确认，使用“示意请求”标签，不声称可直接复制运行。
- 一段脱敏响应示例，只保留错误码、描述、有效期和数据列表等教学字段。
- “HTTP 请求成功不等于业务成功”的三层判断：HTTP 状态、业务错误码、目标数据。
- `> 截图建议：开放平台应用详情中的凭证与权限区域；发布前遮盖全部真实值。`
- 一份可勾选的完成检查表。
- 参考资料使用可点击的官方链接，并标注项目文件只代表“本项目实践”。

- [ ] **Step 4: 检查第一篇的范围和敏感信息**

Run:

```powershell
$file = 'docs/knowledge-sharing/01-douyin-open-api-first-request.md'
rg -n "^# |^## |^```mermaid$|APP_ID_EXAMPLE|APP_SECRET_EXAMPLE|ACCOUNT_ID_EXAMPLE|TOKEN_EXAMPLE|完成检查表|参考资料" -- $file
rg -n --pcre2 "clt\\.[A-Za-z0-9]{12,}|act\\.[A-Za-z0-9]{12,}|1[3-9][0-9]{9}|postgres(?:ql)?://|mysql://|mongodb(?:\\+srv)?://|[A-Z]:\\\\Users\\\\" -- $file
git diff --check -- $file
```

Expected:

- 第一条命令找到标题、Mermaid、安全示例值、检查表和参考资料。
- 第二条命令没有输出。
- `git diff --check` 没有输出。

- [ ] **Step 5: 独立提交第一篇**

Run:

```powershell
git add -- docs/knowledge-sharing/01-douyin-open-api-first-request.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: add Douyin API first-request guide"
```

Expected:

- 暂存区只包含 `docs/knowledge-sharing/01-douyin-open-api-first-request.md`。
- 提交成功。

---

### Task 2: 撰写“开放平台 API 与来客后台导出”

**Files:**
- Create: `docs/knowledge-sharing/02-douyin-data-acquisition-options.md`
- Read: `docs/knowledge-sharing/01-douyin-open-api-first-request.md`
- Read: `src/dy_data/douyin_client.py:75`
- Read: `apps/worker/collect_once.py:13`
- Read: `apps/worker/browser_exports/backend_aweme.py:52`
- Read: `docs/architecture.md:1`
- Read: `docs/runbook.md:95`

**Interfaces:**
- Consumes: 第一篇的认证概念、开放平台生活服务资料、项目 API 客户端和受控浏览器导出实现。
- Produces: 第二篇独立文章；与第一篇互相链接，不重复完整 Token 教程。

- [ ] **Step 1: 建立数据来源与证据对照**

核对以下官方页面：

- `https://open.douyin.com/platform/resource/docs/accession-guide/common-solution/`
- `https://open.douyin.com/platform/resource/docs/ability/life-service-ability/scene-solution/`
- `https://open.douyin.com/platform/resource/docs/accession-guide/type-and-permission`

Run:

```powershell
rg -n "def query_|ORDER_URL|VERIFY|CERTIFICATE|REFUND|SHOP_POI|CRAFTSMAN|CLUE|cursor|page_size" src/dy_data/douyin_client.py
rg -n "skip-browser-export|run_collect_and_settle|export_workbook_via_browser|fetch_backend_aweme_records_via_bind_list_api|导出" apps/worker/collect_once.py apps/worker/browser_exports/backend_aweme.py docs/runbook.md
```

Expected:

- 能区分 API 路径与后台导出路径。
- 能从当前项目确认订单、核销、券、退款、门店、职人和线索等数据类型的实现依据。
- 不能从官方资料确认的数据类型，只能标为“本项目当前接入”，不能写成开放平台对所有应用默认开放。

- [ ] **Step 2: 创建文章并按固定结构写完正文**

Create `docs/knowledge-sharing/02-douyin-data-acquisition-options.md` with these exact top-level sections:

```markdown
# 抖音后台有哪些数据获取方式：开放平台 API 与来客后台导出

> 适合谁：需要获取抖音业务数据，但不确定应该使用 API 还是后台导出的产品、运营和初级开发。
>
> 读完能做什么：根据用途选择取数路径，分别完成一次小范围 API 请求或后台导出，并检查结果是否可用。

## 先判断：你要什么数据，多久取一次
## 两种取数方式怎么选
## 常见业务数据从哪里来
## 路径一：用开放平台 API 跑出一小批数据
## 路径二：从来客后台导出一份数据
## 拿到结果后，先做四项检查
## 常见问题
## 完成检查表
## 进阶实践：什么时候需要改成定时任务
## 参考资料
```

正文必须包含：

- 一张“是否持续自动获取”的 Mermaid 选择流程图。
- 一张 API 与后台导出的对照表，覆盖适用场景、前置条件、操作成本、数据形态、验证重点和主要风险。
- 一张“数据类型—可能来源—权限提醒”表；订单、核销、券、退款、门店、职人和线索必须逐项说明。
- API 操作按“选择接口—设置小时间范围—发起请求—检查结果”展开。
- 后台导出按“登录—进入数据模块—设置筛选—查询—导出—检查文件”展开。
- 页面名称和按钮无法验证时使用功能性描述，并写明“具体名称以当前来客后台为准”。
- `> 截图建议：来客后台筛选条件和导出入口；发布前遮盖账号、门店、金额和订单号。`
- 结果检查固定为：来源、时间范围、字段、记录数。
- 对登录失效、空结果、权限不足和字段差异给出可执行排查顺序。
- 只用一小段话解释分页；不展开补拉、去重、长期调度。
- 相对链接到 `./01-douyin-open-api-first-request.md`。

- [ ] **Step 3: 检查第二篇的范围和敏感信息**

Run:

```powershell
$file = 'docs/knowledge-sharing/02-douyin-data-acquisition-options.md'
rg -n "^# |^## |^```mermaid$|开放平台 API|来客后台导出|订单|核销|退款|门店|职人|线索|完成检查表|参考资料" -- $file
rg -n --pcre2 "clt\\.[A-Za-z0-9]{12,}|act\\.[A-Za-z0-9]{12,}|1[3-9][0-9]{9}|postgres(?:ql)?://|mysql://|mongodb(?:\\+srv)?://|[A-Z]:\\\\Users\\\\" -- $file
git diff --check -- $file
```

Expected:

- 第一条命令覆盖所有必需数据类型和结构。
- 第二条命令没有输出。
- `git diff --check` 没有输出。

- [ ] **Step 4: 独立提交第二篇**

Run:

```powershell
git add -- docs/knowledge-sharing/02-douyin-data-acquisition-options.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: add Douyin data acquisition guide"
```

Expected:

- 暂存区只包含 `docs/knowledge-sharing/02-douyin-data-acquisition-options.md`。
- 提交成功。

---

### Task 3: 撰写“为什么开发协作需要 Linear”

**Files:**
- Create: `docs/knowledge-sharing/03-linear-development-collaboration.md`
- Read: `AGENTS.md:121`
- Read: `docs/rules/docs-and-plans.md:1`
- Read: Linear document `document:cb35bfde-4ea5-42c4-9dd3-2903c690b0a8`
- Read: Linear document `document:8281c1a4-43c9-4953-8c08-d856b269d766`

**Interfaces:**
- Consumes: Linear 官方 Issue、Project、标签和负责人说明，团队协作手册，仓库 Linear-first 规则。
- Produces: 第三篇独立文章；第四篇复用其中的统一需求池概念和虚构需求。

- [ ] **Step 1: 核对 Linear 官方产品概念**

逐页读取：

- `https://linear.app/docs/creating-issues`
- `https://linear.app/docs/projects`
- `https://linear.app/docs/labels`
- `https://linear.app/docs/assigning-issues`
- `https://linear.app/docs/issue-templates`

必须核对：

- Issue 至少需要标题和状态，并且属于一个团队。
- Project、优先级、标签、负责人和评论分别解决什么问题。
- Linear 当前一个 Issue 只有一个 assignee；代理协作与责任归属不能混淆。

- [ ] **Step 2: 读取团队权威文档和仓库规则**

使用 Linear 获取：

- `document:cb35bfde-4ea5-42c4-9dd3-2903c690b0a8`：《Codex + Linear 协作手册》
- `document:8281c1a4-43c9-4953-8c08-d856b269d766`：《团队首页资源索引》

Run:

```powershell
rg -n "Linear-First|统一需求池|Requirement Intake|type:|source:|affected area|priority:|risk labels|current state|Development Gate" AGENTS.md docs/rules/docs-and-plans.md
```

Expected:

- 能列出本团队需求进入 Linear 前需要补齐的字段。
- 能明确聊天、Linear 和代码仓库各自承担的权威范围。

- [ ] **Step 3: 创建文章并按固定结构写完正文**

Create `docs/knowledge-sharing/03-linear-development-collaboration.md` with these exact top-level sections:

```markdown
# 为什么开发协作需要 Linear：从聊天想法到统一需求池

> 适合谁：需要和产品、运营、开发或 Codex 一起推进需求的团队成员。
>
> 读完能做什么：判断一条聊天想法是否应该进入需求池，并把它整理成一条可追踪、可分工、可验收的 Linear Issue。

## 聊天适合讨论，不适合长期承载需求
## Linear 在开发协作中承担什么角色
## 一条 Issue 需要承载哪些信息
## Linear 里的几个核心对象
## 从一句聊天想法到统一需求池
## 产品、运营、开发和 Codex 如何协作
## 什么留在聊天，什么必须回填 Linear
## 常见误区
## 完成检查表
## 进阶实践：用模板统一团队输入
## 参考资料
```

正文必须包含：

- 一张“聊天想法—需求判断—补齐定义—创建 Issue—确认负责人—决定开发”的 Mermaid 流程图。
- 一张“聊天、Linear、代码仓库”的职责边界表。
- 一张 Issue、Project、状态、优先级、标签、负责人和评论的用途表。
- 使用“优化门店月度结算筛选体验”作为贯穿全文的虚构需求。
- 展示聊天原句和整理后的 Issue；Issue 必须包含背景、当前问题、目标结果、范围、不做、涉及区域、验收标准、风险和验证计划。
- 明确产品、运营、开发和 Codex 的协作责任，但不写 Git 或分支交接。
- 说明 Linear 中的负责人表示最终责任归属，协作者或代理不替代负责人。
- 相对链接到 `./04-linear-issue-lifecycle.md`。

- [ ] **Step 4: 检查第三篇的协作重点**

Run:

```powershell
$file = 'docs/knowledge-sharing/03-linear-development-collaboration.md'
rg -n "^# |^## |^```mermaid$|统一需求池|聊天|Linear|代码仓库|背景|目标结果|范围|不做|验收标准|完成检查表|参考资料" -- $file
rg -n "git checkout|git switch|分支交接|前后端联调|FastAPI|React|Docker" -- $file
git diff --check -- $file
```

Expected:

- 第一条命令覆盖统一需求池和完整 Issue 定义。
- 第二条命令没有输出。
- `git diff --check` 没有输出。

- [ ] **Step 5: 独立提交第三篇**

Run:

```powershell
git add -- docs/knowledge-sharing/03-linear-development-collaboration.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: explain Linear development collaboration"
```

Expected:

- 暂存区只包含 `docs/knowledge-sharing/03-linear-development-collaboration.md`。
- 提交成功。

---

### Task 4: 撰写“一个需求如何在 Linear 中流转”

**Files:**
- Create: `docs/knowledge-sharing/04-linear-issue-lifecycle.md`
- Read: `docs/knowledge-sharing/03-linear-development-collaboration.md`
- Read: `AGENTS.md:165`
- Read: `AGENTS.md:217`
- Read: `AGENTS.md:251`
- Read: `AGENTS.md:265`
- Read: Linear document `document:e7e727f8-6338-44c5-a21e-0dea1c1420f0`
- Read: Linear document `document:cb35bfde-4ea5-42c4-9dd3-2903c690b0a8`

**Interfaces:**
- Consumes: 第三篇的虚构需求、团队状态和验收规则、Linear 官方工作流资料。
- Produces: 第四篇独立文章；完整演示同一需求从 Backlog 到 Done 的生命周期。

- [ ] **Step 1: 核对工作流和团队验收规则**

逐页读取：

- `https://linear.app/docs/creating-issues`
- `https://linear.app/docs/editing-issues`
- `https://linear.app/docs/issue-templates`
- `https://linear.app/docs/assigning-issues`

使用 Linear 获取：

- `document:e7e727f8-6338-44c5-a21e-0dea1c1420f0`：《Issue 模板与验收规范》
- `document:cb35bfde-4ea5-42c4-9dd3-2903c690b0a8`：《Codex + Linear 协作手册》

Run:

```powershell
rg -n "Backlog|Todo|In Progress|In Review|Done|Verification Gate|Done Gate|验收标准|验证记录|remaining risk|剩余风险" AGENTS.md docs/rules/docs-and-plans.md
```

Expected:

- 能说明各状态的进入条件和最小输出。
- 能说明测试通过、业务验收和最终 Done 之间的区别。

- [ ] **Step 2: 创建文章并按固定结构写完正文**

Create `docs/knowledge-sharing/04-linear-issue-lifecycle.md` with these exact top-level sections:

```markdown
# 一个需求如何在 Linear 中流转：定义、分工、推进与验收

> 适合谁：已经开始使用 Linear，但需求仍容易卡住、失真或缺少验收证据的团队成员。
>
> 读完能做什么：推动一条 Issue 从 Backlog 进入 Todo、In Progress、In Review 和 Done，并在每个阶段留下足够记录。

## 一条 Issue 不等于一个已经定义好的需求
## 先看完整生命周期
## Backlog：捕获想法并判断价值
## Todo：完成定义并满足开发门槛
## In Progress：明确负责人并真实同步进度
## In Review：用证据支持验收
## Done：被接受后再关闭
## 需求变化或验收未通过时怎么办
## 用一个案例走完整个流程
## 常见误区
## 完成检查表
## 进阶实践：把剩余风险拆成后续 Issue
## 参考资料
```

正文必须包含：

- 一张 Backlog → Todo → In Progress → In Review → Done 的 Mermaid 流程图，包含验收未通过返回 In Progress 的分支。
- 一张五个状态的“核心问题—进入条件—最小输出”表。
- 沿用第三篇“优化门店月度结算筛选体验”的虚构需求，不新造第二个案例。
- Definition 阶段明确背景、当前问题、目标、范围、不做、验收和风险。
- 分工阶段明确唯一负责人、协作者和依赖。
- 推进阶段给出一条简洁进度评论示例和一条阻塞评论示例。
- 验收阶段说明测试、截图、PR、部署和业务确认应按实际任务选择，不能机械要求全部提供。
- Done 阶段明确：验证已记录、剩余风险已说明、负责方已接受。
- 说明需求变化时应更新 Issue；超出原范围时拆分新 Issue。
- 相对链接到 `./03-linear-development-collaboration.md`。

- [ ] **Step 3: 检查第四篇的状态真实性**

Run:

```powershell
$file = 'docs/knowledge-sharing/04-linear-issue-lifecycle.md'
rg -n "^# |^## |^```mermaid$|Backlog|Todo|In Progress|In Review|Done|验收未通过|验证记录|剩余风险|完成检查表|参考资料" -- $file
rg -n "构建通过就|自动视为完成|无需验收|多人同时负责" -- $file
git diff --check -- $file
```

Expected:

- 第一条命令覆盖完整状态流转、回流和验收证据。
- 第二条命令没有输出；如正文为了反驳误区引用了这些词，应人工确认其语义明确是否定。
- `git diff --check` 没有输出。

- [ ] **Step 4: 独立提交第四篇**

Run:

```powershell
git add -- docs/knowledge-sharing/04-linear-issue-lifecycle.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: add Linear issue lifecycle guide"
```

Expected:

- 暂存区只包含 `docs/knowledge-sharing/04-linear-issue-lifecycle.md`。
- 提交成功。

---

### Task 5: 系列统一审阅、验证和 Linear 回填

**Files:**
- Modify if required: `docs/knowledge-sharing/01-douyin-open-api-first-request.md`
- Modify if required: `docs/knowledge-sharing/02-douyin-data-acquisition-options.md`
- Modify if required: `docs/knowledge-sharing/03-linear-development-collaboration.md`
- Modify if required: `docs/knowledge-sharing/04-linear-issue-lifecycle.md`
- Update externally: Linear issue `DYDATA-51`

**Interfaces:**
- Consumes: 四篇已独立验证的文章。
- Produces: 术语一致、链接可用、严格脱敏、可交付用户审阅的文章系列，以及 Linear 验证记录。

- [ ] **Step 1: 检查四篇文件、标题和 Mermaid**

Run:

```powershell
rg --files docs/knowledge-sharing
rg -n "^# " docs/knowledge-sharing
rg -n "^```mermaid$" docs/knowledge-sharing
```

Expected:

- 目录中存在计划列出的四个文件。
- 每个文件只有一个一级标题。
- 每个文件至少有一个 Mermaid 代码块。

- [ ] **Step 2: 检查篇幅和必需结构**

Run:

```powershell
$files = Get-ChildItem -LiteralPath 'docs/knowledge-sharing' -Filter '*.md' | Sort-Object Name
foreach ($file in $files) {
  $text = Get-Content -LiteralPath $file.FullName -Encoding UTF8 -Raw
  [pscustomobject]@{
    File = $file.Name
    Characters = $text.Length
    Sections = ([regex]::Matches($text, '(?m)^## ')).Count
    Checkboxes = ([regex]::Matches($text, '(?m)^- \\[ \\]')).Count
  }
}
```

Expected:

- 第一、三、四篇正文长度接近设计建议的 1800—3000 中文字符，第二篇不超过约 3500 中文字符；Markdown 标记会造成少量统计偏差，以人工阅读为最终判断。
- 每篇包含完整章节和至少一份可勾选检查表。

- [ ] **Step 3: 执行敏感信息和范围扫描**

Run:

```powershell
rg -n --pcre2 "clt\\.[A-Za-z0-9]{12,}|act\\.[A-Za-z0-9]{12,}|1[3-9][0-9]{9}|postgres(?:ql)?://|mysql://|mongodb(?:\\+srv)?://|[A-Z]:\\\\Users\\\\|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY" docs/knowledge-sharing
rg -n "前后端联调|真实回读|数据口径|质量门禁|分支交接|FastAPI|React|Docker|CI 实现" docs/knowledge-sharing
```

Expected:

- 第一条命令没有输出。
- 第二条命令没有输出；若为了说明“不展开”而出现，应删除该句，保持文章聚焦。

- [ ] **Step 4: 人工统一术语与链接**

逐篇确认：

- 统一使用“抖音开放平台 API”“来客后台导出”“Linear Issue”“统一需求池”。
- `client_token`、`access_token` 和项目代码中的字段命名保持原样，不擅自改写。
- 第一、第二篇互链；第三、第四篇互链。
- 所有外部链接指向官方页面。
- 参考资料不使用搜索结果页、转载文或未经核实的博客。
- 截图建议均包含脱敏提醒。
- 语气自然、句子简短，产品和运营不需要先理解代码即可照着做。

- [ ] **Step 5: 运行仓库文档验证**

Run:

```powershell
git diff --check
python -m pytest tests/test_project_governance.py tests/test_design_system_docs.py tests/cli/test_docs.py
node .agent/project-manager-suite/tools/validate-global-files.mjs .
node .agent/project-manager-suite/tools/route-check.mjs .
```

Expected:

- `git diff --check` 没有由本任务文章引入的错误；如其他协作者文件只出现既有换行提示，应记录但不得擅自修改。
- pytest 共 37 项通过。
- 全局文件校验为 0 errors、0 warnings。
- 路由检查允许当前 S4 阶段继续。

- [ ] **Step 6: 只提交系列审阅产生的修改**

如果 Step 1—5 对文章做了修改：

```powershell
git add -- docs/knowledge-sharing/01-douyin-open-api-first-request.md docs/knowledge-sharing/02-douyin-data-acquisition-options.md docs/knowledge-sharing/03-linear-development-collaboration.md docs/knowledge-sharing/04-linear-issue-lifecycle.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: polish DYDATA-51 knowledge series"
```

Expected:

- 暂存区只包含四篇文章中实际修改的文件。
- 提交成功。

如果没有修改，跳过提交并记录“系列审阅未产生额外变更”。

- [ ] **Step 7: 回填 Linear 并进入用户审阅**

在 `DYDATA-51` 评论中记录：

- 四篇文件路径。
- 每篇对应提交哈希。
- 官方资料核对范围。
- 脱敏扫描结果。
- 文档测试命令与结果。
- 尚待用户完成发布前审阅。

保持 Issue 为 `In Progress` 或转为团队约定的 `In Review`；只有用户明确接受四篇正文后才能进入 `Done`。
