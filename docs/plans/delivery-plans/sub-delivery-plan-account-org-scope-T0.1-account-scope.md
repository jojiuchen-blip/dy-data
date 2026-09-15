# T0.1 账号组织权限与门店选择 Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-account-org-scope.md](main-delivery-plan-account-org-scope.md)
- 任务看板：[task-kanban-account-org-scope.md](task-kanban-account-org-scope.md)

#### T0.1 五级组织数据范围、全量打榜及门店多选导入

**Requirement ID**：LOCAL-ACCOUNT-SCOPE-001

**PRD 双链·读**：
- `mainprd-dy-data.md` §1

**核心逻辑**：
- 用户已明确要求实施、合并主分支并部署。Linear 当前不可访问 DYDATA，按本轮再次直接执行指令记录本地需求，不向其他团队建票。
- 角色与组织数据权限解耦；选择集团/服务中心/大区/区域后动态覆盖下属门店，门店账号保留多店选择。
- 线索、结算、明细及导出统一限制范围；三个打榜指标页面和导出对所有有效登录账号开放全量组织排行。
- 门店选择弹窗顶部按名称和部分 ID 搜索、批量勾选、保留跨搜索选择；Excel 模板含说明、文本 ID、名单，导入先预览错误行后应用。

- 新增账号开通标准xlsx模板、批量预览、整批事务开通和密码结果下载；最高管理员操作，标识冲突和范围矛盾拒绝。

**核心文件**：
- `apps/api/dy_api/auth.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/web/src/pages/AdminAccountsPage.tsx`
- `tests/test_api_access_control.py`

**完成标准**：
- 五级范围与组织变动、同名组织、空范围及越权拒绝通过；排行榜全量与业务明细隔离。
- 门店关键词、部分 ID、多选、去重、Excel/CSV 导入错误提示与保存回读通过。
- 全量 pytest、Web build、迁移、CI、主分支合并、生产部署与 smoke 留有证据。

**Verification Method**：
- pytest、Web build、真实 API 与浏览器验证；CI/生产发布和 smoke。

**Evidence**：
- `docs/devlog/20260915_account_org_scope.md`

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 的状态。
- 同步后重新运行 `node <suite-path>/tools/route-check.mjs <host> --target-stage S4 --json`（route-check 是套件的阶段门禁检查工具；`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`，命令默认在宿主项目根目录执行），确认正式开发计划文件组三者一致；未通过前不得宣称本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：进行中
