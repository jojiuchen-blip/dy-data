# Database Schema - dy-data（抖音经营引擎）

> 生成时间: 2026-07-17 15:46
> 来源: foundation-builder Phase 3
> 关联: [术语表](foundation-glossary-dy-data.md) · [API](foundation-api-dy-data.md)
> 范围: DYDATA-1/21/30/31/33/38 的商品、费率、双费用结算、原始订单主键迁移与四页查询地基；本文是结构索引，不是 DDL
> 增量修订: 2026-07-17 补齐账单汇总行与账单来源项；2026-07-20 确认参与分账 SKU 双费率批量导入、全量原子写入、日级生效及原始订单/券内部主键迁移口径；2026-07-20 14:54 补齐 3 张结算查询既有只读依赖表的逐表字段定义

---

## §0 统一结构约束

- 新表遵循小写下划线、单数表名、`id / gmt_create / gmt_modified` 三字段规范；现有复数表名为兼容迁移保留，不在本轮强制重命名。
- 金额统一使用有符号整数“分”，字段后缀为 `_cent`；退款调整允许负数，禁止浮点金额。
- 费率统一使用 `decimal(8,6)`，取值范围 `0` 到 `1`；计算结果按单券四舍五入到分后再汇总。
- 表间只保存逻辑关联 ID，不创建数据库外键或级联；应用服务负责存在性校验和一致性。
- 外部枚举同时保存 `_raw` 原始值和 `_normalized` 标准化值；未知渠道默认不计费并记录数据质量问题。
- 同一 SKU、同一规则生效日只能有一个费率版本，由唯一索引约束；同月不同日期允许创建新版本，订单按业务日匹配不晚于该日的最新有效版本。
- 订单费用结果按“券 + 费用方向 + 结果版本”不可变保存；当前版本由独立指针表维护。
- 已锁账结果不得重算或覆盖；退款、取消核销等后续事件通过独立调整记录计入事件发生月份。

## §1 全表总览

| # | 表名 | 所属业务域 | 来源 | 作用 | 定义于 | 变更 |
|---|------|----------|------|------|--------|------|
| 1 | `dim_sku_product_rules` | 商品治理 | 现有·需改动 | SKU 人工分类与平台当前快照的统一事实源 | [商品与原始数据 §1](foundation-schema-dy-data/product-rule-source.md#1-dim_sku_product_rules--sku-统一事实源现有需改动) | |
| 2 | `sku_product_sync_history` | 商品同步 | 新建 | 保存每次平台同步的商品/SKU 属性快照 | [商品与原始数据 §2](foundation-schema-dy-data/product-rule-source.md#2-sku_product_sync_history--商品同步历史) | |
| 3 | `settlement_scope_rule` | 结算范围 | 新建 | 配置有效商品归属账号与允许渠道 | [商品与原始数据 §3](foundation-schema-dy-data/product-rule-source.md#3-settlement_scope_rule--结算范围规则) | |
| 4 | `sku_fee_rule` | 费率规则 | 新建 | 保存 SKU 双费率不可变版本 | [商品与原始数据 §4](foundation-schema-dy-data/product-rule-source.md#4-sku_fee_rule--sku-双费率版本) | |
| 5 | `sku_fee_rule_import_batch` | 费率导入 | 新建 | 保存批量预校验、确认写入与审计批次 | [商品与原始数据 §5](foundation-schema-dy-data/product-rule-source.md#5-sku_fee_rule_import_batch--费率导入批次) | **变更** |
| 6 | `sku_fee_rule_import_row` | 费率导入 | 新建 | 保存导入逐行校验和写入结果 | [商品与原始数据 §6](foundation-schema-dy-data/product-rule-source.md#6-sku_fee_rule_import_row--导入逐行结果) | **变更** |
| 7 | `raw_douyin_orders` | 原始订单 | 现有·需改动 | 保留销售时间、金额、渠道和归属账号原始事实 | [商品与原始数据 §7](foundation-schema-dy-data/product-rule-source.md#7-raw_douyin_orders--原始订单现有需改动) | **变更** |
| 8 | `raw_douyin_order_coupons` | 原始券 | 现有·需改动 | 保存单券实付、累计退款和状态 | [商品与原始数据 §8](foundation-schema-dy-data/product-rule-source.md#8-raw_douyin_order_coupons--原始券现有需改动) | **变更** |
| 9 | `douyin_refund_event` | 退款事件 | 新建 | 保存全额/部分退款事件及其发生时间 | [商品与原始数据 §9](foundation-schema-dy-data/product-rule-source.md#9-douyin_refund_event--退款事件) | |
| 10 | `settlement_fee_result` | 双费用计算 | 新建 | 保存单券、单费用方向的不可变计算快照 | [结算与报表 §1](foundation-schema-dy-data/settlement-reporting.md#1-settlement_fee_result--单券费用结果) | **变更** |
| 11 | `settlement_fee_result_current` | 双费用计算 | 新建 | 指向每张券、每个费用方向的当前结果 | [结算与报表 §2](foundation-schema-dy-data/settlement-reporting.md#2-settlement_fee_result_current--当前结果指针) | |
| 12 | `settlement_fee_adjustment` | 费用调整 | 新建 | 保存退款、取消核销产生的负向调整 | [结算与报表 §3](foundation-schema-dy-data/settlement-reporting.md#3-settlement_fee_adjustment--费用调整记录) | |
| 13 | `settlement_statement` | 锁账与开票 | 新建 | 保存门店月度账单状态、锁账时间和双费用汇总 | [结算与报表 §4](foundation-schema-dy-data/settlement-reporting.md#4-settlement_statement--门店月度账单与锁账) | **变更** |
| 14 | `settlement_statement_line` | 锁账与开票 | 新建 | 保存账单内按费用方向和产品维度冻结的汇总行 | [结算与报表 §5](foundation-schema-dy-data/settlement-reporting.md#5-settlement_statement_line--账单汇总行) | **新增** |
| 15 | `settlement_statement_entry` | 锁账与开票 | 新建 | 冻结账单实际纳入的费用结果或调整记录 | [结算与报表 §6](foundation-schema-dy-data/settlement-reporting.md#6-settlement_statement_entry--账单来源项) | **新增** |
| 16 | `agg_store_monthly_settlement` | 单店分账 | 现有·需改动 | 提供单店月度双费用汇总投影 | [结算与报表 §7](foundation-schema-dy-data/settlement-reporting.md#7-agg_store_monthly_settlement--单店月度双费用投影现有需改动) | |
| 17 | `agg_store_ranking` | 全国榜单 | 现有·需改动 | 提供月度和正式累计的门店排名投影 | [结算与报表 §8](foundation-schema-dy-data/settlement-reporting.md#8-agg_store_ranking--门店排名投影现有需改动) | |

### §1.1 本轮外既有依赖表

以下表不计入 17 张目标设计表，因为本轮不改变其结构；它们仍是 API 字段和结算计算的明确数据来源，不能用“查询派生”掩盖：

| 既有表 | 本轮读取字段 | 用途 | 定义于 |
|--------|-------------|------|--------|
| `dim_stores` | `store_id`、`store_name` | 门店筛选、榜单和分账展示名称 | [既有只读依赖 §1](foundation-schema-dy-data/existing-read-dependencies.md#1-dim_stores--门店维表既有只读引用) |
| `dim_store_poi_mappings` | `poi_id`、`store_id` | 把核销 POI 映射为核销门店 | [既有只读依赖 §2](foundation-schema-dy-data/existing-read-dependencies.md#2-dim_store_poi_mappings--poi-与门店映射既有只读引用) |
| `raw_douyin_verify_records` | `verify_id`、`coupon_id`、`verify_status`、`verify_time`、`poi_id` | 管理服务费的核销业务日、门店和明细时间来源 | [既有只读依赖 §3](foundation-schema-dy-data/existing-read-dependencies.md#3-raw_douyin_verify_records--抖音核销原始记录既有只读引用) |
| `job_runs` | 任务 ID、名称、状态、时间、计数、错误和 `metadata_json` | 商品同步运行状态、阶段计数与幂等摘要 | 主索引概述；本轮无 PRD 字段引用 |
| `data_quality_issues` | 问题 ID、类型、订单/券、严重度、来源运行和时间 | 同步与结算阻断原因及问题数量 | 主索引概述；本轮无 PRD 字段引用 |

这些依赖表继续沿用当前运行 Schema；若后续需要改变字段或约束，必须另行进入 Schema 变更流程。

## §2 拆分子文件

| 子文件 | 行数上限 | 内容 |
|--------|:---:|------|
| [product-rule-source.md](foundation-schema-dy-data/product-rule-source.md) | < 400 | 商品当前/历史、范围规则、双费率、导入批次、订单券与退款事件 |
| [settlement-reporting.md](foundation-schema-dy-data/settlement-reporting.md) | < 400 | 费用结果、当前指针、调整、账单头、账单汇总行、账单来源项与报表投影 |
| [existing-read-dependencies.md](foundation-schema-dy-data/existing-read-dependencies.md) | < 400 | 门店、POI 映射与核销原始记录的既有只读字段定义 |

## §3 页面 → 表字段追溯

| 页面/模块 | 关键展示或编辑字段 | Schema 来源 |
|----------|------------------|-------------|
| SKU 规则后台 | SKU ID/名称、产品范围、商品类型、双费率、生效日、状态、版本 | `dim_sku_product_rules` + `sku_fee_rule` |
| SKU 批量导入 | SKU 名称、SKU ID、双费率、文件状态、逐行错误位置与原因、结果文件 | `sku_fee_rule_import_batch` + `sku_fee_rule_import_row` |
| 商品同步后台 | 商品/SPU、创建者、归属账号、状态、最近同步时间 | `dim_sku_product_rules` + `sku_product_sync_history` |
| 全国门店榜单 | 月度/累计、门店、产品维度、销售/核销/双费用净额 | `agg_store_ranking` |
| 单店分账 | 门店/月/产品维度、推广费、管理费、调整后净额、账单状态 | `agg_store_monthly_settlement` + `settlement_statement` + `settlement_statement_line` |
| 锁定账单明细 | 费用方向、产品维度、逐笔订单/券、原始或调整金额、规则版本 | `settlement_statement_line` + `settlement_statement_entry` + `settlement_fee_result` + `settlement_fee_adjustment` |
| 订单费用明细 | 订单/券、方向、规则匹配日、原始月、调整月、基数、费率、金额、规则版本 | `settlement_fee_result_current` + `settlement_fee_result` + `settlement_fee_adjustment` |
| 开票确认 | 账单月份、状态、推广费开票范围、锁账状态 | `settlement_statement` |

## §4 逻辑关联与事务边界

- `dim_sku_product_rules.sku_id` ←→ `sku_fee_rule.sku_id`：应用层校验 SKU 必须存在，商品同步不修改费率表。
- `raw_douyin_order_coupons.raw_order_id` → `raw_douyin_orders.id`：内部数值 ID 用于应用层关联；`order_id` 同时保留为平台业务 ID 快照和兼容查询键，不创建新的数据库级联。
- `sku_fee_rule.rule_version` ←→ `settlement_fee_result.rule_version`：费用结果固化实际使用版本。
- `settlement_fee_result_current.fee_result_id` ←→ `settlement_fee_result.fee_result_id`：未锁账重算在一个事务内新增版本并切换指针。
- `douyin_refund_event.refund_event_id` → `settlement_fee_adjustment.refund_event_id`：退款事件幂等生成方向性调整。
- `settlement_statement.statement_id` → `settlement_statement_line.statement_id` → `settlement_statement_entry.statement_line_id`：账单头、产品/方向汇总和逐笔来源形成固定三层结构。
- `settlement_statement_entry.source_record_id` 按 `source_type` 精确引用 `settlement_fee_result.fee_result_id` 或 `settlement_fee_adjustment.adjustment_id`；同一来源记录最多进入一个账单。
- `settlement_statement` 锁账事务必须冻结对应月份的当前费用结果和当月调整：先写逐笔来源项，再汇总账单行和账单头，最后原子切换为已锁账；三层金额不一致时禁止锁账。
- 锁账后账单头、汇总行和来源项均不可修改或删除，也不允许切换已纳入账单的结果指针；后续退款只能创建调整并进入事件发生月份的另一张账单。
- 任何缺失单券金额、未知渠道、未知归属账号、未知 SKU 或冲突费率都不得猜测计算，应进入既有 `data_quality_issue` 体系并阻断对应费用方向。

## §5 迁移与兼容边界

- 现有 `dim_sku_product_rules.commission_rate` 不自动复制到 `sku_fee_rule`，首批正式规则由管理员确认后从 `2026-08-01` 发布。
- 现有 `settlement_order_details` 可在迁移期保留为旧版只读投影；新双费用结果以 `settlement_fee_result` 为事实源，完成验证后再停用旧写入。
- 现有聚合表在迁移时增加新字段或重建投影；旧接口字段在前端切换完成前保留兼容映射，但不得继续把同一金额解释为两个费用方向。
- 原始订单/券内部主键迁移由 [DYDATA-38](https://linear.app/keith-lim/issue/DYDATA-38/分阶段将原始订单与券表迁移到自增主键并保留平台业务-id) 跟踪，采用两个发布阶段：
  1. **兼容扩展与回填**：增加并回填两表 `id`，增加并回填券表 `raw_order_id`，保留字符串主键、旧外键和旧应用读写；核对迁移前后行数、内部 ID 空值/重复及订单—券孤儿数。
  2. **应用与约束切换**：采集 upsert 改为按平台业务 ID 查询后更新或新增，内部关联改用数值 ID；验证无孤儿和结算差异后再把 `id` 切为主键、平台业务 ID 切为非空唯一键，并移除字符串主键/级联角色。
- 两阶段之间不得删除或改写 `order_id`、`coupon_id`；若第二阶段应用切换失败，应以前滚修复或切回保留的平台业务 ID 查询路径恢复，不直接回滚已产生的新主键值。
- 迁移验证至少包含订单/券行数、内部 ID 空值和重复数、订单—券孤儿数、重复采集幂等、结算明细数量及关键样例金额；生产 `alembic upgrade head` 不在 foundation 阶段执行。
- 目标商品归属账号 ID、真实渠道枚举和开票材料仍是上线前外部依赖；Schema 已预留稳定 ID、原始/标准化值和待通知边界，不需要硬编码占位值。

## §6 Phase 3 确认状态

1. **已确认**：批量导入模板行固定为 SKU 名称、SKU ID、推广服务费率和管理服务费率；首批生效日为 `2026-08-01`，后续由批次选择到自然日；`commit_mode=1`，全表预校验通过后原子写入，任一非法行阻止整批发布，并按行号、字段和原因提示错误。
2. **已确认**：原始订单/券表分阶段迁移到自增 `id` 主键，`order_id`、`coupon_id` 永久保留为非空唯一的平台业务 ID；先兼容扩展和回填，再切换应用关联与主键约束，真实实现由 DYDATA-38 跟踪。
3. **已确认**：锁账头按“门店 + 月份”唯一；账单汇总行按“费用方向 + 产品范围 + 商品类型”拆分，账单来源项逐笔冻结费用结果或调整记录，产品维度不单独产生多个锁账头。
4. **增量确认**：`dim_stores`、`dim_store_poi_mappings`、`raw_douyin_verify_records` 只补充当前代码已存在且被结算查询消费的字段定义，不新增数据库字段、索引或迁移。

Phase 3 全部确认完成。Phase 4 已生成并获用户确认的 [API 契约](foundation-api-dy-data.md)，并把 17 张表的“使用接口”回填到两个 Schema 子文件。真实数据库迁移按 DYDATA-38 的开发与部署门禁另行执行。

## §7 Phase 4 回填状态

- [商品与原始数据](foundation-schema-dy-data/product-rule-source.md) 中 9 张表已回填公开查询、管理员写入或“仅内部 worker 写入”的接口边界。
- [结算与报表](foundation-schema-dy-data/settlement-reporting.md) 中 8 张表已回填榜单、单店分账、订单费用明细、导出及“无公开写接口”的锁账边界。
- 公开 API 只使用平台/业务 ID，不暴露 DYDATA-38 迁移新增的内部自增 `id`。
- 开票确认页不新增发票 API；账单确认和锁账本轮保持内部流程，待未来独立需求补齐角色、审计与撤回口径后再扩展。
- 2026-07-20 用户确认 Phase 4 的 22 个目标接口、批量文件限制、不可变费率版本、只读锁账/开票边界、新订单费用路径和外部商品 API 待样例边界；Phase 5 只做一致性修正，不改变上述业务决策。
- 2026-07-20 PRD Phase 5 回溯补齐 3 张既有只读依赖表的字段定义；API 契约未变化，无需新增或修改接口。
