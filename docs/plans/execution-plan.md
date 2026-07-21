# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代后续 S3 正式交付计划。

## 1. 当前阶段

- 套包阶段：`S4 代码实装`。
- 当前状态：T1.1～T3.3 已完成本地实现与验证；T4.1 为唯一 `进行中（等待外部依赖）` Task，依赖关闭前只进行发布准备，不执行生产迁移或部署。
- 当前 Linear issues：执行范围为 `DYDATA-1/21/30/31/33/38`；`DYDATA-23` 仅作为已完成设计证据，`DYDATA-39` 已 Done。
- 当前正式计划文件组：[主计划](delivery-plans/main-delivery-plan-dy-data.md) · [任务看板](delivery-plans/task-kanban-dy-data.md) · 12 份子开发计划。
- 当前子开发计划：[T4.1 端到端核验与生产发布](delivery-plans/sub-delivery-plan-dy-data-T4.1-release-verification.md)；最近完成计划为 [T3.3 商品、费率、导入与同步后台](delivery-plans/sub-delivery-plan-dy-data-T3.3-admin-console.md)。

## 2. 当前目标

- 等待并关闭 T4.1 的外部生产依赖，再执行目标 PostgreSQL 迁移核验、真实商品 API 联调、全量回归、部署 smoke test 与业务验收。

## 3. 进行中任务

- S2 已完成：功能列表、mainprd、4/4 subprd、Foundation 与 Phase 5 一致性检查全部确认。
- `DYDATA-39` 的实现、验证和用户验收已闭合，可在 Linear 标记 Done。
- T1.1～T3.3 已在主计划、任务看板和子计划三处同步完成事实；T4.1 已三处同步为唯一 `进行中（等待外部依赖）` Task，但尚不满足生产执行 Entry Criteria。

## 4. 下一步任务

- 人类 Owner 提供或确认：抖音商品在线 API 脱敏成功/空页/错误样例、稳定归属账号 ID、真实渠道枚举和 DYDATA-32 最终权限矩阵。
- 准备可执行 Alembic 升降级与双会话核验的目标 PostgreSQL/脱敏副本环境，以及生产部署与 smoke test 权限。

## 5. 完成标准

- `docs/plans/delivery-plans/main-delivery-plan-dy-data.md`、`task-kanban-dy-data.md` 和 12 份 sub delivery plans 已存在且结构有效。
- main plan、kanban 与 sub plans 的 Task ID、状态、依赖和文件范围一致；当前仅 T4.1 为 `进行中`，且外部依赖关闭前不得执行生产迁移或部署。
- 每个 Task 可追溯到 Linear issue、PRD 区块、Foundation 契约、核心文件、验证命令和风险边界。
- 计划明确区分目标契约与当前实现，不把 Mock、历史字段或未关闭外部依赖写成已完成事实。
- 每个 Task 完成实现、验证、Foundation 漂移判断、Linear 与开发日志回填后，才允许切换下一 Task 为唯一 `进行中`。

## 6. 状态与权威边界

- issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 当前阶段快照以 `project-profile.md` 为准。
- Foundation 权威入口为 `docs/prd/foundation/foundation-delivery-dy-data.md`。
- 历史计划保留其时间点事实，不反向覆盖本文件或 Linear。
- 本文件只保留当前阶段和紧邻下一步，不提前扩写 S3 任务正文。

## 7. 本轮验证证据

- 套包版本锁：`project-manager-suite@2.0.0` 有效。
- 全局治理：0 错误、0 警告。
- 页面环节：`pageStageClosedForPrd.pass = true`，9 条交互语义全部 locked，未解决 gap 为 0。
- Foundation：`foundationReadyForPrd.pass = true`，交付清单及声明产物均存在。
- PRD Phase 2：`prd-check structure` 为 0 fail、0 warn、0 needs_ai_review。
- PRD Phase 3：`mainprd-dy-data.md` 的 `prd-check structure` 为 0 fail、0 warn、0 needs_ai_review。
- PRD Phase 4：4/4 subprd 已确认；`04-subprd-invoice-guide.md` 的 `prd-check structure` 为 0 fail、0 warn、0 needs_ai_review；双索引状态均为 `已确认`。
- PRD Phase 5：progress 显示 4/4 已确认且 pending 为空；Foundation 增量补档后 crosscheck 为 0 fail、0 warn、0 needs_ai_review；P1/P2/P4/P5/P6/P9 量化覆盖全部闭合，P3/P8 已人工复核，并已获用户确认。
- S3 路由：`route-check --target-stage S3` 可进入，`fullPrdReady.pass = true`、`foundationReadyForDevelopmentPlan.pass = true`，目标 skill 为 `delivery-planner`。
- S3 计划结构：`validate-plan-structure.mjs` 通过，13/13 必需章节、12/12 Task、0 错误、0 警告。
- 项目索引：已收录功能列表、mainprd 和全部 4 份 subprd；PRD 产物断链为 0，剩余两条 DYDATA-22 历史计划坏链与本轮无关。
- T3.2：前端契约 65 passed、API dashboard 17 passed、浏览器/视觉 102 passed（含真实 FastAPI 两角色、空态、403、422 requestId、409 导出），Web build 通过；390/768/1440 截图已复核；独立代码复审 Critical/Important/Minor 均为 0；Foundation 无漂移。
- T3.3：后端/API/Schema/Alembic 回归 56 passed；完整浏览器/视觉 112 passed，数据库级商品同步幂等加固后的真实同步浏览器路径 1 passed；Web build 与 `git diff --check` 通过；独立代码复审 Critical/Important 均为 0；Foundation 业务契约无漂移。
