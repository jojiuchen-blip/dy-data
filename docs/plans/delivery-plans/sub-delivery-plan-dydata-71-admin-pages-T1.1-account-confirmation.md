# T1.1 账号列表独立滚动与创建确认

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-71-admin-pages.md](main-delivery-plan-dydata-71-admin-pages.md)
- 任务看板：[task-kanban-dydata-71-admin-pages.md](task-kanban-dydata-71-admin-pages.md)

#### T1.1 让新建账号始终可达并在创建前复核敏感信息

**Requirement ID**：DYDATA-71-ACCOUNT

**PRD 双链·读**：

- Linear `DYDATA-71`“账号管理页面”范围和验收标准
- `docs/rules/account-access-control.md`“账号管理页面”
- `docs/design-system/tokens.json` `dialog`、`dataTable`、`button`

**核心逻辑**：

- 列表容器在桌面视口内独立滚动；编辑器 sticky 且不被长表拉伸。
- 编辑账号仍直接保存；新建账号首次提交只生成确认态，不调用 `createAccount`。
- 确认卡显示账号名、显示名称、密码和角色；密码默认掩码，可临时显示，关闭即复位。
- 确认创建期间禁用关闭和重复提交；失败保留原草稿并给用户可理解提示。

**核心文件**：

- `apps/web/src/pages/AdminAccountsPage.tsx`
- `apps/web/src/styles.css`
- `tests/test_frontend_admin_accounts.py`

**完成标准**：

- 账号表格被 `account-admin-main__scroll` 容器包裹，桌面最大高度受视口约束并独立滚动。
- 新建提交设置确认态，`createAccount` 只存在于确认创建处理函数中。
- “新建账号信息确认”展示四项信息，并有“返回修改”“确认创建”“显示/隐藏密码”。
- 确认卡关闭后密码恢复掩码；提交中按钮禁用且只发送一次请求。
- `python -m pytest tests/test_frontend_admin_accounts.py -q` 与 Web build 通过。

**Verification Method**：

- 先运行新增契约测试并确认因缺少确认态/滚动容器失败，再实现并重跑。
- 运行账号 API 回归、设计系统静态检查和 Web build。
- 浏览器检查长列表滚动、返回修改、显示密码和确认创建。

**Evidence**：

- `python -m pytest tests/test_frontend_admin_accounts.py tests/test_api_admin_accounts.py tests/test_api_account_permissions.py -q`：16 passed。
- `npm --prefix apps/web run build`：通过。
- foundation 漂移：无；复用现有账号创建 API 与 Dialog 契约。

**Failure Handling**：

- 若现有账号 API 与 Linear 字段冲突，停止改变接口并回到 Linear 记录差异；不得在前端伪造字段。
- 若确认卡无法满足焦点陷阱与返回焦点，复用 `Dialog` 组件，不自建简化弹层。

**完成收尾：状态同步**：

- 完成实现、验证和 foundation 漂移判断后，将事实、证据、完成日期、漂移结论和下一 Task 提交给 `ai-project-manager`。
- 由 `delivery-planner` 同步 main plan、kanban、sub plan；随后运行 `route-check --target-stage S4`。

**Owner**：AI 执行 -> 人审核

**前置**：Linear DYDATA-71 已确认；最新 `origin/main` 隔离 worktree

**状态**：已完成（2026-08-12）
