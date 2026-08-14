# DYDATA-72 商品口径页面重构主交付计划

> **版本**：v1
> **发布日期**：2026-08-13
> **适用范围**：`/admin/product-types`、SKU 商品口径管理 API、导入批次模型与自动化测试
> **需求基线**：Linear `DYDATA-72`；用户已确认页面规则、批量导入方案并授权进入代码修改
> **上游发现**：`canProceed=true`，`slug=dy-data`，目标契约以 Linear DYDATA-72 与现有 Foundation 为准
> **执行边界**：不修改分佣规则；不负责从 `/admin/rules` 移除旧入口（由 DYDATA-71 处理）

## 0. 本计划使用指南

1. 同一时刻仅一个 Task 为“进行中”，主计划、看板和对应子计划状态保持一致。
2. 每个 Task 先写失败测试，再实现最小改动并运行目标测试。
3. 产品范围与商品类型是两个可单独更新的人工字段；未提交字段必须保持原值。
4. 用户已批准开发，T1 初始状态为“进行中”，后续任务按前置依赖串行推进。

### 0.1 PRD 加载约束

- 全局地图：`docs/prd/mainprd-dy-data.md`、`docs/prd/prd-feature-list-dy-data.md`。
- 商品事实源：`docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md`。
- 管理端接口与原子导入：`docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`、`common-contract.md`。
- 本次新增规则以 Linear `DYDATA-72` 为业务权威，不把分佣导入的费率字段带入商品口径。

### 0.2 读前门禁 / AI 自检清单

- 工作目录必须为 `.worktrees/dydata-72-product-types`，分支为 `codex/dydata-72-product-types`。
- 页面只有“待完善”和“已配置”两个顶部入口；待完善内部状态为未配置、部分配置。
- 列表默认每页 50，待完善按未配置优先，不增加 SKU 详情跳转和待完善原因列。
- 批量选择可跨页保留；批量设置和导入允许更新单个字段，未更新字段明确保持原值。
- 商品口径影响线索中心、核销表现、订单分佣的分类口径；订单分佣仍额外受有效分佣规则限制。

### 0.3 完成前验证门禁

- API 目标 pytest 覆盖状态筛选、排序、单个更新、跨 SKU 批量原子更新和导入原子提交。
- 前端契约测试与 TypeScript/Vite build 通过。
- `/admin/product-types` 完成桌面端真实页面 smoke；错误、空态、加载态和危险提交确认均可理解。
- `git diff --check`、目标测试、完整 `python -m pytest` 和 `npm --prefix apps/web run build` 通过。

## 1. 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node --version` |
| npm | 可构建 apps/web | `npm --version` |
| Python | >= 3.12 | `python --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |

## 2. 差距基线

| 差距 | 优先级 | 影响 | 对应 Task | 状态 |
|---|---|---|---|---|
| SKU 列表没有配置状态与待完善优先排序 | P1 | 管理员无法快速定位待处理商品 | T1.1 | 待处理 |
| 单条接口强制同时写三字段且没有批量更新 | P1 | 单字段修正和跨页批量操作不可用 | T1.1 | 待处理 |
| 商品口径没有独立预校验、确认提交的原子导入 | P1 | 大批量维护风险高且不可追溯 | T1.2 | 待处理 |
| 商品口径页仍是旧“展示口径”配置模型 | P1 | 页面语义与真实 SKU 工作流不一致 | T2.1 | 待处理 |
| 缺少跨端回归、真实页面和文档漂移验证 | P1 | 容易影响线索、核销与分佣筛选 | T3.1 | 待处理 |

## 3. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 代码理解、测试先行实现、数据库迁移、页面实现、验证与计划/Linear 回写 |
| 人类 Owner | 审核业务口径、页面操作体验与最终验收 |

高冲突文件 `fee_admin.py`、`models.py`、`schemas.py`、`client.ts`、`dashboard.ts` 和商品口径页面由当前任务串行维护。分佣规则页面与 DYDATA-71 的入口迁移不在本计划中修改。

## 4. 执行阶段

### Phase 1：商品口径 API

**Entry Criteria**：Linear DYDATA-72 已是 In Progress，用户已授权开发，测试数据库可运行。
**Exit Criteria**：查询、配置状态、单条和批量更新契约均由目标测试覆盖。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [商品口径查询与更新 API](sub-delivery-plan-dydata-72-product-types-T1.1-product-api.md) | 已完成（2026-08-13） |
| T1.2 | [商品口径原子导入](sub-delivery-plan-dydata-72-product-types-T1.2-product-import.md) | 已完成（2026-08-13） |

### Phase 2：管理页面与验收

**Entry Criteria**：T1、T2 API 契约和目标测试通过。
**Exit Criteria**：页面、跨页批量操作、导入和全量回归证据齐备。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T2.1 | [商品口径管理页面](sub-delivery-plan-dydata-72-product-types-T2.1-product-page.md) | 已完成（2026-08-13） |
| T3.1 | [集成验证与交付回写](sub-delivery-plan-dydata-72-product-types-T3.1-verification.md) | 已完成（2026-08-14） |

## 5. 任务看板

- [task-kanban-dydata-72-product-types.md](task-kanban-dydata-72-product-types.md)

## 6. 发布闸门

- [x] 配置状态、默认排序、筛选、单字段更新与批量原子更新均通过测试。
- [x] CSV/XLSX 模板、预校验、错误定位、确认提交和整批回滚均通过测试。
- [x] 两个顶部入口、URL 状态、默认 50 条、跨页勾选、单个/批量抽屉与导入流程可用。
- [x] 商品口径不再表达“控制是否展示”，订单分佣额外限制说明准确。
- [x] 完整测试、前端构建、页面 smoke、diff check 通过并回填 Linear。

## 7. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 产品范围与商品类型映射来源只包含现有有效组合 | 新组合无法安全校验 | 以当前 SKU 事实源生成映射；无足够映射时只做必填与保留原值校验并记录限制 | AI -> 人审核 | 待观察 |
| 导入批次中途失败留下部分写入 | 数据口径不一致 | 单事务重新校验并一次性提交，任一失败整批回滚 | AI | 已控制 |
| 跨页勾选与筛选变化混淆影响范围 | 误改 SKU | Set 保存业务 ID、展示已选数量、提交前列出影响数量并支持清空 | AI -> 人审核 | 已控制 |
| DYDATA-71 同时改动旧入口 | 合并冲突 | 本任务仅维护新页面与 API，不编辑旧人工分类面板 | AI | 已控制 |

## 8. AI 执行示例

开始 T1.1 时先运行上下文门禁，再新增失败 API 测试；测试确认红灯后实现状态表达式和更新事务。T1.1 完成后同步三处状态，再让 T1.2 进入进行中。

## 9. PRD → 任务反向索引

| 需求依据 | Task | 子开发计划 |
|---|---|---|
| DYDATA-72 列表、状态、单个/批量设置 | T1.1 | [商品口径查询与更新 API](sub-delivery-plan-dydata-72-product-types-T1.1-product-api.md) |
| DYDATA-72 CSV/XLSX 原子导入 | T1.2 | [商品口径原子导入](sub-delivery-plan-dydata-72-product-types-T1.2-product-import.md) |
| DYDATA-72 页面布局与交互 | T2.1 | [商品口径管理页面](sub-delivery-plan-dydata-72-product-types-T2.1-product-page.md) |
| DYDATA-72 三页面影响与回归 | T3.1 | [集成验证与交付回写](sub-delivery-plan-dydata-72-product-types-T3.1-verification.md) |
