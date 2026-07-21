# T1.1 原始订单/券兼容 ID 扩展

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T1.1 完成 DYDATA-38 第一阶段兼容扩展与回填

**Requirement ID**：DYDATA-38-S1

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-dy-data.md` §4-§6
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` §7-§8
- Linear DYDATA-38 的范围、验收与风险标签

**核心逻辑**：
- 为 `raw_douyin_orders`、`raw_douyin_order_coupons` 增加内部 bigint `id`，为券增加 `raw_order_id`；第一阶段保留字符串主键、旧外键和旧应用读写。
- 按平台 `order_id/coupon_id` 回填且保证稳定重跑；`raw_order_id` 与券的 `order_id` 必须指向同一订单。
- 采集 upsert 仍以业务 ID 幂等，但开始回读内部 ID；不得删除、改写或向 API 暴露业务 ID。

**核心文件**：
- `apps/api/dy_api/models.py`
- `apps/worker/repositories.py`
- `apps/worker/collectors/orders.py`
- `alembic/versions/`
- `tests/test_alembic_migrations.py`
- `tests/test_worker_order_collector.py`

**完成标准**：
- 空库和既有库升级后两表内部 `id` 非空且不重复，券 `raw_order_id` 非空；业务 ID、旧关联和现有查询保持可用。
- 迁移前后订单/券行数不变；业务 ID 重复数、内部 ID 空值/重复数、订单—券孤儿数、`raw_order_id/order_id` 不一致数均为 0。
- 同一采集 fixture 连续执行两次仍各保留 1 条订单和 1 条券，且内部 ID 不变化。

**Verification Method**：
- 先补迁移与重复采集失败测试；执行 `python -m pytest tests/test_alembic_migrations.py tests/test_worker_order_collector.py -q`。
- 在脱敏数据库副本执行行数、空值、重复、孤儿和双关联一致性 SQL；记录升级前后结果。

**Evidence**：
- `docs/devlog/` 当日开发日志中的 DYDATA-38 Stage 1 记录。
- `tests/test_alembic_migrations.py`、`tests/test_worker_order_collector.py` 自动化结果与脱敏 SQL 摘要。

**Failure Handling**：
- 发现业务 ID 重复、孤儿或双关联不一致时阻断回填完成，不自动选择订单。
- SQLite 与 PostgreSQL 自增/约束行为不一致时，以 PostgreSQL 迁移验证为发布依据。
- 不通过回滚删除已分配 ID；采用前滚修复或继续使用保留的业务 ID 路径。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：已完成（2026-07-20）
