# T5.1 财务闭环 Schema 与领域地基

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.1 建立可版本化、可审计的账单与财务事实地基

**Requirement ID**：DYDATA-19-SCHEMA

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md` §1～§8
- `docs/prd/subprd/02-subprd-store-settlement.md` §3
- `docs/prd/subprd/04-subprd-invoice-registration.md` §3
- `docs/prd/subprd/08-subprd-finance-disputes.md` §3
- `docs/prd/subprd/09-subprd-finance-imports.md` §3

**核心逻辑**：
- 新增确认、异议、异议订单、发票版本、状态事件、导入批次、导入行和财务审计 8 张表；金额使用整数分、时间使用带时区时间。
- 发票、账单、异议与导入只新增版本或事件，不覆盖/删除历史；门店 ID 是唯一匹配键。
- 既有 `settlement_statement` 通过新的前向兼容迁移演进为不可变版本：历史记录回填为 V1 且保持当前，新版本以 Vn+1 新增并原子切换当前指针；来源项唯一性限定在账单版本内。
- SQLAlchemy 模型与 Alembic 迁移同批提交，约束、索引和枚举范围与 Foundation 一致。

**核心文件**：
- `apps/api/dy_api/models.py`
- `apps/api/dy_api/schemas.py`
- `alembic/versions/`
- `tests/test_data_schema.py`
- `tests/test_alembic_migrations.py`

**完成标准**：
- 8 张表、业务唯一键、当前发票部分唯一索引、导入版本字段和审计索引均可从模型元数据与迁移结构核验。
- 空库可升级到 head；重复升级无额外写入；历史迁移文件不被修改，既有结算表仅通过新的前向兼容迁移演进。
- 既有账单升级后为 `version_no=1`、`is_current=true`；同一门店账期可保存多个版本但只能有一个当前版本，Vn+1 可重新快照 Vn 的相同来源。
- SQLite 测试与 PostgreSQL DDL 编译均通过，新增结构测试覆盖主要约束和索引。

**Verification Method**：
- 先补失败的模型/迁移测试，再执行 `python -m pytest tests/test_data_schema.py tests/test_alembic_migrations.py -q`。
- 执行 Alembic 空库升级和 PostgreSQL 离线 SQL 生成，核对 8 张表及约束。
- 从 `20260821_0028` 升级至 head，核对 V1 回填、Vn+1 追加、当前版本部分唯一索引及来源键的版本内唯一性；只在尚未产生 Vn+1 时允许降级。

**Evidence**：
- `docs/devlog/` 中的 T5.1 测试、迁移、表/索引核对记录，以及 `S4-FCR-001` 的已采纳结论。

**Failure Handling**：
- 目标字段与现有账单模型冲突时停止迁移并记录 Foundation 漂移，不复用含义不同的旧字段。
- 迁移存在不可逆破坏或锁表风险时拆成兼容迁移，不修改历史迁移掩盖问题。
- PostgreSQL 验证不可用时不得宣称生产迁移完成，只记录本地和离线证据。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其调度 `delivery-planner` 同步主计划、看板和本子计划，并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：PRD、Foundation 和页面设计回环已冻结

**状态**：进行中
