# prd-writer Mock Fixtures

Mock fixture coverage is implemented in `project-manager-suite/tests/prd-check.test.mjs`.

The matrix covers:

- happy path with 2 pages, 3 blocks, 3 subprd files
- missing page layout panorama
- missing page coverage from page-delivery
- feature-list block/detail drift
- feature-list detail anchor loss
- feature-list/mainprd index status drift
- subprd missing X.6 acceptance
- schema field missing
- API path missing, including `:id` / `{id}` normalization
- invalid or unlocked interaction ids
- safe and dangerous mainprd Phase 5 tables for route-check pollution regression
