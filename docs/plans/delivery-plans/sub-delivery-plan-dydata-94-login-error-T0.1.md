# T0.1 登录错误与后台提示

- 主开发计划：[main-delivery-plan-dydata-94-login-error.md](main-delivery-plan-dydata-94-login-error.md)
- 任务看板：[task-kanban-dydata-94-login-error.md](task-kanban-dydata-94-login-error.md)

#### T0.1 登录错误与后台提示

**Requirement ID**：DYDATA-94

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1

**核心逻辑**：初始页、导出超时和备用路径检查登录；短稳定错误保留原因；后台翻译为恢复指引。

**核心文件**：apps/worker/browser_exports/backend_aweme.py；apps/web/src/utils/userFacingLabels.ts；相关 tests。

**完成标准**：三种失效场景明确报错；正常路径及非登录异常不误分类；后台中文指引测试通过。

**Verification Method**：pytest 采集、任务和前端契约测试；Web build；git diff --check。

**Failure Handling**：保留原异常分类；不退出生产登录来测试；失败时停止发布。

**Owner**：AI

**前置**：用户同意开发；登录失效根因已查明。

**状态**：进行中

**完成收尾：状态同步**：回填 Linear、开发日志和本计划；生产发布单独记录。
