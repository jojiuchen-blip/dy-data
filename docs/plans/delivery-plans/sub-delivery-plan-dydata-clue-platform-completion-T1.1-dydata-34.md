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

**Evidence**：旧路径 RED 测试、迁移/恢复计数、相关回归和静态搜索结果。

**Failure Handling**：迁移发现重复当前轮或门店归属缺失时停止写入并输出可恢复冲突清单。

**完成收尾：状态同步**：完成后同步三份计划并切换 T2.1。

**Owner**：主代理

**前置**：T0.4

**状态**：待开发
