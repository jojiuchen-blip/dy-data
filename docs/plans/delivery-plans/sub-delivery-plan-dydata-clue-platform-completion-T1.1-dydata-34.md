# T1.1 DYDATA-34 旧分配引擎全面下线

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T1.1 移除 legacy 轮次创建和运行时兼容分支

**Requirement ID**：DYDATA-34

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-clue-center/clue_assignment_round.md`
- `docs/prd/foundation/foundation-api-clue-center/follow-up-and-rounds.md`
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md`

**核心逻辑**：原始线索/订单/商品/联系方式投影与分配解耦；运行时只接受 formal/trial；现有 legacy 轮次保持门店归属转换为正式轮次；自动分配和再分配仍默认关闭。

**核心文件**：`apps/worker/clue_center.py`、`apps/worker/pipeline.py`、`apps/worker/materialize_once.py`、`apps/api/dy_api/routes/admin.py`、`apps/api/dy_api/routes/clues.py`、Alembic 迁移与恢复测试。

**完成标准**：生产路径不再写 `execution_mode=legacy`；列表/详情/导出/指标/手机号/跟进仅依赖正式轮次；迁移幂等且无重复当前轮。

**Verification Method**：
- `rg -n "execution_mode.*legacy|rebuild_clue_center" apps tests`
- `python -m pytest tests/test_worker_clue_center.py tests/test_clue_operability_recovery.py tests/test_api_clues.py -v`
- `python -m pytest tests/test_alembic_migrations.py -v`

**Evidence**：
- 2026-08-31：旧物化器改为纯投影刷新，不再创建轮次；采集、物化和跟进状态链均不自动调用正式分配或再分配。
- `20260831_0046` 将现有 legacy 轮次按原 ID、主档、订单、门店、轮次序号和跟进引用原地转换为 formal；活动轮次关闭自动过期，新增 formal/trial 数据库约束及精确回滚日志。
- 迁移和只读 preflight 均阻断未知模式、正式命名空间冲突、活动轮次归属/指针异常、重复活动轮次及跟进记录跨表归属不一致；trial 证据不能进入查看号码、跟进或删除业务路径。
- 投影只接受归属一致的活动 formal 当前轮次；关闭轮次不会复活为当前轮，且待再分配状态继续保留上一轮跟进结果和关闭原因。
- 旧引擎专项与相关订单回归 `155 passed`；Alembic 全量 `54 passed`；`compileall`、`git diff --check` 通过；静态搜索未发现 apps 下 legacy 运行时写入或 `rebuild_clue_center`。
- 两轮独立只读审查均无 P0/P1；发现的 trial 删除、preflight 全局门禁、投影摘要和跨表归属 P2 均已修复并补负例。
- 未执行生产迁移、线上重建或服务重启；真实 PostgreSQL 发布验收保留到最终发布门禁。

**Failure Handling**：迁移发现重复当前轮或门店归属缺失时停止写入并输出可恢复冲突清单。

**完成收尾：状态同步**：完成后同步三份计划并切换 T2.1。

**Owner**：主代理

**前置**：T0.4

**状态**：已完成（2026-08-31）
