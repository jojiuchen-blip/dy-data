# T1.1 自然月运行与结算链自动维护

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T1.1 自然月运行与结算链自动维护

**Requirement ID**：DYDATA-104 D

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：复用已存在 month_close 与受 claim fence 保护的 compaction runner；深度 48 提前维护，保留 64 硬限制。固定 base 派生任务身份、最多三次，不生成 -rN 绕过预算。读取真实 PostgreSQL 卷所在文件系统的有界容量证据：只读 marker 文件挂载，禁止 Docker socket/整卷暴露及自动创建缺失路径。run_once、run_on_start、常规 tick 每轮至多一个重任务；来源不全、来源变化、已有保护账单和陈旧 base 均拒绝或安全延后。

**核心文件**：
- `apps/worker/scheduler.py`
- `apps/worker/month_close.py`
- `apps/worker/settlement_compaction.py`
- `apps/worker/legacy_projection_bootstrap.py`
- `apps/worker/projection_publish.py`
- `deploy/compose.yaml`
- `deploy/tencent/deploy.sh`
- `tests/test_settlement_compaction_runner.py`
- `tests/test_month_close.py`

**完成标准**：48 前不分配、48 起按真实资源准入；同 base 幂等、耗尽不复活、陈旧 base 有审计，逐 tick 不串行启动两个重任务。实际 manifest/closure/tombstone 有界读取与累计 DISTINCT 正确；无全历史全量拉取。上海跨月/跨年、晚到来源、重复重跑及保护事实验证通过。未来结算范围按已核实生效规则承接，缺少语义时先记录缺口，不永久复制八月。

**Verification Method**：单元与真实 PostgreSQL 并发/租约/崩溃恢复、代表性规模查询预算、Compose 安全配置、月结日期边界与保护账单回归。

**已确认范围语义（2026-10-20）**：账号、渠道范围从生效月持续适用，直到明确变更或停用；历史已确认账单不追溯。按账号、渠道选择不晚于业务月的最新规则，再判断启停；不得跳过停用记录回退到旧启用。新增规则只影响明确提交的渠道，同月唯一、幂等重试与权限保护保持。旧请求缺省启用，与显式启用保持同一语义。

**已核实接入风险**：既有 settlement_rebuild 使用独立 claim 锁且没有 heavy_sync 槽，不能依赖 compaction 的唯一索引证明两者互斥。自动启用前需将相关领取入口按一致锁序接入共享重任务保护，并用真实 PG 并发证明；单 tick 早退与跨进程互斥分别验收。只读入队估算先查 head/深度，计数遵守直接 lineage closure 和去重 manifest（含 tombstone、明确 legacy_root 处理），不得每轮展开全部历史。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：统一 main；先审阅既有执行器契约

**状态**：待验收

