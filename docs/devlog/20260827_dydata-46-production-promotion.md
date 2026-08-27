# DYDATA-46 腾讯云正式生产升格开发日志

## 2026-08-27

- 用户明确确认将 `https://dy-business-engine.com` 直接升格为正式生产，不再等待企业内网部署。
- Linear `DYDATA-46` 已进入 In Progress；`DYDATA-45` 在既有测试环境黑盒 UAT 证据和用户确认后进入 Done；`DYDATA-55` 保留为独立内网项目且不再阻塞本次升格。
- 基于 `origin/main@b56396d` 建立隔离分支 `codex/dydata-46-production-promotion`，未改动原工作区既有未提交内容。
- 完成代码与配置差距审计：CLI 环境注册、API 环境 guard、MCP initialize、审计和部署 smoke 仍存在 `test` 硬编码，不能直接视为 production。
- 建立 DYDATA-46 正式计划文件组；当前 Task 为 T1.1 production 环境与凭证隔离，后续为 T1.2 官方入口切换和 T2.1 生产发布/UAT。
- 发布硬边界：test 凭证不得迁移或复用；production 必须重新授权；失败回滚上一 production 版本且禁止 fallback 到 test 数据。
- T1.1 完成：先观察 10 项 production 行为测试按预期失败，再完成最小实现；CLI 子集 213/213、CLI/API/OAuth/MCP/审计组合 311/311 通过，`git diff --check` 通过。
- OAuth 四类持久化对象原本均有 `environment` 字段，production 切换会直接拒绝旧 test client/code/access/refresh 数据，不新增迁移；本任务无 Foundation 漂移。
- 当前进入 T1.2：官方 discovery、README/Skill、CLI 0.4.0 升级策略与部署契约切换。
- T1.2 本地证据：生产环境与版本回归、迁移、API、线索、前端契约、worker 和项目治理累计 `1183 passed, 2 skipped`；Alembic 单文件 47 项用时 12 分 13 秒；Web production build 通过，治理套件 `122/122`、部署脚本 Git Bash 语法和 `git diff --check` 通过。229 项浏览器视觉矩阵在本机单文件执行超过工具时限且未报告失败，改由 PR CI 完整执行后再推进 T2.1。
