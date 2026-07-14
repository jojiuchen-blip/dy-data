# AI PM Tool Tests

本目录存放套件脚本化能力的最小测试样例，共 4 个测试文件。

当前覆盖范围（按测试文件）：

- `ai-pm-tools.test.mjs` —— 主链路与高风险写入动作：
  - `tools/` 脚本：`validate-global-files.mjs`、`route-check.mjs`（S2–S7 各阶段门禁、baseline 路由、新旧页面目录优先级）、`generate-host-rules.mjs`、`install-suite-into-host.mjs`（首装、升级、脱敏 manifest 与版本锁）、`verify-suite-lock.mjs`（版本与内容漂移校验）、`bootstrap-host.mjs`（容器目录判定、访谈门禁）、`devlog-sync.mjs`（建日志 / 追加 / 候选池）
  - skill 侧脚本：`project-baseline-auditor/scripts/collect-baseline-gaps.mjs`、`project-link-indexer/scripts/collect-project-links.mjs` / `validate-project-links.mjs` / `run-project-link-indexer.mjs`、`delivery-planner/scripts/collect-upstream-context.mjs` / `validate-plan-structure.mjs` / `check-plan-consistency.mjs`、`coding-standards/scripts/verify-task-context.mjs`、`brd-writer/scripts/ledger-query.mjs`（D.5 复触发判断，经 `ledger-io.mjs` 构造台账）
  - 文档一致性断言：对 SKILL / 协议 / PIPELINE 的关键口径做文本检查（多文件计划命名、foundation 目录、link-indexer 伴随调度、baseline 刷新归属、S4 一致性门禁），防止文档被改回旧口径
- `protocol-alignment.test.mjs` —— `tools/check-protocol-alignment.mjs`：当前套件全量对齐通过、合成 fixture 检出缺失反向链接、非 git 环境安全降级、`--changed` 关联文件提示
- `page-ledger.test.mjs` —— `page-designer/scripts/page-ledger-io.mjs` / `page-ledger-mutate.mjs` / `page-ledger-query.mjs`：台账创建与恢复、phase 相位图推进与非法跳转拦截、回环 start-loop、BRD 缺失兜底
- `prd-check.test.mjs` —— `prd-writer/scripts/prd-check.mjs`：structure / crosscheck / set-status / sync-index 各命令，另含 PRD 自查表与 `route-check` 互不污染的回归

当前**未被任何测试直接覆盖**的脚本（改动它们时测试不会报警，需要人工验证）：

- `brd-writer/scripts/ledger-mutate.mjs`、`ledger-render.mjs`（台账写操作与 Markdown 渲染）
- `doc-governance/scripts/scan-authority-overlap.mjs`
- `page-designer/scripts/search.py`、`design_system.py`、`core.py`（Python 设计知识库链路）
- `project-link-indexer/scripts/render-project-links.mjs`（人读 wiki 索引渲染）

运行方式：

```bash
cd project-manager-suite
npm run test:ai-pm
```

说明：

- 使用 Node 原生测试运行器，不引入额外依赖
- 测试基于临时宿主目录执行，不依赖真实业务项目目录
- 当前属于第一版最小测试链路，重点覆盖主链路和高风险写入动作

## 什么时候使用

以下场景建议主动运行这组测试：

- 改了协议层之后
  例如修改 `SKILL.md`、`runtime.md`、`global-files-protocol.md`、`routing.md`，或调整 `lib/ai-pm-protocol/` 下的字段、阶段、路由配置。

- 改了工具脚本之后
  例如修改 `route-check.mjs`、`bootstrap-host.mjs`、`install-suite-into-host.mjs`、`devlog-sync.mjs`、`validate-global-files.mjs`。

- 一轮脚本化改造准备收口时
  当你觉得“这轮改完了”，需要用测试确认主链路没有被改坏。

- 怀疑出现回归时
  例如发现阶段门禁失效、骨架补齐异常、日志没有正确追加时，可以先跑测试判断是不是主链路已经被破坏。

- 后续 AI 接手维护时
  AI 改完协议或脚本后，不应只看文档判断，应跑一遍测试确认行为仍成立。

## 典型使用场景

### 场景 1：新增字段

例子：

- 你给页面任务新增了一个必须补齐的字段
- 先改协议文档
- 再改 `field-contracts.js`
- 如果 `route-check.mjs` 需要消费它，再改脚本
- 改完后运行测试，确认原有门禁没有被破坏

### 场景 2：修阶段门禁

例子：

- 你修复“阶段切换前必须先日志回写”的判断逻辑
- 改完 `route-check.mjs` 后，运行测试确认：
  - 该拦的时候仍然会拦
  - 其他主链路行为没有被顺手改坏

### 场景 3：调整骨架补齐逻辑

例子：

- 你修改了 `bootstrap-host.mjs`
- 想确认容器目录识别、规则目录补齐、模板延后创建仍然成立
- 这时应该立刻跑测试，而不是只看代码

### 场景 4：调整日志回写能力

例子：

- 你修改了 `devlog-sync.mjs`
- 想确认：
  - 第一次会建日志
  - 第二次会追加而不是覆盖
  - 命中规则升级信号时仍会更新候选池

### 场景 5：提交前最小验收

例子：

- 这次同时改了协议层和 2 个工具脚本
- 在提交或结束这一轮修改前，运行一次测试，把它作为最小验收动作

### 场景 6：修改协议映射关系

例子：

- 你改了协议文件里的“对应实现与执行入口”
- 或者你给结构化实现文件新增 / 修改了 Traceability 头
- 这时应该运行测试，确认协议文档和结构化实现之间仍然双向对齐

## 一句话原则

只要你改的是“协议、脚本、bootstrap 执行链、主链路行为”，就应该跑这组测试。

## 补充命令

如果你只想单独检查“协议文档 ↔ 结构化实现”是否仍然对齐，可直接运行：

```bash
cd project-manager-suite
node tools/check-protocol-alignment.mjs
```

如果你还想让工具提示“本次改了哪些文件后，还应该同步检查哪些关联文件”，可显式传入变更文件：

```bash
cd project-manager-suite
node tools/check-protocol-alignment.mjs --changed skills/00-01-ai-project-manager/references/core/runtime.md
```

如果你不传 `--changed`，脚本会优先尝试从当前 git 工作区自动识别变更文件，并输出同样的关联检查建议。
