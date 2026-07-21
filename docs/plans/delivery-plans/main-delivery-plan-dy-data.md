# dy-data 商品治理与双费用结算主开发计划

> **版本**：v1
> **发布日期**：2026-07-20
> **前序版本**：无；DYDATA-22 历史计划不属于本计划
> **适用范围**：DYDATA-1/21/30/31/33/38；DYDATA-23 仅作为已完成的页面设计证据
> **参与角色**：AI 执行，人类 Owner 审核与业务验收
> **开发模式**：solo-local；保留生产发布与数据正确性闸门
> **执行约束**：TDD；FastAPI / SQLAlchemy / PostgreSQL / Alembic / React / TypeScript / Vite；金额使用整数分，费率使用精确小数；不执行真实资金划拨
> **目标**：在不破坏平台业务 ID 和既有调用方的前提下，落地统一 SKU 商品事实、日级双费率与原子导入、商品同步、不可变双费用结果与调整、账单投影，以及四个生产查询页面
> **当前需求基线**：Linear DYDATA-1/21/30/31/33/38，已确认的 mainprd、4 份 subprd 与 Foundation
> **上游发现结论**：`collect-upstream-context.mjs` 返回 `canProceed=true, slug=dy-data, mode=pipeline`；全部必需产物存在。`03-subprd-order-fee-details.md` 已按章节读取，Foundation 拆分文件已全部读取

## 0. 本计划使用指南

1. 先读取本主计划和任务看板，只选择依赖已满足且状态为 `待开发` 的 Task。
2. 再读取该 Task 的子计划、其中列出的 PRD 章节、Linear issue、真实代码和测试文件。
3. 人类 Owner 已于 2026-07-20 确认全部计划；T1.1～T3.3 已完成本地实现与验证，T4.1 已切换为唯一 `进行中（等待外部依赖）` Task；依赖关闭前只进行发布准备，不执行生产迁移或部署。
4. 每个 Task 先补失败测试，再做最小实现，最后回填测试、数据核对、截图或发布证据。

### 0.1 PRD 加载约束

- 全局地图：`docs/prd/mainprd-dy-data.md`、`docs/prd/prd-feature-list-dy-data.md`。
- 数据与接口：`docs/prd/foundation/foundation-delivery-dy-data.md` 声明的全部 Foundation 主文件和拆分子文件。
- 页面任务按子计划精确读取对应 subprd；订单费用明细继续按 §3～§8 分节读取，避免一次性加载超大文件。
- `docs/commission-dashboard-navigation-mock.html` 和 DYDATA-23 只提供已确认交互证据，不证明生产 API、数据库或页面已经实现。
- Linear 是范围、状态和验收权威。DYDATA-23 已 Done，不重新创建实现任务；DYDATA-32 的最终权限矩阵是发布依赖，不在本计划扩建权限管理域。

### 0.2 读前门禁 / AI 自检清单

- 套包锁、全局文件与当前阶段路由通过；计划三处状态一致。
- 当前 Task 的前置项已完成，且最多一个 Task 为 `进行中`。
- 已读取 Task 指向的当前代码、迁移和测试；不得从目标 Foundation 误判现状已实现。
- 涉及财务结果时，先确认金额单位、业务日、原始发生月、调整入账月、费率版本和锁账边界。
- 涉及外部商品 API 时，先确认脱敏成功/空页/错误样例和正式枚举；缺失时不得猜 URL、鉴权、游标或枚举。

### 0.3 完成前验证门禁

- 执行子计划的 `Verification Method`，将实际命令和结果写入 `Evidence` 所指开发日志、测试或截图位置。
- 数据库任务必须给出升级、结构、回填、幂等、行数、空值、重复和孤儿核对；约束切换需有恢复方案。
- API 任务覆盖正常、空数据、非法参数、无权限、冲突、幂等与导出重新验权。
- 页面任务完成真实 API 联调、构建、390/768/1440 视口和加载/空/错/无权状态验证。
- 发布前执行 `python -m pytest`、`npm --prefix apps/web run build`、治理校验、计划一致性、`git diff --check`，并记录生产 smoke test 与回退判断。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.11 | `python --version` |
| Node.js | >= 20 | `node -v` |
| npm | >= 10 | `npm -v` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 原始订单/券仍以平台字符串 ID 为主键，券只按字符串订单 ID 关联 | P0 | 无法安全切换内部关联，迁移风险高 | T1.1、T2.5 | 已完成本地实现与验证；真实 PostgreSQL 迁移验收保留到 T4.1 |
| `dim_sku_product_rules` 仅有单费率，缺商品当前快照、历史、双费率、导入与结算范围版本表 | P0 | 商品与规则没有统一、可审计事实源 | T1.2、T2.1、T2.2 | Schema、商品同步内部链路、双费率与原子导入管理 API 已完成；真实商品 API 联调待外部样例 |
| 结算仍覆盖式重建 `settlement_order_details`，退款直接整体排除，缺不可变结果、调整、账单和当前指针 | P0 | 无法复核部分退款、日级费率和锁账历史 | T1.3、T2.3、T2.4 | 已完成 Schema、双方向不可变结果、当前指针、事件调整、三层账单冻结和双费用投影；PostgreSQL 并发与大数据量验证保留到 T4.1 |
| 榜单、单店分账和明细 API 仍是旧 snake_case 单分佣契约 | P0 | 四个页面无法消费已确认的双费用口径 | T3.1 | 已完成本地实现与验证；目标回归 30 passed、全 API 135 passed |
| Web 仍使用旧三指标、旧分佣表和通用订单明细，没有生产开票指引页 | P1 | 页面与 4 份 subprd 不一致 | T3.2 | 已处理 |
| `/admin/rules` 仍是单费率批量覆盖式保存，缺版本、原子导入、商品同步运行与历史 | P1 | 管理员无法安全配置和追溯 | T3.3 | 已处理 |
| 外部商品 API 样例、稳定归属账号 ID、真实渠道枚举与最终权限矩阵未关闭 | P0 发布依赖 | 阻断生产数据正确性和权限验收 | T2.1、T2.3、T4.1 | 外部依赖 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI 执行 -> 人审核 | 技术取证、TDD、迁移与服务实现、接口和页面联调、数据核对、文档和状态回写 |
| 人类 Owner | 审阅本计划；提供/确认外部 API 样例、稳定账号 ID、渠道枚举；完成财务、运营和权限业务验收 |
| Linear | 需求范围、优先级、Issue 状态、验收和剩余风险的权威来源 |

边界：本计划不执行真实资金划拨，不开放账单确认/锁账/解锁或发票写接口，不把当前单费率自动复制成首批正式双费率，不扩建 DYDATA-32 的完整权限管理功能，不重新实现 DYDATA-23。

## 3. 执行阶段

### Phase 1：兼容迁移与目标数据地基

**Entry Criteria**：计划获审阅确认；本地 Alembic head、模型和现有测试基线可复现。

**Exit Criteria**：原始订单/券兼容 ID 已回填且旧读写仍可用；商品/规则和结算目标表、约束与模型均可通过空库升级和结构测试。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [原始订单/券兼容 ID 扩展](sub-delivery-plan-dy-data-T1.1-raw-id-compat.md) | 已完成（2026-07-20） |
| T1.2 | [商品、双费率与导入 Schema](sub-delivery-plan-dy-data-T1.2-product-rule-schema.md) | 已完成（2026-07-20） |
| T1.3 | [双费用结算与报表 Schema](sub-delivery-plan-dy-data-T1.3-settlement-schema.md) | 已完成（2026-07-20） |

### Phase 2：领域写入与结算事实

**Entry Criteria**：T1.1～T1.3 完成；目标模型与迁移可用。T2.1 的生产验收还要求外部商品 API 脱敏样例。

**Exit Criteria**：商品同步不覆盖人工字段；双费率和批量导入可审计且原子；双费用结果、调整、账单与投影可按已确认口径重建；主键切换核对通过。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T2.1 | [商品在线同步与历史](sub-delivery-plan-dy-data-T2.1-product-sync.md) | 已完成本地实现与验证（2026-07-20）；生产验收依赖外部样例 |
| T2.2 | [SKU 商品、双费率与原子导入 API](sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md) | 已完成（2026-07-20） |
| T2.3 | [不可变双费用结果与调整](sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md) | 已完成（2026-07-20） |
| T2.4 | [账单冻结与月度/榜单投影](sub-delivery-plan-dy-data-T2.4-statement-projections.md) | 已完成（2026-07-20） |
| T2.5 | [原始订单/券应用与约束切换](sub-delivery-plan-dy-data-T2.5-raw-id-cutover.md) | 已完成本地实现与验证（2026-07-20） |

### Phase 3：查询契约与生产页面

**Entry Criteria**：T2.2～T2.5 完成；查询可从目标事实和投影读取；最终权限矩阵至少能支持服务端门店范围重验。

**Exit Criteria**：22 个目标 API 中本轮运行接口可用；四个页面和后台管理入口通过真实 API、权限、导出与响应式验收；旧 `/order-details` 保持通用查询语义。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T3.1 | [结算筛选、榜单、单店与订单费用 API](sub-delivery-plan-dy-data-T3.1-reporting-api.md) | 已完成本地实现与验证（2026-07-20） |
| T3.2 | [四个门店结算生产页面](sub-delivery-plan-dy-data-T3.2-settlement-pages.md) | 已完成（2026-07-21） |
| T3.3 | [商品、费率、导入与同步后台](sub-delivery-plan-dy-data-T3.3-admin-console.md) | 已完成（2026-07-21） |

### Phase 4：数据正确性、联调与生产放行

**Entry Criteria**：T3.1～T3.3 完成；外部商品 API、稳定归属账号 ID、真实渠道枚举和 DYDATA-32 权限矩阵均已关闭或由 Owner 明确接受受限发布。

**Exit Criteria**：迁移前后数据核对、全量自动化、真实浏览器、目标环境升级、部署 smoke test、回退判断和业务验收证据全部记录到 Linear 与开发日志。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T4.1 | [端到端核验与生产发布](sub-delivery-plan-dy-data-T4.1-release-verification.md) | 进行中（等待外部依赖） |

## 4. 任务看板

- 看板入口：[task-kanban-dy-data.md](task-kanban-dy-data.md)

## 5. 发布闸门

- [ ] 所有 Task 的 `Requirement ID -> Verification Method -> Evidence` 可追溯，三处状态一致。
- [ ] 原始订单/券迁移的行数、ID 空值/重复、业务 ID 唯一、订单—券孤儿、重复采集幂等和结算样例差异均为 0 或有明确处置。
- [ ] 首批正式双费率由管理员从 `2026-08-01` 发布，未从旧 `commission_rate` 自动复制；后续可选择到自然日。
- [ ] `.xlsx` 与 UTF-8 `.csv` 导入在 10 MiB、5000 行边界内全量校验；任一行错误时正式规则零写入，并能下载逐行结果。
- [ ] 推广费按销售业务日/销售门店，管理费按核销业务日/核销门店；仅有效商品、稳定归属账号和直播/短视频渠道纳入。
- [ ] 部分/全额退款和取消核销形成独立调整；原结果、已锁账账单和规则版本不被覆盖。
- [ ] 全国榜单、单店分账、订单费用明细和导出均服务端重验权限；全国前 20 例外不扩展明细权限。
- [ ] 开票页仅为静态只读指引，无发票、账单确认或财务写操作。
- [ ] 外部商品 API 样例、稳定归属账号 ID、真实渠道枚举和最终权限矩阵已形成生产验收证据。
- [ ] `python -m pytest`、Web build、治理校验、计划一致性、目标环境迁移和生产 smoke test 通过。

## 6. 风险与应对

| 风险 / 依赖 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 外部商品 API 无正式样例 | 无法冻结字段、游标、限流与错误映射 | T2.1 只允许基于白名单 fixture 搭骨架；生产验收前必须取得成功/空页/错误样例 | 人类 Owner 提供，AI 校验 | 阻塞生产验收 |
| 稳定归属账号 ID 与真实渠道枚举缺失 | 可能错误计费 | 未知渠道默认不计费并记录质量问题；T4.1 前必须确认真实值 | 人类 Owner + AI | 阻塞数据正确性验收 |
| DYDATA-32 权限矩阵未最终冻结 | 查询/导出可能越权 | 复用现有后端门店范围；发布前按最终矩阵补角色矩阵测试，不在前端授权 | 人类 Owner + AI | 发布依赖 |
| 订单/券主键切换锁表或产生孤儿 | 采集与结算中断 | 两阶段迁移、批量回填、影子核对、前滚修复；不删除业务 ID | AI 执行 -> 人审核 | 高风险 |
| 旧单分佣调用方仍在使用 | 契约切换造成回归 | 保留旧 `/order-details` 和只读兼容边界；目标页面独立切换新双费用接口 | AI | API 兼容边界已控制；T3.2 页面切换已完成 |
| 后台页面没有独立 subprd | UI 可能无边界扩张 | T3.3 仅复用现有 `/admin/rules` 与 `/admin/sync` 布局，实现 Foundation 已冻结字段和 Linear 验收；新增交互先回到 Linear/PRD | AI -> 人审核 | 已控制 |
| 2026-07 测试数据混入正式账期 | 累计、账单和开票口径错误 | 投影和 API 固定正式起点 `2026-08`，专项回归验证 | AI | T2.4 投影与 T3.1 API 均已控制 |

## 7. AI 执行示例

1. 开始 T3.1：先读取 SubPRD 1～3 的查询契约与子计划，按筛选、榜单、单店汇总、订单费用明细、导出和权限边界补红灯测试，再实现生产查询 API。
2. 继续 T3.3：复用现有 `/admin/rules` 与 `/admin/sync`，按 Foundation 契约实现商品人工字段、双费率版本发布、整批原子导入及同步运行历史。

## 8. PRD → 任务反向索引

| 需求来源 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| DYDATA-38；Foundation Schema §5、商品与原始数据 §7-§8 | DYDATA-38-S1 | T1.1 | [T1.1](sub-delivery-plan-dy-data-T1.1-raw-id-compat.md) |
| DYDATA-1/21/30；Foundation 商品/规则 Schema | DYDATA-1-SCHEMA / DYDATA-21-SCHEMA / DYDATA-30-SCHEMA | T1.2 | [T1.2](sub-delivery-plan-dy-data-T1.2-product-rule-schema.md) |
| DYDATA-31/33；Foundation 结算与报表 Schema | DYDATA-31-SCHEMA | T1.3 | [T1.3](sub-delivery-plan-dy-data-T1.3-settlement-schema.md) |
| DYDATA-30；Foundation 商品同步 API §1-§5 | DYDATA-30-SYNC | T2.1 | [T2.1](sub-delivery-plan-dy-data-T2.1-product-sync.md) |
| DYDATA-1/21；Foundation SKU、双费率与导入 API §1-§13 | DYDATA-1-ADMIN / DYDATA-21-RULES | T2.2 | [T2.2](sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md) |
| DYDATA-31；术语表及结算 Schema §1-§3 | DYDATA-31-FEE | T2.3 | [T2.3](sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md) |
| DYDATA-31；结算 Schema §4-§8 | DYDATA-31-STATEMENT | T2.4 | [T2.4](sub-delivery-plan-dy-data-T2.4-statement-projections.md) |
| DYDATA-38；Foundation Schema §5 第二阶段 | DYDATA-38-S2 | T2.5 | [T2.5](sub-delivery-plan-dy-data-T2.5-raw-id-cutover.md) |
| SubPRD 1 §3-§6、SubPRD 2 §3-§8、SubPRD 3 §3-§8 | DYDATA-33-API | T3.1 | [T3.1](sub-delivery-plan-dy-data-T3.1-reporting-api.md) |
| 4/4 SubPRD；9 条 locked 交互语义 | DYDATA-33-WEB | T3.2 | [T3.2](sub-delivery-plan-dy-data-T3.2-settlement-pages.md) |
| DYDATA-1/21/30；Foundation 管理接口 | DYDATA-ADMIN-WEB | T3.3 | [T3.3](sub-delivery-plan-dy-data-T3.3-admin-console.md) |
| MainPRD §4-§6；全部 issue 验收 | DYDATA-RELEASE | T4.1 | [T4.1](sub-delivery-plan-dy-data-T4.1-release-verification.md) |
