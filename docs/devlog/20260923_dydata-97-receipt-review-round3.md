# DYDATA-97 实收基数与导出进展（第三轮，2026-09-23）

## 结论
- T1.1 仍为**进行中**：未完成、未验收，不改为 Done。
- 上一轮 Codex 独立测试为**199 通过 / 2 失败**，该轮两个旧夹具缺失实收已返修：A-B-A 幂等用例改走 coupon 级 `receipt_amount`，双券归属用例补上第二张券实收。另修复 `sub_order_amount_infos` 存在但非 list 被当作“缺失”回退到整单实收的漏洞：present-but-not-list 现判为损坏并阻断。历史失败已返修，但**不等于全量全绿**。
- 本轮最终全量 `python -m pytest --tb=short -q`：**3160 通过 / 169 跳过 / 1 失败**，耗时 4444.29 秒。唯一失败为 `tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable`，retry 阶段 0.05 秒 fence deadline 超时，继发 Windows SQLite 临时文件占用；**不得写成全绿**。

## 最终真实证据

### 全量回归
- 命令：`python -m pytest --tb=short -q`。
- 结果：3160 passed / 169 skipped / 1 failed，4444.29 秒。
- 唯一失败：`tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable`。表现为 retry 阶段 0.05 秒 fence deadline 超时，继发 Windows SQLite 临时文件占用；不属本任务实收/导出改动。
- 跳过说明：169 skipped 为专用 PostgreSQL 条件未配置（并发、恢复、发布数据库等），**不计入通过**。

### Codex 对照交替复跑（写锁时序敏感）
- 当前分支：lock-fixed-1 失败、lock-fixed-2 通过 15.76 秒。
- 独立未修改 d36d991 基线：lock-baseline-1 通过 16.30 秒、lock-baseline-2 同样失败 22.61 秒。
- 同目录临时还原 HEAD 的 `settlement.py`：测试通过 16.62 秒；随后已 `finally` 恢复修复文件并确认字节一致。
- 证据结论：这是**基线也可复现的时序敏感失败**；记录为限制项，**不改阈值、不修无关写锁模块**。

### 定向与结构验证
- `tests/test_receipt_commission_basis.py` + `tests/test_data_settlement_incremental.py`：99 passed，60.54 秒。
- 导出 API：20 passed / 103 deselected。
- 管理费 history 浏览器：新代码通过；旧代码失败（完成失败复现）；已恢复新代码。
- 既有 4 项导出浏览器测试通过。
- `npm --prefix apps/web run build`：通过，22.98 秒。
- `git diff --check`：通过。
- 治理锁、全局文件 0 errors / 0 warnings、路由 S4、计划结构一致性：通过。
- 索引 33 个已存在断链保持原状，未扩大无关修复。

### 批量查询回归（2026-09-23 新增）
- 用例：`tests/test_receipt_commission_basis.py::test_receipt_batch_variable_limit_resolves_all_coupons_without_n_plus_one`，构造 1001 张券，触及 SQLite 999 变量上限。
- 旧实现红测：**1 failed / 54 deselected（5.92 秒）**，`sqlite3.OperationalError: too many SQL variables`，证据 `logs/dydata97/receipt-batch-red.txt`。
- 修复（dsh）：`apps/worker/settlement.py::_receipt_amounts_for_details` 按 `RECEIPT_COUPON_BATCH_SIZE = 500` 分批查询，归属计数按 `raw_order_id` 跨批次保留整单口径。
- 绿测：Codex 已完成，`logs/dydata97/receipt-batch-green.txt` 已完成：实收、结算、增量定向 **215 passed（135.06 秒，2026-09-24）**。

## 实现口径（已实现）
- 佣金按实收计算：覆盖实收为 0、缺失、损坏、多券、退款、锁账、legacy 月度基数。
- 管理费导出 `includeHistory` 修复。

## 未复现 / 待最终验收
- 用户报告的“整体不能导出”尚未复现；**已再次请求用户提供页面与错误信息**。目前只有管理费 `includeHistory` 列表与导出口径不一致取得失败复现与修复证据，不得据此声称两类导出全面恢复。
- T1.1 与 Issue 保持进行中，待业务故障证据；**无用户验收、无部署、无迁移、无历史账单重算**。
- 空结果行为不变：finance 两导出 200 仅表头，`/order-fee-details/export` 409 `EXPORT_EMPTY`。
