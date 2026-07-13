# 线索分配引擎 M1 控制规格

Status: Active
Date: 2026-07-12
Controller: Codex
Repo / workspace: `C:\Own Docm\Coding\抖音结算中心\dy-data`
Branch / target: `feat/clue-allocation-m1` from `main` at `6fc7d61`

## 1. 用户目标

完成 Linear M1 里程碑的三个需求，并保持现有线索中心可用：

- `DYDATA-8`：全量线索主池与订单生命周期。
- `DYDATA-9`：POI 锚点、门店地理数据与候选资格。
- `DYDATA-10`：门店评分与每日快照。

交付为隔离功能分支上的小步提交；本轮不推送、不部署，除非用户另行要求。

## 2. 当前证据

| Area | Evidence | Source | Confidence | Notes |
|---|---|---|---|---|
| 现有线索中心只物化履约中订单 | `rebuild_clue_center()` 过滤 `RawDouyinClue.order_status == "履约中"` | `apps/worker/clue_center.py` | High | 不能作为全量主池。 |
| 现有轮次直接使用抖音分配门店 | `follow_life_account_id/name` 写入第 1 轮 | `apps/worker/clue_center.py` | High | M1 只建立锚点/资格/评分，不替换分配策略。 |
| 现有 POI 门店映射来源存在 | `DimStorePoiMapping`、`collect_shop_pois()` | `models.py`、worker pipeline | High | 需要确认可映射字段和坐标导入边界。 |
| 每次采集后自动重建线索中心 | `run_collect_and_settle()` 调用 `rebuild_clue_center()` | `apps/worker/pipeline.py` | High | M1 必须把主池/评分物化放入可靠的同步链路。 |
| 基线测试可通过 | `257 passed` | `python -m pytest`，2026-07-12 | High | 有 24 个既有 Python 3.12 adapter warning。 |

## 3. 范围

Included:

- 建立全量业务线索主池，保留原始线索、订单状态、生命周期状态、当前池位置、分配准备状态、锚点快照和分配周期关联；不覆盖原始 payload。
- 首次采集即已核销或已退款的线索保留在主池、标记为未进入分配即结束、且不创建轮次。
- 让已进入业务池的线索在核销/退款时可被物化逻辑关闭，保留当前轮次关闭所需的兼容字段。
- 通过 `follow_poi_id` 映射锚点门店，建立独立可审计的门店地理/候选资格数据层：标准省市/城市编码、经纬度、营业和参与分配开关。
- 提供受控的坐标导入入口；导入结果写入运行数据库，运行时不依赖个人本地 Excel 或未跟踪源文件。
- 提供 Haversine 直线距离、锚点数据质量判定和候选资格判断的公共服务。
- 建立每日门店评分快照和计算服务：滚动窗口、成熟样本、城市/全局冷启动回退、固定权重 70/30 与权重 1。
- 将主池物化和评分刷新接入现有 worker 链路；测试覆盖建模、状态、映射、资格、距离、评分和历史快照不被覆盖。
- 为 M2 提供稳定、受测试的 Python 数据契约；只在必要时扩展内部 API/schema。
- 提供仅最高管理员可访问的主池/评分查询 API 与手动评分刷新 API；不新增管理前端页面。

Excluded:

- 不实现三种分配策略、规则版本、实际多轮分配或决策日志（`DYDATA-11`、`DYDATA-12`）。
- 不变更五类跟进动作、SLA、保护期和再分配状态机（`DYDATA-13`）。
- 不实现总部池页面/权限/再投放（`DYDATA-14`）或分配管理后台（`DYDATA-15`）。
- 不改既有抖音原始采集接口，不接客户精准定位或驾车距离，不实现商品服务能力矩阵。
- 不改变现有店端 UI 分配含义；M1 的新数据层不得把 `follow_life_account_id/name` 当作自有实际归属。

Scope control rule:

- 新建分配策略、规则配置 UI、现有详情 UI 字段重构或生产全量重建需要新 Linear 任务或本规格显式更新。

## 4. 假设和开放问题

| ID | Item | Type | Owner | Resolution |
|---|---|---|---|---|
| A1 | 业务提供的门店经纬度 Excel 需要进入可追溯运行时数据层，不直接读取个人临时目录 | Assumption | Controller | 已确认：采用幂等导入脚本，输入只作为本地导入源。 |
| A2 | 当前 `DimStorePoiMapping` 可作为 `follow_poi_id` 映射的首选来源 | Assumption | Explorer B | 已确认：`follow_poi_id -> poi_id -> store_id`。 |
| A3 | 评分正式/试运行隔离需要明确的 `is_trial` 或等价可追溯字段 | Assumption | Controller | 采用 `execution_mode`，旧轮次默认 `legacy`，正式评分只读取 `formal`。 |
| A4 | 订单核销与退款的原始状态映射必须基于当前数据，而非新增猜测性枚举 | Question | Explorer A | 已确认：核销以结算/核销记录优先；退款只接受明确退款状态；`交易关闭` 保留为未知，不猜测为退款。 |
| A5 | 坐标工作簿没有省份列 | Data limitation | Controller | 已确认：导入可接受可选省份列；缺失时只接受同 POI 的唯一原始省市证据补齐，未补齐门店不可参与分配。 |
| A6 | M1 尚未实现自有门店分配 | Scope boundary | Controller | 已确认：有效锚点线索以 `allocation_state=pending_allocation` 表示预分配状态，`pool_location` 不写入未定义第四业务池。 |

## 5. 工作分解

| Task ID | Role | Owner | Responsibility | Write Set | Acceptance Gate |
|---|---|---|---|---|---|
| E1 | Explorer | Explorer A | 主池/生命周期现状与迁移风险 | Read-only | 提供可实施的兼容路径。 |
| E2 | Explorer | Explorer B | POI、门店、坐标来源与资格数据 | Read-only | 确定可靠键和数据缺口。 |
| E3 | Explorer | Explorer C | 评分数据、调度、成熟样本边界 | Read-only | 明确计算入口和测试点。 |
| I1 | Implementer | Controller/Worker | 模型、Alembic、主池及锚点/资格领域服务 | `models.py`、migration、allocation domain、主池 worker、相关测试 | 全量主池、锚点和资格通过测试。 |
| I2 | Implementer | Controller/Worker | 评分快照、刷新入口和 worker 集成 | scoring domain、worker pipeline、相关测试 | 所有评分口径和回退通过测试。 |
| R1 | Spec Reviewer | Independent agent | 逐条核对 DYDATA-8/9/10 与本规格 | Read-only | 无缺失或越界。 |
| R2 | Code Quality Reviewer | Independent agent | 回归、数据正确性、迁移和隐私审查 | Read-only | 无阻塞问题。 |

## 6. 子代理任务包

### E1-E3：现状调查

Role: Explorer

Context:

- M1 是 M2/M3 的数据基础，不能把现有店端分配逻辑误当作自有分配逻辑。

Ownership:

- 只读；不得改文件、迁移、配置、Git 状态或 Linear。

Required output:

- 已检查文件、可验证事实、最小实现建议、测试建议、风险与未知项。

Acceptance gate:

- 输出能让实现者避免重写已有有效行为或依赖个人本地数据。

### I1：主池、锚点与资格

Role: Implementer

Context:

- 将原始抖音线索转成完整业务主账，并为后续分配提供锚点与候选资格，不实施任何策略分配。

Ownership:

- 仅可改模型、迁移、主池/锚点领域模块、相应 worker 和相应测试；不得改前端或路由以外的非必要代码。

Non-goals:

- 不创建实际分配轮次，不选择候选门店，不读个人临时 Excel。

Acceptance gate:

- 主池涵盖已结束线索，锚点不可用有可审计原因，距离/资格逻辑有确定测试。

### I2：评分与刷新

Role: Implementer

Context:

- 为 M2 排序提供每日可复核快照，不能实时变动历史决策。

Ownership:

- 仅可改评分领域模块、快照模型、worker 刷新接入和相应测试。

Non-goals:

- 不做评分后台、不做逐店权重编辑、不做策略分配。

Acceptance gate:

- 30 天窗口、成熟样本、城市/全局回退、试运行排除、权重和历史不可变性均有测试。

## 7. 审查计划

1. 实现者自查变更范围和测试。
2. 独立规格审查：逐项检查 M1 验收标准与非目标。
3. 独立质量审查：数据正确性、迁移兼容、性能、敏感字段和回归风险。
4. 仅对已确认问题做最小修复，并重新运行对应审查。

## 8. 验证计划

| Gate | Command / Method | Owner | Required For Done | Notes |
|---|---|---|---|---|
| Diff review | `git diff --check` 与 scoped diff | Controller | Yes | 不混入前端/部署无关变更。 |
| M1 unit/integration | `python -m pytest tests/test_data_schema.py tests/test_worker_clue_center.py -v` 加新增领域测试 | Controller | Yes | 覆盖模型和物化。 |
| Worker pipeline | `python -m pytest tests/test_worker_collection_pipeline.py -v` | Controller | Yes | 验证采集后物化/评分接入。 |
| Full backend suite | `python -m pytest` | Controller | Yes | 所有既有行为回归。 |
| Web build | `npm --prefix apps/web run build` | Controller | Yes | 验证共享类型/前端无回归。 |
| Migration review | SQLite 测试 schema + Alembic head 检查 | Controller | Yes | 不运行生产迁移。 |

## 9. 最终验收清单

- [ ] `DYDATA-8`、`DYDATA-9`、`DYDATA-10` 的验收标准均有代码和测试证据。
- [ ] 原始数据不被覆盖，明文手机号不会被写入日志或不必要的输出。
- [ ] 现有店端页面和现有线索中心 API 不被 M1 数据层破坏。
- [ ] 所有独立调查、规格审查和质量审查已由主控复核。
- [ ] 全量 pytest、web build、diff 检查和 Git 状态已执行。
- [ ] 分支内提交按逻辑切片完成；未在未获指示时推送或部署。

## 10. 决策日志

| Time | Decision | Reason | Evidence |
|---|---|---|---|
| 2026-07-12 | 从 `main` 创建 `feat/clue-allocation-m1` | 用户要求新分支完成 M1。 | Git status / `6fc7d61`。 |
| 2026-07-12 | M1 先建立数据基础，不替换现有分配策略 | 与已确认 M1/M2 任务依赖一致。 | DYDATA-8/9/10 与设计文档。 |
| 2026-07-12 | 评分使用每日快照而非实时计算 | 可复核且不改变历史决策。 | 产品设计 5.6。 |
| 2026-07-12 | 新增主池而不改造旧线索中心主键 | 现有表按 `order_id` 投影且直接写抖音跟进门店；M1 需要隔离迁移。 | Explorer A。 |
| 2026-07-12 | 门店坐标写入 `dim_stores`，Excel 的门店 ID 按 POI 映射，不直接当作内部 `store_id` | 坐标表键是 POI 型门店 ID；当前映射表已具备唯一 POI 关系。 | Explorer B。 |
| 2026-07-12 | 旧轮次默认 `legacy`，不进入正式评分 | 历史抖音分配不代表我方自有分配，避免污染新评分。 | Explorer C。 |
| 2026-07-12 | `pool_location` 只保存三种业务池，M1 预分配状态独立保存 | 尚未实现 M2 自有策略时不能把线索伪装成总部或门店任务。 | 产品规格 1.2 / 本文件 A6。 |
| 2026-07-12 | 主池以不可展示的订单加联系方式身份键去重，`clue_id` 仅为规范标识 | 接口可能先缺少 `clue_id` 后补齐，不能形成重复主实体。 | M1 回归测试。 |
| 2026-07-12 | 评分核销只归因核销时最新正式轮次 | 同订单历史轮次不得因后续核销重复得分。 | 产品规格 5.2 / M1 回归测试。 |

## 11. 变更日志

| Time | Change | Owner | Evidence |
|---|---|---|---|
| 2026-07-12 | 建立 M1 控制规格与验收门槛 | Controller | 本文件。 |
| 2026-07-12 | 完成 E1/E2/E3 只读调查并冻结 M1 数据边界 | Explorers / Controller | 代理调查输出与本规格第 4、10 节。 |
| 2026-07-12 | 实现 M1 主池、POI 锚点、坐标导入、候选资格、评分快照与管理员 API | Controller | `20260712_0012`、`clue_allocation.py`、管理员 API 与测试。 |
