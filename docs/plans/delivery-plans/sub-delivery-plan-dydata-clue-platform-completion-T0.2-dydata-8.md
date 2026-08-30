# T0.2 DYDATA-8 完整线索主池验收

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T0.2 核验主池、跟进池、总部池和关闭态

**Requirement ID**：DYDATA-8

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-clue-center/clue_master_lead.md`
- `docs/prd/foundation/foundation-schema-clue-center/clue_source_record_link.md`
- `docs/prd/foundation/foundation-api-clue-center/allocation-runtime-and-headquarters.md`

**核心逻辑**：所有来源线索保留在主池；活跃线索进入门店正式轮次或总部池；首见终态线索保留但不建轮次；终态关闭当前轮。

**核心文件**：`apps/worker/clue_allocation.py`、`apps/api/dy_api/routes/clues.py`、`tests/test_clue_allocation_m1.py`、`tests/test_clue_headquarters_pool.py`。

**完成标准**：主池分类互斥完整，终态不创建新轮次，原始数据不被覆盖，用户视角列表/详情一致。

**Verification Method**：`python -m pytest tests/test_clue_allocation_m1.py tests/test_clue_headquarters_pool.py tests/test_api_clues.py -v`

**Evidence**：2026-08-31：新增 `clue_source_record_links`、主档完整池/状态观测/版本字段及 0044 回填迁移；逐源行映射、缺订单隔离、多源行合并、冲突留痕、幂等和终态不回退均有回归。T0.2 相关组合测试 85 项通过，数据结构 6 项通过，0044 聚焦迁移 3 项通过，worker 状态专项 15 项通过。

**Failure Handling**：发现分类缺口时保持 issue 未完成，补最小测试和实现。

**完成收尾：状态同步**：完成后同步三份计划并切换 T0.3。

**Owner**：主代理 -> Human Owner 验收

**前置**：T0.1

**状态**：已完成（2026-08-31）
