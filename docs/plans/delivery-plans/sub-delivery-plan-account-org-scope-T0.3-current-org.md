# T0.3 账号组织目录接入已生效正式名单

## 任务来源

- 主计划：[main-delivery-plan-account-org-scope.md](main-delivery-plan-account-org-scope.md)
- 看板：[task-kanban-account-org-scope.md](task-kanban-account-org-scope.md)
- 用户于2026-09-17授权跳过Linear建票，修复、部署并继续开户。

#### T0.3 当前组织目录与动态权限一致

**Requirement ID**：LOCAL-ACCOUNT-SCOPE-003

**PRD 双链·读**：`mainprd-dy-data.md` §1；`docs/rules/account-access-control.md` §10。

**核心逻辑**：账号目录与动态权限优先读取当前已生效的完整正式组织版本，通过store_id关联有效门店；存在正式版本时禁止混入旧表或逐店历史版本。尚未发布正式版本的既有环境保留旧归属兼容。未来版本不提前生效，停用及移除门店不授权，三项打榜全量权限不变。

**核心文件**：`apps/api/dy_api/account_scope.py`、`tests/test_account_current_org.py`。

**完成标准**：空旧表有正式名单时目录与批量开户成功；跨区域拒绝；换版撤权；未来版本和停用门店拒绝；原权限测试通过；主分支CI与服务器部署成功。

**Verification Method**：先失败复现，再pytest专项与全量、Web build、git diff --check、CI与生产上传预览。

**Evidence**：`docs/devlog/20260917_account_current_org.md`。

**Failure Handling**：失败停止发布，保留错误行，不覆盖既有账号，不放开空范围。

**完成收尾：状态同步**：验证部署后同步主计划、看板、执行摘要及日志。

**Owner**：AI

**前置**：T0.2

**状态**：进行中

实施验收：PR #37已合入main，部署35176467356成功；生产70行预览无错误，70个组织账号创建成功并与结果表逐项核对。待用户验收。详见关联开发日志。
