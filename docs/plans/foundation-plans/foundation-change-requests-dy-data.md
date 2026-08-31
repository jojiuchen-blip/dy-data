# dy-data Foundation 变更请求

> 本文件记录 S4 实装从真实代码与迁移约束中发现的 Foundation 漂移。条目由 `coding-standards` 追加，由 `ai-project-manager` 裁决并交给 `foundation-builder` 修订；不得在此文件直接替代 Foundation 正文。

## S4-FCR-006：门店开票登记与状态查询契约补充

| 字段 | 内容 |
|---|---|
| ID | `S4-FCR-006` |
| 来源 Task | `T1.1 DYDATA-81 门店端财务页面` |
| 分类 | `DRIFT` |
| 改动项 | 门店开票登记增加服务端日期边界校验；发票列表增加号码精确查询条件并在服务端分页前执行；B02 写操作权限按既有页面权限与门店范围控制，不再额外限定仅门店角色。 |
| 原因 | 用户 2026-08-28 最新明确确认覆盖冲突旧讨论：开票日期不得早于账单确认/锁账日且不得晚于服务器北京时间当前日；发票号要求精确服务端查询；管理员不被角色硬编码禁止登记或处理替换。现有 Foundation 尚未完整冻结这些条件。 |
| 指向代码块 | `apps/api/dy_api/routes/dashboard.py` 的推广费发票列表、登记与生命周期端点；`apps/web/src/api/client.ts`；`apps/web/src/pages/StoreInvoicePage.tsx`；`apps/web/src/pages/StoreInvoiceStatusPage.tsx`；`tests/test_api_store_billing.py` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md §4`；对应权限与状态流转章节 |
| 严重度 | `高（日期越界、查询语义或角色硬限制会直接改变门店开票结果）` |
| 状态 | `待评审` |

### 已按最新确认实现的保护边界

- 列表查询使用发票号码精确等值条件，先筛选再计算总数与分页；不在浏览器做号码子串过滤。
- 开票日期下界取所覆盖账期的确认时间、账单确认时间和锁账时间中的最晚日期，上界取服务器北京时间当前日期。
- 页面访问与写操作继续经过 B02、门店数据范围和既有操作权限；不以 `role === store` 作为额外业务限制。
- 本条只记录 Foundation 漂移，不修改财务端页面、财务端接口、导航、权限或测试。

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
