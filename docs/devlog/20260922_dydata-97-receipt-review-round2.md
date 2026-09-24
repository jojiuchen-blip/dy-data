# DYDATA-97 实收基数审查返修（第二轮）

## 背景

首轮 140 个金额/结算测试通过，但 Codex 代码审查发现实收解析与月度分佣基数仍有缺口。
本轮只改金额侧文件与测试，不改前端。工作区约束禁止 pwsh/bash，本轮**未执行任何
pytest/node 命令**；下面记录的是新增用例在修复前代码上按代码路径推断的预期失败位置，
供 Codex 独立复跑核对，不是已运行结论。

## 新增/加强用例与预期旧版失败位置

全部在 `tests/test_receipt_commission_basis.py`。

| 用例 | 覆盖 | 旧版预期失败位置 |
|---|---|---|
| `test_single_coupon_multi_sub_entries_sum_to_order_receipt` | 单券、无 item id、子项 5000+3000=8000 | `apps/worker/receipt_amounts.py` 旧 `SubOrderReceipts.from_payload` 跳过无 `order_item_id` 行，`unique` 为空；旧 resolver 单券回退 `len(unique)==1` 不成立返回 `None`，`_fee_result(...)` 为 `None`，`assert promotion is not None` 失败 |
| `test_single_coupon_multi_sub_entries_aggregate_beats_order_total` | 子项合计优先于整单 9999 | 旧 resolver 忽略无 id 子项后落到订单 `receipt_amount`（旧第 179-183 行），返回 9999，`assert promotion.source_amount_cent == 8000` 失败 |
| `test_multi_coupon_sub_entries_without_item_id_are_not_aggregated` | 多券禁止按比例/合计分摊 | 旧版已阻断，本轮为防回归覆盖 |
| `test_single_coupon_duplicate_sub_attribution_blocks_aggregate` | 显式重复归属不得用不完整合计 | 旧版已阻断，本轮为防回归覆盖 |
| `test_single_coupon_corrupt_sub_entry_blocks_even_with_own_item_id` | 自身 item 有效、兄弟项损坏不得掩盖 | 旧 resolver 命中 `unique[item-a]`（旧第 171-175 行）返回 5000，`assert ... is None` 失败 |
| `test_single_coupon_corrupt_no_id_entry_is_not_ignored` | 无 id 损坏项不得被忽略后取整单 8000 | 旧 resolver 跳过无 id 损坏项后回退订单 8000（旧第 179-183 行），`assert ... is None` 失败 |
| `test_single_coupon_interface_count_above_one_blocks_order_basis` | 接口 `count=2` 时禁用整单/合计 | 旧 resolver 无 `count` 校验，返回 9999，`assert ... is None` 失败 |
| `test_single_coupon_interface_count_one_allows_order_receipt` | `count=1` 保留整单口径 | 旧版同样返回 8000，正向对照 |
| `test_coupon_level_unusable_receipt_blocks_despite_valid_order_receipt`（bad/null） | 券级字段存在但损坏必须阻断 | 旧 resolver 旧第 161-165 行把 `None` 当“未提供”，回退订单 8000，`assert ... is None` 失败 |
| `test_corrupt_sub_order_array_blocks_instead_of_order_receipt` | sub 数组存在但损坏不得被订单额掩盖 | 旧 resolver 忽略损坏子项后回退订单 8000，`assert ... is None` 失败 |
| `test_coupon_level_zero_receipt_beats_order_receipt` | 券级 0 优先级 | 旧版返回 0，正向对照 |
| `test_locked_statement_survives_unprovable_receipt_force_recalculation`（missing/invalid） | 锁账 + 缺失/非法实收 + force 重算不得删冻结额 | 旧版 `_retire_unqualified_fee_result` 已按锁账提前返回，预期旧版也通过；本轮为强制回归闸门 |
| `test_legacy_monthly_commissionable_total_uses_receipt_basis` | legacy 月度基数 8000（实付 10000），月份 2026-07 避开投影重建 | `apps/worker/settlement.py` 旧 `_rebuild_monthly_settlement` 第 6014 行 `+= detail.paid_amount_cent`，`commissionable_total_cent` 为 10000，`assert == 8000` 失败 |
| `test_legacy_monthly_commissionable_total_keeps_receipt_on_rounding` | 小额舍入：receipt 12345、佣金 1235 | 同上，旧基数 10000，`assert == 12345` 失败 |
| `test_legacy_missing_receipt_yields_no_commission`（加强） | legacy 缺失实收记录数据质量问题 | 旧 `_materialize_coupon` 只把 `is_commissionable` 置 False，无 `legacy_missing_receipt_amount`，`_has_issue(...)` 失败 |

月度用例把事件放在 2026-07：`_projection_months()` 只重建 `>= 2026-08` 的月份，
因此 `rebuild_dual_fee_projections` 不会删除 legacy 月度行，断言读到的就是
`_rebuild_monthly_settlement` 的产物。

## 实现要点

- `apps/worker/receipt_amounts.py`
  - `SubOrderReceipts` 增加 `entries_present` 与 `complete_total`：仅当每行都是 dict、
    `receipt_amount` 可证明、且无重复 item 归属时才给出整数分总和；否则为 `None`。
  - 券级 `receipt_amount` 键存在即视为证据：合法（含 0）直接返回，损坏/`null` 返回
    `None`，不再回退订单额。
  - 单券订单：先看接口 `count`（`>1` 阻断），再优先用完整子项合计，否则订单额。
  - 多券订单：仍只按唯一 `order_item_id` 归属，不按比例猜。
  - 新增 `OrderAttribution` 与 `load_order_attributions`，用两个 group by 批量预取
    券数/同 item 券数，供批次复用；不持久化、不跨运行缓存。
- `apps/worker/settlement.py`
  - `_materialize_coupon`：实收不可证明且其余条件满足时，记录
    `legacy_missing_receipt_amount` 数据质量问题，不再静默关闭佣金；实付字段含义不变。
  - 新增 `_receipt_amounts_for_details`，在当前批次预取 order/coupon/归属并复用 helper，
    避免逐券 N+1。
  - `_rebuild_monthly_settlement` 的 `commissionable_total_cent` 改用解析出的实收分，
    不从已舍入佣金除费率反推；`self_verify_income_cent` 等实付统计保留。
- 无新增表列、无迁移、不执行真实账期重算。

## 未执行与待验证

- 本轮未运行 `python -m pytest`、未运行任何 node/npm 命令；上表为静态推断的旧版失败位置。
- 待 Codex 独立运行 `tests/test_receipt_commission_basis.py` 及相关回归并核对。
