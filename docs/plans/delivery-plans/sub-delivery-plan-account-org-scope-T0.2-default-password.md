# T0.2 批量开户默认密码

## 任务来源

- 主计划：[main-delivery-plan-account-org-scope.md](main-delivery-plan-account-org-scope.md)
- 任务看板：[task-kanban-account-org-scope.md](task-kanban-account-org-scope.md)

#### T0.2 批量开户初始密码统一123456

**Requirement ID**：LOCAL-ACCOUNT-SCOPE-002

**PRD 双链·读**：`mainprd-dy-data.md` §1；`docs/rules/account-access-control.md` 批量开通规则。

**核心逻辑**：用户明确要求新批量账号初始密码为123456，后续自行修改。仅替换批量创建的随机密码，保持已有账号、密码哈希、权限及事务行为；同步模板与页面说明，复用“我的→修改密码”。

用户追加纠正：集团与服务中心互不隶属，服务中心/大区/区域账号不填集团。范围解析、页面选项、批量校验及模板说明必须一并修正。先交付可直接转发的模板，再继续实现及发布；错误按表格行号反馈，不静默开通。

**核心文件**：`apps/api/dy_api/account_bulk_import.py`、`apps/api/dy_api/routes/admin.py`、`apps/web/src/components/AccountBulkImport.tsx`。

**完成标准**：新账号123456可登录，修改后旧密码失效；重复导入不覆盖；模板一致；验证通过并发布。

**Verification Method**：批量创建、认证及浏览器专项；Web build；独立复审；CI及生产部署核验。

**Evidence**：`docs/devlog/20260915_account_default_password.md`。

**Failure Handling**：定位失败原因并修复后复验，不覆盖既有账号密码。

**完成收尾：状态同步**：发布后向ai-project-manager回报证据、完成日期及foundation判断，由delivery-planner同步主计划、看板与子计划状态并重新运行route-check。

**Owner**：AI

**前置**：T0.1

**状态**：进行中
