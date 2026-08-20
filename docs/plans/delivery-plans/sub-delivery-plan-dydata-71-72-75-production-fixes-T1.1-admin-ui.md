# T1.1 后台交互与账号门店选择 Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-71-72-75-production-fixes.md](main-delivery-plan-dydata-71-72-75-production-fixes.md)
- 任务看板：[task-kanban-dydata-71-72-75-production-fixes.md](task-kanban-dydata-71-72-75-production-fixes.md)
- Linear：DYDATA-71

#### T1.1 优化分佣规则流程和账号创建门店选择

**Requirement ID**：DYDATA-71

**PRD 双链·读**：
- Linear DYDATA-71 最新描述、2026-08-20 的步骤条/商品口径提醒/账号管理评论与附件
- `docs/rules/frontend-tasks.md`
- `docs/rules/account-access-control.md` §4-5

**核心逻辑**：
- 分佣四步导航 sticky，按滚动锚点与点击同步高亮；移除独立浏览搜索，批量导入移入第 1 步。
- 已启用/未启用切换强化状态，并对商品类型未配置 SKU 提示前往 `/admin/product-types`。
- 指定门店选择支持名称/ID 搜索及 CSV/TXT 批量导入；导入只合并合法门店到草稿，拒绝未知项并去重。
- 新建账号不展示账号名；服务端生成不可变技术用户名，编辑沿用原值；右侧编辑区独立滚动。

**核心文件**：
- `apps/web/src/pages/AdminSkuRulesPage.tsx`
- `apps/web/src/pages/AdminAccountsPage.tsx`
- `apps/web/src/styles.css`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/routes/admin.py`
- `tests/test_api_admin_accounts.py`
- `tests/test_frontend_admin_accounts.py`
- `tests/test_frontend_admin_rules_workflow.py`
- `tests/test_visual_smoke.py`

**完成标准**：
- 四步导航固定、可点击、滚动高亮；批量导入只在第 1 步主模块出现。
- 两种启用状态视觉明显，未配置商品类型存在可访问的商品口径入口。
- 门店搜索和批量导入可用于指定门店草稿，非法/重复项有明确反馈且不越权。
- 新建表单无账号名字段，创建成功返回唯一技术用户名；编辑不改变该值。
- 右侧创建模块在桌面端独立滚动，窄屏恢复自然文档流。

**Verification Method**：
- `python -m pytest tests/test_api_admin_accounts.py tests/test_frontend_admin_accounts.py tests/test_frontend_admin_rules_workflow.py tests/test_visual_smoke.py -q`
- `npm --prefix apps/web run build`
- Playwright 检查桌面长表单滚动、门店搜索/导入、步骤点击和启用状态焦点样式。

**Evidence**：
- 2026-08-20：先在远端基线上建立 6 个失败断言，覆盖账号名、技术用户名、门店选择、右侧滚动、步骤条和状态视觉。
- `python -m pytest tests/test_frontend_admin_accounts.py tests/test_frontend_admin_rules_workflow.py tests/test_api_admin_accounts.py -q`：18 passed。
- `npm --prefix apps/web run build`：通过；仅保留既有大 chunk 警告。
- 完整视觉套件和提交 SHA 在 T1.3 总体验证阶段统一追加。

**Failure Handling**：
- 若技术用户名无法在不改变登录能力下自动生成，停止并回到 Linear 记录身份决策。
- 若导入包含未知门店，整份文件不合并到草稿并显示未知门店 ID。

**完成收尾：状态同步**：
- 完成后同步主计划、看板、本子计划，并运行 S4 route-check；随后把证据回填 DYDATA-71。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：已完成
