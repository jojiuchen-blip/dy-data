# DYDATA-104：10月30日商品类型权威查询性能验证

## 范围与安全边界

基线为 `d146719c95fb23bcbd06b66c62253212717389ef`。本次只优化新商品类型分析的查询组织，不改变 `commission-product-type-v3` 合同、费用、调整、账单、确认、发票或独立打榜。

- 机械提取 `_sparse_authority_source`，保留原结果、有效调整、完整受保护账单三支来源。
- 默认 `_sparse_authority_relation` 继续原四维展开。以基线函数和当前函数分别编译 8/9 月 PostgreSQL SQL，逐字符相同。
- 分类路径在同一 SELECT 内物化当前受保护账单、全部冻结分录、准确来源及分类结果，后续四维聚合复用同一分类结果。
- 受保护账单及分录 CTE **不按请求月份收窄**；跨月、跨店移动链的排除和后续调整依据保持完整。确认、争议、发票分配、历史发票、状态及时间保护条件全部保留。
- 准确来源保留 `DISTINCT`：原四维 `UNION` 后筛回准确维度形成集合，新路径在展开前直接形成同一集合。空值归一及 `all` 维度去重不变。
- 不新增缓存、索引、迁移，不扩大超时，不跳过验证或锁账拒绝。本任务无 foundation 漂移。

## 编译 SQL 与查询身份

以下均为 `months=('2026-08', '2026-09')`、PostgreSQL dialect、`literal_binds=True` 的 UTF-8 SQL SHA-256。

| 查询 | 字符数 | SHA-256 |
|---|---:|---|
| 原 coverage | 115225 | `af49d5a7d4c5fa2ec3623dace25c32164e4051a93f3b0f1f3cd2e1534f1c8d2a` |
| 新 coverage | 15111 | `2a380a75d2755f2a107431614b5c9ac95774e04f22b725f7e7cb1ceaad07fb61` |
| 原 partitions | 465848 | `61beacdb0662792e4648e612b8a9c8e589096513228284639b6d6d11a244ab89` |
| 新 partitions | 21163 | `a8d6fb0e3352659092a4619e754abb3f2bf95ca5f3070158a4c053695b08d968` |

## PostgreSQL 等价性与回归

在专用本地 PostgreSQL 测试库中，每例创建随机独立 schema 并只清理自身 schema；未读取或修改共享 public 数据。

最终专项命令：

```text
python -m pytest tests/test_commission_authority_query_postgres.py tests/test_commission_product_types_postgres.py tests/test_protected_billing_authority_postgres.py -q
```

结果：**39 passed**，114.23 秒。新增查询对照遍历空月份、八月、九月、两月集合，逐字段比较原展开后准确关系与新准确关系，并比较分类行、has_changes、coverage、partitions、lines。覆盖：

- 方向确认、confirmed_at、locked_at、状态3/4、进行中争议及已结束但保留结果账单的争议；非当前发票分配、已作废历史发票；未保护与已退役账单。
- 跨店跨月冻结链、负数冻结分录、后续退款、明确再核销恢复、未批准替换拒绝、carryforward 仅当前应用及另一方向保留、锁账拒绝。
- 完整 Alembic 升级后的未知快照、两类未解决迁移异常。异常记录不作为全部受保护来源的替代集合，查询前后异常记录及账务事实不变。
- 同单多 SKU 的 distinct 订单数、金额和原快照；未覆盖历史聚合行仍显示；空 SKU、空类型、all 维度。

分类、API、原保护逻辑、只发布流程、队列、实收费用、独立打榜和打榜快照等12个相关测试文件：**208 passed**，62.13 秒。`git diff --check` 通过。最终专项仅有现有 Alembic/Starlette 弃用警告，无测试错误；之前新增测试的必填字段 fixture 错误已修正，不涉及查询结果修复。

## 本地合成规模实际测量

合成数据：5005 条费用结果、3003 条当前指针、1001 条调整、1001 张受保护账单、2002 条账单行、3003 条冻结分录、1001 条确认。分析统计完成后，在相同数据上分别执行 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`，每条 SQL 均保持 3000ms statement_timeout。

| 查询 | Planning Time | Execution Time | 结果 |
|---|---:|---:|---|
| 新 coverage | 4.014ms | 59.510ms | 成功 |
| 原 coverage | 22.007ms | 112.228ms | 成功 |
| 新 partitions | 2.904ms | 151.166ms | 成功 |
| 原 partitions | — | — | 57014，3秒预算取消 |

新 coverage / partitions 计划分别63/69节点；确认、争议、推广发票分配及历史发票各1个表扫描节点。原 coverage 303节点，各保护表28个扫描节点。以上为本地合成数据实测，不能推导所有生产规模的固定时延。

## 主线程生产只读实测

主线程在 `2026-10-30T07:06:39.345304Z` 对上述 **新 coverage 固定哈希**执行强制 READ ONLY、REPEATABLE READ、单 SQL 3秒/总20秒预算的独立查询；执行单元回读私有收据确认哈希、只读标志、完成状态及 schema `20261027_0066`。

- EXPLAIN（非 ANALYZE）20.963ms；实际 SELECT 执行47.161ms，成功。原查询此前两次在3秒预算下返回57014。
- 生产计划59节点，确认、争议及票据保护表各1个扫描节点。
- 当前8/9月权威集合完成分类核查；真实业务行数和SKU统计仅保存在104受控回执。这些是费用/冻结分录事实，**不是券数，不代表缺费已补或历史聚合已全覆盖**。

这证明指定 SQL 的只读查询性能，不代表本代码已部署、全模块已发布、历史账务已修复或 DYDATA-104 已完成。生产 partitions、完整发布及其他业务验收由主线程分别记录。未覆盖历史聚合应复用当前 pinned monthly/ranking 来源，以对应月/累计的准确来源 store 集合做反连接，单独核对行数，不能从 coverage 事实数推断为零。

## 可复核调用与证据

调用接口未改变；在调用方已建立并限时的只读事务中执行：

```python
from apps.api.dy_api.dashboard_publications import commission_types

coverage = commission_types.coverage(session, ("2026-08", "2026-09"))
partitions = commission_types.partitions(session, ("2026-08", "2026-09"))
```

编译可用捕获 `session.execute` 参数的无数据库对象，测试文件提供该方式。工作树忽略目录保留 `authority-query-comparison.json`、`authority-synthetic-explain.json`、`authority-postgres-final.xml`、`authority-regression.xml`；主线程私有目录保留生产只读收据。真实业务标识、凭据、完整生产SQL/计划未提交Git。

## 10月31日标准API入口交叉验证

全仓经标准`dy_api`入口暴露了一个双导入路径缺陷：分类CTE选择相对模型，而保护谓词的默认模型来自`apps.api.dy_api`，产生重复FROM并报列名歧义。修正为显式向保护谓词传入本次选择的SettlementStatement；不改默认worker金融关系或保护条件。

新增双入口coverage/partitions四例先红（2失败/2通过），修复后与原finance publication完整文件合计25通过；同四例在真实PostgreSQL均通过、0跳过。重新编译两类查询仍与上表SHA一致，原默认金融SQL逐字符相同；此前指定SQL的生产只读性能证据继续适用。这也区分了此前只测apps入口的39项证据与新增标准API入口的证据。
