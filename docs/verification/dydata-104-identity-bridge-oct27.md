# DYDATA-104：订单身份桥与 OpenAPI 采集粒度复核（2026-10-27）

本次仅离线复核主线程已保存的只读聚合与现有代码，不重新采数、不调用平台接口、不更改归属、资格或生产数据。本文是核查证据增量，不改变 DYDATA-104 范围或验收状态。

## 1. 已证实的身份关系与统计边界

官方订单字段合同已明确：`order_sale_info.transfer_uid` 是加密的订单归属人 UID，且**不是抖音 UID**；`order_sale_info.transfer_douyin_uid` 是订单归属人的抖音号；顶层 `craftsman_uid` 是脱敏的职人用户 ID。依据为主线程已实查的[官方订单查询文档](https://partner.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/order.query/query)，其字段摘录文件 SHA256 为 `7e08a059ae322fddba23f6668352e9fb45e7bc45dff48728a88ec61dce881447`。

本次真实保存结果已经证明**同一个原订单响应对象同时返回加密 `transfer_uid` 与短号**，可以作为有来源的配对证据；不再把“加密账号到短号完全未知”作为当前结论。不能通过不同命名空间中相同的文本、昵称、数字形态或状态码建立另一条桥。

复核输入为主线程保存的 `.tmp/identity-short-workbook-oct27-current.json`，SHA256：`d98bdc19de2e0485275461d7d5ed4298f288cf39c78bd54ab349d93f85551283`。记录时间为 2026-10-27 15:53:44（上海时区），原执行为 READ ONLY，5.651 秒，session mutation 为 0。当前 workbook 同一成功采集保留 3,096 行，当下符合既有来源条件的行数与唯一后台账号数均为 **1,150**；主线程已显式将旧基准 1,151 更新为 1,150。这里没有重算、放宽或补写资格。

订单范围是 2026-10-01（含）至 2026-11-01（不含）存在任意原始核销来源的订单，并非已通过核销状态、退款、费率、锁账及确认单资格的订单。

| 互斥范围 | 订单数 | 本次可证实的含义 |
| --- | ---: | --- |
| 同一原响应有短号 | 217 | 全部出现在 `order_sale_info`；全部同时有加密 UID，且原 UID、短号各自与规范化字段一致 |
| 无原始短号，且无 owner | 5,941 | 当前没有可用于本次精确历史 JOIN 的 owner；不能据此推断均需补录或均为某一角色 |
| 无原始短号，有 owner，但无历史同对象配对 | 2,137 | 当前保留数据中未找到所需配对；不是已证明平台从未返回 |
| 无原始短号，有同源历史候选 | 1,400 | 有同对象 UID→短号证据，但跨订单、跨时间的适用性仍需保留边界 |
| 合计 | 9,695 | `217 + 5,941 + 2,137 + 1,400 = 9,695` |

- 217 笔带短号订单中，**2 笔订单**可精确匹配当下合格 workbook，215 笔没有合格匹配；没有输出这 2 笔所涉及的 distinct 账号数。没有合格匹配不等于已确定其具体不合格原因。
- 1,400 笔历史候选中，1,154 笔可候选匹配当下合格 workbook，246 笔没有合格匹配。`1,154 + 246 = 1,400`。当前不是月末资格事实，不能自动入账。
- 历史查询按当前 345 个 distinct owner 限定，检查 240,843 条 retained 订单，找到 3,483 条同对象配对观察，归并为 121 个 distinct UID→短号候选对。在这个范围内没有观察到 UID→多短号、短号→多 UID 或配对 UID 与本行 owner 不一致。
- 其中 **16 个候选对**可匹配当下合格 workbook；该指标统计整个当前 owner cohort 的候选集合，**不是专门对上述 1,154 笔订单子集计算的 distinct 账号数**。不能直接写成“1,154 笔恰好覆盖 16 个账号”。
- 当前 `sale_info` 路径各项均为 0，没有跨 `sale_info`、`order_sale_info` 拼接字段。

## 2. 身份桥还缺的最小证据

| 尚未覆盖的证据 | 为什么需要 | 最小可审计材料；本轮未采集 |
| --- | --- | --- |
| 候选对的逐条原响应出处 | 聚合数可验证分组，不能供协作者追溯每一对 | 每个候选对引用原订单、来源运行、同一 JSON 对象路径、原响应摘要及观察时间；保留字段命名空间，避免导出昵称或完整 payload |
| 历史配对对目标交易的时间适用性 | 一个账号曾使用某短号，不直接证明其他时间仍使用该短号 | 候选来源订单的业务时间、观察时间、目标订单时间、配对最早/最晚观察；短号变更、复用及冲突应原样保留 |
| 当前 cohort 以外的反向冲突 | 本次零冲突只覆盖当前 owner cohort，不能排除范围外短号复用 | 在同一明确来源/商家/租户合同内核对短号→加密 UID 多值及时间交叉；不同范围不能仅按文本合并 |
| 权威月末资格来源 | 10 月 27 日当下 workbook 不等于既定月末时点事实 | 按既有需求采集的完整来源、快照时间/时区、内容摘要及同一短号对应后台账号与资格标签；由既有资格流程判定 |
| 2,137 笔有 owner、无配对的记录 | 不能从昵称或未知详情接口补出短号 | 相同订单的正式字段响应，或有明确输入/输出命名空间合同的权威对应材料；不能把加密 UID 直接传给只接受抖音 UID 的接口 |
| 5,941 笔无 owner 的记录 | 字段可条件返回，缺值不必然是异常或可修复缺口 | 结合原角色、场景及官方返回条件判断缺值是否预期；不按账号名称或相似订单猜补 |
| 1,154 笔子集的精确账号覆盖 | 当前 16 是整体候选对数，不能替代子集去重指标 | 同一个只读结果中对该子集明确统计 distinct owner、短号及后台账号；本轮不重新采数 |

同源配对本身已成立；上述缺口主要决定历史外推与月末资格能否成立。本文不改变已授权历史裁决，不将新候选自动扩展为补录清单。

## 3. OpenAPI `fetched=2,334` 与 `retained=1,926`：代码事实

主线程保存的 v2 结果显示：相应采集任务及阶段成功，`fetched=2,334`，当前该来源保留 1,926 行，差额为 408。**完整性门禁仍拒绝这一不一致**。workbook 独立核查不依赖这一路的资格覆盖；该路完整性仍未知。

本轮核查的四个源文件与主线程当前源码逐字节一致；不以旧版本推断新行为。

| 环节 | 可证实的代码行为 | 对统计的影响与边界 |
| --- | --- | --- |
| item 计数 | [collector](../../apps/worker/collectors/aweme_bindings.py#L18) 对 `data_items` 返回的每个字典先增加 `fetched`，之后才检查规范化账号/短号；两者都为空则增加 `skipped` 并跳过 | identity skip 可造成 `fetched` 大于写入记录数；本次真实 skipped 数尚未包含在保存聚合内 |
| 原始表键 | [绑定键](../../apps/worker/collectors/aweme_bindings.py#L60) 仅由规范化 `account_id:douyin_id:poi_id` 构成，不含状态、绑定起止时间、源版本或观察序号 | 同一键的不同状态/区间不会成为不同 raw 行；这不证明本次 408 条均是此类不同事实 |
| 同键写入 | [upsert_aweme_binding](../../apps/worker/repositories.py#L1214) 调用 [_merge](../../apps/worker/repositories.py#L334)，通过 `session.merge` 按主键合并并 flush；传入本次完整 raw payload 和状态 | 合成输入中已复现同键不同状态/区间最后一个 payload 留存。生产是否发生此情形、涉及多少条，需原响应证据 |
| `upserted` 粒度 | [collector](../../apps/worker/collectors/aweme_bindings.py#L44) 每个可接受观察计一次 raw 操作，有 account_id 时另计一次 Dim 操作 | `upserted` 不是 distinct raw 行数，也不能直接代替接口 item 数 |
| 列表别名 | [data_items](../../apps/worker/collectors/normalizers.py#L88) 按参数顺序取第一个 list，过滤非字典后返回，不拼接多个别名；第一个 list 为空也立即返回 | 不会仅因三个别名同时存在就重复累加；非字典在 `fetched` 计数之前已被排除 |
| 字段规范化 | [first](../../apps/worker/collectors/normalizers.py#L25) 先选非 `None`/空串值，[text](../../apps/worker/collectors/normalizers.py#L42) 再做字符串 trim 和末尾 `.0` 去除 | 某些输入文本可能归为同一规范值；空白首选值也可能挡住后续别名。没有证据证明真实 408 差额包含这些情况 |
| 分页防环 | [collector](../../apps/worker/collectors/aweme_bindings.py#L14) 维护 `seen_cursors`，一次调用内同一规范 cursor 至多请求一次；不同 cursor 的返回 item 没有按绑定键/响应事实去重计数 | 能阻止同 cursor 无限请求，不能阻止不同 cursor 页面含相同绑定；防环退出本身不增加失败计数，因此任务成功不独立证明分页读完。是否真实发生重叠或提前退出尚未证明 |
| cursor 提取 | [next_cursor](../../apps/worker/collectors/normalizers.py#L99) 先读 `next_cursor`/`cursor`，再尝试固定列表尾项；该尾项 fallback 未包含 `openapi_merchat_craftsman_info`；`0`/`-1` 或显式 `has_more=False` 结束 | 缺少支持的 cursor 字段可能提前结束，需真实响应才能判定；不能将其直接当作本次 408 的解释 |
| HTTP 重试 | [query_craftsman_bind_info](../../src/dy_data/douyin_client.py#L343) 返回单次查询结果；[重试包装](../../src/dy_data/douyin_client.py#L411) 最终返回一个成功 payload，失败尝试不会逐次送入 collector | 不存在由客户端将重试响应自动拼成多页的代码。不能仅凭存在 retry 就断言 fetched 重复 |

在“一个独立捕获完成、其 raw 成员随后未被其他写入改变”的条件下，差额可分解为 `身份无效跳过数 + 相同规范绑定键的重复观察数`。当前 retained 行与阶段汇总不能恢复每一条被合并观察的状态或区间，也不能证明以上隔离条件在真实运行中成立。

### 最小下一证据

1. 优先检查**该次既有运行**已经保存的完整 phase 计数（`fetched/skipped/failed/upserted`）和原分页证据。仅有当前 raw payload 不足以重建完整 item 多重集。
2. 对已有原响应计算规范绑定键的频次；按完整状态、精确绑定起止时间及 payload 摘要区分“完全重复观察”和“同键不同事实”。保留页 cursor 摘要与页序，核对不同页是否重叠。
3. 明确该次运行的结束页证据及之后同键写入来源。若当时原响应未保存，应明确“该次差额不能完全复原”；再由主线程决定是否在下一次正常采集保存最小白名单来源证据。本轮不额外请求平台、不补抓、不放宽门禁。

## 4. 本轮验证与未做事项

- 忽略目录中的离线工具：`.tmp/identity_bridge_review/review_aggregate.py`，结果：`.tmp/identity_bridge_review/offline-review-result.json`。
- 保存聚合的所有互斥分组、配对数和来源门禁已断言通过；输入及四个源码文件的 SHA256 在前后保持一致。
- 本地 SQLite 内存合成验证：4 个计入 fetched 的观察，1 个 identity skip，3 个有效观察合并为 1 个 raw 绑定；状态/区间保留最后 payload，`upserted=6` 为 raw 与 Dim 操作合计；两次不同 cursor 请求后重复 cursor 被拦截。
- 合成验证只证明代码机制，不模拟真实的 2,334 条响应，不证明 408 条全为重复、全被覆盖或历史事实已丢失。
- 现有采集测试 `tests/test_worker_aweme_binding_collector.py`：1 passed；治理测试 `tests/test_project_governance.py`：9 passed；套件锁、全局文件门禁及 `git diff --check` 通过。隔离工作树的全局链接检查退出 1，报告其他文件 37 条坏链；本次新增文档没有关联链接错误。主线程整合时统一刷新项目链接索引，本次不改共享索引。
- 本轮没有业务代码变更、生产/API/浏览器访问、重新采数或资格/历史裁决修改。没有完成或部署声明。
