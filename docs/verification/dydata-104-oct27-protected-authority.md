# DYDATA-104：受保护账单完整来源 authority

## 边界与合同

本提交仅改变读取、来源捕获及投影聚合 authority；不修复 fee pointer，不重算/写入费用，不改确认、票据或受保护金额。尚未提供生产执行或发布恢复结论；实际四店月 379 entries 的生产证据由主线程独立验收。

- 统一复用原账单生成器 `_protected` 合同：任一方向确认、已确认/锁账头、争议或任一历史票据依赖均保护整份 current bill 的全部 entries、双方金额及全部 lines。
- 保护来源使用 immutable entry 的 ID、金额、维度及展示快照。展示 NULL 保留 NULL，不从当前 raw/product/门店资料补齐。
- 经济 `source_amount_cent` 始终通过精确 `original_fee_result_id` 读取旧 immutable FeeResult；逐项校验 coupon/order/direction/month/base/fee/rule。允许旧 result 已被 supersede（status=2），不能改用 current pointer 或 received display snapshot。
- 当前 primary 与冻结 primary 同 coupon+direction 的费用链在搬店、搬月后仍被抑制；相关旧月/新月进入月份闭包。此链过滤仅作用于 primary，不吞其他方向或其他 event anchor 的调整。
- 新的 exact-old-basis refund/cancel/carryforward 保留原 anchor 与冻结展示；carryforward 仅当前 application 生效。新 verification 必须具有显式旧 anchor、旧核销取消且剩余费归零、独立新 verify、确切 restoration 证据；不能证明则 fail closed，不自动重锚或折算差额。
- 保护槽位的新费用或未批准调整不进入该槽位；无保护槽位继续当前事实。entry/header/line 不闭合、重复身份、未知 basis 均拒绝。冻结 adjustment 比较其精确 immutable event 的金额及 anchor 身份，不把 adjustment 金额直接与 primary 金额比较。
- 捕获按排序 slot locks 后锁 current bill 行，再重新读取完整来源，序列化真实确认写入；新增槽位或来源漂移要求新事务/新 job。原 bundle 指纹校验及普通锁账重算拒绝均保持。

## 合成 fixture 修订

`test_dashboard_publication_finance.py` 原 fixture 只创建 status4/已确认头及 177/101 等金额，部分只创建 line，未创建 immutable entries；新完整 authority 校验会正确拒绝。现在只为这些合成头补齐与原有 header/line 金额、数量、维度一致的 entries 与精确 original FeeResult。原 177 分、分类汇总、锁账、确认和导出断言保留。未发现或推断真实业务允许缺失来源；真实数据如不闭合必须独立调查，不能套用测试修订。

`test_billing_source_capture.py` 的 slot-wait 单元 stub 显式 mock 新的完整来源检查和 bill 行锁；该单元只测原 slot 等待后复读，真实保护与确认竞争由 PostgreSQL 用例验证。

## 验证

- SQLite 合成覆盖：单方向确认保护双方、status2 头、同槽及跨店/月 current V2、冻结负调整、NULL 展示、经济 source_amount 与 received snapshot 区别、exact old basis、新 pointer 拒绝、cancel/reverify/restoration、active carryforward、另一方向合法调整、nested lines/metrics 同 authority、闭包及缺失来源 fail closed。
- PostgreSQL：专用 loopback `dydata_delivery_test`，每 case 随机 `protected_authority_<uuid>` schema，结束仅删除该 schema；使用 `DYDATA_PROTECTED_TEST_DATABASE_URL`，不记录密码。覆盖真实 SQL、同/跨月、nested lines、basis 拒绝及确认行锁等待；另一个 case 执行完整 Alembic head 后验证 fail closed 与 source counters 不变。
- 本提交不新增 schema/migration。GET、正常 source version/counters 的写入合同不变。
- 普通 `refresh_active_settlement_lineage` 的 plan 提前取得同一月份闭包，用于 capture/build/hash；闭包触及锁月明确拒绝。新回归请求单月但冻结链跨两月，真实 capture 和 build 入口接收同两月。
- 已执行：相关 authority/finance/monthly/projection/capture/billing/generation 回归 **213 passed, 2 skipped**；追加普通 month-scoped/plan/generation 回归 **127 passed**；冻结 adjustment 精确 anchor 校验后的 authority+finance **36 passed**；最终 PostgreSQL（含完整迁移与确认竞争）**7 passed / 87.11s**。命令均为共享 venv Python 的 `-m pytest <对应测试路径> -q --tb=short`，退出码 0。

## 后续独立提交

纯发布 coordinator/CLI 应使用正常 heavy admission、claim/lease，默认 dry-run；preview hash 绑定 active base、请求与闭包月份、完整 authority sources、账单 ID/版本/保护状态。apply 重验后直接 capture→build→ready→锁后 recapture→publish+generate_pending 原子事务，不调用普通 materialize/rebuild fees。本 core 不宣称已经提供该受控恢复入口；当前仍拒绝 status4 月份。
