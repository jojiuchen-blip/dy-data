# dy-data Foundation 变更请求

> 本文件记录 S4 实装从真实代码与迁移约束中发现的 Foundation 漂移。条目由 `coding-standards` 追加，由 `ai-project-manager` 裁决并交给 `foundation-builder` 修订；不得在此文件直接替代 Foundation 正文。

## S4-FCR-006：旧轮次原地转为正式轮次并保留历史身份

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-006` |
| 来源 Task | `DYDATA-34 / T1.1 旧分配引擎全面下线` |
| 分类 | `DRIFT` |
| 改动项 | 旧 `execution_mode=legacy` 轮次不删除、不生成替代 ID，而是在迁移门禁通过后原地改为 `formal`；保留轮次 ID、门店归属、轮次序号、状态、时间及跟进记录引用。现有活动轮次同时关闭自动过期，正式自动分配和自动再分配继续保持关闭。 |
| 原因 | 当前系统尚未正式投入门店生产使用，用户明确不存在需要保留为独立语义的“历史旧轮次”；原地转换可以恢复现有有效线索的可操作性，并避免重建造成归属和跟进历史断链。 |
| 指向代码块 | `alembic/versions/20260831_0046_retire_legacy_clue_rounds.py`；`apps/worker/clue_center.py`；`apps/worker/clue_operability_recovery.py`；`apps/api/dy_api/routes/_data.py` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-delivery-clue-center.md` 交付边界；`foundation-api-clue-center/jobs-security-and-migration.md` 正式重建与迁移章节；`foundation-schema-clue-center/clue_assignment_round.md` |
| 严重度 | `高（直接影响既有线索是否可跟进及历史引用是否连续）` |
| 状态 | `产品裁决已确认；运行实现、可逆迁移与本地门禁已完成，待 Foundation 正文同步` |

### 实现与门禁

- 转换前阻断未知模式、正式命名空间冲突、活动轮次归属/指针异常、同一主档多个活动旧轮次及跟进记录跨表归属不一致。
- 迁移只改变命名空间和活动轮次自动过期开关；不重写主档指针、线索中心投影、门店归属、SLA 时间或跟进记录。
- 迁移保留精确回滚日志；降级只恢复本次转换的轮次及其原始自动过期开关，出现后续正式命名空间冲突时拒绝降级。
- 业务列表、指标、导出、联系方式和跟进只读取 `formal`；`trial` 继续作为隔离证据，不进入经营数据。

## S4-FCR-005：账单响应缺少服务端可确认金额

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-005` |
| 来源 Task | `T5.7 系统 UAT 与发布验收` |
| 分类 | `GAP` |
| 改动项 | 在门店账单列表与详情响应中补充 `promotionConfirmableAmountCent`、`managementConfirmableAmountCent`，并明确其为确认写接口校验的服务端权威金额。 |
| 原因 | 账单确认接口会扣除活动中异议的冻结金额，并对管理费结果执行不小于零的约束；现有 Foundation 仅返回原始方向净额，前端无法在不复制业务规则的情况下提交必然通过服务端校验的金额。 |
| 指向代码块 | `apps/api/dy_api/routes/dashboard.py` 的 `_statement_confirmable_amounts` 与 `_statement_header_item`；`apps/web/src/types/dashboard.ts` 的 `StoreBillingStatement`；`apps/web/src/pages/StoreSettlementPage.tsx`；`tests/test_api_store_billing.py`；`tests/test_frontend_store_settlement_confirmation.py` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md §2.1～§2.3` |
| 严重度 | `高（存在活动异议时，缺少该字段会使前端按原始净额确认并收到 422）` |
| 状态 | `待评审` |

### 建议契约

- 两个字段均由服务端按当前账单版本实时返回；前端只展示并原样提交，不自行复制异议状态或金额计算规则。
- 可确认金额等于对应方向净额减去活动中异议冻结金额；管理费结果最低为零。
- 确认写接口与账单读接口必须复用同一计算口径；活动异议、成功确认及无异议场景均需保留 API 回归测试。

## S4-FCR-004：财务导入四模板仍保留旧拆分口径

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-004` |
| 来源 Task | `T5.5 四类财务导入与更正` |
| 分类 | `DRIFT` |
| 改动项 | 将旧的“推广审核结果、推广结算结果、管理费发票明细、厂家扣款结果”替换为 Linear 正文冻结的“基础信息、推广服务费厂家结果、管理服务费厂家结果、SAP 确认”；管理费发票与扣款合并为同一模板。 |
| 原因 | 旧 SubPRD/Foundation 在正文收敛前形成，和 DYDATA-19 当前 Linear 权威正文冲突；若继续实施会缺失基础/SAP 版本事实并重复管理费导入。 |
| 指向代码块 | `apps/api/dy_api/routes/dashboard.py`；`apps/api/dy_api/models.py`；`alembic/versions/20260821_0034*`～`0036*`；`tests/test_api_finance_imports.py` |
| 目标 foundation 文件:章节 | `foundation-glossary-dy-data.md`；`foundation-schema-dy-data/billing-invoice.md §4～§7`；`foundation-api-dy-data/billing-invoice.md §5` |
| 严重度 | `阻断（旧模板不可作为发布契约）` |
| 状态 | `已改（2026-08-21；Linear 最终四模板、Schema、API、术语、迁移和测试已统一）` |

### 裁决与实现

- Linear 为需求权威，当前正文覆盖旧 SubPRD 和历史评论中的拆分模板。
- 基础信息与 SAP 确认写入 `store_finance_profile` 不可变版本；推广厂家结果按发票号码精确匹配；管理厂家结果按门店与账期原子登记发票及全额扣款。
- 上传和提交分别保留幂等键与规范化请求摘要；同键不同请求返回 409，同内容新键返回无变化。

## S4-FCR-003：推广费发票号码唯一范围与不可变版本冲突

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-003` |
| 来源 Task | `T5.5 四类财务导入与更正` |
| 分类 | `DRIFT` |
| 改动项 | 将 `promotion_invoice.invoice_number` 的“全历史唯一”改为“仅当前版本唯一”，允许同一张外部发票在状态导入或更正时使用原号码生成 Vn+1，同时通过 `supersedes_invoice_id` 保留版本链。 |
| 原因 | Foundation 同时要求推广费发票和四类财务导入采用不可变新版本，但 §4.1 又把发票号码定义为全局唯一；同号 V2 会直接违反唯一约束，导致外部审核结果无法按版本落库。 |
| 指向代码块 | `apps/api/dy_api/models.py` 的 `PromotionInvoice`；`alembic/versions/20260821_0033_promotion_invoice_version_number.py`；`tests/test_alembic_migrations.py`；`tests/test_api_store_billing.py` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md §4.1` |
| 严重度 | `阻断（阻塞推广费审核/结算结果的不可变版本提交）` |
| 状态 | `已改（2026-08-21；Foundation Schema/Delivery、页面说明、模型、迁移与回归已统一为当前版本部分唯一）` |

### 建议裁决

- 发票号码继续标识同一外部发票事实，但只约束一个当前有效版本；历史版本允许重复该号码。
- 新版本仍使用新的 `invoice_id`，并以 `supersedes_invoice_id` 指向上一版本；任何时刻只允许一条同号 `is_current=true` 记录。
- 若后续需要区分“同号状态版本”与“换票版本”，应新增稳定发票链 ID，而不是恢复全历史号码唯一并覆盖旧记录。

## S4-FCR-002：推广费发票跨账期口径冲突

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-002` |
| 来源 Task | `T5.2 门店确认与推广费发票登记` |
| 分类 | `DRIFT` |
| 改动项 | 统一推广费发票是否可以覆盖多个完整账期，以及对应的数据模型、请求字段和查询展示方式。 |
| 原因 | DYDATA-19 当前正文规定“同一门店、同一开票主体的一张发票可覆盖多个完整账期，并按账期保存独立分配行”；但 Foundation API §4.2 与 T5.2 子计划仍规定 `statementId + statementMonth`、一门店一账期一张有效发票、不得跨账期。两种口径不能同时实现。 |
| 指向代码位 | `apps/api/dy_api/models.py` 的 `InvoiceRecord` 当前按 `store_id + statement_month + fee_direction` 建模；尚未开始 `POST /api/v1/promotion-invoices` 写入实现。 |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md §4.1–4.2`，以及对应 Schema / SubPRD 发票分配规则。 |
| 严重度 | `阻塞（仅阻塞推广费发票接口 #29–#30；不阻塞账单读取与费用确认 #23–#25）` |
| 状态 | `已改（2026-08-21；Foundation Schema/API/Delivery 已按 DYDATA-19 当前正文收敛）` |

### 裁决与实现边界

- 采纳 Linear 当前正文的“可跨多个完整账期 + 账期分配行”。新增发票—账期分配实体；“一个账期不得拆分多张发票”解释为每个账期只能被一个当前有效分配覆盖。
- 推广费 `POST /api/v1/promotion-invoices` 以发票主记录和完整账期分配集合原子写入；每一行分配必须等于该账期当前有效推广费确认金额，全部分配严格等于发票金额。
- Foundation 正文的单账期 API 契约需由 `foundation-builder` 按本条更新；当前工作树已有未提交 Foundation 文档修改，T5.2 实现不直接覆盖这些修改。

## S4-FCR-001：补齐月度账单不可变版本模型

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-001` |
| 来源 Task | `T5.1 财务闭环 Schema 与领域地基` |
| 分类 | `GAP` |
| 改动项 | 在 `settlement_statement` 明确定义账单版本号、当前版本标识、版本来源/替代关系及“门店 + 账期仅一个当前版本”的部分唯一索引；移除“门店 + 账期全历史唯一”的旧约束；把账单来源项从全局唯一调整为“账单版本内唯一”，并同步迁移、API 字段和验收说明。 |
| 原因 | SubPRD 2 与 DYDATA-19 API 已要求 `versionNo/isCurrent`、历史版本查询以及异议成立后生成新账单版本；但当前 Foundation Schema §4 仍保留 `uk_settlement_statement_store_month (store_id, statement_month)` 且未定义版本字段，运行模型也因此无法同时保存 Vn 与 Vn+1。 |
| 指向代码块 | `apps/api/dy_api/models.py`；`alembic/versions/20260821_0029_version_settlement_statements.py`；`tests/test_data_schema.py`；`tests/test_alembic_migrations.py` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md §4`；`docs/prd/foundation/foundation-api-dy-data/billing-invoice.md §2.1～§2.3、§3.3` |
| 严重度 | `阻断` |
| 状态 | `已改（2026-08-21；兼容迁移、Schema/API 契约和专属回归均已完成）` |

### 验收口径

- 同一 `store_id + statement_month` 可永久保留多个账单版本，但只能有一个 `is_current=true`。
- `statement_id` 继续作为每个不可变版本的业务 ID；账单行、来源项、确认、异议和发票均精确引用该版本。
- 新版本原子切换当前指针，旧版本及旧确认不可删除；并发切换使用读取版本并返回 409。
- 迁移必须兼容既有账单：历史行回填 `version_no=1`、`is_current=true`，移除旧唯一约束后创建版本唯一约束和当前版本部分唯一索引。
- `settlement_statement_entry` 的来源唯一键包含 `statement_id`，允许 Vn+1 重新快照 Vn 的不可变来源，同时禁止同一版本内重复来源。

### 裁决与实现

- 2026-08-21：用户确认采纳。本次只新增 `20260821_0029` 前向兼容迁移，不修改任何历史迁移文件。
- 已实现 V1 回填默认值、版本唯一约束、当前版本部分唯一索引、版本来源关系与账单版本内来源唯一键；测试覆盖 V1 升级、Vn+1 追加、来源复用和第二个当前版本冲突。
