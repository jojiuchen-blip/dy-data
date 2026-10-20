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

**状态**：进行中

**当前边界**：2026-10-20 用户确认按推荐方案修复发布阻碍，无需 Linear。最新 main 已无冲突合入；原工作区未提交修改保留。补采目标日期已成功，但退款原始记录尚未形成有效退款事件，两条旧维度任务因仅调度当日任务而滞留。按下列范围修复，生产上线继续受业务基线、来源活动及磁盘门禁约束。

**发布阻碍修复范围**：
- 核实退款端点实际字段、金额单位、状态及类型含义；只接受有明确证据的端点契约，未知单位仍阻断。
- 为保留的退款原始数据提供默认 dry-run、有界、幂等且可审计的重放；保留原始 payload、来源与历史质量记录，受保护账单不直接覆盖。
- 修复跨日维度任务的正常重试选择，保留限流、租约、资源和次数限制；旧任务通过正常执行或有覆盖证据的审计取消收敛，不伪造成功。
- 修复后核对事件、后续物化与结算，再验证五个模块首版及部署。

**增量核心文件**：`apps/worker/collectors/refunds.py`、退款重放工具、`apps/worker/priority_scheduler.py` 及对应测试、退款契约与运行手册。

**增量完成标准**：未知/冲突金额不得入账；发起来源不得误判为全退；同一原始记录重复重放不重复退款，旧快照不得覆盖新观察；跨日重试保持资源/租约/重试限制；预演、执行、后续对账分别记录。缺少确定契约时只交付安全修复及具体缺口，不猜测财务金额。

**完成收尾：状态同步**：
向 ai-project-manager 提交实现和验证事实、日期、foundation 漂移结论，由其调度 delivery-planner 同步主计划、看板与子计划；重跑 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`，未完成同步不标记完成。
