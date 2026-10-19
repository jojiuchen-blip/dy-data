# T1.1 静态发布验收

## 任务来源

[主计划](main-delivery-plan-unified-dashboard-publications.md) / [看板](task-kanban-unified-dashboard-publications.md)

#### T1.1 真实数据库与浏览器验收

**Requirement ID**：PUB-01 至 PUB-07

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局设计规则
- `docs/api/dashboard-publications.md`

**核心逻辑**：比较新旧口径、验证真实规模的性能及容量；在远端再次对齐后形成可审阅交付。生产生效与代码验证分开记录。

**核心文件**：`tests/`、`docs/devlog/20261019_unified_dashboard_publications.md`、`docs/api/dashboard-publications.md`

**完成标准**：完整 pytest 和前端 build 通过；真实 PG 迁移、并发发布、失败恢复通过；浏览器筛选与错误/空状态检查完成；常见筛选耗时、内存、投影存储体积有记录；部署后的健康和磁盘状态仅在实际验证后宣称。

**Verification Method**：完整 pytest、前端 build、真实 PG 与浏览器；只读线上容量核对，部署门禁另记。

**Evidence**：`docs/devlog/20261019_unified_dashboard_publications.md`

**Failure Handling**：失败记录具体门禁及原因；保持上一发布版本，不用空表或新请求时间掩盖失败。

**Owner**：Codex 执行、人类 Owner 审核

**前置**：T0.1

**状态**：待开发

**完成收尾：状态同步**：
向 ai-project-manager 提交实现和验证事实、日期、foundation 漂移结论，由其调度 delivery-planner 同步主计划、看板与子计划；重跑 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`，未完成同步不标记完成。
