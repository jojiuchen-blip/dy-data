# T2.3 不可变双费用结果与调整

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T2.3 重构结算引擎为推广/管理双方向不可变结果与事件调整

**Requirement ID**：DYDATA-31-FEE

**PRD 双链·读**：
- `docs/prd/foundation/foundation-glossary-dy-data.md` 中结算范围、双费用、基数、调整与月份术语
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` §1-§3
- `docs/prd/subprd/02-subprd-store-settlement.md` §4-§6
- `docs/prd/subprd/03-subprd-order-fee-details.md` §3-§5
- Linear DYDATA-31

**核心逻辑**：
- 推广费按销售业务日、销售门店和销售月；管理费按核销业务日、核销门店和核销月。只纳入有效商品、稳定归属账号、直播/短视频渠道。
- 按规则匹配日选取不晚于该日的最新 ACTIVE 双费率版本；冲突或缺失进入数据质量阻断。
- 一券一方向生成不可变结果；未锁账重算新增版本后事务切换当前指针，不覆盖旧结果。
- 部分退款同比减少基数、全额退款归零、取消核销仅调整管理费；后续事件新增调整并进入事件发生月份。

**核心文件**：
- `apps/worker/settlement.py`
- `apps/worker/repositories.py`
- `apps/worker/collectors/orders.py`
- `apps/api/dy_api/models.py`
- `tests/test_data_settlement.py`
- `tests/test_worker_order_collector.py`

**完成标准**：
- 正常销售/核销、同店/跨店、未支付关闭、未知 SKU/渠道/账号、双费率日界、部分/全额退款、取消核销和重复事件均有自动化用例。
- 金额以整数分和 ROUND_HALF_UP 计算；原始金额 + 调整金额 = 调整后净额；重复运行不重复创建当前结果或调整。
- 原结果、费率和规则版本保持不变；锁账来源不得切换当前指针。
- 数据质量问题记录可追溯但不泄露原始载荷或凭据。

**Verification Method**：
- 先扩展 fixture 形成红灯；执行 `python -m pytest tests/test_data_settlement.py tests/test_worker_order_collector.py -q`。
- 对至少 10 个覆盖边界的脱敏样例执行输入、结果、调整和质量问题逐项比较。

**Evidence**：
- 自动化测试、脱敏样例对照表与 `docs/devlog/` 双费用核对记录。

**Failure Handling**：
- 稳定归属账号 ID 或真实渠道枚举缺失时，相关方向标记 BLOCKED，不按名称或未知渠道猜测。
- 缺单券金额的多券订单不得重复使用整单金额；阻断并记录质量问题。
- 任一方向失败不得污染另一方向已经合法的不可变结果。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.3、T2.1、T2.2

**状态**：已完成（2026-07-20）
