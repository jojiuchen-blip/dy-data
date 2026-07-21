# T2.5 原始订单/券应用与约束切换

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T2.5 完成 DYDATA-38 第二阶段应用关联与主键约束切换

**Requirement ID**：DYDATA-38-S2

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-dy-data.md` §4-§6
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` §7-§8
- Linear DYDATA-38

**核心逻辑**：
- 采集 upsert 改为按平台业务 ID 查询后更新或新增，内部关联与结算读取优先使用数值 ID，同时保留业务 ID 查询路径。
- 影子核对无差异后，将 `id` 切为主键，`order_id/coupon_id` 切为非空唯一，字符串外键不再承担级联角色。
- API、导出、对账和日志继续只使用平台业务 ID，不暴露内部 ID。

**核心文件**：
- `apps/api/dy_api/models.py`
- `apps/worker/repositories.py`
- `apps/worker/collectors/orders.py`
- `apps/worker/settlement.py`
- `alembic/versions/`
- `tests/test_alembic_migrations.py`
- `tests/test_worker_order_collector.py`
- `tests/test_data_settlement.py`

**完成标准**：
- 切换前后订单/券行数、孤儿数、重复采集结果、结算明细数量和关键样例金额一致。
- 数据库主键/唯一约束符合目标结构，所有内部关联使用数值 ID；平台业务 ID 永久非空唯一。
- 旧业务 ID 查询可作为恢复路径；API/CSV 中不存在内部 `id/raw_order_id`。

**Verification Method**：
- 执行 `python -m pytest tests/test_alembic_migrations.py tests/test_worker_order_collector.py tests/test_data_settlement.py tests/test_api_dashboard.py -q`。
- 在脱敏数据库副本执行切换前后 SQL 对照和 `EXPLAIN`，验证关联一致性、索引和关键查询。

**Evidence**：
- DYDATA-38 Stage 2 SQL 核对摘要、测试结果、迁移恢复演练和 `docs/devlog/` 记录。
- 2026-07-20 目标回归 `66 passed`；`compileall`、`git diff --check` 和 Alembic 单 head 检查通过。
- PostgreSQL 离线 DDL 已覆盖并发唯一索引、两级短锁、`USING INDEX` 约束交换、双 Identity 序列同步及降级恢复；三轮代码审查无 Critical/Important 问题。
- 未执行生产迁移；真实 PostgreSQL 双会话、脱敏副本、锁时长、序列和升降级演练保留到 T4.1。

**Failure Handling**：
- 任一孤儿、双关联不一致或结算差异阻断约束切换。
- 生产切换失败优先前滚修复；需要恢复时切回保留的业务 ID 查询路径，不删除已生成内部 ID。
- 未经人类 Owner 审核不得在生产执行主键/约束切换。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T2.4

**状态**：已完成本地实现与验证（2026-07-20）；生产迁移验收保留到 T4.1
