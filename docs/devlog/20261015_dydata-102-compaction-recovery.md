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

## 2026-10-16 控制者独立验收与生产只读核验

- 生产仍为 `b81c71b248771a72f9f3754578313d67f5bda069`，连续压缩兼容补丁尚未部署。`3cf8428` 的完整 CI 为 3611 passed / 189 skipped，不能代替后续未提交补丁的验收。
- 九月来源只读汇总：36182 条支付时间落在九月的原始订单，11009 条原始核销事件（含撤销），10882 条已物化有效核销券；九月 current 费用结果与账单均为 0。原始与物化数量口径不同，不能当成丢单差额。[只读证据](https://github.com/jojiuchen-blip/dy-data/actions/runs/38838780134)。
- 生产范围规则仅有八月启用的 2 条，九月/十月无配置；结算器按有效月份精确匹配，因此这是费用为 0 的直接阻断之一。用户核对现有账号/渠道后明确确认“九月的规则和八月一致”。仅授权补九月范围，不改费率或复制金额。现有范围服务会自动排队重建，须待深度阻断解除后调用；尚未写规则。
- API 内执行只读 Python 诊断曾触发 768MiB cgroup OOM，uvicorn 被杀后重启，诊断退出137。后续诊断已移至 worker，保留数据库 READ ONLY 和查询超时。[恢复核验](https://github.com/jojiuchen-blip/dy-data/actions/runs/38840748071)：API/worker/PostgreSQL 均 healthy，公开财务入口 HTTP200，磁盘可用 25743392768 bytes；API 570.4MiB/768MiB。不得把历史 OOM 隐瞒为无服务影响。
- 侧栏 DSH 误操作共享 Git 暂存的用户 stash 已按原对象恢复引用，注入文件先完整备份再移除；主工作区干净，集成区 staging 为空，用户内容保留。DSH 后续仅在无 `.git` 的隔离源代码副本执行，控制者独立负责 Git/CI/部署。
- 控制者对 DSH 新补丁独立复测：`tests/test_settlement_projection.py` 先 10 passed / 1 failed（查询次数断言），修改后 11 passed。另以关闭后拒绝读取的会话探针复现 `_compaction_source_payload_page` 在 finally 关闭后仍调用 provenance verifier。当前仍需修正会话生命周期，补足大批量读取及更深层篡改回归；没有接受补丁或宣称生产修复。
- 无 foundation 契约变更；Linear DYDATA-102/103 保持 In Progress，生产数据补跑、范围落库、费用重建、月结及最终 UI/导出验收尚未完成。

### 补充：冻结副本扩大回归

控制者在冻结的 DSH V2 源码副本运行 legacy bootstrap、settlement projection、compaction publisher/runner、finalize、recovery 六组测试：**367 passed, 4 skipped**，324.12s；PG相关4项因未配置测试DSN跳过。此证据不覆盖尚在执行的会话生命周期返修，不替代真实PG CI。已将探针失败证据及小范围返修要求下发DSH。

补充纠正：上述会话探针替换了真实 resolver，证明关闭后仍调用校验方法，不能证明合法生产路径发生数据库重开；真实 resolver 会无条件预热终端 compact closure，正常路径命中缓存。顺序调整属于生命周期防御，不应称为已证实的生产连接泄漏/P1。

### 补充：DSH 返修接入前验收

- 控制者对返修冻结副本运行 `python -m pytest tests/test_settlement_projection.py -q`：**14 passed**，27.53s。包括第四次真实metadata压缩及后续日、原始叶子金额/非空冻结事实保留、C1深层digest篡改拒绝、同来源/深度的105个分区与单分区查询数相同，以及会话调用顺序防御。
- 对照干净源码归档逐文件比对，执行者仅改约定的5份业务/测试文件；额外诊断脚本不接入。控制者核对执行者文件与独立测试副本字节相同后，仅复制这5份文件到集成分支；原集成文件另有本地恢复备份。未复制缓存/临时目录/诊断脚本，未暂存无关工作。
- `git diff --check`、全局文件及S4路由检查通过。仍需本次提交完整CI与真实PG门禁，生产未更新。
