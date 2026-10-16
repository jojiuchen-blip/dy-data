# DYDATA-102：日计划受控恢复与独立代际裁决

2026-10-13：由 DSH 执行、Codex 独立验收，在隔离 worktree `dydata-102-fee-details` 完成针对生产 9 月 14/16/20/25/28 五天的 `date_sync` 3/3 失败后的独立父计划恢复链路（本地代码修复 + 回归验证）。生产 SSH 与 Linear 当前连接不可用，未做生产写入、部署或推送，未补跑生产，未回填 Linear。

## 根因与设计

- `begin_job_attempt` 用 `attempt_number = attempt_count + 1` 派生，`job_attempts` 唯一约束 `(job_id, attempt_number)`；原位把 `attempt_count` 归零会与已记录的 3 条 attempt 冲突，保持单调又破坏每行 attempt 预算。原位 attempt_count=0 方案不可行。
- 恢复改为创建**独立新 parent**：新 `config_version = priority-daily-v1-recovery-<sha256(idempotency_key)[:12]>`，使 `plan_daily_sync` 派生全新的 range parent 与全新 job_id 的 date children，attempt 空间为空；旧 JobAttempt 与旧错误证据原样保留。
- 代际由显式 `recovery_ordinal` 裁决（禁止 job_id 词典序）；每原日最多 2 代；幂等 key 返回同代；原 parent 行锁后重验取消/暂停/lease 与 child 活跃 lease 后才允许。
- 父聚合与 `_day_state` 只认最新有效代际：旧代 failed children 不计入日失败、不被重跑；单一 finalize 只属于获胜代际。

## 关键修复

- `apps/worker/day_recovery.py`（新增）：显式代际模型、幂等 key、2 代预算、锁后重验、恢复代不能自恢复、跨日 key 复用拒绝、`priority_generation_config`/`winning_generation`。
- `apps/worker/priority_scheduler.py`：恢复 config 在所有 scheduler 选择点可见（`_priority_generation_config_filter`）；`_day_state`/claim 路径排除被取代旧代；恢复代在 manual 选择前 stamp 正确 purpose；request_budget_date 每次 tick 刷新。
- `apps/worker/repositories.py`：`is_priority_resource_config` 覆盖 recovery 前缀；删除 `queue_recovery_job` 占位与死代码。
- `apps/worker/daily_task.py`、`priority_budget.py`：恢复代纳入 paged/budget 治理，不落 legacy 无预算路径。
- `apps/api/dy_api/routes/operations.py`：`recover` 从 501 占位改为真实调度；沿用管理权限、reason/actor/idempotency 审计；同 key 同代、不同 root 409、预算耗尽 409。
- `apps/worker/subprocess_supervisor.py` 未改；恢复代通过真实 claim → `begin_job_attempt`（新 job_id 下 attempt 1）→ 真实 `run_daily_stages` collect_dimensions 传播 → complete → 单一 finalize 全链路验证。

## 验证命令与结果（真实退出码）

- `python -m pytest tests/test_job_recovery_and_evidence.py -q -p no:cacheprovider` → 21 passed，EXIT=0。
- 定向 worker/month_close/priority/API 套件：
  `python -m pytest tests/test_priority_scheduler.py tests/test_month_close.py tests/test_worker_daily_orchestrator.py tests/test_finalize_parent_promotion.py tests/test_settlement_finalize.py tests/test_settlement_generation_recovery.py tests/test_job_recovery_and_evidence.py tests/test_api_admin_sync_control_plane.py tests/test_worker_subprocess_recovery.py -q -p no:cacheprovider` → 147 passed、8 skipped，EXIT=0。
- `git diff --check` → EXIT=0。
- 覆盖：真实 3×JobAttempt 旧代 + 新独立 parent + attempt1 + child/parent 成功 + 单一 finalize + day 成功；未完成/失败恢复不通过月结；幂等同代；预算耗尽；并发仅 1 代；未来 retry_wait 代仍 block 并行新代；request_budget_date 次日推进且 purpose 不变；生产 pending parent + 终态 failed child 阻塞形态可恢复。

## 限制

- 生产 2026-09 来源与月结 watermark 未补跑；Linear 不可用未回填；无生产部署/推送/写库。
- Codex 完全权限独立综合验收：13 个相关测试文件，首次 `205 passed, 8 skipped, 1 failed`（282.17 秒）。唯一失败是旧 scheduler 测试未模拟新增月结依赖；修正测试夹具后独立重跑 `tests/test_worker_subprocess_recovery.py`，`12 passed, 8 skipped`（9.20 秒），退出码 0。综合范围内的全部失败已消除，合计 206 个用例通过、8 个跳过。
- 生产连接复核：结算页 HTTPS 返回 200；SSH 在 banner exchange 阶段超时。网页可访问不代表具备部署或历史补跑通道。
- 原始 `worker_exit_1` 的具体异常仍需生产完整日志核验；本轮修复恢复机制与错误证据保留，不声称已证实原始崩溃原因。
