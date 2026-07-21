# 项目文件引用索引

> 本文件由 project-link-indexer 编译生成。它是给人和 LLM 读取的索引，不替代原始需求、PRD、计划或代码文件。

## 1. 摘要

- 文件节点：405
- 文件关系：307
- 诊断问题：3
- 机器索引：`docs/index/project-link-graph.json`
- 关系 schema：`docs/index/project-wiki-schema.json`

## 2. Wiki 入口

| 文件 | 类型 | owner skill | wiki 链接 | markdown 链接 |
|---|---|---|---|---|
| ci-cd.yml | config | host-project | [[.github/workflows/ci-cd.yml|ci-cd.yml]] | [ci-cd.yml](../../.github/workflows/ci-cd.yml) |
| tencent-lighthouse-deploy.yml | config | host-project | [[.github/workflows/tencent-lighthouse-deploy.yml|tencent-lighthouse-deploy.yml]] | [tencent-lighthouse-deploy.yml](../../.github/workflows/tencent-lighthouse-deploy.yml) |
| AGENTS.md | doc | host-project | [[AGENTS.md|AGENTS.md]] | [AGENTS.md](../../AGENTS.md) |
| env.py | source_code | coding-standards | [[alembic/env.py|env.py]] | [env.py](../../alembic/env.py) |
| 20260612_0001_backend_production_mvp.py | source_code | coding-standards | [[alembic/versions/20260612_0001_backend_production_mvp.py|20260612_0001_backend_production_mvp.py]] | [20260612_0001_backend_production_mvp.py](../../alembic/versions/20260612_0001_backend_production_mvp.py) |
| 20260616_0002_sync_settings.py | source_code | coding-standards | [[alembic/versions/20260616_0002_sync_settings.py|20260616_0002_sync_settings.py]] | [20260616_0002_sync_settings.py](../../alembic/versions/20260616_0002_sync_settings.py) |
| 20260616_0003_clue_center_mvp.py | source_code | coding-standards | [[alembic/versions/20260616_0003_clue_center_mvp.py|20260616_0003_clue_center_mvp.py]] | [20260616_0003_clue_center_mvp.py](../../alembic/versions/20260616_0003_clue_center_mvp.py) |
| 20260617_0004_non_commission_rules.py | source_code | coding-standards | [[alembic/versions/20260617_0004_non_commission_rules.py|20260617_0004_non_commission_rules.py]] | [20260617_0004_non_commission_rules.py](../../alembic/versions/20260617_0004_non_commission_rules.py) |
| 20260618_0005_account_module.py | source_code | coding-standards | [[alembic/versions/20260618_0005_account_module.py|20260618_0005_account_module.py]] | [20260618_0005_account_module.py](../../alembic/versions/20260618_0005_account_module.py) |
| 20260622_0006_clue_phone_plain.py | source_code | coding-standards | [[alembic/versions/20260622_0006_clue_phone_plain.py|20260622_0006_clue_phone_plain.py]] | [20260622_0006_clue_phone_plain.py](../../alembic/versions/20260622_0006_clue_phone_plain.py) |
| 20260624_0007_clue_follow_up_records.py | source_code | coding-standards | [[alembic/versions/20260624_0007_clue_follow_up_records.py|20260624_0007_clue_follow_up_records.py]] | [20260624_0007_clue_follow_up_records.py](../../alembic/versions/20260624_0007_clue_follow_up_records.py) |
| 20260624_0008_user_feedback_submissions.py | source_code | coding-standards | [[alembic/versions/20260624_0008_user_feedback_submissions.py|20260624_0008_user_feedback_submissions.py]] | [20260624_0008_user_feedback_submissions.py](../../alembic/versions/20260624_0008_user_feedback_submissions.py) |
| 20260626_0009_product_type_visibility.py | source_code | coding-standards | [[alembic/versions/20260626_0009_product_type_visibility.py|20260626_0009_product_type_visibility.py]] | [20260626_0009_product_type_visibility.py](../../alembic/versions/20260626_0009_product_type_visibility.py) |
| 20260626_0010_product_type_default.py | source_code | coding-standards | [[alembic/versions/20260626_0010_product_type_default.py|20260626_0010_product_type_default.py]] | [20260626_0010_product_type_default.py](../../alembic/versions/20260626_0010_product_type_default.py) |
| 20260706_0011_product_scope_visibility.py | source_code | coding-standards | [[alembic/versions/20260706_0011_product_scope_visibility.py|20260706_0011_product_scope_visibility.py]] | [20260706_0011_product_scope_visibility.py](../../alembic/versions/20260706_0011_product_scope_visibility.py) |
| 20260707_0012_sku_product_scope.py | source_code | coding-standards | [[alembic/versions/20260707_0012_sku_product_scope.py|20260707_0012_sku_product_scope.py]] | [20260707_0012_sku_product_scope.py](../../alembic/versions/20260707_0012_sku_product_scope.py) |
| 20260712_0012_clue_allocation_m1_foundation.py | source_code | coding-standards | [[alembic/versions/20260712_0012_clue_allocation_m1_foundation.py|20260712_0012_clue_allocation_m1_foundation.py]] | [20260712_0012_clue_allocation_m1_foundation.py](../../alembic/versions/20260712_0012_clue_allocation_m1_foundation.py) |
| 20260712_0013_clue_allocation_rule_versions.py | source_code | coding-standards | [[alembic/versions/20260712_0013_clue_allocation_rule_versions.py|20260712_0013_clue_allocation_rule_versions.py]] | [20260712_0013_clue_allocation_rule_versions.py](../../alembic/versions/20260712_0013_clue_allocation_rule_versions.py) |
| 20260712_0014_clue_allocation_engine.py | source_code | coding-standards | [[alembic/versions/20260712_0014_clue_allocation_engine.py|20260712_0014_clue_allocation_engine.py]] | [20260712_0014_clue_allocation_engine.py](../../alembic/versions/20260712_0014_clue_allocation_engine.py) |
| 20260712_0015_clue_follow_up_state_machine.py | source_code | coding-standards | [[alembic/versions/20260712_0015_clue_follow_up_state_machine.py|20260712_0015_clue_follow_up_state_machine.py]] | [20260712_0015_clue_follow_up_state_machine.py](../../alembic/versions/20260712_0015_clue_follow_up_state_machine.py) |
| 20260712_0016_clue_allocation_cycles.py | source_code | coding-standards | [[alembic/versions/20260712_0016_clue_allocation_cycles.py|20260712_0016_clue_allocation_cycles.py]] | [20260712_0016_clue_allocation_cycles.py](../../alembic/versions/20260712_0016_clue_allocation_cycles.py) |
| 20260713_0017_drop_clue_reassign_rule_settings.py | source_code | coding-standards | [[alembic/versions/20260713_0017_drop_clue_reassign_rule_settings.py|20260713_0017_drop_clue_reassign_rule_settings.py]] | [20260713_0017_drop_clue_reassign_rule_settings.py](../../alembic/versions/20260713_0017_drop_clue_reassign_rule_settings.py) |
| 20260715_0018_merge_sku_and_clue_heads.py | source_code | coding-standards | [[alembic/versions/20260715_0018_merge_sku_and_clue_heads.py|20260715_0018_merge_sku_and_clue_heads.py]] | [20260715_0018_merge_sku_and_clue_heads.py](../../alembic/versions/20260715_0018_merge_sku_and_clue_heads.py) |
| 20260720_0019_raw_order_internal_ids.py | source_code | coding-standards | [[alembic/versions/20260720_0019_raw_order_internal_ids.py|20260720_0019_raw_order_internal_ids.py]] | [20260720_0019_raw_order_internal_ids.py](../../alembic/versions/20260720_0019_raw_order_internal_ids.py) |
| 20260720_0020_product_rule_schema.py | source_code | coding-standards | [[alembic/versions/20260720_0020_product_rule_schema.py|20260720_0020_product_rule_schema.py]] | [20260720_0020_product_rule_schema.py](../../alembic/versions/20260720_0020_product_rule_schema.py) |
| 20260720_0021_settlement_reporting_schema.py | source_code | coding-standards | [[alembic/versions/20260720_0021_settlement_reporting_schema.py|20260720_0021_settlement_reporting_schema.py]] | [20260720_0021_settlement_reporting_schema.py](../../alembic/versions/20260720_0021_settlement_reporting_schema.py) |
| 20260720_0022_raw_order_settlement_fields.py | source_code | coding-standards | [[alembic/versions/20260720_0022_raw_order_settlement_fields.py|20260720_0022_raw_order_settlement_fields.py]] | [20260720_0022_raw_order_settlement_fields.py](../../alembic/versions/20260720_0022_raw_order_settlement_fields.py) |
| 20260720_0023_refund_success_observed_at.py | source_code | coding-standards | [[alembic/versions/20260720_0023_refund_success_observed_at.py|20260720_0023_refund_success_observed_at.py]] | [20260720_0023_refund_success_observed_at.py](../../alembic/versions/20260720_0023_refund_success_observed_at.py) |
| 20260720_0024_raw_order_internal_pk_cutover.py | source_code | coding-standards | [[alembic/versions/20260720_0024_raw_order_internal_pk_cutover.py|20260720_0024_raw_order_internal_pk_cutover.py]] | [20260720_0024_raw_order_internal_pk_cutover.py](../../alembic/versions/20260720_0024_raw_order_internal_pk_cutover.py) |
| 20260721_0025_product_sync_active_slot.py | source_code | coding-standards | [[alembic/versions/20260721_0025_product_sync_active_slot.py|20260721_0025_product_sync_active_slot.py]] | [20260721_0025_product_sync_active_slot.py](../../alembic/versions/20260721_0025_product_sync_active_slot.py) |
| 20260721_0026_product_sync_idempotency_key.py | source_code | coding-standards | [[alembic/versions/20260721_0026_product_sync_idempotency_key.py|20260721_0026_product_sync_idempotency_key.py]] | [20260721_0026_product_sync_idempotency_key.py](../../alembic/versions/20260721_0026_product_sync_idempotency_key.py) |
| __init__.py | source_code | coding-standards | [[apps/api/dy_api/__init__.py|__init__.py]] | [__init__.py](../../apps/api/dy_api/__init__.py) |
| auth.py | source_code | coding-standards | [[apps/api/dy_api/auth.py|auth.py]] | [auth.py](../../apps/api/dy_api/auth.py) |
| db.py | source_code | coding-standards | [[apps/api/dy_api/db.py|db.py]] | [db.py](../../apps/api/dy_api/db.py) |
| main.py | source_code | coding-standards | [[apps/api/dy_api/main.py|main.py]] | [main.py](../../apps/api/dy_api/main.py) |
| models.py | source_code | coding-standards | [[apps/api/dy_api/models.py|models.py]] | [models.py](../../apps/api/dy_api/models.py) |
| _data.py | source_code | coding-standards | [[apps/api/dy_api/routes/_data.py|_data.py]] | [_data.py](../../apps/api/dy_api/routes/_data.py) |
| admin.py | source_code | coding-standards | [[apps/api/dy_api/routes/admin.py|admin.py]] | [admin.py](../../apps/api/dy_api/routes/admin.py) |
| auth.py | source_code | coding-standards | [[apps/api/dy_api/routes/auth.py|auth.py]] | [auth.py](../../apps/api/dy_api/routes/auth.py) |
| clues.py | source_code | coding-standards | [[apps/api/dy_api/routes/clues.py|clues.py]] | [clues.py](../../apps/api/dy_api/routes/clues.py) |
| dashboard.py | source_code | coding-standards | [[apps/api/dy_api/routes/dashboard.py|dashboard.py]] | [dashboard.py](../../apps/api/dy_api/routes/dashboard.py) |
| fee_admin.py | source_code | coding-standards | [[apps/api/dy_api/routes/fee_admin.py|fee_admin.py]] | [fee_admin.py](../../apps/api/dy_api/routes/fee_admin.py) |
| feedback.py | source_code | coding-standards | [[apps/api/dy_api/routes/feedback.py|feedback.py]] | [feedback.py](../../apps/api/dy_api/routes/feedback.py) |
| jobs.py | source_code | coding-standards | [[apps/api/dy_api/routes/jobs.py|jobs.py]] | [jobs.py](../../apps/api/dy_api/routes/jobs.py) |
| meta.py | source_code | coding-standards | [[apps/api/dy_api/routes/meta.py|meta.py]] | [meta.py](../../apps/api/dy_api/routes/meta.py) |
| rule_utils.py | source_code | coding-standards | [[apps/api/dy_api/rule_utils.py|rule_utils.py]] | [rule_utils.py](../../apps/api/dy_api/rule_utils.py) |
| schemas.py | source_code | coding-standards | [[apps/api/dy_api/schemas.py|schemas.py]] | [schemas.py](../../apps/api/dy_api/schemas.py) |
| index.html | doc | host-project | [[apps/web/index.html|index.html]] | [index.html](../../apps/web/index.html) |
| package-lock.json | config | host-project | [[apps/web/package-lock.json|package-lock.json]] | [package-lock.json](../../apps/web/package-lock.json) |
| package.json | config | host-project | [[apps/web/package.json|package.json]] | [package.json](../../apps/web/package.json) |
| app.js | source_code | coding-standards | [[apps/web/public/account-activation-guide/assets/app.js|app.js]] | [app.js](../../apps/web/public/account-activation-guide/assets/app.js) |
| print.css | doc | host-project | [[apps/web/public/account-activation-guide/assets/print.css|print.css]] | [print.css](../../apps/web/public/account-activation-guide/assets/print.css) |
| styles.css | doc | host-project | [[apps/web/public/account-activation-guide/assets/styles.css|styles.css]] | [styles.css](../../apps/web/public/account-activation-guide/assets/styles.css) |
| index.html | doc | host-project | [[apps/web/public/account-activation-guide/index.html|index.html]] | [index.html](../../apps/web/public/account-activation-guide/index.html) |
| dy-data Web | readme | host-project | [[apps/web/README.md|dy-data Web]] | [dy-data Web](../../apps/web/README.md) |
| client.ts | source_code | coding-standards | [[apps/web/src/api/client.ts|client.ts]] | [client.ts](../../apps/web/src/api/client.ts) |
| App.tsx | source_code | coding-standards | [[apps/web/src/App.tsx|App.tsx]] | [App.tsx](../../apps/web/src/App.tsx) |
| AdminProductSyncPanel.tsx | source_code | coding-standards | [[apps/web/src/components/AdminProductSyncPanel.tsx|AdminProductSyncPanel.tsx]] | [AdminProductSyncPanel.tsx](../../apps/web/src/components/AdminProductSyncPanel.tsx) |
| AdminSkuGovernancePanel.tsx | source_code | coding-standards | [[apps/web/src/components/AdminSkuGovernancePanel.tsx|AdminSkuGovernancePanel.tsx]] | [AdminSkuGovernancePanel.tsx](../../apps/web/src/components/AdminSkuGovernancePanel.tsx) |
| Button.tsx | source_code | coding-standards | [[apps/web/src/components/Button.tsx|Button.tsx]] | [Button.tsx](../../apps/web/src/components/Button.tsx) |
| Chips.tsx | source_code | coding-standards | [[apps/web/src/components/Chips.tsx|Chips.tsx]] | [Chips.tsx](../../apps/web/src/components/Chips.tsx) |
| CommissionRulesButton.tsx | source_code | coding-standards | [[apps/web/src/components/CommissionRulesButton.tsx|CommissionRulesButton.tsx]] | [CommissionRulesButton.tsx](../../apps/web/src/components/CommissionRulesButton.tsx) |
| DataTable.tsx | source_code | coding-standards | [[apps/web/src/components/DataTable.tsx|DataTable.tsx]] | [DataTable.tsx](../../apps/web/src/components/DataTable.tsx) |
| DefinitionList.tsx | source_code | coding-standards | [[apps/web/src/components/DefinitionList.tsx|DefinitionList.tsx]] | [DefinitionList.tsx](../../apps/web/src/components/DefinitionList.tsx) |
| Dialog.tsx | source_code | coding-standards | [[apps/web/src/components/Dialog.tsx|Dialog.tsx]] | [Dialog.tsx](../../apps/web/src/components/Dialog.tsx) |
| Filters.tsx | source_code | coding-standards | [[apps/web/src/components/Filters.tsx|Filters.tsx]] | [Filters.tsx](../../apps/web/src/components/Filters.tsx) |
| FormControls.tsx | source_code | coding-standards | [[apps/web/src/components/FormControls.tsx|FormControls.tsx]] | [FormControls.tsx](../../apps/web/src/components/FormControls.tsx) |
| MetricCard.tsx | source_code | coding-standards | [[apps/web/src/components/MetricCard.tsx|MetricCard.tsx]] | [MetricCard.tsx](../../apps/web/src/components/MetricCard.tsx) |
| ResourceState.tsx | source_code | coding-standards | [[apps/web/src/components/ResourceState.tsx|ResourceState.tsx]] | [ResourceState.tsx](../../apps/web/src/components/ResourceState.tsx) |
| SearchableStoreSelect.css | doc | host-project | [[apps/web/src/components/SearchableStoreSelect.css|SearchableStoreSelect.css]] | [SearchableStoreSelect.css](../../apps/web/src/components/SearchableStoreSelect.css) |
| SearchableStoreSelect.tsx | source_code | coding-standards | [[apps/web/src/components/SearchableStoreSelect.tsx|SearchableStoreSelect.tsx]] | [SearchableStoreSelect.tsx](../../apps/web/src/components/SearchableStoreSelect.tsx) |
| Shell.tsx | source_code | coding-standards | [[apps/web/src/components/Shell.tsx|Shell.tsx]] | [Shell.tsx](../../apps/web/src/components/Shell.tsx) |
| SolarIcon.tsx | source_code | coding-standards | [[apps/web/src/components/SolarIcon.tsx|SolarIcon.tsx]] | [SolarIcon.tsx](../../apps/web/src/components/SolarIcon.tsx) |
| TablePagination.tsx | source_code | coding-standards | [[apps/web/src/components/TablePagination.tsx|TablePagination.tsx]] | [TablePagination.tsx](../../apps/web/src/components/TablePagination.tsx) |
| TertiaryNav.tsx | source_code | coding-standards | [[apps/web/src/components/TertiaryNav.tsx|TertiaryNav.tsx]] | [TertiaryNav.tsx](../../apps/web/src/components/TertiaryNav.tsx) |
| TooltipLabel.tsx | source_code | coding-standards | [[apps/web/src/components/TooltipLabel.tsx|TooltipLabel.tsx]] | [TooltipLabel.tsx](../../apps/web/src/components/TooltipLabel.tsx) |
| clue_center.json | config | host-project | [[apps/web/src/data/mock/clue_center.json|clue_center.json]] | [clue_center.json](../../apps/web/src/data/mock/clue_center.json) |
| page1_store_ranking.json | config | host-project | [[apps/web/src/data/mock/page1_store_ranking.json|page1_store_ranking.json]] | [page1_store_ranking.json](../../apps/web/src/data/mock/page1_store_ranking.json) |
| page2_commission_tables.json | config | host-project | [[apps/web/src/data/mock/page2_commission_tables.json|page2_commission_tables.json]] | [page2_commission_tables.json](../../apps/web/src/data/mock/page2_commission_tables.json) |
| page2_store_month_summary.json | config | host-project | [[apps/web/src/data/mock/page2_store_month_summary.json|page2_store_month_summary.json]] | [page2_store_month_summary.json](../../apps/web/src/data/mock/page2_store_month_summary.json) |

## 3. 关系

| 来源 | 关系 | 目标 | 证据 |
|---|---|---|---|
| AGENTS.md | links_to | AGENTS.md | AGENTS.md:80 |
| AGENTS.md | links_to | docs/governance/authority-map.md | AGENTS.md:92 |
| AGENTS.md | links_to | docs/plans/execution-plan.md | AGENTS.md:88 |
| AGENTS.md | links_to | project-profile.md | AGENTS.md:85 |
| AGENTS.md | links_to | project-rules.md | AGENTS.md:83 |
| apps/web/README.md | links_to | docs/design-system/README.md | apps/web/README.md:35 |
| docs/技术架构与部署规划.md | links_to | docs/architecture.md | docs/技术架构与部署规划.md:3 |
| docs/技术架构与部署规划.md | links_to | docs/runbook.md | docs/技术架构与部署规划.md:3 |
| docs/项目产品介绍书.md | links_to | docs/api-contract.md | docs/项目产品介绍书.md:85 |
| docs/项目产品介绍书.md | links_to | docs/architecture.md | docs/项目产品介绍书.md:84 |
| docs/项目产品介绍书.md | links_to | docs/data-model.md | docs/项目产品介绍书.md:86 |
| docs/项目产品介绍书.md | links_to | docs/design-system/README.md | docs/项目产品介绍书.md:88 |
| docs/项目产品介绍书.md | links_to | docs/governance/authority-map.md | docs/项目产品介绍书.md:89 |
| docs/项目产品介绍书.md | links_to | docs/runbook.md | docs/项目产品介绍书.md:87 |
| docs/项目产品介绍书.md | links_to | project-profile.md | docs/项目产品介绍书.md:89 |
| docs/api-contract.md | links_to | docs/prd/foundation/foundation-api-dy-data.md | docs/api-contract.md:3 |
| docs/architecture.md | links_to | docs/项目产品介绍书.md | docs/architecture.md:81 |
| docs/architecture.md | links_to | docs/runbook.md | docs/architecture.md:74 |
| docs/baseline/dydata-6-baseline-dry-run-review.md | links_to | docs/governance/authority-map.md | docs/baseline/dydata-6-baseline-dry-run-review.md:50 |
| docs/baseline/dydata-6-baseline-dry-run-review.md | links_to | project-profile.md | docs/baseline/dydata-6-baseline-dry-run-review.md:16 |
| docs/baseline/dydata-6-baseline-dry-run-review.md | links_to | README.md | docs/baseline/dydata-6-baseline-dry-run-review.md:41 |
| docs/brd/BRD-dy-data-20260716-1255.md | links_to | docs/brd/brd-ledger-dy-data.md | docs/brd/BRD-dy-data-20260716-1255.md:7 |
| docs/brd/BRD-dy-data-20260716-1255.md | links_to | project-profile.md | docs/brd/BRD-dy-data-20260716-1255.md:6 |
| docs/commission-settlement-rework-decisions.md | links_to | docs/single-store-monthly-settlement-mock.html | docs/commission-settlement-rework-decisions.md:51 |
| docs/commission-settlement-rework-decisions.md | links_to | docs/store-ranking-mock.html | docs/commission-settlement-rework-decisions.md:23 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | AGENTS.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:52 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | docs/项目产品介绍书.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:50 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | docs/api-contract.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:51 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | docs/architecture.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:51 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | docs/data-model.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:51 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | docs/governance/authority-map.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:52 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:52 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | project-profile.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:50 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | project-rules.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:52 |
| docs/devlog/20260714_refactor_log_Keith_Chen.md | links_to | README.md | docs/devlog/20260714_refactor_log_Keith_Chen.md:50 |
| docs/devlog/20260716_refactor_log_Keith_Chen.md | links_to | project-rules.md | docs/devlog/20260716_refactor_log_Keith_Chen.md:71 |
| docs/devlog/20260717_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260717_refactor_log_jojiuchen-blip.md:69 |
| docs/devlog/20260720_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260720_refactor_log_jojiuchen-blip.md:88 |
| docs/devlog/20260721_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260721_refactor_log_jojiuchen-blip.md:76 |
| docs/github-cicd.md | links_to | docs/tencent-lighthouse-cicd.md | docs/github-cicd.md:10 |
| docs/governance/authority-map.md | links_to | AGENTS.md | docs/governance/authority-map.md:17 |
| docs/governance/authority-map.md | links_to | apps/web/README.md | docs/governance/authority-map.md:29 |
| docs/governance/authority-map.md | links_to | docs/技术架构与部署规划.md | docs/governance/authority-map.md:30 |
| docs/governance/authority-map.md | links_to | docs/项目产品介绍书.md | docs/governance/authority-map.md:23 |
| docs/governance/authority-map.md | links_to | docs/api-contract.md | docs/governance/authority-map.md:31 |
| docs/governance/authority-map.md | links_to | docs/architecture.md | docs/governance/authority-map.md:25 |
| docs/governance/authority-map.md | links_to | docs/brd/BRD-dy-data-20260716-1255.md | docs/governance/authority-map.md:38 |
| docs/governance/authority-map.md | links_to | docs/brd/brd-ledger-dy-data.md | docs/governance/authority-map.md:39 |
| docs/governance/authority-map.md | links_to | docs/data-model.md | docs/governance/authority-map.md:34 |
| docs/governance/authority-map.md | links_to | docs/design-system/README.md | docs/governance/authority-map.md:24 |
| docs/governance/authority-map.md | links_to | docs/github-cicd.md | docs/governance/authority-map.md:32 |
| docs/governance/authority-map.md | links_to | docs/plans/execution-plan.md | docs/governance/authority-map.md:21 |
| docs/governance/authority-map.md | links_to | docs/prd/mainprd-dy-data.md | docs/governance/authority-map.md:42 |
| docs/governance/authority-map.md | links_to | docs/runbook.md | docs/governance/authority-map.md:26 |
| docs/governance/authority-map.md | links_to | docs/tencent-edgeone-migration.md | docs/governance/authority-map.md:33 |
| docs/governance/authority-map.md | links_to | docs/tencent-lighthouse-cicd.md | docs/governance/authority-map.md:32 |
| docs/governance/authority-map.md | links_to | project-profile.md | docs/governance/authority-map.md:20 |
| docs/governance/authority-map.md | links_to | project-rules.md | docs/governance/authority-map.md:19 |
| docs/governance/authority-map.md | links_to | README.md | docs/governance/authority-map.md:28 |
| docs/plans/2026-06-11-two-person-development-division.md | links_to | docs/项目产品介绍书.md | docs/plans/2026-06-11-two-person-development-division.md:44 |
| docs/plans/2026-06-11-two-person-development-division.md | links_to | docs/architecture.md | docs/plans/2026-06-11-two-person-development-division.md:68 |
| docs/plans/2026-06-11-two-person-development-division.md | links_to | docs/runbook.md | docs/plans/2026-06-11-two-person-development-division.md:69 |
| docs/plans/2026-06-11-two-person-development-division.md | links_to | README.md | docs/plans/2026-06-11-two-person-development-division.md:67 |
| docs/plans/2026-06-12-automatic-collection-production-closure.md | links_to | docs/技术架构与部署规划.md | docs/plans/2026-06-12-automatic-collection-production-closure.md:523 |
| docs/plans/2026-06-12-automatic-collection-production-closure.md | links_to | docs/data-model.md | docs/plans/2026-06-12-automatic-collection-production-closure.md:524 |
| docs/plans/2026-06-12-automatic-collection-production-closure.md | links_to | docs/runbook.md | docs/plans/2026-06-12-automatic-collection-production-closure.md:522 |
| docs/plans/2026-06-12-backend-production-mvp-controller-spec.md | links_to | docs/api-contract.md | docs/plans/2026-06-12-backend-production-mvp-controller-spec.md:21 |
| docs/plans/2026-06-12-backend-production-mvp-controller-spec.md | links_to | docs/data-model.md | docs/plans/2026-06-12-backend-production-mvp-controller-spec.md:20 |
| docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md | links_to | docs/api-contract.md | docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md:974 |
| docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md | links_to | docs/data-model.md | docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md:973 |
| docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md | links_to | docs/runbook.md | docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md:975 |
| docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md | links_to | docs/superpowers/specs/2026-07-12-clue-allocation-engine-product-design.md | docs/plans/2026-06-16-clue-allocation-center-mvp-plan.md:3 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:89 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:90 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:91 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:101 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:102 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:103 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.4-statement-projections.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:104 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.5-raw-id-cutover.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:105 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.1-reporting-api.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:115 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.2-settlement-pages.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:116 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.3-admin-console.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:117 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T4.1-release-verification.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:127 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:131 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | depends_on | docs/prd/foundation/foundation-delivery-dy-data.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:24 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | depends_on | docs/prd/mainprd-dy-data.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:23 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | links_to | docs/prd/prd-feature-list-dy-data.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:23 |
| docs/plans/delivery-plans/main-delivery-plan-dy-data.md | depends_on | docs/prd/subprd/03-subprd-order-fee-details.md | docs/plans/delivery-plans/main-delivery-plan-dy-data.md:12 |
| docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md | depends_on | docs/brd/BRD-dy-data-20260716-1255.md | docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md:12 |
| docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md | docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md:78 |
| docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.2-backend.md | docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md:79 |
| docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md | docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md:80 |
| docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md | links_to | docs/plans/delivery-plans/task-kanban-dydata-22-dual-id-activation.md | docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md:84 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md:5 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md:6 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md | depends_on | docs/prd/foundation/foundation-schema-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md:13 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md | depends_on | docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md:14 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md:5 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md:6 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md | depends_on | docs/prd/foundation/foundation-schema-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md:13 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md | depends_on | docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.2-product-rule-schema.md:14 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md:5 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md:6 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md | depends_on | docs/prd/foundation/foundation-schema-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md:13 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md | depends_on | docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md:14 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md | depends_on | docs/prd/subprd/03-subprd-order-fee-details.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.3-settlement-schema.md:15 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md:5 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md:6 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md | depends_on | docs/prd/foundation/foundation-api-dy-data/product-sync.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md:13 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md | depends_on | docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.1-product-sync.md:14 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md:5 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md:6 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md | depends_on | docs/prd/foundation/foundation-api-dy-data/common-contract.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md:14 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md | depends_on | docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md:13 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md:5 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md:6 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md | depends_on | docs/prd/foundation/foundation-glossary-dy-data.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md:13 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md | depends_on | docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md:14 |
| docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md | depends_on | docs/prd/subprd/02-subprd-store-settlement.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md:15 |

## 4. 诊断问题

| 级别 | code | 位置 | 说明 |
|---|---|---|---|
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md references missing file docs/plans/account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md references missing file docs/plans/account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md |
| info | orphan_artifact | src/frontend/page-preview/explainer-b-gap-dy-data.md | src/frontend/page-preview/explainer-b-gap-dy-data.md has no discovered file-level relationship |
