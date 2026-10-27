# DYDATA-104：月末冻结自动计算与统一出账门禁

## 原因与边界

原 `ensure_month_close_job` 在冻结月末资格后调用正式发布 preflight；旧 current 未 pin 会被 qualification digest 拒绝，零 current 被 NO_CURRENT_RESULTS 拒绝，导致正式月任务无法自动启动。冻结本身不创建费用 JobImpact，普通增量没有源 delta 时不会重算整月，不能靠手动全库模式解环。

本修复只改月结派发/既有 runner 的资格门禁，复用原 month-scoped 费用选择、计算、queue/heavy claim/resource/lease/retry 和正常发布事务。没有改资格、身份、分币、费率、已确认金额或旧费处置策略；没有执行生产操作。10 月实际月底尚未发生，以下为合成完整日/观察证明，不能当作真实月末冻结收据。

## 启动与正式发布分别判定

- 2026-10 起：成功冻结 + 当月每个上海业务日真实 finalize 完成 + 未锁账 + 无其他活跃 rebuild，允许派发原正式 month-scoped 计算任务；启动不依赖先存在新资格费用。
- `month_close_preflight` 和 `month_source_watermark` 仍要求至少一条 current 且该月全部 current pin 期望冻结版本。派发不会假报正式 READY。
- 8/9 月原派发与已核验 watermark 行为保留。普通增量路径不新增特殊全库模式，不伪造 JobImpact。

## 稳定计算输入

启动 SHA-256 绑定协议/月、完整 day@finalize revisions、冻结 version/content 和历史裁决。原始输入范围从当月核销候选及该月不可变历史费用的 coupon/order **地址**取得，再读取相关订单及同订单券、核销、退款事件、SKU、有效费率/范围配置、销售账号/绑定、POI/门店和不分佣配置。

- 历史费用仅定位原始来源地址，不将费用 ID、金额、状态、版本、pin 或计算时间写入 hash。退役 current 后保留原地址，防止输出改变自己的输入 scope；新费用地址本来已由当月核销覆盖。真实 retire 回归先复现 hash 变化，再验证修复后不新增任务/预算。
- 只查询必要列和受控 JSON 子字段（身份 origin、receipt/count/sub-order、绑定 interval/type），保留 missing/null/0 类型差别；不加载完整 raw payload 或全库历史订单。
- SQL 按月/关联地址限定并稳定排序，500 行流式处理，无条数截断；没有缓存或全库 counter。不分佣名称使用原规范化函数，只查询相关唯一配置键。
- 不相关月份、来源更新时间、采集 run ID 和无关大字段不改变 key；相关实收、费率等变化产生新 key。
- job key 使用输入 SHA 前 32 hex，以满足下游 generation/bundle 的现有 128 字符边界；metadata 保存并复核完整 64 hex，冲突拒绝。该长度问题由真实 PG 完整自动发布测试发现并修复，无 schema 放宽。
- 自动任务在费用重算前及提交前复核同一输入摘要。重复 tick、重算追加费用版本和失败重试均复用同一 job；真实 worker 三次失败后预算耗尽，scheduler 不通过随机 job 重置预算。

成本只测合成规模：2 个 coupon、31 日完成证明，独立 digest 每次 15 条查询，三轮 SQLite 为 40.74/35.89/28.70 ms；不将该数值当生产容量结论。

## 统一正式出账保护

- month runner：真实重算后、费用事务提交/refresh 前，核验该月每条 current fee 均引用期望冻结版本；未知/明确不合格旧未 pin 费用留存时，抛出明确 `current_fee_qualification_version_mismatch`，整批回滚。
- full runner：原 legacy 费用和聚合事务提交前，对实际 current fee/current bill 涉及的 2026-10 起月份检查；active pointer 为空也不能绕过。没有 10 月经济输出的 8/9 初始化继续正常。
- refresh：首次及最终捕获前后都核验实际 `plan.affected_months`，包括 slot/bill 锁等待后的复读；任一 current 未 pin 即拒绝切换 pointer/账单版本。
- publication-only：对真实月份 closure 提前同样核验，apply 首末持锁捕获继续严格检查。8/9 不含 10 月 closure 时不要求 10 月冻结；真实依赖闭包包含尚未冻结的 10 月时拒绝整个批次，不截断闭包。
- 没有过滤/删除旧费用来通过门禁，不改普通 dashboard GET/prewarm，不触及 qualification policy。

## 验证范围

新增 `tests/test_month_close_auto_bootstrap.py`：完整 31 日真实 daily plan/finalize + 最后完整月末 observation，通过 ensure 自动派发，正常月 runner 实际选择 Oct5/Oct20 两券全月重算双费、pin、发布并生成账单。分别覆盖旧未 pin 和月中真实零费状态；没有 stub 费用、选择月份或资格判断。

另覆盖缺日、月底末次失败、活跃任务、锁账、资源 STOP、相关/无关源变化、同输入三次正常 worker 失败预算、current retire 不换 key、排队后源漂移、未知/明确不合格旧 current 金额/指针不变、末次持锁捕获一条未 pin 阻断、full 无 active 的费用/聚合整体回滚、纯发布真实 Oct closure 拒绝和 8/9 正常。

SQLite full legacy 事务测试使用文件库并只 stub heartbeat progress（SQLite 单写者限制），实际费用、选择、资格、guard 和 commit fence 均执行；PG full 路径使用真实独立事务及 heartbeat。现有 rebuild PG 小 fixture 补齐新严格事务门禁实际查询的 fee/current/statement 表，不能跳过缺表校验。

新增 `tests/test_month_close_auto_bootstrap_postgres.py`，复用 `DYDATA_PROTECTED_TEST_DATABASE_URL`，只允许 loopback `_test` 库，每 case UUID schema，覆盖两自动完整闭环、并发 tick 幂等/预算、未知旧 current 回滚及 full 无 active 聚合回滚。未用生产库。

已执行相关旧合同与新用例：109 passed；新增 PG 首次完整五项 5 passed / 67.55s。immutable 地址选择后的 PG 完整五项重验 **5 passed / 160.83s**；PG full 无 active 使用真实 heartbeat/独立事务再验 **1 passed / 41.76s**。最终月结/资格/只发布/正常 worker/API 相关集 **179 passed / 280.27s**。命令为共享 venv `python -m pytest <对应文件> -q --tb=short`，退出码均 0；编译与 diff-check 通过。
