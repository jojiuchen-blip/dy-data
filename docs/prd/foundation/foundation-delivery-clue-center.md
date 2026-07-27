# Foundation 交付清单 - 线索中心

> 生成时间: 2026-07-22 14:09
> Skill: foundation-builder
> 模式: 首次
> 适用需求: DYDATA-41

## 上游依赖

| 上游 Skill | 产物文件 |
|-----------|---------|
| brd-writer | docs/brd/BRD-clue-center-20260721-2134.md |
| page-designer | src/frontend/page-preview/page-delivery-dy-data.md |
| page-explainer | src/frontend/page-preview/explainer-flow-dy-data.md<br>src/frontend/page-preview/explainer-b-interaction-dy-data.md<br>src/frontend/page-preview/explainer-delivery-dy-data.md |

## 交付产物

| 产物 | 文件路径 | 行数 | 拆分子文件 |
|------|--------|------|----------|
| 术语表 | docs/prd/foundation/foundation-glossary-clue-center.md | 212 | — |
| 数据库 Schema | docs/prd/foundation/foundation-schema-clue-center.md | 237 | docs/prd/foundation/foundation-schema-clue-center/raw_douyin_refund_record.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_master_lead.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_source_record_link.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_contact.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_order_status_event.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_center_order.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_order_metric_fact.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_assignment_round.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_follow_up_record.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_store_group.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_store_group_member.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_rule.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_rule_version.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_strategy_config.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_lead_rule_version_binding.md<br>docs/prd/foundation/foundation-schema-clue-center/store_score_snapshot_run.md<br>docs/prd/foundation/foundation-schema-clue-center/store_score_snapshot.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_cycle.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_cycle_item.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_decision.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_allocation_candidate.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_headquarters_pool_entry.md<br>docs/prd/foundation/foundation-schema-clue-center/clue_operation_audit_log.md |
| API 接口设计 | docs/prd/foundation/foundation-api-clue-center.md | 142 | docs/prd/foundation/foundation-api-clue-center/common-contract.md<br>docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md<br>docs/prd/foundation/foundation-api-clue-center/follow-up-and-rounds.md<br>docs/prd/foundation/foundation-api-clue-center/rules-and-store-groups.md<br>docs/prd/foundation/foundation-api-clue-center/allocation-runtime-and-headquarters.md<br>docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md |

## 产物摘要

| 指标 | 数值 |
|------|------|
| 术语总数 | 119 |
| 数据表总数 | 23 |
| API 接口数 | 55 个 HTTP 契约；另含 5 个外部依赖项 |

## 一致性自查结果

- 检查时间: 2026-07-22 14:09
- 页面可写字段覆盖率: 21/21 (100%)
- API ↔ Schema 覆盖率: 318/318 (100%)
- 显式 `table.field` 引用: 41/41 (100%)
- 锁定交互覆盖率: 20/20 (100%)
- Schema 使用接口覆盖率: 23/23 (100%)
- 术语一致性: 全部通过
- 孤立项: 无

## 交付边界

- 本交付清单描述目标技术地基，不表示当前业务代码、数据库表、DDL、API 路由或前端页面已经按目标契约完成实现。
- 旧 `execution_mode=legacy`、旧物化轮次和旧重建入口不属于兼容对象，后续由 DYDATA-34 一次性删除。
- 试运行、正式分配、重建、联系方式访问和跟进删除必须沿用本交付中的权限、幂等、并发和审计边界。
- 未列入本清单的自动索引图、案例汇报材料和其他业务域文件不属于 DYDATA-41 Foundation 交付范围。

## 下游可消费信息

| 下游 Skill | 应读取 | 用途 |
|-----------|--------|------|
| prd-writer | 本清单 + glossary + schema + api | 由 DYDATA-42 补齐线索中心 PRD 的页面细则、业务规则、状态迁移和验收条件，并统一使用术语表命名 |

## S2 路由门禁

- 检查时间: 2026-07-22 14:09
- 检查命令: `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S2 --json`
- `gateChecks.foundationReadyForPrd.pass`: `true`
- `foundationDeliveryExists`: `true`
- `artifactsReady`: `true`
- `validation`: 0 errors, 0 warnings, 0 infos
- 下一路由: `prd-chief`，由 `prd-writer` 消费本清单及全部 Foundation 产物
