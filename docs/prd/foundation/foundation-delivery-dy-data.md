# Foundation 交付清单 - dy-data（抖音经营引擎）

> 生成时间: 2026-10-27；2026-10-31补记10月30日已确认合同（S4增量回捞，历史记录保留）
> Skill: foundation-builder
> 模式: 增量更新
> 范围: 已确认 DYDATA-104 分类/账期、月末资格、精确历史归属/纠错、财务预览/撤销与整账来源权威；同步相关既有发票来源。不修改原业务事实，不新增规则，不代表部署或生产闭环验收。

## 上游依赖

| 上游 Skill | 产物文件 |
|---|---|
| brd-writer | docs/brd/BRD-dy-data-20260716-1255.md |
| page-designer | src/frontend/page-preview/page-delivery-dy-data.md |
| page-explainer | src/frontend/page-preview/explainer-flow-dy-data.md<br>src/frontend/page-preview/explainer-b-interaction-dy-data.md<br>src/frontend/page-preview/explainer-delivery-dy-data.md |
| 冻结规格 | docs/superpowers/specs/2026-08-20-dydata-19-settlement-finance-design.md |

## 交付产物

| 产物 | 文件路径 | 行数 | 拆分子文件 |
|---|---|---:|---|
| 术语表 | docs/prd/foundation/foundation-glossary-dy-data.md | 203 | — |
| 数据库 Schema | docs/prd/foundation/foundation-schema-dy-data.md | 154 | docs/prd/foundation/foundation-schema-dy-data/account-qualification.md<br>docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md<br>docs/prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md<br>docs/prd/foundation/foundation-schema-dy-data/historical-sale-attribution.md<br>docs/prd/foundation/foundation-schema-dy-data/invoice-source.md<br>docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md<br>docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md |
| API 接口设计 | docs/prd/foundation/foundation-api-dy-data.md | 299 | docs/prd/foundation/foundation-api-dy-data/billing-invoice.md<br>docs/prd/foundation/foundation-api-dy-data/common-contract.md<br>docs/prd/foundation/foundation-api-dy-data/product-sync.md<br>docs/prd/foundation/foundation-api-dy-data/settlement-authority.md<br>docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md<br>docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md |

## 产物摘要

| 指标 | 数值 |
|---|---|
| 数据表范围 | 33 张核心设计/回捞表（含0051、0065和0066）+ 5 张既有依赖表 + 本轮引用定义的3张既有发票来源支持表；不是全库表数 |
| API 接口范围 | 主索引编号44项；另列既有分类批量/导入5条路径，非全库路由总数；资格与仅发布CLI不新增HTTP写接口 |
| DYDATA-19 新增接口 | 20 |
| DYDATA-19 新增表 | 11（并变更 `settlement_statement` 版本模型） |
| DYDATA-19 冻结交互语义 | 4 |
| 正式累计起点 | `2026-08` |

## 一致性自查结果（2026-08-21 历史检查）

- 检查时间: 2026-08-21
- DYDATA-19 页面可写操作覆盖率: 5/5 (100%)
- 新增 API ↔ Schema 覆盖率: 20/20 (100%)
- 新增表消费覆盖率: 9/9 (100%)
- 交互语义 → API/Schema 覆盖率: 4/4 (100%)
- 术语一致性: 全部通过
- 孤立项: 无
- 文件拆分约束: 主文件及全部子文件均少于 400 行

## 已确认的 DYDATA-19 关键边界

- 开票与厂端审核在系统外完成；系统不创建开票申请单、不执行开票、不创建审核任务。
- 门店账号按费用方向确认账单、提交异议和登记推广费发票；财务人员使用管理员角色导入结果，管理员与最高管理员在本模块权限一致。
- 推广费状态固定为“待开票 / 提交成功，待厂端审核 / 审核通过，已结算 / 审核不通过，请重新上传”；管理服务费不套用此审核状态链。
- 账单、发票和四类导入均采用不可变版本；更正覆盖当前指针，不删除历史。四类导入任一错误行时正式业务表整批零写入。
- 四类导入固定为基础信息、推广服务费厂家结果、管理服务费厂家结果和 SAP 确认；管理服务费厂家结果在同一行登记发票与全额厂家扣款，不再拆成两个模板。
- 推广费发票号码只在当前有效版本中唯一；状态导入或更正可沿用原号码生成新版本，历史版本通过 `supersedes_invoice_id` 永久保留。
- 门店只按 `store_id` 精确匹配；禁止 SAP 编码、名称、金额或月份模糊匹配。推广费一张发票可覆盖同一门店多个完整账期，但每个账期仅一条当前有效分配且不得拆分；管理服务费仍是一门店一账期一张当前有效发票/厂家扣款事实。
- 单月与正式累计同时可查；正式累计从 `2026-08` 开始，确认金额只显示单月。历史审计可归档低成本存储，但必须可查询。

## 外部依赖与非阻断项

| 项目 | 当前处理 | 影响 |
|---|---|---|
| 企业微信发送 | 本期未开发，不设计接口 | 不阻断发票登记与状态导入 |
| 外部真实开票/厂端审核 | 系统外业务，系统仅登记和导入结果 | 不纳入系统验收 |
| DYDATA-22 身份治理 FCR | 与 DYDATA-19 无关，保持待评审且未消费 | 不影响本次财务底座设计 |
| DYDATA-32 页面权限登记 | 页面设计缺口保持 out_of_scope | 正式开放新生产路由前需独立完成 |

## 下游可消费信息

| 下游 Skill | 应读取 | 用途 |
|---|---|---|
| planner / prd-writer | 本清单、glossary、schema、api、冻结规格和全部拆分子文件 | 生成实施计划、验收映射、迁移顺序和接口任务 |

## 下游进入条件

- 任务拆分必须以本清单声明的相对路径为准，不从历史评论重新拼接需求。
- API 和 Schema 是目标契约，不表示运行代码、迁移或生产适配已经实现。
- 开发顺序必须先完成迁移与领域服务，再接 API 和页面；所有写操作必须包含权限、幂等、版本冲突和审计测试。

## DYDATA-87 已确认口径增量（2026-09-09）

【用户确认】两费均须有效核销，统一按有效核销月计入、有效核销日匹配各自费率版本、同一核销实收基数计算。确认来源为 [DYDATA-87 控制规格](../../plans/2026-09-09-dydata-87-settlement-invoice-controller-spec.md) 的最新确认；追踪请求为 `S4-FCR-013`，状态由主控维护，本清单不宣称已发布生产。

推广仍归销售门店、管理仍归核销门店；保留独立配置费率和历史不可变结果。销售时间/月为独立展示及筛选事实，不替代费用核销日期。取消核销影响两方向，已冻结来源通过独立调整追溯；不改写旧账单、确认或发票事实，不新增系统内开票/审核工作流。

### 变更与字段追溯

| 变更 | 术语/字段 | Schema 来源 | API 响应 | 页面消费 |
|---|---|---|---|---|
| **变更** | 原始发生月份 | `settlement_fee_result.original_business_month`（有效核销月） | `GET /api/v1/order-fee-details` 的 `list[].originalBusinessMonth` | `apps/web/src/pages/OrderDetailsPage.tsx` 原始/销售/核销月 |
| **变更** | 规则匹配日 | `settlement_fee_result.rule_match_date`（有效核销日） | 同接口 `list[].ruleMatchDate` | 同页面匹配日 |
| **变更** | 共同核销实收金额/基数 | `settlement_fee_result.source_amount_cent / fee_base_cent` | 同接口 `list[].sourceAmountCent / originalBaseCent` | 同页面来源金额/原始基数 |
| 不变 | 销售月份 | `raw_douyin_orders.sale_time` 按上海时区派生 | 同接口 `list[].saleMonth` | 同页面销售月筛选及列 |
| 不变 | 各方向费率 | `settlement_fee_result.fee_rate / rule_version` | 同接口 `list[].feeRate / ruleVersion` | 同页面实际费率及版本；查询不重算 |

### 本轮检查边界

- C2：本次无页面可编辑字段、新请求或 UI 结构变更；不新增费用字段写入 API。
- C3/C4：上表涉及的日期、月份、来源金额和基数字段已逐项与 glossary、Schema、API、03 子 PRD 对齐；未新增表、接口或改变字段类型。
- C5：本次变更字段均有既有明细 API/页面消费，未发现本次新增孤立字段。
- C6/C7：沿用现有已冻结交互边界；本轮仅同步用户已确认的计算口径，不重写历史 explainer 或快照，不宣称完成所有 locked 条目的全量重验。
- 本轮为限定写集的文档一致性核查，不复用上方历史百分比宣称全量页面/API/Schema 覆盖；未运行浏览器、业务计算测试或部署。S2 路由结构校验与治理测试结果由本轮交接记录提供。
- 下游同步：`docs/prd/subprd/03-subprd-order-fee-details.md`、`docs/plans/delivery-plans/main-delivery-plan-dy-data.md`、`docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md`；T2.3 历史完成状态不代表本次增量验收完成。

### FCR013 结构与发布合同补齐

- 可消费结构：0051 的 `qualifying_verify_id/time/store_id/name`、`reverification_anchor_id`、锚点复合普通索引，以及 `SettlementBillingSourceBundle` 七字段、复合主键、JSONB 和应用侧创建时间；以实际 models/迁移为依据，不虚构自增 ID、外键或默认值。
- 可消费内部合同：冻结来源及空槽位、完整性指纹、job → active → slot 锁顺序、锁后重查、新槽位新事务重试；发布与待确认生成最终同事务、来源/投影及账单三层一致性、零来源新版本、无变化幂等和受保护事实跳过；来源漂移必须新 job，不覆盖冻结包。
- 追溯：`settlement_fee_result.qualifying_verify_*` → `_statement_source_snapshots` → 私有 `StatementSource[]` → `settlement_statement_entry` 的核销时间/门店快照 → 授权账单详情；`reverification_anchor_id` 仅为内部调整血缘，不新增公开参数。`job_events` 完成标记保存计数/指纹，不保存详细来源。
- 来源：`apps/api/dy_api/models.py`、`alembic/versions/20260909_0051_fee_result_verification_provenance.py`、`apps/worker/billing_source_capture.py`、`apps/worker/billing_statements.py`、`apps/worker/settlement_rebuild.py`；Schema 索引和账单 Schema/API 已同步，未新增接口。
- 不宣称 FCR013 全部完成：文档回捞不代替主控的核销/重核销全量边界回归、生产迁移、部署、数据重算和用户验收；FCR013 状态仍由主控维护。

### 校验命令与结果

- 结构补齐后运行 `python -m pytest tests/test_billing_source_capture.py tests/test_billing_statement_generation.py tests/test_billing_publication_locks.py -q --tb=short`：32 passed、2 skipped；两项需 `DY_RELEASE_POSTGRES_URL` 指向可丢弃 PostgreSQL 服务，当前未配置，不视为并发 PostgreSQL 验证通过。
- 补齐后重新运行 suite-lock 和 scoped `git diff --check`：通过；S2 foundation 门禁仍通过，整体阶段日志检查仍未通过，交主控收口。

- `git diff --check`：通过（仅既有前端文件换行符警告）。
- `python -m pytest tests/test_project_governance.py -q --tb=short`：9 passed。
- `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S2 --json`：`foundationReadyForPrd.pass=true`、`pageStageClosedForPrd.pass=true`；整体退出码 1，`stageWritebackBeforeRouting.pass=false` / `stage_transition_writeback_missing`。当前 S4 至 S2 的阶段日志回写由主控负责，本次限定文档写集不修改日志，不将局部 foundation 门禁通过表述为 S2 整体放行。
- `node .agent/project-manager-suite/skills/00-03-project-link-indexer/scripts/run-project-link-indexer.mjs . --trigger need_broken_link_or_reverse_link_check --json`：只读检查报告全库 33 项问题，本轮七份文档无命中；未重写索引或扩展修复范围。

## DYDATA-104 回捞与一致性（2026-10-27）

本轮消费已确认增量及 `foundation-change-requests-dydata-104-oct23.md` 的004—008，并消除001—003仍冲突的发票来源、历史下架SKU与精确归属合同。仅建议主控评审状态；本清单不修改FCR、上游冻结记录、开发计划或生产数据。

| 增量 | 可消费文件 | 精确依据/约束 |
|---|---|---|
| 004 普通类型/默认月 | glossary、product-rule-source、SKU/common/reporting API | `product_classification.py`、fee_admin schemas/routes、[现有分类合同](../../api/product-type-classification.md)；独立打榜scope不变，财务历史类型不改 |
| 005 冻结字段预览/撤销 | billing-invoice Schema/API | `dashboard.py` 的 capture/list preview/commit/reversal、前端 FinanceImportPreviewTable/types；__preview上传时固化、summary全批、finalSapCode与type1链、号码锁/依赖保护 |
| 006 已批准人工纠错 | historical-sale-attribution、settlement-authority | 精确原费用锚点、既有MANUAL_CORRECTION与finance audit；非零/零差额及退款边界，拒绝扩大批准范围 |
| 007 月末资格 | account-qualification、settlement-authority、费用结果字段 | models/0066/account_qualification/month_close/settlement；三表、nullable FK、仅version来源counter、完整导出proof、窗口和容量预算 |
| 008 整账权威/仅发布 | settlement-authority、settlement-reporting | protected_billing_authority、settlement_publication_only与CLI；entry+原fee、经济/展示NULL分离、status4拒绝、无fee重算/指针替换 |
| 001—003 关联冲突 | invoice-source、billing-invoice、historical-sale-attribution | 可信合票金额/负抵扣/号码归属、已知INACTIVE档案其余检查、0065精确核销决定；不回填旧月结果 |

C2/C3 核查了本次页面写字段、模板及冻结预览响应到实际 routes/types/models 的映射；C4 统一账号/UID/短号、资格观察/版本、整账权威及展示/经济金额术语；C5 三个资格表、历史决定及私有来源包均有内部消费者，无公开CRUD是有意边界。C6/C7 对照既有 locked 交互范围及本次已确认规则，保留双方向独立操作与现有发票状态机；不凭历史百分比宣称61个页面或所有运行路由已全量重验。

全部声明 Foundation 文件检查本地链接和<400行约束。宿主 PostgreSQL/models/迁移及 `{data,definitions?,meta}` 覆盖套件默认MySQL/响应示例；不补造自增ID、默认值、外键禁令或HTTP资格写入口。原历史检验记录留存，其百分比不作本轮验收证据。

### 本次验证与待主控收口

- `python -m pytest tests/test_project_governance.py -q --tb=short`：9 passed，退出0。
- `verify-suite-lock.mjs . --json`：valid，套件v2.0.1；`validate-global-files.mjs . --json`：0 errors/0 warnings。
- 逐文件本地链接存在性与行数检查：无失效路径，全部<400行；交付清单已枚举全部拆分文件并回填实际行数。
- `route-check.mjs . --target-stage S2 --json`：foundationReadyForPrd.pass=true、pageStageClosedForPrd.pass=true；整体退出1/canEnter=false，唯一失败子门禁为既有 stageWritebackBeforeRouting（当前S4、阶段回写由主控处理）。不把子门禁通过视为阶段切换。`git diff --check`：退出0，仅既有换行规范提示。
- 未生产：没有采集、资格冻结、数据库迁移/写入、历史修复、费用重算或发布。月末实际采集、冻结后自动重算/月结链、真实覆盖与部署验收仍由主控验证；不把合同回捞或fixture当作运行闭环完成。
- 无新增业务规则待确认；004—008及相关001—003的状态由主控根据本提交和运行证据回写。既有项目阶段日志/上游文档的一致性治理超出本次限定写集，保留交主控。

## 2026-10-30 增量回捞

本轮依据用户已确认的五项，回捞展示/原财务分类、中文模板与隔离示例、资料与SAP准确来源继承、正式处理计数、逾期方向确认/hold。未新增数据库表列、业务页或无鉴权HTTP写接口，不改旧冻结事实；实现和生产状态见[交付证据](../../verification/dydata-104-oct30-delivery.md)。

| 一致性 | 核对范围 |
|---|---|
| C2/C3 | 财务模板中文字段→规范化键→profile/厂家结果；预览统计从row_status和冻结载荷派生；确认由正式版本与方向记录。 |
| C4 | productType展示与snapshotProductType原文、校验有效与正式写入、厂家确认与人工更正依据分别定义。 |
| C5 | 复用既有审计/导入行/档案表，无新孤立表字段；worker hold/恢复入口为有意的非HTTP边界。 |
| C6/C7 | 保留既有双方向/全组开票/原子导入、权限及版本语义；以10月30日明确用户确认覆盖旧scope和基础列表状态列冲突，不伪造新locked语义。 |

本轮为已确认业务合同的增量记录；新集成CI与生产处理仍独立验收，未据此切换项目阶段或关闭104。


## 2026-10-31 仅发布CLI增量一致性

S4-FCR-020仅同步非HTTP运维参数的派生观察预算及显式上限。C2/C3无页面写字段、公开API或Schema变化；C4继续使用正式压力策略的recovery/stable/ALLOW术语；C5无新表列；C6/C7保留原鉴权、实际资源观察、claim/lease和精确来源hash，不将等待时间当准入许可。主入口沿用104既有授权处理技术参数缺口，无新增业务规则待确认；全量基础文件行数/链接及门禁继续按交付检查，阶段保持S4。
