# T2.3 DYDATA-58 剩余增量链路与控制能力

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T2.3 集成增量结算、最终汇总、管理员控制台和 Ops 护栏

**Requirement ID**：DYDATA-58 T3.3-T5.1

**PRD 双链·读**：
- `docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md`
- `docs/prd/foundation/foundation-delivery-dy-data.md`

**核心逻辑**：受影响订单增量 upsert 结算；跨日/月聚合单独 finalize；最高管理员查看/控制组件任务；普通管理员只读；受限 Ops 动作 allowlist、冷却和审计；worker 容器资源隔离。

**核心文件**：`apps/worker/settlement.py`、增量结算/finalize 模块、admin API、组件控制台前端、ops-agent、`deploy/compose.yaml`、0035-0036 迁移和相关测试。

**完成标准**：不全删结算结果、不全表 ORM 载入；聚合可重跑；后台状态来自数据库事实；运维动作最小权限；worker 内存限制不会拖垮 API/Postgres/宿主机。

**Verification Method**：运行结算等价/幂等、finalize、admin 权限/API、前端 build/视觉契约、Ops allowlist 和 Compose 配置测试。

**Evidence**：逐片差异审查、PG 专项、前端构建、权限矩阵和资源配置检查。

**Failure Handling**：结算 checksum 不一致或运维越权时禁止切换新路径；保留只读诊断证据。

**完成收尾：状态同步**：完成后同步三份计划并切换 T2.4。

**Owner**：主代理

**前置**：T2.2

**状态**：已完成（2026-08-31）

**完成证据**：受影响订单增量 rebuild、generation lineage 和月度/全局投影已集成；最高管理员 D10 控制面与前端控制台已集成；Ops Agent 只允许 `restart(worker|browser)`，通过 owner/epoch/lease fencing、同目标 300 秒冷却、唯一容器匹配和 replacement heartbeat 约束；worker/browser/API/ops-agent 资源与权限边界进入 Compose。专项验证包括 Ops/resource/Compose `62 passed`、Aweme/pipeline `40 passed`、控制台/API 权限专项通过及 Web production build 通过。最终全量结果归入 T2.4。
