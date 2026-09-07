# DYDATA-88 Foundation 增量待改请求

本记录只描述 F01–F11 修复暴露的实现衔接，不替代既有 Foundation，也不提前实施独立联系人表或新电话审计接口。

## S4-FCR-DYDATA88-001：联系方式缓存的来源验证合同

| 字段 | 内容 |
| --- | --- |
| ID | `S4-FCR-DYDATA88-001` |
| 来源 Task | 线索平台 S4 问题回归，`DYDATA-88 F03/F04/F08` |
| 分类 | `GAP` |
| 改动项 | 将来源指纹、源变化失效、旧无指纹缓存重新验证、成功/失败缓存时效写入联系人迁移与解析合同。 |
| 原因 | 当前宿主仍在 `clue_center_orders` 保存旧电话字段，本轮为该实现追加 nullable 来源指纹防止返回过期号码。Foundation 的独立 `clue_contact` 仍是后续目标，迁移时需要一并迁移来源验证，不能把历史明文直接认作可信。 |
| 指向代码块 | `apps/api/dy_api/models.py:4244`；`apps/api/dy_api/routes/_data.py:4650`；`alembic/versions/20260907_0051_clue_phone_source_fingerprint.py:34` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-schema-clue-center/clue_contact.md` 迁移与访问规则；`docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` 联系方式解析 |
| 严重度 | 建议（后续联系人迁移需要承接；不阻断本轮既有接口漏洞修复） |
| 状态 | 待评审 |

## S4-FCR-DYDATA88-002：现有概览的唯一订单去重规则

| 字段 | 内容 |
| --- | --- |
| ID | `S4-FCR-DYDATA88-002` |
| 来源 Task | 线索平台 S4 问题回归，`DYDATA-88 F10` |
| 分类 | `GAP` |
| 改动项 | 明确现有 `overview` 在筛选范围内按唯一订单聚合，分子取范围内轮次布尔汇总；当前有效计数仅认当前轮次；轮次明细不去重。 |
| 原因 | 术语已规定订单级经营统计，原 SQL 却按轮次 COUNT。本轮修复去重并保留现有门店/时间过滤；后续事实表与接口替换必须保持同一分子、分母和筛选规则。 |
| 指向代码块 | `apps/api/dy_api/routes/_data.py:4188`；`tests/test_api_clues.py:524` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 概览指标；`docs/prd/foundation/foundation-schema-clue-center/clue_order_metric_fact.md` 指标生成 |
| 严重度 | 建议 |
| 状态 | 待评审 |
