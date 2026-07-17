---
name: test-case-runner
description: >
  测试用例执行引擎。当用户提到"跑测试""执行测试用例""运行 TC""跑某个业务域""验证用例"
  "测试报告""PASS/FAIL""开始测试""逐条跑"时触发。
  标准化四段式闭环执行（数据准备→测试→验证→清理），覆盖 API / UI 两种方式。
  只要涉及执行已有测试用例文档、生成测试报告、追踪测试进度，都应使用本 skill。
  注意：本 skill 负责"执行"，不负责"设计"（设计由 test-case-writer 承接，调度由 test-case-chief 负责）。
---

# 测试用例执行引擎

本 skill 标准化执行 `docs/test-case/` 下已有的测试用例文档，确保每条用例按完整闭环跑完，结果有据可查。

**权威文档源**：
- 测试主文档：`docs/test-case/tc-main-<slug>.md`
- 环境配置：`application.yml`（地址/端口/目录）+ `.env`（仅密码凭证）——这两个文件不是流水线上游 skill 的产物，首次执行测试前由测试执行者按宿主实际环境在项目根目录创建，最小示例见 [references/env-setup.md](references/env-setup.md)
- 项目规则：宿主项目规则文件（如 `project-rules.md`）

**外部依赖**：

| 依赖 | 用途 | 安装方式 |
|------|------|---------|
| pymysql | 数据准备/清理（执行 SQL） | `pip install pymysql` |
| expect | SSH 隧道（仅 DB 直连失败时需要） | macOS 自带；Linux: `apt install expect` |
| Playwright MCP | UI 用例（浏览器操作） | npm 包名 `@playwright/mcp`；接入命令见表下说明 |

Playwright MCP 接入：宿主环境已配置过 Playwright MCP server 时直接复用，无需重复添加；未配置时在终端执行：

```bash
claude mcp add playwright -- npx @playwright/mcp@latest
```

其中 `claude mcp add` 是 Claude Code 自带的 MCP server 注册命令，`npx @playwright/mcp@latest` 会在启动时临时下载并运行官方 Playwright MCP 包。注册后重启会话即可使用浏览器操作工具。

---

## 一、执行前：环境初始化（每次会话仅做一次）

任何一步失败都必须停下来解决，不要跳过。详见 [references/env-setup.md](references/env-setup.md)。

1. **检查必需依赖**：`python3 -c "import pymysql"`
2. **读取配置**：从 `application.yml` 读地址/端口/目录，从 `.env` 读密码凭证（详见 [references/env-setup.md](references/env-setup.md)）
3. **验证连通性**：API 返回 200 + DB 可连接 + 前端页面可访问
4. **确认报告目录**：确保 `docs/test-case/reports/screenshots/` 存在

按需依赖（到用时再检查）：
- Playwright MCP：第一条 UI 用例开始前检查，阻塞 UI 但不影响 API
- `expect`：仅当 pymysql 直连 DB 失败时

初始化通过后宣布："环境初始化完成，依赖/API/DB 均就绪，开始执行用例。"

---

## 二、用例加载：读取测试文档

业务域 TC 文件位于 `docs/test-case/{业务域}/tc-{业务域}.md`，编号前缀按域简称生成（如 `TC-<DOMAIN>-`），由 test-case-writer 的 project-conventions 决定。

1. 读取索引文件 + 用例详情文件
2. 构建执行清单，向用户展示确认

**执行顺序**：先 API（01~09），再 UI（11~19）。API 先跑是因为接口不对就别验页面。

---

## 三、逐条执行：四段式闭环

每条用例严格遵循四段式。跳过任何一段都会导致结果不可信或污染后续用例。

### 3.1 数据准备

读取用例文档中的"数据准备"段执行。常见写法：

| 写法 | 怎么做 |
|------|--------|
| 引用 SQL 文件 | 读 SQL 文件，找到数据准备段执行 |
| 内联 SQL | 直接执行文档中的 SQL |
| 复用其他用例 | 读被引用的 SQL 文件执行 |
| 无需准备 | 跳过 |

SEED 前置：文档提到 SEED SQL 的，在该组第一条用例之前执行一次。

### 3.2 测试执行 + 结果验证（渐进式披露）

**根据用例类型，读取对应的 reference 文件后再执行。** 不要凭记忆执行，每次切换类型都必须重新读取。

| 用例类型 | 必读文件 | 核心要点 |
|---------|---------|---------|
| API 用例（01~09） | **[references/exec-api.md](references/exec-api.md)** | curl + 逐字段比对 |
| UI 用例（11~19） | **[references/exec-ui.md](references/exec-ui.md)** | 视口设置 + 截图 + Read 截图验证 |

**⚠️ 这是强制门禁：未读取对应 reference 文件就开始执行 = 流程违规。**

### 3.3 数据清理

读取用例文档中的"数据清理"段执行。常见写法：

| 写法 | 怎么做 |
|------|--------|
| 引用 SQL 文件清理段 | 读 SQL 文件，找到清理段执行 |
| 复用其他用例 | 读被引用的 SQL 清理段执行 |
| UI 操作还原 | **用浏览器在配置页面操作还原**（不能用 SQL） |
| 无需清理 | 跳过（仅当文档明确说无需清理时） |

**清理不可跳过** — 脏数据会导致后续用例产生虚假的 PASS 或 FAIL。

### 3.4 记录结果

**每条用例闭环完成后，必须读取 [references/per-case-checklist.md](references/per-case-checklist.md) 并逐项执行。**

---

## 四、执行节奏与异常处理

- 每条用例独立执行，不合并多条用例的数据准备
- 一条跑完（含清理）再跑下一条
- 联调环境默认按**严格单用例串行**执行：`单条数据准备 -> 单条测试 -> 单条验证 -> 单条清理 -> 单条写报告` 完整收口后，才能进入下一条
- 禁止把多条用例放进同一个脚本、同一个批处理命令、同一个长事务或同一个“批量执行器”里一起跑；**即使脚本内部看起来是顺序执行，也视为违规**
- **禁止并行发起同一条用例的跨阶段操作**：同一条用例的 `数据准备`、`接口/页面验证`、`数据库回查`、`数据清理` 绝不能放进并行工具调用里同时执行。必须等上一步得到结果并确认后，再进入下一步。否则很容易出现“清理先于验证”“回查先于提交”“证据互相污染”的假 FAIL。
- **发现疑似矛盾证据时，先排除执行顺序污染**：如果出现“UI 看起来正常，但直连 API 为空”“事务内可见、换连接不可见”“回查有数据但接口无数据”这类矛盾，第一反应不是改代码，而是立即用**严格串行**方式重跑同一条链路：`写入 -> 提交 -> 新连接回查 -> 调用真实接口 -> 清理`。只有串行重跑后仍失败，才允许登记真实缺陷。
- 每跑完 3 条用例，向用户简报进度
- 遇到异常时，读取 [references/exception-handling.md](references/exception-handling.md) 查表处理

---

## 五、报告与缺陷

| 文件 | 路径 | 模板 |
|------|------|------|
| 索引报告 | `reports/index.md` | [references/report-template.md](references/report-template.md) |
| 业务域报告 | `reports/测试验收-{业务域}.md` | 同上 |
| 缺陷跟踪 | `reports/defects.md`（全项目唯一） | [references/defect-template.md](references/defect-template.md) |
| 截图 | `reports/screenshots/测试验收-{业务域}/` | — |

> 路径前缀均为 `docs/test-case/`。报告按**业务域**粒度组织，`{业务域}` 与 TC 文件目录 `docs/test-case/{业务域}/` 的域名一致，一个域一份报告。

---

## 六、硬规则

1. **先 API 后 UI** — API 全部跑完再跑 UI，接口不对就别验页面
2. **清理不可跳** — 哪怕用例 PASS 了也要清理
3. **证据不可少** — API 贴 JSON 摘要，UI 截图，没证据不算跑过
   - 对于删除/提交/覆盖/同步等**存在二次确认弹窗**的按钮操作，证据必须拆成两拍分别留存：`确认弹窗截图` + `结果 toast/结果弹窗截图`
   - 只留“操作成功后的 toast”而没有“确认弹窗”截图，或只留“确认弹窗”而没有“结果 toast”截图，均视为**过程证据不完整**
   - 若交互过程已实际验证通过但留档缺任一拍，报告中必须明确写“证据不完整，需补采”，不得把单张结果图写成完整过程证据
4. **一次一条** — 不合并多条用例的数据准备，隔离性比效率重要
5. **FAIL 不跳过** — 记录后继续跑下一条，不要停下来修代码
6. **结果即时写** — 每条跑完立即写入报告，不攒到最后批量写
7. **测试用户路径，不是接口能力** — 界面操作失败就是 BUG，严禁用 curl/SQL 绕过界面
8. **BLOCKED 必须有真依赖** — 多条用例操作同一页面的不同字段不构成依赖，必须独立测试
9. **切换用例类型时必须读 reference** — 从 API 切到 UI 必须先读对应的 exec-*.md
10. **测试资产必须原样执行** — 数据准备、步骤、SQL、输入参数必须按用例文档原样执行；若文档/SQL 本身失败或与真实环境不一致，直接记 `FAIL`/缺陷，不得为了"跑通用例"擅自修改 SQL、步骤或测试输入
11. **UI 执行必须人类可见** — 所有 UI 浏览器测试都必须以人类可见的浏览器窗口执行，并让协作中的人类可以同步看到当前页面；不得仅用无头浏览器、后台截图、隐藏窗口或仅 AI 可见的方式直接完成 UI 判定
12. **服务器默认不支持批量跑多条** — 除非用例文档或用户明确授权“可批量执行”，否则一律按服务器只支持串行理解；禁止为了提速把 `3` 条或更多用例打包到一次脚本执行中
13. **单条闭环内也禁止并行** — 即使只跑 1 条用例，也不能把“准备 / 验证 / 清理”拆成并行子任务；串行是证据可信度要求，不只是节奏要求

---

## 七、与用户的沟通

- **每条用例开始前，必须先向用户播报**：①该用例测试什么（场景+验证目标）②数据准备做了什么（插入了哪些关键数据、刻意缺少什么数据）。让用户不用翻文档也能判断当前在测什么、数据是否合理
- 环境初始化完成后，告知环境状态
- 每跑完 3 条用例，简报进度
- 遇到 FAIL，简要说明失败原因
- 全部跑完，给出汇总统计和关键发现

---

## 八、快速参考

### 测试文档路径
```
docs/test-case/{业务域}/tc-{业务域}.md                # 索引
docs/test-case/{业务域}/tc-{业务域}-用例详情.md       # 详情（超约 200 行时拆出）
docs/test-case/{业务域}/sql/{PREFIX}-{NN}.sql        # 场景数据 SQL，与用例编号一一对应
docs/test-case/{业务域}/sql/{PREFIX}-SEED.sql        # 种子数据 SQL，多用例共用
```

`{PREFIX}` 为该域编号前缀（形如 `TC-{域缩写}`），由 test-case-writer 的 project-conventions 决定。

### 报告输出路径
```
docs/test-case/reports/index.md
docs/test-case/reports/测试验收-{业务域}.md
docs/test-case/reports/screenshots/测试验收-{业务域}/
docs/test-case/reports/defects.md
```

### Reference 文件速查
```
references/exec-api.md          ← API 用例执行规则
references/exec-ui.md           ← UI 用例执行规则
references/env-setup.md         ← 环境配置与连接
references/visual-check.md      ← 截图视觉审查标准
references/per-case-checklist.md ← 单条用例完成检查清单
references/exception-handling.md ← 异常处理查表
references/report-template.md   ← 报告模板
references/defect-template.md   ← 缺陷模板
```
