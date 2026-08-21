# dy-data Foundation 变更请求

> 本文件记录 S4 实装从真实代码与迁移约束中发现的 Foundation 漂移。条目由 `coding-standards` 追加，由 `ai-project-manager` 裁决并交给 `foundation-builder` 修订；不得在此文件直接替代 Foundation 正文。

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
| 状态 | `已采纳（2026-08-21，以 DYDATA-19 当前正文为准）` |

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
| 状态 | `已采纳` |

### 验收口径

- 同一 `store_id + statement_month` 可永久保留多个账单版本，但只能有一个 `is_current=true`。
- `statement_id` 继续作为每个不可变版本的业务 ID；账单行、来源项、确认、异议和发票均精确引用该版本。
- 新版本原子切换当前指针，旧版本及旧确认不可删除；并发切换使用读取版本并返回 409。
- 迁移必须兼容既有账单：历史行回填 `version_no=1`、`is_current=true`，移除旧唯一约束后创建版本唯一约束和当前版本部分唯一索引。
- `settlement_statement_entry` 的来源唯一键包含 `statement_id`，允许 Vn+1 重新快照 Vn 的不可变来源，同时禁止同一版本内重复来源。

### 裁决与实现

- 2026-08-21：用户确认采纳。本次只新增 `20260821_0029` 前向兼容迁移，不修改任何历史迁移文件。
- 已实现 V1 回填默认值、版本唯一约束、当前版本部分唯一索引、版本来源关系与账单版本内来源唯一键；测试覆盖 V1 升级、Vn+1 追加、来源复用和第二个当前版本冲突。
