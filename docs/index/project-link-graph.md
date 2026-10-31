# 项目文件引用索引

> 本文件由 project-link-indexer 编译生成。它是给人和 LLM 读取的索引，不替代原始需求、PRD、计划或代码文件。

## 1. 摘要

- 文件节点：1456
- 文件关系：1744
- 诊断问题：43
- 机器索引：`docs/index/project-link-graph.json`
- 关系 schema：`docs/index/project-wiki-schema.json`

## 2. Wiki 入口

| 文件 | 类型 | owner skill | wiki 链接 | markdown 链接 |
|---|---|---|---|---|
| ci-cd.yml | config | host-project | [[.github/workflows/ci-cd.yml|ci-cd.yml]] | [ci-cd.yml](../../.github/workflows/ci-cd.yml) |
| local-ranking-export-20261009.yml | config | host-project | [[.github/workflows/local-ranking-export-20261009.yml|local-ranking-export-20261009.yml]] | [local-ranking-export-20261009.yml](../../.github/workflows/local-ranking-export-20261009.yml) |
| pdca-readonly-verify.yml | config | host-project | [[.github/workflows/pdca-readonly-verify.yml|pdca-readonly-verify.yml]] | [pdca-readonly-verify.yml](../../.github/workflows/pdca-readonly-verify.yml) |
| tencent-lighthouse-deploy.yml | config | host-project | [[.github/workflows/tencent-lighthouse-deploy.yml|tencent-lighthouse-deploy.yml]] | [tencent-lighthouse-deploy.yml](../../.github/workflows/tencent-lighthouse-deploy.yml) |
| tencent-resume-verified.yml | config | host-project | [[.github/workflows/tencent-resume-verified.yml|tencent-resume-verified.yml]] | [tencent-resume-verified.yml](../../.github/workflows/tencent-resume-verified.yml) |
| AGENTS.md | doc | host-project | [[AGENTS.md|AGENTS.md]] | [AGENTS.md](../../AGENTS.md) |
| Register all domain tables before Alembic compares metadata. Historical | source_code | coding-standards | [[alembic/env.py|Register all domain tables before Alembic compares metadata. Historical]] | [Register all domain tables before Alembic compares metadata. Historical](../../alembic/env.py) |
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
| 20260830_0044_clue_source_record_links.py | source_code | coding-standards | [[alembic/versions/20260830_0044_clue_source_record_links.py|20260830_0044_clue_source_record_links.py]] | [20260830_0044_clue_source_record_links.py](../../alembic/versions/20260830_0044_clue_source_record_links.py) |
| 20260831_0044_finance_dispute_detection_idempotency.py | source_code | coding-standards | [[alembic/versions/20260831_0044_finance_dispute_detection_idempotency.py|20260831_0044_finance_dispute_detection_idempotency.py]] | [20260831_0044_finance_dispute_detection_idempotency.py](../../alembic/versions/20260831_0044_finance_dispute_detection_idempotency.py) |
| 20260831_0045_clue_allocation_cycle_evidence.py | source_code | coding-standards | [[alembic/versions/20260831_0045_clue_allocation_cycle_evidence.py|20260831_0045_clue_allocation_cycle_evidence.py]] | [20260831_0045_clue_allocation_cycle_evidence.py](../../alembic/versions/20260831_0045_clue_allocation_cycle_evidence.py) |
| 20260831_0046_retire_legacy_clue_rounds.py | source_code | coding-standards | [[alembic/versions/20260831_0046_retire_legacy_clue_rounds.py|20260831_0046_retire_legacy_clue_rounds.py]] | [20260831_0046_retire_legacy_clue_rounds.py](../../alembic/versions/20260831_0046_retire_legacy_clue_rounds.py) |
| 20260831_0047_merge_dydata81_and_clue_heads.py | source_code | coding-standards | [[alembic/versions/20260831_0047_merge_dydata81_and_clue_heads.py|20260831_0047_merge_dydata81_and_clue_heads.py]] | [20260831_0047_merge_dydata81_and_clue_heads.py](../../alembic/versions/20260831_0047_merge_dydata81_and_clue_heads.py) |
| 20260831_0048_allow_finance_detection_succeeded.py | source_code | coding-standards | [[alembic/versions/20260831_0048_allow_finance_detection_succeeded.py|20260831_0048_allow_finance_detection_succeeded.py]] | [20260831_0048_allow_finance_detection_succeeded.py](../../alembic/versions/20260831_0048_allow_finance_detection_succeeded.py) |
| 20260901_0049_promotion_invoice_manual_fields.py | source_code | coding-standards | [[alembic/versions/20260901_0049_promotion_invoice_manual_fields.py|20260901_0049_promotion_invoice_manual_fields.py]] | [20260901_0049_promotion_invoice_manual_fields.py](../../alembic/versions/20260901_0049_promotion_invoice_manual_fields.py) |
| 20260903_0050_douyin_api_quota_usage.py | source_code | coding-standards | [[alembic/versions/20260903_0050_douyin_api_quota_usage.py|20260903_0050_douyin_api_quota_usage.py]] | [20260903_0050_douyin_api_quota_usage.py](../../alembic/versions/20260903_0050_douyin_api_quota_usage.py) |
| 20260907_0051_clue_phone_source_fingerprint.py | source_code | coding-standards | [[alembic/versions/20260907_0051_clue_phone_source_fingerprint.py|20260907_0051_clue_phone_source_fingerprint.py]] | [20260907_0051_clue_phone_source_fingerprint.py](../../alembic/versions/20260907_0051_clue_phone_source_fingerprint.py) |
| 20260909_0051_fee_result_verification_provenance.py | source_code | coding-standards | [[alembic/versions/20260909_0051_fee_result_verification_provenance.py|20260909_0051_fee_result_verification_provenance.py]] | [20260909_0051_fee_result_verification_provenance.py](../../alembic/versions/20260909_0051_fee_result_verification_provenance.py) |
| 20260909_0052_merge_clue_and_fee_provenance.py | source_code | coding-standards | [[alembic/versions/20260909_0052_merge_clue_and_fee_provenance.py|20260909_0052_merge_clue_and_fee_provenance.py]] | [20260909_0052_merge_clue_and_fee_provenance.py](../../alembic/versions/20260909_0052_merge_clue_and_fee_provenance.py) |
| 20260910_0053_quota_pause_attempts.py | source_code | coding-standards | [[alembic/versions/20260910_0053_quota_pause_attempts.py|20260910_0053_quota_pause_attempts.py]] | [20260910_0053_quota_pause_attempts.py](../../alembic/versions/20260910_0053_quota_pause_attempts.py) |
| 20260911_0054_dim_store_service_code.py | source_code | coding-standards | [[alembic/versions/20260911_0054_dim_store_service_code.py|20260911_0054_dim_store_service_code.py]] | [20260911_0054_dim_store_service_code.py](../../alembic/versions/20260911_0054_dim_store_service_code.py) |

## 3. 关系

| 来源 | 关系 | 目标 | 证据 |
|---|---|---|---|
| AGENTS.md | links_to | AGENTS.md | AGENTS.md:80 |
| AGENTS.md | links_to | CHANGELOG.md | AGENTS.md:142 |
| AGENTS.md | links_to | docs/api/dashboard-publications.md | AGENTS.md:135 |
| AGENTS.md | links_to | docs/api/ranking-lifecycle.md | AGENTS.md:133 |
| AGENTS.md | links_to | docs/governance/authority-map.md | AGENTS.md:92 |
| AGENTS.md | links_to | docs/plans/execution-plan.md | AGENTS.md:88 |
| AGENTS.md | links_to | docs/rules/storage-management.md | AGENTS.md:124 |
| AGENTS.md | links_to | project-profile.md | AGENTS.md:85 |
| AGENTS.md | links_to | project-rules.md | AGENTS.md:83 |
| AGENTS.md | links_to | RELEASING.md | AGENTS.md:141 |
| apps/web/README.md | links_to | docs/design-system/README.md | apps/web/README.md:53 |
| CHANGELOG.md | links_to | docs/devlog/2026-09-10-priority-daily.md | CHANGELOG.md:168 |
| CHANGELOG.md | links_to | docs/devlog/20260723_refactor_log_Keith_Chen.md | CHANGELOG.md:184 |
| CHANGELOG.md | links_to | docs/devlog/20260827_dydata-46-production-promotion.md | CHANGELOG.md:184 |
| CHANGELOG.md | links_to | docs/devlog/20260910_refactor_log_Keith_Chen.md | CHANGELOG.md:168 |
| CHANGELOG.md | links_to | docs/devlog/20260911_ranking_dashboard_production.md | CHANGELOG.md:152 |
| CHANGELOG.md | links_to | docs/devlog/20260915_account_org_scope.md | CHANGELOG.md:153 |
| CHANGELOG.md | links_to | docs/devlog/20260917_account_current_org.md | CHANGELOG.md:153 |
| CHANGELOG.md | links_to | docs/devlog/20260928_refactor_log_Your_Name.md | CHANGELOG.md:135 |
| CHANGELOG.md | links_to | docs/devlog/20260929_activation_guide_reminder.md | CHANGELOG.md:136 |
| CHANGELOG.md | links_to | docs/devlog/20261009_disk_ranking_retention.md | CHANGELOG.md:118 |
| CHANGELOG.md | links_to | docs/devlog/20261020_dydata-104-followthrough.md | CHANGELOG.md:101 |
| CHANGELOG.md | links_to | docs/devlog/20261028_refactor_log_Keith_Chen.md | CHANGELOG.md:68 |
| CHANGELOG.md | links_to | docs/plans/delivery-plans/sub-delivery-plan-dydata-46-production-promotion-T2.1-release-uat.md | CHANGELOG.md:184 |
| CHANGELOG.md | links_to | docs/verification/dydata-104-oct23.md | CHANGELOG.md:84 |
| CHANGELOG.md | links_to | docs/verification/dydata-104-oct27-delivery.md | CHANGELOG.md:49 |
| CHANGELOG.md | links_to | docs/verification/dydata-104-oct28-verify-impact.md | CHANGELOG.md:67 |
| CHANGELOG.md | links_to | docs/verification/dydata-104-oct30-delivery.md | CHANGELOG.md:32 |
| CHANGELOG.md | links_to | README.md | CHANGELOG.md:3 |
| CHANGELOG.md | links_to | RELEASING.md | CHANGELOG.md:3 |
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
| docs/api-contract.md | links_to | docs/api/dashboard-publications.md | docs/api-contract.md:44 |
| docs/api-contract.md | links_to | docs/api/pdca-event-snapshot.md | docs/api-contract.md:52 |
| docs/api-contract.md | links_to | docs/api/product-type-classification.md | docs/api-contract.md:223 |
| docs/api-contract.md | links_to | docs/api/settlement-scope-rules.md | docs/api-contract.md:230 |
| docs/api-contract.md | links_to | docs/devlog/20260914_ranking_export.md | docs/api-contract.md:206 |
| docs/api-contract.md | links_to | docs/prd/foundation/foundation-api-dy-data.md | docs/api-contract.md:3 |
| docs/api-contract.md | links_to | docs/prd/foundation/foundation-api-dy-data/billing-invoice.md | docs/api-contract.md:245 |
| docs/api-contract.md | links_to | docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md | docs/api-contract.md:247 |
| docs/api-contract.md | links_to | docs/verification/dydata-104-oct30-delivery.md | docs/api-contract.md:247 |
| docs/api/dashboard-publications.md | links_to | docs/api/product-type-classification.md | docs/api/dashboard-publications.md:93 |
| docs/api/pdca-event-snapshot.md | links_to | docs/api/pdca-event-manifest.schema.json | docs/api/pdca-event-snapshot.md:83 |
| docs/api/pdca-event-snapshot.md | links_to | docs/api/pdca-event-page.schema.json | docs/api/pdca-event-snapshot.md:84 |
| docs/api/pdca-event-snapshot.md | links_to | docs/api/pdca-event-synthetic-example.json | docs/api/pdca-event-snapshot.md:85 |
| docs/api/pdca-event-snapshot.md | links_to | docs/devlog/20260928_refactor_log_Your_Name.md | docs/api/pdca-event-snapshot.md:87 |
| docs/api/pdca-source-evidence.md | links_to | docs/api/pdca-api-release-checklist.md | docs/api/pdca-source-evidence.md:7 |
| docs/api/product-type-classification.md | links_to | docs/ops/product-type-conversion.md | docs/api/product-type-classification.md:23 |
| docs/api/ranking-lifecycle.md | links_to | docs/rules/storage-management.md | docs/api/ranking-lifecycle.md:34 |
| docs/api/refund-evidence-recovery.md | links_to | docs/api/dashboard-publications.md | docs/api/refund-evidence-recovery.md:31 |
| docs/api/refund-evidence-recovery.md | links_to | docs/devlog/20261019_unified_dashboard_publications.md | docs/api/refund-evidence-recovery.md:3 |
| docs/api/settlement-scope-rules.md | links_to | docs/devlog/20261020_dydata-104-followthrough.md | docs/api/settlement-scope-rules.md:35 |
| docs/architecture.md | links_to | docs/项目产品介绍书.md | docs/architecture.md:81 |
| docs/architecture.md | links_to | docs/runbook.md | docs/architecture.md:74 |
| docs/baseline/dydata-6-baseline-dry-run-review.md | links_to | docs/governance/authority-map.md | docs/baseline/dydata-6-baseline-dry-run-review.md:50 |
| docs/baseline/dydata-6-baseline-dry-run-review.md | links_to | project-profile.md | docs/baseline/dydata-6-baseline-dry-run-review.md:16 |
| docs/baseline/dydata-6-baseline-dry-run-review.md | links_to | README.md | docs/baseline/dydata-6-baseline-dry-run-review.md:41 |
| docs/brd/BRD-clue-center-20260721-2134.md | links_to | docs/plans/2026-07-12-clue-allocation-m1-controller-spec.md | docs/brd/BRD-clue-center-20260721-2134.md:258 |
| docs/brd/BRD-clue-center-20260721-2134.md | links_to | docs/plans/2026-07-12-clue-allocation-m2-m3-controller-spec.md | docs/brd/BRD-clue-center-20260721-2134.md:258 |
| docs/brd/BRD-dy-data-20260716-1255.md | links_to | docs/brd/brd-ledger-dy-data.md | docs/brd/BRD-dy-data-20260716-1255.md:7 |
| docs/brd/BRD-dy-data-20260716-1255.md | links_to | project-profile.md | docs/brd/BRD-dy-data-20260716-1255.md:6 |
| docs/cli-agent-guide.md | links_to | docs/cli-agent-acceptance.md | docs/cli-agent-guide.md:28 |
| docs/cli-agent-guide.md | links_to | docs/cli-command-reference.md | docs/cli-agent-guide.md:28 |
| docs/commission-pages-collaborator-handoff.md | links_to | docs/commission-pages-collaborator-handoff.md | docs/commission-pages-collaborator-handoff.md:19 |
| docs/commission-pages-collaborator-handoff.md | links_to | docs/superpowers/specs/2026-07-15-dydata-23-store-dashboard-visual-design.md | docs/commission-pages-collaborator-handoff.md:18 |
| docs/commission-settlement-rework-decisions.md | links_to | docs/single-store-monthly-settlement-mock.html | docs/commission-settlement-rework-decisions.md:51 |
| docs/commission-settlement-rework-decisions.md | links_to | docs/store-ranking-mock.html | docs/commission-settlement-rework-decisions.md:23 |
| docs/data-model.md | links_to | docs/api/ranking-lifecycle.md | docs/data-model.md:88 |
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

## 4. 诊断问题

| 级别 | code | 位置 | 说明 |
|---|---|---|---|
| error | broken_link | docs/brd/BRD-clue-center-20260721-2134.md | docs/brd/BRD-clue-center-20260721-2134.md references missing file .gstack/qa-reports/qa-report-clue-allocation-2026-07-18.md |
| error | broken_link | docs/brd/BRD-clue-center-20260721-2134.md | docs/brd/BRD-clue-center-20260721-2134.md references missing file .gstack/qa-reports/qa-report-clue-allocation-round2-2026-07-18.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.2-settlement-pages.md | docs/plans/delivery-plans/sub-delivery-plan-dy-data-T3.2-settlement-pages.md references missing file docs/plans/delivery-plans/docs/prd/subprd/04-subprd-invoice-guide.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-106-T1.1-clue-filters.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-106-T1.1-clue-filters.md references missing file docs/plans/delivery-plans/foundation/foundation-api-clue-center/lead-query-and-contact.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-106-T1.1-clue-filters.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-106-T1.1-clue-filters.md references missing file docs/plans/delivery-plans/foundation/foundation-schema-clue-center.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-110-T1.1-auth.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-110-T1.1-auth.md references missing file docs/plans/delivery-plans/foundation/foundation-api-dy-data/common-contract.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md references missing file docs/plans/account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md references missing file docs/plans/account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md references missing file docs/plans/delivery-plans/docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md references missing file docs/plans/delivery-plans/docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md references missing file docs/plans/delivery-plans/docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md |
| error | broken_link | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md | docs/plans/delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md references missing file docs/plans/delivery-plans/docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md |
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
| error | broken_link | docs/verification/dydata-104-oct28-control-origin.md | docs/verification/dydata-104-oct28-control-origin.md references missing file apps/api/Dockerfile |
| error | broken_link | docs/verification/dydata-104-oct28-control-origin.md | docs/verification/dydata-104-oct28-control-origin.md references missing file deploy/nginx.conf |
| error | broken_link | docs/verification/dydata-105-verification.md | docs/verification/dydata-105-verification.md references missing file pwScreenShot/dydata105/admin-rule-published.png |
| error | broken_link | docs/verification/dydata-105-verification.md | docs/verification/dydata-105-verification.md references missing file pwScreenShot/dydata105/admin-scoped-permissions.png |
| error | broken_link | docs/verification/dydata-105-verification.md | docs/verification/dydata-105-verification.md references missing file pwScreenShot/dydata105/clue-bulk-1440.png |
| error | broken_link | docs/verification/dydata-105-verification.md | docs/verification/dydata-105-verification.md references missing file pwScreenShot/dydata105/clue-bulk-390.png |
| error | broken_link | RELEASING.md | RELEASING.md references missing file deploy/tencent/deploy.sh |
