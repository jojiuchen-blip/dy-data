# DYDATA-102：compaction runner 与 day_recovery blocked-shape 修复（2026-10-15）

## 本轮交付

1. **可执行压缩维护 runner**（`apps/worker/settlement_compaction.py` +
   `scripts/ops/compact_settlement_projection.py`）
   - 真实领取：queued JobRun（`execution_slot='heavy_sync'`）+ 精确 job_id CAS 领取；
     共享 `HEAVY_SYNC_CLAIM_LOCK_KEY` advisory 锁、heavy 限流冷却、
     `uq_job_runs_heavy_sync_running_slot` 唯一运行索引，与 date/finalize/rebuild 互斥。
   - 资源准入：claim 默认解析 `current_resource_decision()`（guard 开但监视器缺失/过期 =
     STOP）；ops 入口启动既有 ResourceMonitor 并在 `--admission-wait-seconds` 内有界等待
     真实健康观察，STOP/DRAIN/缺监视器不领取，ALLOW 才领取；不关闭 guard、不伪造
     daily_required。
   - builder claim-fence：每个 builder 写事务 commit 前重验 claim
     （`_fence_settlement_compaction_commit`），丢失租约的旧 runner 无法继续写同一
     compaction 代（回归：builder 提交被拒且零残留）。
   - 发布=已验收 `publish_settlement_compaction`（实际 manifest/closure 校验），发布与
     success 同事务；崩溃后按一次性审计事件幂等恢复；`_fail` 仅在租约仍有效时写终态；
     过期 running 行可被重领。
2. **day_recovery blocked-shape 修复**（生产确证流水线 38692345077）
   - 原根 `range-sync-10562f3369ac7d31e9801d42d8db1d60`（failed）的 ledger 恰有 1 条
     ordinal-1（`range-sync-cfd16d...`，pending，collection 子作业真实 success、finalize
     failed 3/3 耗尽）。`_in_flight_generation` 原把该 pending 一律判为在飞，ordinal 2
     被挡。
   - 修复：仅当**最新**恢复代 pending 且通过 fail-closed 精确形态校验时，原根 ledger 可
     追加 ordinal 2 —— 校验含：恢复 metadata（recovery root/ordinal/request_key）与
     ledger 条目及原根一致、config_version 与 ledger 一致且为 recovery 前缀、窗口/
     data_source 与原根一致、子作业恰为 1 date_sync + 1 parent_sync + 1 finalize、全部
     子作业与候选无 open `job_attempts`、无 cancel/pause、无 live lease、collection 真实
     success、finalize 终态 failed 且预算耗尽。
   - 回归（先红后绿，红=真实 "in flight" 拒绝）：ordinal-2 放行；未耗尽 finalize/live
     lease/可运行 child/缺来源 child/open attempt/child cancel/恢复 metadata 不匹配/
     窗口漂移全部仍拒绝；"恢复代不可再恢复"既有回归保持。
3. **CI/PG 门禁**：`.github/workflows/ci-cd.yml` 新增 PG 步骤
   `tests/test_settlement_compaction_runner.py tests/test_job_recovery_and_evidence.py`
   （loopback dydata_release）；runner 套件补 PG 端到端（真实建表与约束）：发布链路、
   caller rollback 拒绝、失效租约拒绝 + 重领、双线程 claim 互斥 + 唯一索引兜底。

## 对此前说明的修正

- `recovery_generations` 必须用正确 key（`recovery_generations`）读取；此前"ledger 为空、
  预算 2/2 空闲"的说法作废：实际已有 ordinal 1，ordinal 2 在 `MAX_RECOVERY_GENERATIONS=2`
  预算内。
- 恢复入口是**原根** `range-sync-10562f3369ac7d31e9801d42d8db1d60`；对 ordinal-1 恢复代
  `range-sync-cfd16d...` recover 会被 `_assert_recoverable_plan` 以 "a recovery generation
  cannot itself be recovered" / "only a base daily generation can be recovered" 拒绝，
  不存在"新 ledger 再审批"路径。
- 恢复代 pending 曾被一律判为在飞；现仅在上述 fail-closed stopped 形态下放行，其余
  root 恢复规则未放宽。

## 验证

- 本地：`pytest tests/test_settlement_compaction_runner.py tests/test_job_recovery_and_evidence.py
  tests/test_projection_publish_compaction.py tests/test_projection_publish.py
  tests/test_settlement_finalize.py` 全绿（PG 用例无 DSN 时 skip，CI 接入后执行）。
- 剩余依赖：真实 PG（CI 门禁）+ 生产执行前重跑 runbook 只读核实。

## 不做 / 保护

不改旧任务 status/attempt/lease/error 证据；不伪装成功 child；不做 SQL 重置；不提高 64
阈值；不触碰冻结/确认/发票事实；实际回采成本 = 9/14 单日整链（既有安全恢复仅支持整日
新代）。资源参数一律取执行时观测值。
