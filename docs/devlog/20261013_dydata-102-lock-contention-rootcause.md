# DYDATA-102/103 生产日链失败真实根因：clue master materialization 事务锁竞争

2026-10-13 补充：只读生产诊断（GitHub Actions run `38491997277`，`--ref codex/dydata-102-103-readonly-diagnosis`）已取回并解密报告，**原始 `worker_exit_1` 根因已确证，不再是未知占位**。本文件只记录定位证据与下一步，不含任何生产写入。

## 1. 已确证证据

- 六个固定日期（2026-09-14/16/20/25/28、2026-10-09）共 **18 条 attempt**（六日 × 3 次重试），**完整异常末尾全部相同**：
  `RuntimeError: clue master materialization lock unavailable`。
- 调用链（报告中的 traceback 逐帧）：`daily_task.materialize` → `run_incremental_clue_materialization` → `_process_incremental_clue_work_item`。
- 该消息只有一个产生点（源码核实）：`apps/worker/clue_allocation.py:1579-1580`——增量页处理调用 `materialize_clue_master_leads(...)` 后，若返回 `{"skipped": "locked"}` 即抛出。
- 九月源数据现状（只读，未推定可结算）：`raw_douyin_verify_records` 非取消 10,909 行、取消 100 行；`settlement_statement`（`2026-09`、`is_current`）0 行、相关金额 0；`settlement_fee_result` join `settlement_fee_result_current`（`2026-09`）**为空**。合格来源与金额口径后续必须复用真实 settlement 选源读路径核对，不得用 raw/`paid_amount` 代替。
- 运行态：实际运行镜像仍为 `dydata103-alert-20261010`；服务器 checkout `ba3976c`；`last-deploy.json` 的 `08cd321` **不能**作为实际运行代码的证据。
- 全量 `python -m pytest` 仍在另一进程进行（约 80%，已出现 1 个失败待末尾详情）。**该进程不得终止或重复启动。**

## 2. 竞争机制（代码只读追踪）

- 锁是**事务级 advisory lock**：`_try_transaction_lock`（`apps/worker/clue_allocation.py:3649-3654`）使用
  `pg_try_advisory_xact_lock(_advisory_lock_key("clue-allocation-master-materialization"))`，
  锁键 = `sha256(lock_name)[:8]` 的有符号 64 位整数（非机密，可作为只读诊断输出项）。
- `materialize_clue_master_leads` 在**函数开头**取锁（`clue_allocation.py:174-175`）；取不到立即返回
  `{"skipped": "locked"}`——**没有等待、没有 backoff、没有重试窗口**。
- 调用方把“锁不可用”当成**终态致命错误**抛出：`clue_allocation.py:1580`（增量页路径）与
  `apps/worker/daily_task.py:707`、`apps/worker/daily_task.py:809`（同一锁的另外两处）均直接 `raise RuntimeError`，
  该异常使 daily child 以 exit 1 结束并记为 `worker_exit_1`（`apps/worker/subprocess_supervisor.py` 记录
  `exit_type`/`exit_code`）。
- 因此命中竞争时，当天计划的所有重试都在同一个竞争窗口内立即失败，日链整体失败；这也解释了 18/18 完全同因。
- 其他同锁竞争方（本次未改动，仅登记）：`apps/worker/pipeline.py:322`、`apps/worker/formal_allocation_runtime.py:176`
  （`notify_formal_allocation` → `run_formal_allocation_batch` 的每页回调，随增量页在同一事务内被调用）、
  `apps/worker/materialize_once.py:98`。**持锁者身份仍是假设，不得写成结论**：候选是并发增量页/正式分配回调造成的长事务
  （同一 worker 的多会话，或其它 worker/手工重建），需要用下面的只读诊断证实。

## 3. 下一步：锁竞争专项（待门禁）

1. **只读持锁诊断（仅诊断分支扩展）**：查询 `pg_locks`（`locktype='advisory'`、`classid/objid/objsubid` 映射锁键）join `pg_stat_activity`，
   只输出 PID、锁键、`state`、`xact_start`/`query_start` 与等待时长，**不输出 SQL 文本、不输出凭据**；固定日期窗口内取样即可。
2. **最小根因修复（回 `codex/dydata-102-103-controlled-release`，先等 pytest 结束再 merge/main/业务代码）**：
   - 把“锁被占用”从终态失败改为**可重试的瞬时状态**：对 advisory lock 采用**有界等待 + backoff**（或把 `skipped: locked`
     明确上抛为可重试错误码/状态，由既有重试机制重新领取），让页处理在持锁事务提交后继续，而不是立即杀死当天计划。
   - 保持锁语义不变：**禁止强制释放生产锁、禁止绕过锁**；`skipped: locked` 仍不得被当作“成功”吞掉。
   - 同类调用方（`daily_task.py:707/809`）使用同一可重试语义，避免只修一条路径。
   - 必要的诊断可观测性：记录等待时长/重试次数（不含 SQL 文本与凭据）。
   - 生产持锁者确证后，若确为长事务（正式分配回调跨页持锁），再评估把该回调移出持锁事务或缩小事务范围；**这属于后续独立变更**。
3. **必要回归**：`tests/test_clue_allocation_incremental.py`（现有用例在 `~2991` 处断言 `RuntimeError match="lock unavailable"`，
   必须随语义更新为“有界重试后仍不可用才失败/或等待期间成功”），并补两个用例：①同一把锁被另一会话持有时本会话等待后成功；
   ②超过有界等待仍被占用时才以可重试错误结束且不吞锁。Postgres 路径用例（若仓库已有 `*_postgres` 相关锁测试）一起更新。

## 4. 边界

- 本轮只做定位与方案；未部署、未补跑、未释放任何生产锁、未改业务代码。
- 诊断分支只保留只读诊断（不把覆盖 deploy workflow 的版本合入业务发布分支）；业务修复走集成分支 → PR → main → 既有 `tencent-lighthouse-deploy.yml` 门禁。
