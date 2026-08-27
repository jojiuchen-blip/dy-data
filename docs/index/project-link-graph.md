# 项目文件引用索引

> 本文件由 project-link-indexer 编译生成。它是给人和 LLM 读取的索引，不替代原始需求、PRD、计划或代码文件。

## 1. 摘要

- 文件节点：725
- 文件关系：802
- 诊断问题：29
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
| 20260721_0018_account_access_control.py | source_code | coding-standards | [[alembic/versions/20260721_0018_account_access_control.py|20260721_0018_account_access_control.py]] | [20260721_0018_account_access_control.py](../../alembic/versions/20260721_0018_account_access_control.py) |
| 20260721_0025_product_sync_active_slot.py | source_code | coding-standards | [[alembic/versions/20260721_0025_product_sync_active_slot.py|20260721_0025_product_sync_active_slot.py]] | [20260721_0025_product_sync_active_slot.py](../../alembic/versions/20260721_0025_product_sync_active_slot.py) |
| 20260721_0026_product_sync_idempotency_key.py | source_code | coding-standards | [[alembic/versions/20260721_0026_product_sync_idempotency_key.py|20260721_0026_product_sync_idempotency_key.py]] | [20260721_0026_product_sync_idempotency_key.py](../../alembic/versions/20260721_0026_product_sync_idempotency_key.py) |
| 20260722_0019_add_cli_authorizations.py | source_code | coding-standards | [[alembic/versions/20260722_0019_add_cli_authorizations.py|20260722_0019_add_cli_authorizations.py]] | [20260722_0019_add_cli_authorizations.py](../../alembic/versions/20260722_0019_add_cli_authorizations.py) |
| 20260722_0020_cli_audit_and_refresh_families.py | source_code | coding-standards | [[alembic/versions/20260722_0020_cli_audit_and_refresh_families.py|20260722_0020_cli_audit_and_refresh_families.py]] | [20260722_0020_cli_audit_and_refresh_families.py](../../alembic/versions/20260722_0020_cli_audit_and_refresh_families.py) |
| 20260722_0021_mcp_oauth.py | source_code | coding-standards | [[alembic/versions/20260722_0021_mcp_oauth.py|20260722_0021_mcp_oauth.py]] | [20260722_0021_mcp_oauth.py](../../alembic/versions/20260722_0021_mcp_oauth.py) |
| 20260722_0022_agent_audit_context.py | source_code | coding-standards | [[alembic/versions/20260722_0022_agent_audit_context.py|20260722_0022_agent_audit_context.py]] | [20260722_0022_agent_audit_context.py](../../alembic/versions/20260722_0022_agent_audit_context.py) |
| 20260727_0027_merge_settlement_and_agent_heads.py | source_code | coding-standards | [[alembic/versions/20260727_0027_merge_settlement_and_agent_heads.py|20260727_0027_merge_settlement_and_agent_heads.py]] | [20260727_0027_merge_settlement_and_agent_heads.py](../../alembic/versions/20260727_0027_merge_settlement_and_agent_heads.py) |
| 20260727_0028_product_sync_production_fields.py | source_code | coding-standards | [[alembic/versions/20260727_0028_product_sync_production_fields.py|20260727_0028_product_sync_production_fields.py]] | [20260727_0028_product_sync_production_fields.py](../../alembic/versions/20260727_0028_product_sync_production_fields.py) |
| 20260804_0029_clue_source_identifier_history.py | source_code | coding-standards | [[alembic/versions/20260804_0029_clue_source_identifier_history.py|20260804_0029_clue_source_identifier_history.py]] | [20260804_0029_clue_source_identifier_history.py](../../alembic/versions/20260804_0029_clue_source_identifier_history.py) |
| 20260806_0030_sync_control_plane.py | source_code | coding-standards | [[alembic/versions/20260806_0030_sync_control_plane.py|20260806_0030_sync_control_plane.py]] | [20260806_0030_sync_control_plane.py](../../alembic/versions/20260806_0030_sync_control_plane.py) |
| 20260806_0031_task_control_state_machine.py | source_code | coding-standards | [[alembic/versions/20260806_0031_task_control_state_machine.py|20260806_0031_task_control_state_machine.py]] | [20260806_0031_task_control_state_machine.py](../../alembic/versions/20260806_0031_task_control_state_machine.py) |
| 20260806_0032_sync_impacts.py | source_code | coding-standards | [[alembic/versions/20260806_0032_sync_impacts.py|20260806_0032_sync_impacts.py]] | [20260806_0032_sync_impacts.py](../../alembic/versions/20260806_0032_sync_impacts.py) |
| 20260806_0033_clue_incremental_indexes.py | source_code | coding-standards | [[alembic/versions/20260806_0033_clue_incremental_indexes.py|20260806_0033_clue_incremental_indexes.py]] | [20260806_0033_clue_incremental_indexes.py](../../alembic/versions/20260806_0033_clue_incremental_indexes.py) |
| 20260806_0034_incremental_settlement.py | source_code | coding-standards | [[alembic/versions/20260806_0034_incremental_settlement.py|20260806_0034_incremental_settlement.py]] | [20260806_0034_incremental_settlement.py](../../alembic/versions/20260806_0034_incremental_settlement.py) |
| 20260806_0035_projection_sparse_overlay.py | source_code | coding-standards | [[alembic/versions/20260806_0035_projection_sparse_overlay.py|20260806_0035_projection_sparse_overlay.py]] | [20260806_0035_projection_sparse_overlay.py](../../alembic/versions/20260806_0035_projection_sparse_overlay.py) |
| 20260806_0036_projection_compaction_closure.py | source_code | coding-standards | [[alembic/versions/20260806_0036_projection_compaction_closure.py|20260806_0036_projection_compaction_closure.py]] | [20260806_0036_projection_compaction_closure.py](../../alembic/versions/20260806_0036_projection_compaction_closure.py) |
| 20260813_0030_sku_product_import.py | source_code | coding-standards | [[alembic/versions/20260813_0030_sku_product_import.py|20260813_0030_sku_product_import.py]] | [20260813_0030_sku_product_import.py](../../alembic/versions/20260813_0030_sku_product_import.py) |
| 20260819_0037_merge_safe_sync_and_sku_heads.py | source_code | coding-standards | [[alembic/versions/20260819_0037_merge_safe_sync_and_sku_heads.py|20260819_0037_merge_safe_sync_and_sku_heads.py]] | [20260819_0037_merge_safe_sync_and_sku_heads.py](../../alembic/versions/20260819_0037_merge_safe_sync_and_sku_heads.py) |
| 20260821_0028_finance_closure_schema.py | source_code | coding-standards | [[alembic/versions/20260821_0028_finance_closure_schema.py|20260821_0028_finance_closure_schema.py]] | [20260821_0028_finance_closure_schema.py](../../alembic/versions/20260821_0028_finance_closure_schema.py) |
| 20260821_0029_version_settlement_statements.py | source_code | coding-standards | [[alembic/versions/20260821_0029_version_settlement_statements.py|20260821_0029_version_settlement_statements.py]] | [20260821_0029_version_settlement_statements.py](../../alembic/versions/20260821_0029_version_settlement_statements.py) |
| 20260821_0030_statement_confirmation_idempotency.py | source_code | coding-standards | [[alembic/versions/20260821_0030_statement_confirmation_idempotency.py|20260821_0030_statement_confirmation_idempotency.py]] | [20260821_0030_statement_confirmation_idempotency.py](../../alembic/versions/20260821_0030_statement_confirmation_idempotency.py) |
| 20260821_0031_promotion_invoice_allocations.py | source_code | coding-standards | [[alembic/versions/20260821_0031_promotion_invoice_allocations.py|20260821_0031_promotion_invoice_allocations.py]] | [20260821_0031_promotion_invoice_allocations.py](../../alembic/versions/20260821_0031_promotion_invoice_allocations.py) |
| 20260821_0032_dispute_idempotency.py | source_code | coding-standards | [[alembic/versions/20260821_0032_dispute_idempotency.py|20260821_0032_dispute_idempotency.py]] | [20260821_0032_dispute_idempotency.py](../../alembic/versions/20260821_0032_dispute_idempotency.py) |
| 20260821_0033_promotion_invoice_version_number.py | source_code | coding-standards | [[alembic/versions/20260821_0033_promotion_invoice_version_number.py|20260821_0033_promotion_invoice_version_number.py]] | [20260821_0033_promotion_invoice_version_number.py](../../alembic/versions/20260821_0033_promotion_invoice_version_number.py) |
| 20260821_0034_store_finance_profiles.py | source_code | coding-standards | [[alembic/versions/20260821_0034_store_finance_profiles.py|20260821_0034_store_finance_profiles.py]] | [20260821_0034_store_finance_profiles.py](../../alembic/versions/20260821_0034_store_finance_profiles.py) |
| 20260821_0035_finance_import_result_fields.py | source_code | coding-standards | [[alembic/versions/20260821_0035_finance_import_result_fields.py|20260821_0035_finance_import_result_fields.py]] | [20260821_0035_finance_import_result_fields.py](../../alembic/versions/20260821_0035_finance_import_result_fields.py) |
| 20260821_0036_finance_import_upload_idempotency.py | source_code | coding-standards | [[alembic/versions/20260821_0036_finance_import_upload_idempotency.py|20260821_0036_finance_import_upload_idempotency.py]] | [20260821_0036_finance_import_upload_idempotency.py](../../alembic/versions/20260821_0036_finance_import_upload_idempotency.py) |
| 20260821_0037_promotion_invoice_registration_facts.py | source_code | coding-standards | [[alembic/versions/20260821_0037_promotion_invoice_registration_facts.py|20260821_0037_promotion_invoice_registration_facts.py]] | [20260821_0037_promotion_invoice_registration_facts.py](../../alembic/versions/20260821_0037_promotion_invoice_registration_facts.py) |
| 20260821_0038_settlement_carryforward_facts.py | source_code | coding-standards | [[alembic/versions/20260821_0038_settlement_carryforward_facts.py|20260821_0038_settlement_carryforward_facts.py]] | [20260821_0038_settlement_carryforward_facts.py](../../alembic/versions/20260821_0038_settlement_carryforward_facts.py) |
| 20260821_0039_promotion_invoice_lifecycle.py | source_code | coding-standards | [[alembic/versions/20260821_0039_promotion_invoice_lifecycle.py|20260821_0039_promotion_invoice_lifecycle.py]] | [20260821_0039_promotion_invoice_lifecycle.py](../../alembic/versions/20260821_0039_promotion_invoice_lifecycle.py) |
| 20260821_0040_allow_negative_promotion_invoice_allocations.py | source_code | coding-standards | [[alembic/versions/20260821_0040_allow_negative_promotion_invoice_allocations.py|20260821_0040_allow_negative_promotion_invoice_allocations.py]] | [20260821_0040_allow_negative_promotion_invoice_allocations.py](../../alembic/versions/20260821_0040_allow_negative_promotion_invoice_allocations.py) |
| 20260824_0041_g2_management_sap_reversal.py | source_code | coding-standards | [[alembic/versions/20260824_0041_g2_management_sap_reversal.py|20260824_0041_g2_management_sap_reversal.py]] | [20260824_0041_g2_management_sap_reversal.py](../../alembic/versions/20260824_0041_g2_management_sap_reversal.py) |
| 20260824_0042_finance_import_final_version_guard.py | source_code | coding-standards | [[alembic/versions/20260824_0042_finance_import_final_version_guard.py|20260824_0042_finance_import_final_version_guard.py]] | [20260824_0042_finance_import_final_version_guard.py](../../alembic/versions/20260824_0042_finance_import_final_version_guard.py) |
| 20260824_0043_statement_store_snapshots.py | source_code | coding-standards | [[alembic/versions/20260824_0043_statement_store_snapshots.py|20260824_0043_statement_store_snapshots.py]] | [20260824_0043_statement_store_snapshots.py](../../alembic/versions/20260824_0043_statement_store_snapshots.py) |
| __init__.py | source_code | coding-standards | [[apps/api/dy_api/__init__.py|__init__.py]] | [__init__.py](../../apps/api/dy_api/__init__.py) |
| access_control.py | source_code | coding-standards | [[apps/api/dy_api/access_control.py|access_control.py]] | [access_control.py](../../apps/api/dy_api/access_control.py) |
| agent_capabilities.py | source_code | coding-standards | [[apps/api/dy_api/agent_capabilities.py|agent_capabilities.py]] | [agent_capabilities.py](../../apps/api/dy_api/agent_capabilities.py) |
| dydata read-only Agent Skill | source_code | coding-standards | [[apps/api/dy_api/agent_contract.py|dydata read-only Agent Skill]] | [dydata read-only Agent Skill](../../apps/api/dy_api/agent_contract.py) |
| agent_environment.py | source_code | coding-standards | [[apps/api/dy_api/agent_environment.py|agent_environment.py]] | [agent_environment.py](../../apps/api/dy_api/agent_environment.py) |
| auth.py | source_code | coding-standards | [[apps/api/dy_api/auth.py|auth.py]] | [auth.py](../../apps/api/dy_api/auth.py) |
| cli_audit.py | source_code | coding-standards | [[apps/api/dy_api/cli_audit.py|cli_audit.py]] | [cli_audit.py](../../apps/api/dy_api/cli_audit.py) |
| cli_auth.py | source_code | coding-standards | [[apps/api/dy_api/cli_auth.py|cli_auth.py]] | [cli_auth.py](../../apps/api/dy_api/cli_auth.py) |
| cli_contract.py | source_code | coding-standards | [[apps/api/dy_api/cli_contract.py|cli_contract.py]] | [cli_contract.py](../../apps/api/dy_api/cli_contract.py) |
| db.py | source_code | coding-standards | [[apps/api/dy_api/db.py|db.py]] | [db.py](../../apps/api/dy_api/db.py) |
| main.py | source_code | coding-standards | [[apps/api/dy_api/main.py|main.py]] | [main.py](../../apps/api/dy_api/main.py) |
| mcp_oauth.py | source_code | coding-standards | [[apps/api/dy_api/mcp_oauth.py|mcp_oauth.py]] | [mcp_oauth.py](../../apps/api/dy_api/mcp_oauth.py) |
| mcp_server.py | source_code | coding-standards | [[apps/api/dy_api/mcp_server.py|mcp_server.py]] | [mcp_server.py](../../apps/api/dy_api/mcp_server.py) |
| models.py | source_code | coding-standards | [[apps/api/dy_api/models.py|models.py]] | [models.py](../../apps/api/dy_api/models.py) |
| _data.py | source_code | coding-standards | [[apps/api/dy_api/routes/_data.py|_data.py]] | [_data.py](../../apps/api/dy_api/routes/_data.py) |
| admin.py | source_code | coding-standards | [[apps/api/dy_api/routes/admin.py|admin.py]] | [admin.py](../../apps/api/dy_api/routes/admin.py) |

## 3. 关系

| 来源 | 关系 | 目标 | 证据 |
|---|---|---|---|
| AGENTS.md | links_to | AGENTS.md | AGENTS.md:80 |
| AGENTS.md | links_to | docs/governance/authority-map.md | AGENTS.md:92 |
| AGENTS.md | links_to | docs/plans/execution-plan.md | AGENTS.md:88 |
| AGENTS.md | links_to | project-profile.md | AGENTS.md:85 |
| AGENTS.md | links_to | project-rules.md | AGENTS.md:83 |
| apps/web/README.md | links_to | docs/design-system/README.md | apps/web/README.md:43 |
| design-system/dy-data/MASTER.md | links_to | docs/design-system/README.md | design-system/dy-data/MASTER.md:15 |
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
| docs/brd/BRD-clue-center-20260721-2134.md | links_to | docs/plans/2026-07-12-clue-allocation-m1-controller-spec.md | docs/brd/BRD-clue-center-20260721-2134.md:228 |
| docs/brd/BRD-clue-center-20260721-2134.md | links_to | docs/plans/2026-07-12-clue-allocation-m2-m3-controller-spec.md | docs/brd/BRD-clue-center-20260721-2134.md:228 |
| docs/brd/BRD-dy-data-20260716-1255.md | links_to | docs/brd/brd-ledger-dy-data.md | docs/brd/BRD-dy-data-20260716-1255.md:7 |
| docs/brd/BRD-dy-data-20260716-1255.md | links_to | project-profile.md | docs/brd/BRD-dy-data-20260716-1255.md:6 |
| docs/cli-agent-guide.md | links_to | docs/cli-agent-acceptance.md | docs/cli-agent-guide.md:28 |
| docs/cli-agent-guide.md | links_to | docs/cli-command-reference.md | docs/cli-agent-guide.md:28 |
| docs/commission-pages-collaborator-handoff.md | links_to | docs/commission-pages-collaborator-handoff.md | docs/commission-pages-collaborator-handoff.md:19 |
| docs/commission-pages-collaborator-handoff.md | links_to | docs/superpowers/specs/2026-07-15-dydata-23-store-dashboard-visual-design.md | docs/commission-pages-collaborator-handoff.md:18 |
| docs/commission-settlement-rework-decisions.md | links_to | docs/single-store-monthly-settlement-mock.html | docs/commission-settlement-rework-decisions.md:51 |
| docs/commission-settlement-rework-decisions.md | links_to | docs/store-ranking-mock.html | docs/commission-settlement-rework-decisions.md:23 |
| docs/design-system/README.md | links_to | docs/design-system/THIRD_PARTY_NOTICES.md | docs/design-system/README.md:87 |
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
| docs/devlog/20260719_refactor_log_Keith_Chen.md | links_to | docs/devlog/20260719_refactor_log_Keith_Chen.md | docs/devlog/20260719_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260719_refactor_log_Keith_Chen.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260719_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260719_refactor_log_Keith_Chen.md | links_to | project-profile.md | docs/devlog/20260719_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260719_refactor_log_Keith_Chen.md | links_to | project-rules.md | docs/devlog/20260719_refactor_log_Keith_Chen.md:81 |
| docs/devlog/20260720_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260720_refactor_log_jojiuchen-blip.md:88 |
| docs/devlog/20260721_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260721_refactor_log_jojiuchen-blip.md:76 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/brd/BRD-clue-center-20260721-2134.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/brd/brd-ledger-clue-center.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/devlog/20260721_refactor_log_Keith_Chen.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:96 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/governance/authority-map.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/prd/foundation/foundation-glossary-clue-center.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:96 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | docs/prd/foundation/foundation-schema-clue-center.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:107 |
| docs/devlog/20260721_refactor_log_Keith_Chen.md | links_to | project-profile.md | docs/devlog/20260721_refactor_log_Keith_Chen.md:27 |
| docs/devlog/20260722_refactor_log_Keith_Chen.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260722_refactor_log_Keith_Chen.md:36 |
| docs/devlog/20260722_refactor_log_Keith_Chen.md | links_to | docs/prd/foundation/foundation-api-clue-center.md | docs/devlog/20260722_refactor_log_Keith_Chen.md:36 |
| docs/devlog/20260722_refactor_log_Keith_Chen.md | links_to | docs/prd/foundation/foundation-delivery-clue-center.md | docs/devlog/20260722_refactor_log_Keith_Chen.md:116 |
| docs/devlog/20260722_refactor_log_Keith_Chen.md | links_to | docs/prd/foundation/foundation-schema-clue-center.md | docs/devlog/20260722_refactor_log_Keith_Chen.md:36 |
| docs/devlog/20260722_refactor_log_Keith_Chen.md | links_to | project-profile.md | docs/devlog/20260722_refactor_log_Keith_Chen.md:36 |
| docs/devlog/20260723_refactor_log_Keith_Chen.md | links_to | docs/devlog/20260723_refactor_log_Keith_Chen.md | docs/devlog/20260723_refactor_log_Keith_Chen.md:40 |
| docs/devlog/20260723_refactor_log_Keith_Chen.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md | docs/devlog/20260723_refactor_log_Keith_Chen.md:26 |
| docs/devlog/20260723_refactor_log_Keith_Chen.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md | docs/devlog/20260723_refactor_log_Keith_Chen.md:26 |
| docs/devlog/20260723_refactor_log_Keith_Chen.md | links_to | docs/plans/delivery-plans/task-kanban-dydata-45-test-agent-connect.md | docs/devlog/20260723_refactor_log_Keith_Chen.md:26 |
| docs/devlog/20260723_refactor_log_Keith_Chen.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260723_refactor_log_Keith_Chen.md:26 |
| docs/devlog/20260804_refactor_log_Keith_Chen.md | links_to | project-profile.md | docs/devlog/20260804_refactor_log_Keith_Chen.md:40 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/plans/delivery-plans/main-delivery-plan-dy-data.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:91 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/plans/delivery-plans/task-kanban-dy-data.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:92 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:61 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:49 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/prd/foundation/foundation-schema-dy-data.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:158 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:158 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | docs/prd/subprd/03-subprd-order-fee-details.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:49 |
| docs/devlog/20260820_refactor_log_jojiuchen-blip.md | links_to | project-profile.md | docs/devlog/20260820_refactor_log_jojiuchen-blip.md:61 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/2026-08-21-dydata-19-t5-controller-spec.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/dydata-19-task-g1a-brief.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/dydata-19-task-g1b-brief.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/dydata-19-task-g1c-brief.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/dydata-19-task-g2-brief.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/dydata-19-task-g3-brief.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/plans/execution-plan.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:194 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | docs/uat/dydata-19-uat-checklist.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:176 |
| docs/devlog/20260821_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260821_refactor_log_jojiuchen-blip.md:75 |
| docs/devlog/20260824_refactor_log_jojiuchen-blip.md | links_to | project-rules.md | docs/devlog/20260824_refactor_log_jojiuchen-blip.md:69 |
| docs/github-cicd.md | links_to | docs/tencent-lighthouse-cicd.md | docs/github-cicd.md:10 |
| docs/governance/authority-map.md | links_to | AGENTS.md | docs/governance/authority-map.md:17 |
| docs/governance/authority-map.md | links_to | apps/web/README.md | docs/governance/authority-map.md:29 |
| docs/governance/authority-map.md | links_to | docs/技术架构与部署规划.md | docs/governance/authority-map.md:30 |
| docs/governance/authority-map.md | links_to | docs/项目产品介绍书.md | docs/governance/authority-map.md:23 |
| docs/governance/authority-map.md | links_to | docs/api-contract.md | docs/governance/authority-map.md:31 |
| docs/governance/authority-map.md | links_to | docs/architecture.md | docs/governance/authority-map.md:25 |
| docs/governance/authority-map.md | links_to | docs/brd/BRD-clue-center-20260721-2134.md | docs/governance/authority-map.md:40 |
| docs/governance/authority-map.md | links_to | docs/brd/BRD-dy-data-20260716-1255.md | docs/governance/authority-map.md:38 |
| docs/governance/authority-map.md | links_to | docs/brd/brd-ledger-clue-center.md | docs/governance/authority-map.md:41 |
| docs/governance/authority-map.md | links_to | docs/brd/brd-ledger-dy-data.md | docs/governance/authority-map.md:39 |
| docs/governance/authority-map.md | links_to | docs/data-model.md | docs/governance/authority-map.md:34 |
| docs/governance/authority-map.md | links_to | docs/design-system/README.md | docs/governance/authority-map.md:24 |
| docs/governance/authority-map.md | links_to | docs/github-cicd.md | docs/governance/authority-map.md:32 |
| docs/governance/authority-map.md | links_to | docs/plans/execution-plan.md | docs/governance/authority-map.md:21 |
| docs/governance/authority-map.md | links_to | docs/prd/mainprd-dy-data.md | docs/governance/authority-map.md:44 |
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

## 4. 诊断问题

| 级别 | code | 位置 | 说明 |
|---|---|---|---|
| error | broken_link | docs/brd/BRD-clue-center-20260721-2134.md | docs/brd/BRD-clue-center-20260721-2134.md references missing file .gstack/qa-reports/qa-report-clue-allocation-2026-07-18.md |
| error | broken_link | docs/brd/BRD-clue-center-20260721-2134.md | docs/brd/BRD-clue-center-20260721-2134.md references missing file .gstack/qa-reports/qa-report-clue-allocation-round2-2026-07-18.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.2-settlement-pages.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.2-settlement-pages.md references missing file docs/plans/delivery-plans/docs/prd/subprd/04-subprd-invoice-guide.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md references missing file docs/plans/account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md references missing file docs/plans/account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/01-subprd-view-navigation-and-filters.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/02-subprd-operating-metrics-dashboard.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/03-subprd-lead-list-and-export.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/04-subprd-contact-and-order-summary.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/05-subprd-current-round-follow-up.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/06-subprd-rounds-and-follow-up-history.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/07-subprd-clue-sync-status-and-config.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/08-subprd-manual-backfill-and-maintenance.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/09-subprd-allocation-rules-and-versions.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/10-subprd-trial-and-controlled-rebuild.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/11-subprd-allocation-records-and-audit.md |
| error | broken_link | docs/prd/mainprd-clue-center.md | docs/prd/mainprd-clue-center.md references missing file docs/prd/subprd/12-subprd-headquarters-pool.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/01-subprd-view-navigation-and-filters.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/02-subprd-operating-metrics-dashboard.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/03-subprd-lead-list-and-export.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/04-subprd-contact-and-order-summary.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/05-subprd-current-round-follow-up.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/06-subprd-rounds-and-follow-up-history.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/07-subprd-clue-sync-status-and-config.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/08-subprd-manual-backfill-and-maintenance.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/09-subprd-allocation-rules-and-versions.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/10-subprd-trial-and-controlled-rebuild.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/11-subprd-allocation-records-and-audit.md |
| error | broken_link | docs/prd/prd-feature-list-clue-center.md | docs/prd/prd-feature-list-clue-center.md references missing file docs/prd/subprd/12-subprd-headquarters-pool.md |
