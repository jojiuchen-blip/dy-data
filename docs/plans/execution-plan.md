# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代 S3 正式交付计划。

## 0. 当前增量交付：DYDATA-71 / DYDATA-72 / DYDATA-75

- 用户已于 2026-08-20 明确授权核验本轮四项反馈、进入开发并最终生产部署。
- 当前隔离分支：`codex/dydata-71-72-75-production-fixes`，基线为远端 `main` 的 `ee7fb990acb83274f6443135eafdf498c39925cb`。
- 正式计划入口：[主交付计划](delivery-plans/main-delivery-plan-dydata-71-72-75-production-fixes.md)；[任务看板](delivery-plans/task-kanban-dydata-71-72-75-production-fixes.md)。
- T1.1 已完成：分佣步骤条/入口/状态提醒与账号指定门店搜索、批量导入、技术用户名隐藏、右侧独立滚动。
- T1.2 已完成：商品口径支持自定义产品范围/商品类型并保持单项兼容校验和导入原子性。
- 当前执行 T1.3：订单费用明细直接访问、全量本地门禁与最终独立评审均已完成；当前进入提交、远端 CI 与腾讯云公网环境发布。
- Linear 是范围与验收权威；本驾驶舱只记录当前执行顺序。下文历史增量保留为历史证据，不覆盖本轮计划。

## 0. 当前增量交付：DYDATA-45

- 隔离 worktree `feat/dydata-45-agent-connect` 已完成腾讯云测试环境 Agent 一句话接入层；Linear `DYDATA-45` 已进入 In Review。这里的 `production` 专指未来尚未部署的企业内网服务器版本。
- 正式计划入口：[`main-delivery-plan-dydata-45-test-agent-connect.md`](delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md)，T1.1、T1.2、T2.1、T2.2、T3.1 均已完成，等待人类 Owner 最终审核。
- 运行时代码 `cab6aec` 已合入远端 `main` 并由 GitHub Actions run `29934737788` 成功部署腾讯云；最终安全复审为 `ALLOW`，Critical/Important/Minor 均为 0。全量 916 项通过、2 项 opt-in PostgreSQL 用例另在真实 PostgreSQL 连续 5 轮通过；Web production build、API/Web 镜像、空库迁移、Compose、两套 Nginx、锁定依赖审计、增量 Bandit 与公开 smoke 均通过。
- 独立 Agent 黑盒重试 verdict 为 `PASS`：CLI 0.3.0 与官方 Node MCP SDK 均完成用户浏览器授权；测试账号仅返回 3 家授权门店，默认/显式日期统计口径成立，未授权门店整单拒绝，两通道的门店数、行数和完整脱敏聚合一致。非阻断观察为顶层 `--help` / `--version` 不受支持，机器入口 `commands --json` / `version --json` 正常。
- 权威规格：[`2026-07-22-dydata-45-test-agent-connect-design.md`](../superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md)。本增量仅覆盖当前腾讯云测试环境；未来企业内网生产版由 DYDATA-46 对入口、OAuth、keyring、部署、文档和 smoke 做彻底切换。
- 本增量不改变下文 DYDATA-41 线索中心 Foundation 的业务基线与依赖顺序；后续仅在 `DYDATA-46` 生产 Release Gate 中切换企业内网入口、OAuth、keyring、部署、文档和 smoke，禁止复用测试凭据。

## 1. 当前阶段

- 套包阶段：`S4 DYDATA-19 T5.2 门店确认与推广费发票登记进行中`。
- 当前 Linear issue：`DYDATA-19`，状态 `In Progress`，由当前分支单一窗口负责。
- 当前正式计划：[main-delivery-plan-dy-data.md](delivery-plans/main-delivery-plan-dy-data.md)。
- 当前正式计划文件组：`docs/plans/delivery-plans/main-delivery-plan-dy-data.md`、`task-kanban-dy-data.md` 与 T5.2 子开发计划。
- 当前子开发计划：[sub-delivery-plan-dy-data-T5.2-store-billing.md](delivery-plans/sub-delivery-plan-dy-data-T5.2-store-billing.md)。
- 当前 Task：T5.1 已完成；T5.2 为唯一 `进行中` 任务，T5.3～T5.7 等待后续审阅与前置完成。

## 2. 当前目标

- 在复用现有双费用结算事实与查询能力的基础上，完成账单分方向确认、异议、系统外发票登记、管理员财务查询、四类原子导入、操作审计和生产页面闭环。

## 3. 进行中任务

- T5.2：实现门店账单读取、分方向确认与推广费系统外发票登记接口；历史 T4.1 仍等待外部发布依赖。

## 4. 下一步任务

- 以 TDD 完成 T5.2：门店范围鉴权、当前账单版本读取、分方向确认及推广费发票登记/重登接口。
- 完成后记录接口响应、数据库回读与 Foundation 漂移结论，并提交 T5.3/T5.4 的审阅申请。

## 5. 完成标准摘要

- 8 张目标表、20 个接口与 8 条生产路由可追溯到 PRD、验证方法和证据。
- 系统不创建开票申请、不执行真实开票或厂端审核；只登记信息、导入结果、回传状态、查询、导出与审计。
- 四类导入全量校验且整批原子；发票、异议、账单和导入更正只生成新版本，不删除历史。
- 全量 pytest、Web build、真实浏览器、迁移、并发、权限、系统测试及用户验收通过。

## 6. 状态与权威边界

- Issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 业务规则以 `docs/prd/` 与 Foundation 为准；页面文件不复制服务端财务计算或权限真相。
- 正式任务状态以主开发计划、任务看板和当前子计划三处一致为准。

## 7. 本轮验证证据

- 页面原型测试 74/74 与构建通过，关键流程已完成浏览器验证。
- PRD 9/9 功能块已确认；结构与跨文档校验均为 0 错误、0 警告。
- S3 正式计划包含 19 个总任务，其中新增 T5.1～T5.7；结构校验 `passed=true`，缺失字段、缺失子计划和模糊验收均为 0。
- 规格检查点 `b445cb9` 已推送至 `codex/dydata-19-page-loop`。
