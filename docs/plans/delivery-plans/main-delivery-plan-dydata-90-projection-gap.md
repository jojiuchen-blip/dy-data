# DYDATA-90 中心投影缺口增量交付计划

> **版本**：v1
> **日期**：2026-09-10
> **适用范围**：正式分配 worker 的历史 active/pending 主线索中心投影回补
> **开发模式**：isolated-worktrees
> **边界**：只改 `apps/worker` 及本计划，不改 API 路由、前端和生产数据

## 1. 差距与根因

生产发现 234 条 active/pending 主线索缺少 `clue_center_orders`，其中 215 条按当前订单、核销和券证据解析仍为 active。当前 `priority_daily` 使用增量物化路径；中心阶段只消费本轮 `JobImpact` closure 中的 `order_id`，历史主线索没有新的 impact 时不会进入中心投影。正式分配 runtime 又把中心行作为硬资格门槛，因此这些线索稳定落在候选查询之外。

## 2. 增量任务

| Task | 内容 | 状态 |
|---|---|---|
| T0.4 | 在正式分配补偿批次内执行有界中心投影回补，并保持首次分配资格与状态证据门禁 | 已完成代码与专项验证 |

## 3. 最小运行契约修订

1. 每次正式分配批次在同一排他锁范围内，先最多扫描 100 条缺中心的 active/pending 主线索。
2. 回补先调用既有 `materialize_clue_master_leads(order_ids=...)`，由物化器依据来源时间、订单、券和核销证据刷新主线索；随后才调用既有 `refresh_clue_center_projection`。不新增投影事实来源。
3. 回补完成后仍必须通过原 `_eligible()`：中心行、当前 active、待首次分配、无 formal/legacy 历史轮次、非总部池等门禁均保留。
4. 回补使用独立持久 keyset cursor；终态、无来源和其他不可回补行推进 cursor，越过末尾后回绕。显式订单通知不移动该 cursor。
5. 支付成功仍需有效待使用券证据；无券、退款、核销和关闭证据不会进入回补或正式分配。回补、物化、投影和首次分配均受当前批次 deadline 约束；失败计入脱敏结果并保留重试机会。

## 4. PRD 双链·读

- `docs/prd/mainprd-dy-data.md` §1
- `docs/brd/BRD-clue-center-20260721-2134.md` §3
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` J01、J03
- `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 状态解析约束

## 5. 核心文件与完成标准

- `apps/worker/formal_allocation_runtime.py`
- `apps/worker/clue_allocation.py`
- `apps/worker/clue_center.py`
- `tests/test_formal_allocation_runtime.py`

完成标准：有效订单在缺中心时可由有界补偿恢复并进入现有正式分配；缺少券证据、退款/核销、旧快照和既有 formal/legacy 轮次均不误入；排他、cursor、deadline、失败可见性测试通过。

## 6. 验证与证据

- `python -m pytest -q tests/test_formal_allocation_runtime.py`
- `python -m pytest -q tests/test_clue_allocation_eligibility.py tests/test_formal_allocation_runtime.py tests/test_worker_clue_center.py`
- `git diff --check`

生产当前未执行写入、部署或数据修复。上线后由现有 `priority_daily` 的正式分配补偿循环逐页处理存量；每页最多 100 条，215 条有效存量预计至少分三页，终态和证据不足行会被安全跳过并在回绕后复核。若补偿循环未运行，只需在受控 worker 环境按相同 `max_items<=100`、deadline 和只读观测启动任务，不执行手工 SQL 写入。

## 7. 风险

- 物化锁或投影阶段暂时失败时，`center_repair_failed`、`center_repair_scanned`、`center_repair_deferred` 会进入批次结果，cursor 不前移，下一次补偿可重试。
- 来源缺失、来源冲突或当前订单证据不足的主线索不会被强制创建中心行；需要后续来源补拉或状态复核。
- 本增量修复不处理 5620 条 `legacy_engine_retired` 历史轮次，也不扩大到 80 条源已终态或全域陈旧状态清理。
