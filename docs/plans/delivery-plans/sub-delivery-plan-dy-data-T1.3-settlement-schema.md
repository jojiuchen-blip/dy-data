# T1.3 双费用结算与报表 Schema

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T1.3 建立不可变费用结果、调整、账单与投影数据结构

**Requirement ID**：DYDATA-31-SCHEMA

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-dy-data.md` §2-§5
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` §1-§8
- `docs/prd/subprd/03-subprd-order-fee-details.md` §5
- Linear DYDATA-31、DYDATA-33

**核心逻辑**：
- 新增退款事件、不可变费用结果、当前指针、不可变调整、账单头/行/来源项和双费用投影。
- 一张券可分别产生推广与管理方向结果；当前指针按券 + 方向唯一；账单头按门店 + 月份唯一。
- 原始结果、调整和锁账来源分层保存；后续退款不覆盖历史结果，锁账后三层不可变。

**核心文件**：
- `apps/api/dy_api/models.py`
- `alembic/versions/`
- `tests/test_data_schema.py`
- `tests/test_alembic_migrations.py`
- `tests/test_data_settlement.py`

**完成标准**：
- Foundation 的 8 张结算目标表及方向、月份、状态、来源唯一性和查询索引均落到模型/迁移。
- 金额列使用整数分且允许调整为负数；费率使用精确数值；业务 ID 对外保留字符串。
- 空库往返和既有库升级通过；旧 `settlement_order_details` 保留为迁移期只读兼容投影。

**Verification Method**：
- 执行 `python -m pytest tests/test_data_schema.py tests/test_alembic_migrations.py tests/test_data_settlement.py -q`。
- 核对一券双方向、当前指针唯一、账单来源唯一和净额允许负调整的数据库约束。

**Evidence**：
- 测试结果、迁移 inspector 输出摘要与 `docs/devlog/` 当日记录。

**Failure Handling**：
- SQLite 无法表达的 PostgreSQL 约束必须在 PostgreSQL 测试库补证，不以 SQLite 通过替代。
- 若旧投影字段与目标语义冲突，保持旧表只读，不将旧单分佣金额填入两个方向。
- 发现锁账来源不能唯一追踪时阻断后续结算任务。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2

**状态**：已完成（2026-07-20）
