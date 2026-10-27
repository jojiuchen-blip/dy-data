# DYDATA-104 重核销血缘与冻结依据保护修复

2026-10-27，T3.1 已授权的窄范围回归修复。基线为 `1eca0abe321fa594a9fd6c534cfcad7fc6151875` 加独立 CI 提交 `9d2d4cd10eb19029ce98e4bd67d6c197ad7bcbcd`；本修复另行提交，只涉及 `apps/worker/protected_billing_authority.py`、`tests/test_protected_billing_authority.py` 与本文档。未修改结算写入、退款、工作流、迁移或生产配置。

## 失败复现与现有合同

共享项目 Python 独立运行以下两个既有 nodeid，基线为 **2 failed，4.68 秒，exit 1**：

- `tests/test_data_settlement.py::test_locked_reverification_appends_delta_and_preserves_history[False-True]`
- `tests/test_data_settlement.py::test_locked_reverification_appends_delta_and_preserves_history[True-True]`

参数顺序为 `locked_event_month`、`reuse_verify_id`，两例均复用核销 ID。来源捕获调用 `validate_protected_authority` 后，在旧第 278–281 行因 ID 未变化而拒绝合法重核销。

失败帧独立取证：原依据资格时间为 2026-09-05 02:00:00，新依据为 2026-10-10 02:00:00，两者核销 ID 相同；准确 anchor、restoration、cancellation 均存在，原依据费用净额为 0，新依据状态为 2。唯独旧的“核销 ID 必须不同”条件不成立。时间仅为合成测试事实，非生产数据。

[费用结果 Schema](../prd/foundation/foundation-schema-dy-data/settlement-reporting.md) 的 `qualifying_verify_time`（原第 39 行）与 0051 血缘兼容段（原第 59 行）已经明确：ID 和时间共同识别核销血缘；冻结槽位通过关联原结果的追加差额恢复，不替换冻结依据。`settlement.py::_same_qualifying_verification` 也按 ID 与归一化时间共同识别同一次核销。**本任务无 foundation 漂移**，只是保护读端回归到既有合同。

## 最小修复与保护边界

保护守卫要求 basis 和 anchor 的资格时间均非空，并在 `_as_utc` 归一化后判断：核销 ID 不同，或同 ID 对应不同时间，才可能作为另一核销血缘。相同 ID、相同瞬间即使时区表示不同，仍拒绝。

准确冻结 anchor、新依据状态、核销 ID 非空、明确恢复证据、原核销取消证据以及原依据净额归零的检查均保留。冻结账单来源项与当前费用指针不变，不放宽退款口径，不绕过账单保护。

新增 8 组收据集成测试覆盖：同 ID 新时间允许、不同 ID 同时间允许、同 ID 同时间拒绝、同瞬间不同偏移拒绝，以及同/不同 ID 的任一资格时间缺失拒绝。测试同时检查冻结来源项和当前指针不变；SQLite 会丢失存储偏移，因此偏移用例保留 ORM 中真实的 aware 时间快照供守卫检查。

新增测试在旧业务源码上的红测为 **2 failed / 6 passed / 15 deselected，4.80 秒，exit 1**，分别证明合法血缘被误拒绝和原 anchor 时间缺失被误放行，未修改既有断言掩盖回归。

## 验证记录

- 共享项目 Python 执行 `python -m pytest -q tests/test_protected_billing_authority.py tests/test_data_settlement.py tests/test_data_settlement_incremental.py tests/test_billing_source_capture.py --tb=short`：**266 passed，133.19 秒，exit 0**。包含新增 8 组血缘场景、既有锁账重核销测试全部 4 个参数组合，以及结算增量、冻结来源和保护依据相关回归；0 skipped。
- 将受控本地测试配置的 `DYDATA_DELIVERY_TEST_DATABASE_URL` 仅在测试进程中映射到 `DYDATA_PROTECTED_TEST_DATABASE_URL`，确认 loopback、专用 `dydata_delivery_test` 后执行 `python -m pytest -q -ra tests/test_protected_billing_authority_postgres.py --tb=short`：**11 passed，136.52 秒，exit 0，0 skipped**。覆盖真实行锁、迁移 Schema、保护查询及 coordinator；9 条现有依赖弃用警告，没有错误。每个 fixture 使用独立 UUID Schema 并清理，不使用生产库。
- 治理锁、T3.1 计划一致性、执行环境和任务上下文检查通过；全局文件校验 0 errors / 0 warnings，路由 S4 可进入。
- `git diff --check` 通过。新文档链接指向既有费用结果 Schema；未变更 foundation 或迁移。

本轮未执行全仓 pytest 或前端构建；此次写集没有前端或依赖变更，最终集成仍需主线程完整门禁。

## 交付边界

本轮未推送、合并、运行远端 CI 或操作生产；最终集成与生产验收由主线程独立回收。技能 usage/audit 仅写宿主规定的本机日志，工作流 memory 文件未更新。
