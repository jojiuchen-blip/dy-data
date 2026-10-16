# Settlement compaction & 2026-09-14 恢复运维手册（DYDATA-102）

状态：待验收执行。本文档只描述已实现并测试的入口；执行前必须重跑所有只读核实 SQL。
所有资源参数（batch size、manifest 行数上限、磁盘余量）必须取自执行时点的真实观测值，
不得沿用历史数字或编造。

## 0. 生产只读事实基线（流水线 38692345077，2026-10 读数）

- active 头：`settlement-lineage:836ff9c0df69bc5babbc79c8d321bb3def90f48dcc39c2893fb17215ee4aa0be`，
  `generation_kind='lineage'`，`lineage_depth=64`，`state='published'` —— 触发
  `_sparse_base_chain` 的 depth>=64 确定性失败，重试无意义。
- heavy 槽空闲：`heavy_jobs=[]`（无运行中 heavy 作业）。
- 原根：`range-sync-10562f3369ac7d31e9801d42d8db1d60`，`status='failed'`。
  其 `metadata_json->'recovery_generations'` **恰好 1 条**（ordinal 1 ->
  `range-sync-cfd16d14060472e3243b03244fd65322`）。预算事实：`MAX_RECOVERY_GENERATIONS=2`，
  已用 1，ordinal 2 在预算内 —— **不得**表述为"预算 2/2 空闲"，此前基于错误 key 的
  "ledger 为空"判断作废。
- ordinal-1 恢复代 `range-sync-cfd16d...`：`status='pending'`、无 cancel/pause，
  其 `date_sync` 与 `parent_sync` 子作业真实 `success`，其唯一 `finalize` failed 3/3
  （attempt 预算耗尽）。该形态即 `_pending_generation_is_stopped` 的放行前提。

## 1. 只读核实（执行前逐条跑，任何一条不满足即停止）

```sql
-- 1a. active 头与深度
SELECT a.generation_id, g.generation_kind, g.lineage_depth, g.state
FROM settlement_projection_active a
JOIN settlement_projection_generations g ON g.generation_id = a.generation_id
WHERE a.projection_name = 'settlement';

-- 1b. 原根状态与 ledger（必须用 recovery_generations 这个 key 读，不是别的诊断 key）
SELECT job_id, status, cancel_requested_at, pause_after_stage_requested_at,
       lease_expires_at,
       jsonb_pretty(metadata_json->'recovery_generations') AS ledger
FROM job_runs WHERE job_id = 'range-sync-10562f3369ac7d31e9801d42d8db1d60';

-- 1c. ordinal-1 恢复代的终局形态（date/parent success + finalize failed 耗尽、无 open attempt）
SELECT job_id, job_kind, status, attempt_count, max_attempts, lease_expires_at,
       cancel_requested_at, pause_after_stage_requested_at
FROM job_runs WHERE parent_job_id = 'range-sync-cfd16d14060472e3243b03244fd65322';
SELECT job_id, attempt_number, finished_at FROM job_attempts
WHERE job_id IN (SELECT job_id FROM job_runs
                 WHERE parent_job_id = 'range-sync-cfd16d14060472e3243b03244fd65322')
  AND finished_at IS NULL;

-- 1d. heavy 槽空闲
SELECT job_id, job_kind, status FROM job_runs
WHERE execution_slot = 'heavy_sync' AND status = 'running';
```

身份红线：`range-sync-cfd16d...` 是恢复代（metadata 带 `recovery_root_job_id`，
`config_version` 为 recovery 前缀）。`day_recovery._assert_recoverable_plan` /
`_assert_original_identity` 会以 "a recovery generation cannot itself be recovered" /
"only a base daily generation can be recovered" 拒绝对它 recover —— **不存在**
"对新 parent 开新 ledger 再审批"的路径。唯一入口是原根
`range-sync-10562f3369ac7d31e9801d42d8db1d60` 的 ledger。

## 2. 第一步：压缩发布（本仓库新入口，先于恢复，硬顺序）

```bash
python scripts/ops/compact_settlement_projection.py \
  --batch-size <观测值> \
  --max-manifest-rows <观测值> \
  --max-estimated-write-bytes <观测值> \
  --max-estimated-wal-bytes <观测值> \
  --observed-disk-headroom-bytes <执行时 df 实测> \
  --min-disk-headroom-bytes <策略阈值> \
  --lease-minutes 30
```

保障（均已实现并有测试）：

- 真实 JobRun 领取：`job_name='settlement_compaction'`、`execution_slot='heavy_sync'`，
  精确 job_id 领取；进程锁 + 共享 `HEAVY_SYNC_CLAIM_LOCK_KEY` advisory 锁 +
  DB 唯一运行索引 `uq_job_runs_heavy_sync_running_slot` 与 date/finalize/rebuild 互斥。
- 资源准入：claim 默认解析 `current_resource_decision()`；guard 开启但监视器缺失/过期
  = STOP（不领取）；DRAIN 不放行维护作业；脚本按既有 ResourceMonitor 流程启动并在
  `--admission-wait-seconds` 内有界等待真实健康观察，结束时 `monitor.stop()`。
- builder 每个写事务 commit 前 claim-fence（`_fence_settlement_compaction_commit`）；
  心跳失败线程退出后旧 runner 无法继续写同一 compaction 代。
- 发布走已验收的 `publish_settlement_compaction`（校验实际 manifest/closure），发布与
  success 同事务；崩溃后按一次性审计事件幂等恢复（`already_published`）。
- 冻结保护：statement/fee_result/confirmation/invoice 零写入；旧任务
  status/attempt/lease/error 证据零改动。

成功输出：`{"status":"success","outcome":"published","generation_id":"..."}`。
复核 1a：active 指针 = 新 compact 代（depth 0）。

## 3. 第二步：原根 ledger 追加 ordinal 2（既有受审计 API）

```
POST /api/v1/admin/operations/jobs/range-sync-10562f3369ac7d31e9801d42d8db1d60/recover
Idempotency-Key: <16-128 位一次性键，即 request_key>
{"reason": "DYDATA-102: 2026-09-14 finalize failed 3/3 on sparse lineage depth 64"}
```

- super-admin + trusted origin；幂等键决定 `config_version=priority-daily-v1-recovery-<sha256[:12]>`，
  重放返回同一代。
- 新增的 stopped-shape 放行条件（全部 fail-closed，任一不满足仍拒绝 "in flight"）：
  仅最新恢复代 pending；其 metadata（recovery root/ordinal/request_key）与 ledger 条目、
  原根身份一致；窗口/data_source 与原根一致；子作业恰为 1 date_sync + 1 parent_sync +
  1 finalize；全部无 open `job_attempts`、无 cancel/pause、无 live lease；collection 真实
  success；finalize 终态 failed 且 attempt 预算耗尽。
- 恢复代不可再恢复（独立回归覆盖）；不可用恢复代当新根绕过预算。

## 4. 第三步：调度执行与验证

调度按既有管道领取 ordinal-2 新链（真实新 date_sync/parent_sync/finalize，不伪装成功
child）；新 finalize 在 compact 头（depth 0）上构建 depth=1，通过 64 门禁。
验证：ordinal-2 finalize `success`；`settlement_projection_*` 指针前进；9 月账单生成；
ordinal-1 的 pending 行与失败证据保持原样（只增审计，不改 status/attempt/lease）。

## 5. 成本与不做

- 实际回采成本：9/14 单日整链重新采集（day_recovery 设计即整日新代；"仅 finalize 不回采"
  是效率目标，无既有安全入口，不绕过身份/来源门禁）。
- 不做：提高 64 阈值；SQL 改 active/状态；复活旧 3/3 finalize；伪造成功 child；
  移动 8 月累计；重收集其他 29 天；触碰冻结/确认/发票事实；关闭资源 guard。
