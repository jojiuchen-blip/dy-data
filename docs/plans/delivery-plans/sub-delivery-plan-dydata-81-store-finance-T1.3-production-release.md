# T1.3 主系统集成与生产发布子交付计划

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-81-store-finance.md](main-delivery-plan-dydata-81-store-finance.md)
- 任务看板：[task-kanban-dydata-81-store-finance.md](task-kanban-dydata-81-store-finance.md)

#### T1.3 合并门店端财务页面并发布生产

**Requirement ID**：DYDATA-81-RELEASE

**PRD 双链·读**：
- Linear DYDATA-81 当前正文、验收标准及用户 2026-08-30 的生产部署授权。
- `docs/prd/mainprd-dy-data.md` 的系统边界、权限、空态与错误提示规则。
- `docs/prd/subprd/02-subprd-store-settlement.md`、`04-subprd-invoice-registration.md` 与账单发票 Foundation。
- `docs/runbook.md`、`.github/workflows/ci-cd.yml`、`.github/workflows/tencent-lighthouse-deploy.yml` 与 `deploy/tencent/deploy.sh`。

**核心逻辑**：
- 仅消费 T1.1 已通过的提交，不在发布 Task 中扩张产品范围或补写业务数据。
- 合并前必须取得全量 pytest、正式 Web build、正式 API/权限、390/768/1440 视觉回归、受保护 `/finance/*` 范围检查和 `git diff --check` 的零失败新鲜证据。
- 按仓库既有主分支与 CI 流程集成，生产发布只部署已验证 commit SHA；发布脚本在 migration 前保留数据库备份，并以脚本和 CI 的非零退出作为硬阻断。
- 部署后验证生产首页、静态资源、健康接口、未登录鉴权、门店四页路由、绑定门店权限与越权拒绝；保存部署版本、日志、备份/回滚入口和 smoke 结果。
- 生产发布完成与 Issue 关闭相互独立；未经用户最终验收，不关闭 DYDATA-81。

**核心文件**：
- `.github/workflows/ci-cd.yml`
- `.github/workflows/tencent-lighthouse-deploy.yml`
- `deploy/tencent/deploy.sh`
- `deploy/compose.yaml`
- `docs/runbook.md`
- `tests/test_deploy_compose_config.py`
- `tests/test_deploy_agent_config.py`
- `docs/devlog/20260830_dydata-81-store-finance.md`

**完成标准**：
- T1.1 的提交已进入主分支，主分支 CI 对同一 commit SHA 全部通过。
- 生产部署 workflow 或受控腾讯云发布脚本对该 SHA 成功，记录部署 URL、版本、开始/完成时间、数据库备份位置和上一验证版本。
- 生产首页、静态资源、健康接口和未登录鉴权 smoke 通过；门店账号仅能访问其绑定门店，四个门店端路由可直达并读取正式 API，越权访问被拒绝。
- 生产页面无 UAT/演示金额、日期、状态或提示，缺数据仅显示“暂无数据、尚未生成或待确认”。
- 回滚到上一验证 commit 的入口和数据库恢复前置条件已核查；任一 smoke 失败时按 runbook 停止验收并回滚或保留故障发布供诊断。
- Linear DYDATA-81 回填 commit、CI、部署、smoke 与剩余风险，但状态保持 In Progress，等待用户最终验收。

**Verification Method**：
- 合并前运行 `python -m pytest`、`npm --prefix apps/web run build`、门店端视觉矩阵、API/权限专项、部署配置测试与 `git diff --check`。
- 合并后核对主分支 commit SHA 与 CI 结果；仅对该 SHA 触发既有生产发布流程。
- 部署后执行公开端点、鉴权、门店四页、绑定门店和越权拒绝 smoke，并核对部署日志中的备份与回滚信息。

**Evidence**：
- Git commit/PR、主分支 CI 和生产部署 URL。
- `pwScreenShot/dydata-81-store-finance/final/` 与生产 smoke 截图/日志。
- `docs/devlog/20260830_dydata-81-store-finance.md` 和 Linear DYDATA-81 验证记录。

**Failure Handling**：
- 任一合并前门禁、主分支 CI 或受保护范围检查失败时，不触发生产部署。
- migration、部署或生产 smoke 任一失败时，停止新验收，保留日志和备份，按 `docs/runbook.md` 回到上一验证 commit；数据库恢复仅在隔离验证且确认写入影响后执行。
- 生产凭证、目标主机、GitHub Actions 权限或正式 API 会话不可用时，不猜测或绕过，记录为发布阻断并保持 DYDATA-81 In Progress。

**完成收尾：状态同步**：
- 完成部署与生产 smoke 后，把 commit、CI、部署、备份、回滚和权限证据提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主开发计划、任务看板和本子计划状态，并重新运行 S4 一致性检查。
- Task 可在部署证据齐全后标记已完成；DYDATA-81 仍保持 In Progress，直到用户最终验收。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1 全量门禁、正式视觉回归和受保护范围检查通过

**状态**：待开发

## Evidence Log

- 待执行。
