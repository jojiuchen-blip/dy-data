# T1.2 商品、双费率与导入 Schema

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T1.2 建立商品当前事实、同步历史、双费率、原子导入与结算范围表

**Requirement ID**：DYDATA-1-SCHEMA / DYDATA-21-SCHEMA / DYDATA-30-SCHEMA

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-dy-data.md` §2-§5
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` §1-§6
- Linear DYDATA-1、DYDATA-21、DYDATA-30

**核心逻辑**：
- 扩展 `dim_sku_product_rules` 的平台字段、人工分类字段与双审计边界；同步不得覆盖 `product_scope/product_type/is_service_product`。
- 新增商品同步历史、不可变结算范围、不可变双费率版本及导入批次/逐行表；费率精确到六位小数。
- 不把旧 `commission_rate` 自动复制为正式双费率；首批规则等待管理员明确发布。

**核心文件**：
- `apps/api/dy_api/models.py`
- `alembic/versions/`
- `tests/test_data_schema.py`
- `tests/test_alembic_migrations.py`
- `tests/test_api_admin_sku_rules.py`

**完成标准**：
- 6 张目标表/扩展表及 Foundation 声明的唯一约束、索引、状态和审计字段在模型与迁移中一致。
- `sku_id + effective_date` 冲突可由数据库/服务层稳定拒绝；费率范围为 0～1 且精度满足六位小数。
- 旧 SKU 行升级后人工分类保持不变，正式双费率表为空，旧接口仍可读兼容字段。

**Verification Method**：
- 执行 `python -m pytest tests/test_data_schema.py tests/test_alembic_migrations.py tests/test_api_admin_sku_rules.py -q`。
- 使用 SQLAlchemy inspector 与 PostgreSQL 测试库核对表、列、索引、唯一约束、精度及升级后样例。

**Evidence**：
- 上述测试文件与 `docs/devlog/` 当日迁移结构核对记录。

**Failure Handling**：
- 旧数据无法满足非空/唯一约束时保留兼容可空阶段并生成质量清单，不填造平台字段。
- 发现 Foundation 与真实抖音字段冲突时登记 foundation change request，不直接更改业务语义。
- 禁止修改已在共享环境执行的历史迁移，追加新迁移修正。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：已完成（2026-07-20）
