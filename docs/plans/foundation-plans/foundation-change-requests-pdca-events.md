# PDCA独立只读接口：foundation增量请求

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-PDCA-001 |
| 来源 Task | LOCAL-PDCA-EVENTS-20260928 / T0.1 |
| 分类 | GAP |
| 改动项 | 将独立证据快照、可空事件时间及未知完整性语义纳入API权威索引 |
| 原因 | 新API读取既有事件、批次及质量表，不改变业务模型；当前Foundation不含该只读消费者契约 |
| 指向代码块 | apps/api/dy_api/pdca_snapshot_schema.py；apps/api/dy_api/routes/pdca_sources.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-api-dy-data.md 的独立只读查询索引 |
| 严重度 | 建议（发布前文档核对，不授权扩大业务范围） |
| 状态 | 待评审 |

本任务只更新 docs/api-contract.md 与独立契约，不直接改动Foundation。完整水位和历史事件能力缺口见 [契约](../../api/pdca-event-snapshot.md)，其后续采集/持久化变更须独立授权。
