# T2.4 账单冻结与月度/榜单投影

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T2.4 生成三层账单来源并重建双费用月度与排名投影

**Requirement ID**：DYDATA-31-STATEMENT

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` §4-§8
- `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md` §0-§2、§5
- `docs/prd/subprd/01-subprd-store-ranking.md` §3-§5
- `docs/prd/subprd/02-subprd-store-settlement.md` §3-§6
- Linear DYDATA-31

**核心逻辑**：
- 内部锁账事务先冻结费用结果/调整来源项，再按方向 + 产品范围 + 商品类型汇总账单行，最后汇总账单头并原子切换 LOCKED。
- 三层金额不一致禁止锁账；锁账后头、行、来源不可改。后续调整进入事件月另一账单。
- 月度投影区分原始、调整和净额；榜单支持 MONTHLY/CUMULATIVE，正式累计固定从 `2026-08` 开始并排除 7 月测试数据。

**核心文件**：
- `apps/worker/settlement.py`
- `apps/api/dy_api/models.py`
- `apps/api/dy_api/routes/_data.py`
- `tests/test_data_settlement.py`
- `tests/test_api_dashboard.py`

**完成标准**：
- 同一门店 + 月份只有一个账单头；来源只进入一个账单；原始 + 调整 = 净额在来源、行、头和投影四层一致。
- 锁账后修改费率或重跑结算不改变冻结金额、费率集合与规则版本；后续调整进入调整入账月。
- 月度/累计投影覆盖销售、核销、推广净额、管理净额和参考净额，累计不含 `2026-07`。
- 重建可观察、可重跑；失败不留下半锁账或半更新投影。

**Verification Method**：
- 执行 `python -m pytest tests/test_data_settlement.py tests/test_api_dashboard.py -q`。
- 对未锁账、锁账、锁账后退款三个样例核对来源/行/头/投影金额及月份；执行重建两次比较行数和金额。

**Evidence**：
- 测试结果、四层金额对照 SQL 摘要与 `docs/devlog/` 账单/投影记录。

**Failure Handling**：
- 三层金额或来源计数不一致时事务回滚并记录质量问题，禁止进入 LOCKED。
- 已锁账来源异常时不得回退到当前指针；保留审计并阻断查询/发布。
- 大表重建需分批并记录处理/跳过/失败数量，禁止无界生产全表操作。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T2.3

**完成证据**：2026-07-20 完成三层账单冻结、当前结果/调整血缘、事件月调整、月度与累计榜单投影、正式账期隔离、共享门店账期锁、失败回滚审计及锁账后迟到数据阻断；目标测试 45 passed，受影响结算、Dashboard、Schema、Alembic、采集与规则 API 回归 86 passed，最终代码复核无 Critical。PostgreSQL 双会话竞态和生产级大数据量压力验证列入 T4.1 发布门禁。

**Foundation 漂移结论**：业务口径无漂移；为稳定区分“计算快照内退款”和“后续事件月调整”，补充 `douyin_refund_event.successful_observed_at` 不可变首次成功观察时间及 0023 兼容迁移，并已同步 Foundation Schema。

**状态**：已完成（2026-07-20）
