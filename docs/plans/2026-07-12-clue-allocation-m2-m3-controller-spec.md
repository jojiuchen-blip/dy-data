# 线索分配引擎 M2/M3 控制规格

Status: Active
Date: 2026-07-12
Controller: Codex
Repo / workspace: repository root (`.`)
Branch / target: `feat/clue-allocation-m1` from M1 foundation commits

## 1. 交付目标

按既已确认的产品规格，顺序完成 `DYDATA-11` 至 `DYDATA-16`，让当前 M1 主池可以使用自有规则完成试运行分配，并提供受控的后台管理和审计能力。

本轮只在功能分支开发和本地验证：不推送、不部署、不运行生产迁移、不导入或重建生产线索。

## 2. 已冻结的业务边界

1. `follow_poi_id` 是唯一自动位置锚点；`follow_life_account_id/name` 只保留为抖音原始辅助信息，绝不作为我方实际归属。
2. 活跃线索会固定命中一个已发布规则版本；以后各轮沿用该版本，但使用当时最新门店评分并留下决策快照。
3. 固定策略类型和默认顺序：`sales_store_priority`、`nearby_city_optimization`、`city_fallback`。规则只配置启停、顺序和参数，不允许切换策略语义。
4. 只有实际分配到具体门店才生成连续的 `round_no`。跳过策略、无候选和总部池都不占轮次。
5. 现有抖音兼容轮次为 `legacy`；M2 产生的自有轮次才为 `trial` 或 `formal`，不把旧轮次误计为我方分配或评分样本。
6. 跟进动作统一升级为：`appointment`、`further_follow_up`、`lost`、`unreachable`、`request_store_change`。旧历史值只读保留。
7. 所有动作都算一次跟进行为。`appointment`、`further_follow_up`、`unreachable` 在本轮第一次发生时开始固定保护期；`lost`、`request_store_change` 立即关闭本轮并尝试下一策略。
8. 总部池不是轮次也不属于门店。总部池线索不计入任何门店线索数和跟进率分母；核销、退款即关闭。
9. 试运行通过 `auto_expiry_enabled=false` 关闭时间自动迁移，不能用极大 SLA 模拟“无限”。重复全量重建创建新批次并把旧试运行轮次标为 `superseded`，不删除历史。
10. 本期不做总部池再投放、A/B 实验、逐店权重模型、商品服务能力矩阵、预约生效、客户精准定位或驾车距离。

## 3. 依赖顺序与 Linear 映射

| 顺序 | Linear | 模块 | 前置 | 完成定义 |
| --- | --- | --- | --- | --- |
| 1 | DYDATA-11 | 规则范围、规则版本、固定策略配置 | M1 | 可创建草稿、校验、发布、退休；已发布不可改；可按锚点门店/组/城市/全局命中。 |
| 2 | DYDATA-12 | 三策略分配和决策日志 | DYDATA-11 | 可为 M1 活跃主池创建自有轮次，正确跳过与入总部池，完整记录候选与排序。 |
| 3 | DYDATA-13 | 五类动作、SLA、保护期 | DYDATA-11/12 | 动作、定时迁移、核销退款优先关闭和历史展示口径一致。 |
| 4 | DYDATA-14 | 总部池和权限 | DYDATA-12/13 | 总部池有原因、库存与权限隔离；门店不可见不可读手机号。 |
| 5 | DYDATA-15 | 分配管理后台 | DYDATA-11/12/14 | 最高管理员可配置/发布/审计；普通管理员只读；门店拒绝。 |
| 6 | DYDATA-16 | 试运行、重建、切换控制 | DYDATA-11-15 | 可预览和试运行、可重复重建、保留历史与阻断正式使用后的误重建。 |

## 4. 数据模型与职责

### 4.1 M2 数据层

- `clue_allocation_rules` / `clue_allocation_rule_versions`：范围、逻辑规则、版本号、生命周期、计时/评分配置和发布快照。
- `clue_allocation_strategy_configs`：规则版本内三种固定策略的启停、顺序和参数快照。
- `clue_store_groups` / `clue_store_group_members`：门店组范围匹配。
- `clue_lead_rule_version_bindings`：以 `lead_key` 唯一绑定首次命中的已发布版本、范围和配置快照；不能用旧兼容表的 `order_id` 作为绑定主键。
- `clue_allocation_decisions`：每一次策略判定或最终选择的不可变日志，含锚点、销售店、候选、评分、距离、排序、原因和计时快照。
- 扩展 `clue_master_leads`：当前运行批次和自有当前轮次指针；扩展 `clue_assignment_rounds`：策略类型、规则版本、分配决策、SLA/保护期和终止原因快照。M2 必须先替换旧的 `(order_id, round_no)` 唯一约束，隔离 legacy/self-owned 轮次命名空间，避免 `order_id-1` 冲突。
- 扩展 `clue_follow_up_records`：记录五类动作的效果分类，保留旧值的兼容读取。

### 4.2 M3 数据层

- `clue_allocation_cycles`：试运行/正式/重建批次、计划/实际影响、操作者与执行结果。
- `clue_headquarters_pool_entries`：总部池进入时间、原因、来源轮次和规则/决策快照。
- `clue_allocation_audit_logs`：规则发布、停用、试运行和重建的前后值、确认和执行信息。
- 不删除已有轮次或跟进流水；所有重建通过批次和 `superseded` 标记实现。

### 4.3 领域服务边界

- `apps/worker/clue_allocation.py`：只维护 M1 主池/门店资格/评分；新增或拆出的 allocation domain 负责规则命中、候选、排序、策略执行和状态迁移。
- `apps/worker/clue_center.py`：继续承担旧兼容投影；必须只读取自有当前轮次覆盖旧抖音轮次，且重建不能覆盖自有动作、历史或轮次。
- API 路由只作鉴权、schema 与事务边界；复杂决策不得放进路由或前端。

## 5. 实施任务包

### P1 / DYDATA-11：规则版本

Write scope:

- `apps/api/dy_api/models.py`
- 新 Alembic migration
- `apps/worker/clue_allocation_rules.py`（新建）
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/routes/_data.py`
- `tests/test_clue_allocation_rules.py`
- `tests/test_api_clue_allocation_rules.py`

Acceptance:

- 四层范围按锚点门店 > 门店组 > 城市 > 全局解析，候选范围不被范围误缩小。
- 发布校验覆盖自动超期、SLA、保护期、策略、权重、窗口/样本、全局默认规则。
- 已发布版本不可修改；首次命中通过 `lead_key` 绑定固定；后续规则变更只影响新线索。
- 最高管理员写、普通管理员只读、店端拒绝。

### P2 / DYDATA-12：分配引擎与日志

Write scope:

- `apps/worker/clue_allocation_engine.py`（新建）
- `apps/worker/pipeline.py`
- `apps/worker/clue_center.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `tests/test_clue_allocation_engine.py`
- `tests/test_worker_clue_allocation_pipeline.py`
- `tests/test_api_clue_allocation_decisions.py`

Acceptance:

- 销售店优先取订单归因 `sale_store_id`，资格合格且距锚点 <= 10 km 时直分，不评分。
- 15 km 城市优选和城市兜底均排除全部历史门店，按评分、距离、门店 ID 产生唯一选择。
- 策略跳过没有空轮次；最后无候选入总部池；锚点缺失直接总部池。
- 每次决策保留可复核候选、过滤原因和排序快照，评分使用最新快照但不改历史决策。

### P3 / DYDATA-13：动作与状态机

Write scope:

- `apps/worker/clue_follow_up_state.py`（新建）
- `apps/worker/pipeline.py`
- `apps/api/dy_api/routes/clues.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `apps/web/src/**/ClueCenter*`、`apps/web/src/**/client.ts`、相关样式/测试
- `tests/test_clue_follow_up_state.py`
- `tests/test_api_clues.py`
- `tests/test_frontend_clue_center.py`

Acceptance:

- 五类动作可存为不可变流水且同步当前轮摘要。
- 保护期只由首次保护型动作启动一次；后续记录不延长、不重算。
- SLA/保护期到期、战败、换店会关闭后进入下一个启用策略；最后策略后进总部池。
- 核销/退款优先结束本体和当前轮。失效、已核销、已退款均不可写/查看明文手机号。

### P4 / DYDATA-14：总部池

Write scope:

- `apps/api/dy_api/models.py`
- 新 Alembic migration
- `apps/worker/clue_allocation_engine.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `tests/test_clue_headquarters_pool.py`
- `tests/test_api_clue_headquarters_pool.py`

Acceptance:

- 可解释记录所有进入原因；库存与主池状态一致；不创建伪轮次。
- 门店用户既不能列出也不能绕过详情、导出、手机号接口访问总部池。

### P5 / DYDATA-15：后台管理台

Write scope:

- `apps/web/src/**/Admin*`、`apps/web/src/**/client.ts`、路由与样式
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- 前端/接口测试

Acceptance:

- 展示范围、版本、策略、评分、决策、总部池、试运行/重建操作入口。
- 发布、停用、重建均有确认和明确影响提示；不在 UI 或日志暴露手机号。
- 符合现有后台视觉规范，移动端安全降级为只读或拒绝高风险操作。

### P6 / DYDATA-16：试运行与重建

Write scope:

- `apps/api/dy_api/models.py`
- 新 Alembic migration
- `apps/worker/clue_allocation_engine.py`
- `apps/worker/pipeline.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `tests/test_clue_allocation_cycles.py`
- `tests/test_api_clue_allocation_cycles.py`
- 管理台对应测试

Acceptance:

- 试运行关闭自动超期但仍接受核销、退款和主动动作。
- 预览只计算影响，不写轮次；执行需要最高管理员确认。
- 每次重建创建独立 cycle/batch，旧试运行轮次标记替代，保留决策和跟进历史。
- 发现真实门店跟进后拒绝常规全量重建；仅最高管理员二次确认允许，并写审计。

## 6. 开发和审查编排

1. Controller 先完成数据契约与迁移，避免并行编辑 `models.py`、migration、核心路由冲突。
2. 每个 P1-P6 仅在前一任务通过目标测试后进入下一步；完成后提交一个逻辑切片。
3. 无共享写集的前端和测试补充可由 worker 并行，主控负责整合、审阅和纠正。
4. 每个阶段结束后运行独立规格审查与代码质量审查。审查发现的高风险问题先修复，再进入下一个阶段。
5. Linear 只在开始时标记 In Progress 并回填验证证据；用户验收和部署确认前不标记 Done。

## 7. 验证门槛

每阶段至少运行新增/受影响测试。最终必须通过：

```powershell
git diff --check
python -m pytest
npm --prefix apps/web run build
git status --short --branch
```

另需验证：

- Alembic head 和 SQLite 测试 schema 可升级；不执行生产迁移。
- M2/M3 API 没有返回未授权手机号明文；测试日志和异常不泄露 token/secret/完整手机号。
- 本地 UI 同时查看桌面与窄屏，试运行/重建全部以 mock 或本地测试数据验证。

## 8. 本轮风险控制

| 风险 | 控制 |
| --- | --- |
| 老线索中心物化覆盖自有轮次 | 在 worker 中按 `execution_mode` 隔离，测试确保兼容重建不改自有轮次/动作。 |
| 评分口径被试运行污染 | 评分服务仅读取 `formal` 且成熟的自有轮次。 |
| 配置变更追溯不到历史 | 版本、策略、候选、参数和评分均写入决策快照。 |
| 自动任务重复分配 | 分配/状态迁移用事务锁和幂等键；无候选只写判定日志。 |
| 总部池权限绕过 | 列表、详情、导出、电话 reveal/copy 和 follow-up 统一走同一 scope 检查。 |
| 失效或总部池线索被旧导出暴露明文手机号 | 导出、详情、reveal/copy 优先检查自有线索状态和总部池状态，不只依赖旧门店 scope。 |
| 删除跟进记录破坏审计链 | 用户可见“删除”改为审计化撤销/软删除；状态摘要重新计算但原始动作和操作者可追溯。 |
| 高风险重建误操作 | 先预览、后确认、后执行；试运行轮次不删除；真实操作后默认阻断。 |
