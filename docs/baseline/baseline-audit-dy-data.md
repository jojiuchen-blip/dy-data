# 既有项目关键文件诊断清单

- 模式：existing-project-baseline
- 范围：maintenance-docs-only
- slug：dy-data
- 推荐下一步：page-explainer

## 1. 单焦点待确认

- 无

## 2. 关键文件缺口

| 类型 | 状态 | 期望位置 | 推荐 skill | 原因 |
|---|---|---|---|---|
| PROJECT_PROFILE | present | project-profile.md | 无 | 项目画像已存在或已生成草稿 |
| BRD | present | docs/brd/ | 无 | 已发现 BRD 文件 |
| PAGE_EXPLAINER | missing | src/frontend/page-preview/ | page-explainer | 缺少页面流程与交互语义说明；代码中发现页面文件线索 14 个 |
| FOUNDATION | missing | docs/prd/foundation/ | foundation-builder | 缺少术语表、Schema、API 与交付清单；代码中发现 API 端点线索 64 个、模型定义 37 个、迁移 17 个 |
| PRD | missing | docs/prd/ | prd-writer | 缺少功能列表、mainprd 与 subprd |

## 3. 代码证据摘要

- 页面线索：apps/web/src/pages/AdminAccountsPage.tsx、apps/web/src/pages/AdminClueAllocationPage.tsx、apps/web/src/pages/AdminFeedbackPage.tsx、apps/web/src/pages/AdminHomePage.tsx、apps/web/src/pages/AdminProductTypeVisibilityPage.tsx、apps/web/src/pages/AdminSkuRulesPage.tsx、apps/web/src/pages/AdminSyncPage.tsx、apps/web/src/pages/AuthPage.tsx、apps/web/src/pages/ClueCenterPage.tsx、apps/web/src/pages/HomePage.tsx
- 接口线索：apps/api/dy_api/routes/_data.py、apps/api/dy_api/routes/admin.py、apps/api/dy_api/routes/auth.py、apps/api/dy_api/routes/clues.py、apps/api/dy_api/routes/dashboard.py、apps/api/dy_api/routes/feedback.py、apps/api/dy_api/routes/jobs.py、apps/api/dy_api/routes/meta.py、apps/web/src/api/client.ts
- 数据模型线索：alembic/versions/20260612_0001_backend_production_mvp.py、alembic/versions/20260616_0002_sync_settings.py、alembic/versions/20260616_0003_clue_center_mvp.py、alembic/versions/20260617_0004_non_commission_rules.py、alembic/versions/20260618_0005_account_module.py、alembic/versions/20260622_0006_clue_phone_plain.py、alembic/versions/20260624_0007_clue_follow_up_records.py、alembic/versions/20260624_0008_user_feedback_submissions.py、alembic/versions/20260626_0009_product_type_visibility.py、alembic/versions/20260626_0010_product_type_default.py
- 配置线索：apps/web/tsconfig.json、apps/web/vite.config.ts、config.example.json、deploy/.env.example、src/dy_data/config.py

## 4. 边界

- 本清单不诊断测试用例。
- 本清单不诊断待开发任务。
- 本清单不推荐 delivery-planner 或 test-case 系列 skill。
