---
name: coding-standards
description: Load the project coding standards and route Claude to the right rule document before writing, modifying, reviewing, or refactoring Java, Vue, Python, SQL, API, or test-related artifacts. Use this skill only after the task has clearly entered an implementation activity such as code changes, database schema work, REST API design, automated tests, or test case document maintenance, even if the user does not explicitly mention "standards" or "规范".
---

# Coding Standards Router

Use this skill as the entry point for the repository engineering rules. Do not invent style rules from memory when the skill already has a matching standards document.

The authority source is this skill's private reference library under `references/`. This skill routes Claude to the right document inside the skill package.

Boundary note:
- This skill is **not** the entry point for project kickoff, requirements clarification, stage routing, project profile maintenance, or scaffold setup.
- If the user intent is to start a new project or determine the next project stage, route through `ai-project-manager` first.
- Load this skill only after the main entry has determined that the current round is performing implementation work.
- 本 skill 在 S4 中只负责记录 foundation 漂移待改请求，不直接修改 `docs/prd/foundation/` 产物；实际修订由 `foundation-builder` 承接，状态裁决由 `ai-project-manager` 回写。

Current scope note:
- The repository currently contains **11 active standards documents**: `01` to `11`.
- `01`-`09` cover Java, MySQL, Vue, and API standards. `10`-`11` cover Python standards.
- Testing-specific standards documents are **not currently present** under `references/`.
- For test-related work, first check whether testing files have been added later; if not, do not pretend they exist.

## 管线定位

本 skill 是 `project-manager-suite` 流水线的 **S4 代码实装阶段**，在 PIPELINE.md 中的位置：

- **上游**：`delivery-planner`，消费其产出的 `docs/plans/delivery-plans/` 正式开发计划文件组：`main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md`、`sub-delivery-plan-<slug>-<TaskID>-<short-name>.md`
- **下游**：`test-and-acceptance`，为其提供已完成的代码产物和 Task 状态回写
- **相关协议**：[`../../PIPELINE.md`](../../PIPELINE.md)

## 执行前置协议（管线硬约束，不可跳过）

在开始任何实装工作之前，**必须按以下顺序执行**：

```text
0. 主入口 S4 门禁确认：
   ai-project-manager 必须已经触发 delivery-planner 的
   s4_pre_coding_plan_consistency_check，并确认 main plan / kanban / sub plan
   三者一致。该校验未通过时，不得进入本 skill 写代码。

0.5. 执行环境自检（在读正式开发计划文件组之前）：
   node <suite-path>/skills/06-01-coding-standards/scripts/verify-task-context.mjs \
     <main-delivery-plan-path> <task-id> --env-check
   - envReady: true  → 继续读计划
   - envReady: true 但带「0 条环境依赖声明」警告 → 可继续，但先核对主计划
     「环境依赖声明」表格是否符合可解析格式（见 delivery-planner/references/plan-anatomy.md），
     防止格式写错被误当成"无环境依赖"
   - envReady: false → 输出缺失依赖清单，停止，不得开始写代码

1. 读取 `docs/plans/delivery-plans/main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md`，并定位当前 Task 对应的 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md`

2. 运行前置验证脚本：
   node <suite-path>/skills/06-01-coding-standards/scripts/verify-task-context.mjs \
     <host>/docs/plans/delivery-plans/main-delivery-plan-<slug>.md <task-id>

3. 脚本返回 canExecute: false 时：
   - 输出缺失文件清单
   - 即刻停止，不得开始写代码
   - 不得凭记忆假设 PRD 内容并自行完成

4. 脚本返回 canExecute: true 时：
   - 按 Task 的 [PRD双链·读] 字段加载对应 PRD 文件
   - 再按下方 routing table 加载匹配的编码规范，最多加载 2 份
   - 开始实装

5. 完成后：
   - 对照 Task 的 [完成标准] 逐项核查，全部可核查后才能回写状态
   - 执行 foundation 漂移回捞检查：实装中若发现 Schema / API / 术语表或既有契约需要回改 foundation，按下方「Foundation 漂移回捞」追加待改请求；若无漂移，在开发日志记录“本任务无 foundation 漂移”
   - 向 ai-project-manager 提交 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task；正式开发计划文件组三者状态回写由 ai-project-manager 调度 delivery-planner 执行
```

**硬禁令**：
- 未收到 `s4_pre_coding_plan_consistency_check` 通过结论前，禁止开始写任何代码
- 未运行 `verify-task-context.mjs` 前，禁止开始写任何代码
- 环境自检 envReady: false 时，禁止继续执行（即使 PRD 文件全部存在）
- `canExecute: false` 时，禁止凭记忆假设 PRD 内容并继续执行
- Task 的 `完成标准` 未全部核查通过前，禁止提交已完成状态回写请求
- 发现需要回改 foundation 的漂移却未追加待改请求时，禁止回写 Task 为已完成

## Foundation 漂移回捞

S4 实装收尾时必须判断本 Task 是否发现 foundation 漂移。这里的 foundation 漂移只指“代码现实证明上游 Schema / API / 术语表或既有契约需要修订”的问题；如果问题能在代码层按现有契约消化，不进入 backlog。

### 触发条件

- 有漂移：追加到 `<host>/docs/plans/foundation-plans/foundation-change-requests-<slug>.md`；若目录或文件不存在，在首次追加时创建
- 无漂移：不强制创建空文件，只在开发日志记录“本任务无 foundation 漂移”
- 追加规则：只追加新条目，不直接修改 `docs/prd/foundation/`，不替 `foundation-builder` 做修订

### backlog 条目字段

每条待改请求必须包含：

| 字段 | 口径 |
|------|------|
| `ID` | 建议使用 `S4-FCR-001` 递增 |
| `来源 Task` | 当前 delivery plan 的 Task ID 与标题 |
| `分类` | `DRIFT` 契约不符 / `GAP` foundation 缺项 / `BETTER` 更优设计 |
| `改动项` | 需要回改的 foundation 内容 |
| `原因` | 为什么现有代码现实或实现约束证明需要回改 |
| `指向代码块` | `file:line`，必须指向触发判断的代码或测试 |
| `目标 foundation 文件:章节` | 例如 `docs/prd/foundation/foundation-api-<slug>.md §2.1` |
| `严重度` | 阻断 / 建议 / 优化 |
| `状态` | 默认 `待评审`，后续由 `ai-project-manager` 回写为 `已采纳` / `已改` / `已驳回` |

### 职责边界

- `coding-standards`：每个 S4 Task 收尾检查并追加待改请求
- `foundation-builder`：只读 `待评审` 条目，作为增量修订输入
- `ai-project-manager`：在消费点翻条目状态，并向用户报告裁决结果

## Routing workflow

1. Identify the main task type before editing files.
2. Load only the 1-2 most relevant standards documents.
3. Apply the loaded rules while coding, reviewing, or rewriting.
4. If the task spans multiple areas, prioritize the primary implementation area first and then load one supporting document.
5. If no mapping is obvious, open `references/README.md` and choose the closest match.

## Routing table

| Task pattern | Load |
| --- | --- |
| Java class, method, field, DTO, VO, entity naming | `references/01-java-naming.md` |
| Java formatting, comments, whitespace, line breaks | `references/02-java-formatting.md` |
| Java OOP design, collections, concurrency | `references/03-java-oop.md` |
| Java exception handling, logging | `references/04-java-exception-log.md` |
| MySQL table creation, schema change, indexes | `references/05-mysql-table.md` |
| SQL writing, query optimization, MyBatis mapping | `references/06-mysql-sql-orm.md` |
| Vue 3 component, page, frontend interaction | `references/07-vue-frontend.md` |
| Layering, package structure, domain model, module boundaries | `references/08-engineering.md` |
| REST endpoint design, request or response schema, pagination | `references/09-api-design.md` |
| Swagger / OpenAPI annotation, @Operation, @Schema, @Tag, API doc | `references/09-api-design.md` |
| Python class, function, variable, constant naming | `references/10-python-naming-style.md` |
| Python import ordering, type hints, type annotations | `references/10-python-naming-style.md` |
| Python docstring, Google-style docstring, function documentation | `references/10-python-naming-style.md` |
| Python exception handling, custom exception, error class | `references/11-python-engineering.md` |
| Python logging, logger setup, log level | `references/11-python-engineering.md` |
| Python project structure, package layout, pyproject.toml, dependency management | `references/11-python-engineering.md` |
| Unit tests, integration tests, automated test code | `Not currently available in references/; check before loading` |
| Test case document, acceptance matrix, regression case maintenance | `Not currently available in references/; check before loading` |

## Multi-area selection rules

Use at most 2 documents for one task unless the user explicitly asks for a broad standards audit.

Apply this priority order when multiple areas are involved:

1. Language or framework implementation rule
2. API or engineering structure rule
3. Testing or test-case rule

Use these combinations as defaults:

- Java service or controller refactor: `01-java-naming.md` or `03-java-oop.md`, plus `08-engineering.md` if structure changes
- Java exception or log cleanup: `04-java-exception-log.md`, plus `02-java-formatting.md` only if formatting is part of the task
- New table plus SQL changes: `05-mysql-table.md` and `06-mysql-sql-orm.md`
- REST API change with backend implementation: `09-api-design.md`, plus the main Java rule document that matches the implementation
- Vue page plus backend API integration: `07-vue-frontend.md`, plus `09-api-design.md` if the API contract also changes
- Feature delivery with tests: load the main implementation document first, then check whether `12-testing.md` exists before loading it
- Automated tests plus test case document update: first check whether `12-testing.md` and `13-test-case-design.md` exist; if not, do not route to missing files
- Python script or module: `10-python-naming-style.md`, plus `11-python-engineering.md` if the task involves project structure or exception design
- Python service with REST API: `10-python-naming-style.md` or `11-python-engineering.md`, plus `09-api-design.md` if the API contract also changes
- Python with Java interop (e.g., calling Java API): load the primary Python document, plus `09-api-design.md` for interface alignment

## Operating rules

- Do not read all standards files at once.
- Do not cite generic best practices when a project-specific rule exists.
- Do not treat this router as the source of truth; the source of truth is the referenced document.
- If you need a full index inside this skill, start from `references/README.md`.
- Treat any duplicate copy under project `docs/` as a human-facing mirror, not the primary source for this skill.
- Do not route to testing-related files (e.g., future `12-testing.md`) unless those files actually exist in `references/`.

## Quick examples

Example: "Add a new Spring Boot API for device trace history and update the mapper SQL."
Load `09-api-design.md` and `06-mysql-sql-orm.md`. If the task also changes service layering, swap in or add `08-engineering.md` only when necessary.

Example: "Refactor this Vue page and keep the request and response fields consistent."
Load `07-vue-frontend.md`. If the task changes the backend contract, also load `09-api-design.md`.

Example: "补单测并补充测试用例文档。"
Check whether `12-testing.md` and `13-test-case-design.md` exist first. If they do not exist, fall back to the closest active standards file and explicitly note the gap.

Example: "写一个 Python 数据处理脚本，需要从数据库读取数据并导出 CSV。"
Load `10-python-naming-style.md` and `11-python-engineering.md`. If the task also involves database schema changes, also load `05-mysql-table.md` or `06-mysql-sql-orm.md`.

Example: "用 FastAPI 写一个新的 REST API 服务。"
Load `10-python-naming-style.md` and `09-api-design.md`. If the task also involves project scaffolding, swap in `11-python-engineering.md`.
