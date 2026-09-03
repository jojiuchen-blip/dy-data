# Implementation Plan: DYDATA-87 规则发布后门店榜单重算闭环

> **Linear issue**：DYDATA-87（`In Progress`）
> **关联正式任务**：T2.2 SKU 商品、双费率与原子导入 API；T2.4 账单冻结与月度/榜单投影
> **目标**：规则发布成功后，将一次可追踪、可重跑的 `settlement_rebuild` 任务写入 `job_runs`，让门店榜单、单店月度分账和费用明细在符合正式订单口径时读取同一活动结算投影代际。
> **边界**：不直接修改生产数据，不用规则记录虚构门店或金额，不改变 DYDATA-31 的订单资格、账期和正式起算日口径。

## 1. 现状与根因

- 当前 `/admin/rules` 手工发布流程逐 SKU 调用 `POST /api/v1/admin/sku-fee-rules`，接口只写入不可变 `sku_fee_rule` 版本。
- `/ranking` 和单店月度分账页不会直接读取 `sku_fee_rule`：前者读取榜单投影，后者读取 `/stores/{storeId}/monthly-settlement` 与 `/order-fee-details`。发布接口没有创建 `settlement_rebuild` 任务，因此规则记录存在但活动投影可能仍为空；此外榜单带 `rankingBasis` 时原先还会绕过活动代际读取旧表。
- 旧的兼容 `/admin/sku-rules` 已有“写入后排队重算”的模式；新双费率接口需要复用同一 worker 入口，并保持一批手工发布只触发一次重算。

## 2. 实现步骤

### Task 1：补失败回归测试

**Files**：

- `tests/test_api_fee_admin.py`
- `tests/test_frontend_admin_rules_workflow.py`（若现有测试文件已覆盖当前页面，则在该文件补契约断言）

1. 验证最高管理员调用新的规则重算触发接口后，`job_runs` 中有 `settlement_rebuild`、`queued` 状态、来源和更新数量元数据，并返回 `jobId/rebuildStatus`。
2. 验证相同 `Idempotency-Key` 与请求摘要重试返回同一任务，不会重复排队；相同键不同请求返回结构化 409。
3. 验证费率导入原子提交在同一事务中生成规则和重算任务，提交幂等重试返回同一任务；导入冲突时不生成任务。
4. 验证当前手工发布页面在全部 SKU 写入后只调用一次重算接口，并在重算触发失败时保留“规则已写入但任务未排队”的可恢复反馈。
5. 先运行聚焦测试，确认新契约在未实现时失败。

### Task 2：实现可观察的结算重算排队

**Files**：

- `apps/api/dy_api/routes/_settlement_jobs.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/fee_admin.py`
- `apps/api/dy_api/schemas.py`

1. 抽取当前管理员结算重算后台 runner，保留失败时将 `job_runs` 标记为 `failed` 并重新抛出异常的行为；兼容旧管理员路由和新费率路由。
2. 新增 `POST /api/v1/admin/sku-fee-rules/rebuild`，要求最高管理员和 `Idempotency-Key`，限制 `updatedRuleCount` 范围，使用统一成功响应元数据。
3. 用请求幂等摘要生成稳定任务 ID，并在 `job_runs.idempotency_key_hash` 与 `metadata_json.request_payload_sha256` 保存摘要；相同请求只返回原任务，不重复添加后台任务。
4. 规则发布后的任务元数据至少记录 `source_run_id`、`trigger` 和 `updated_rule_count`，任务提交后再注册 `BackgroundTasks`，避免请求依赖关闭导致任务记录丢失；规则页提供人工重建入口，覆盖已存在但尚未重算的历史规则。
5. 费率导入提交在规则版本、批次状态和任务记录同一提交边界内完成；已完成批次的幂等重试补齐缺失任务但不重复写规则。
6. 旧结算重建提交后，若活动投影指针存在，则按受影响月份构建并校验 sparse overlay，通过 CAS 发布活动代际；已发布同一任务重试为幂等空操作，单店月度、费用明细和榜单统一读取该代际。

### Task 3：接通前端手工发布和导入反馈

**Files**：

- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/pages/AdminSkuRulesPage.tsx`
- `apps/web/src/components/AdminSkuRuleImportDrawer.tsx`
- `tests/test_visual_smoke.py`（发布重试可视化契约随新增重算请求同步）

1. 增加共享的重算任务响应类型和请求封装，沿用 credentials、统一错误处理与幂等键。
2. 手工多 SKU 发布完成后只触发一次重算；规则写入成功但任务触发失败时，不清除可重试的幂等意图，并明确提示用户重试任务触发，而不是误报为规则未发布。
3. 批量导入成功提示中显示重算任务已排队及任务编号；不在前端计算结算金额或直接刷新/伪造榜单数据。
4. 规则页提供二次确认的“重建结算投影”入口，仅提交当前已生效 SKU 数量，不修改规则版本；保持加载、进行中、失败恢复和空数据状态，复用现有页面组件和设计令牌。
5. 明确 `/store-settlements` 是独立账单表：规则发布不虚构 `SettlementStatement`，账单尚未生成时单店确认区继续显示未生成状态。

### Task 4：验证与回写

1. 运行 `git diff --check`、费率管理/管理员重算/worker 聚焦 pytest，以及榜单、单店分账和前端契约测试。
2. 运行 `python -m pytest` 和 `npm --prefix apps/web run build`；必要时补真实 TestClient 的失败任务回归。
3. 运行套包锁、全局文件、阶段路由和计划一致性检查；不执行生产发布或生产重算。
4. 更新 `docs/devlog/` 记录实现、测试、未验证的生产数据证据和 foundation 漂移判断；向 `docs/plans/foundation-plans/foundation-change-requests-dy-data.md` 追加新 API 契约缺口待评审条目，不直接改写 Foundation 正文。
5. 将测试结果、任务状态返回契约、生产验证阻断和剩余风险回写 DYDATA-87，保持未完成验收项未勾选，等待用户验收。

## 3. 验收映射

| 验收项 | 代码/测试证据 |
|---|---|
| 发布一批 SKU 后任务可追踪且不静默丢失 | 新重算 API、`job_runs` 回读、前端一次触发契约测试 |
| 重算后榜单与单店结算读取同一投影 | 活动代际发布、单店月度汇总、带分佣口径榜单和单店费用明细回归；生产数据核对待部署后执行 |
| 无合格订单不虚构榜单行 | 不改查询和投影资格逻辑；保留空结果并记录任务状态 |
| 规则版本不可变、同日幂等 | 既有单条发布/导入幂等测试继续通过 |
| 手工、导入、失败与重试 | 手工页面、导入提交、失败状态和同键重试回归 |

## 4. 未解决的外部验证

- 本地测试只能证明触发、持久化和 worker 调用链；不能替代生产 2026-08 源订单、合格订单、费用结果和 `agg_store_ranking` 行数/样本核对。
- 生产部署、worker 实例运行、任务成功状态及页面最终门店数量必须在用户授权的发布窗口执行，并回填 Linear；本计划不执行生产写入。
