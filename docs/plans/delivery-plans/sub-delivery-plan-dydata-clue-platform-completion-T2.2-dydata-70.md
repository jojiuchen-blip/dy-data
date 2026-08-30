# T2.2 DYDATA-70 线索增量物化闭环

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T2.2 用影响集合和 keyset 批处理替代全历史扫描

**Requirement ID**：DYDATA-70 / DYDATA-58 T3.2

**PRD 双链·读**：
- `docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md`
- `docs/prd/foundation/foundation-schema-clue-center/clue_master_lead.md`
- `docs/prd/foundation/foundation-schema-clue-center/clue_source_record_link.md`

**核心逻辑**：按任务影响闭包处理线索、订单和来源标识；keyset/固定批次读取；每批提交；乱序旧日不得回退当前状态；终态、总部池、轮次和历史保持幂等。

**核心文件**：`apps/worker/clue_allocation.py`、增量线索执行模块、`apps/api/dy_api/models.py`、0034 迁移及增量物化测试。

**完成标准**：不再全历史 `.all()`；同一天重复执行无重复；跨天身份和终态正确；shadow checksum 一致；RSS 不随历史总量线性增长。

**Verification Method**：运行增量线索、乱序、幂等、批处理、身份历史、终态和真实 PostgreSQL 专项测试，并生成 RSS 样本。

**Evidence**：查询路径审查、批次数/行数日志、checksum 和 RSS 报告。

**Failure Handling**：影响闭包不完整或 checksum 不一致时保持旧路径只作 shadow，不切换生产执行。

**完成收尾：状态同步**：完成后同步三份计划并切换 T2.3。

**Owner**：主代理

**前置**：T2.1

**状态**：待开发
