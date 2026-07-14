# 项目全局规则

本文件只维护长期权威入口和稳定边界，不复制 `AGENTS.md`、Linear issue、套包协议或专项规则正文。

## 1. 规则入口与引用约定

- 平台与仓库硬规则：`AGENTS.md`。
- 需求、优先级、负责人、验收和 issue 状态：Linear。
- 项目长期边界与权威索引：本文件。
- 当前执行摘要：`docs/plans/execution-plan.md`；正式 S3 计划形成前，开发范围仍以当前 Linear issue 为准。
- 宿主专项实现规则：`docs/rules/`。
- 项目身份与阶段快照：`project-profile.md`。
- 既有材料角色与新旧权威关系：`docs/governance/authority-map.md`。
- 套包协议只从 `.agent/project-manager-suite/` 读取，不依赖外部绝对路径。

## 2. 项目结构约定

- `.agent/project-manager-suite/`：公司治理套包安装态，不承载 dy-data 业务事实。
- `apps/api/`、`apps/web/`、`apps/worker/`：API、Web 和异步任务应用。
- `src/dy_data/`：可复用 Python 领域与基础设施代码。
- `alembic/`：PostgreSQL 迁移；数据库结构变更不得绕过迁移。
- `docs/devlog/`：可提交的开发过程日志。
- `/logs/`：仅存本地运行日志，保持 Git 忽略，不得与开发过程日志混用。
- `/.worktrees/`：本地工作树目录，保持 Git 忽略。

## 3. 工作方式约定

- 默认使用中文沟通和文档，代码标识符遵循宿主技术栈惯例。
- 每轮先通过 `myskills-router`，再校验套包锁并进入 `ai-project-manager`。
- 新需求保持 Linear-first；未经 issue 与开发确认，不进入实现。生产紧急修复也必须建立独立 issue、风险说明和验证记录。
- 每轮形成可复用交付物；阶段、验收或阻塞变化必须写回相应权威入口。
- 同一事实只保留一个 authority；其他文档通过链接或标注引用，不复制第二份权威正文。

## 4. 技术与实现边界

- 当前宿主技术事实以代码、`requirements.txt`、`apps/web/package.json`、迁移和部署配置为准。
- 后端为 FastAPI / SQLAlchemy / PostgreSQL，前端为 React / TypeScript / Vite；具体任务规则见 `docs/rules/`。
- 业务 API 默认需要登录，管理员能力必须使用后端角色和门店范围校验，不能只依赖前端隐藏入口。
- 视觉系统以 `docs/design-system/tokens.json` 和 `docs/design-system/README.md` 为权威入口。
- 套包默认示例中的其他技术栈规则不得直接成为 dy-data 宿主规则。

## 5. 协作边界

- AI 负责代码与资料核对、风险识别、执行、验证和证据整理。
- 用户负责业务目标、范围取舍、关键画像字段和最终验收。
- Linear 管理需求生命周期；GitHub 管理代码、commit、PR 和 CI 证据。

## 6. 交付件要求

- 每轮沉淀必要交付物，但不得为了满足模板复制第二份权威文档。
- 既有项目 baseline 必须先 dry-run、人工审核，再允许正式写入。
- 文档、代码、计划或状态发生变化时，同步检查交叉引用、开发日志与 Linear 回写。
- 交付前至少执行套包锁校验、套包测试、协议一致性、全局文件校验、阶段路由、宿主 pytest、前端构建和 `git diff --check`。

## 7. AI 协作规则

- 项目任务必须先读取 `AGENTS.md`，并按安装态 `ai-project-manager` 路由。
- 套包缺失或内容锁失配时，只允许在有效治理 issue 下执行恢复动作。
- 不直接修改安装态套包；先修改标准源、测试、重新安装，再同时更新安装态与锁。
- 不把扫描器推断写成 `【用户确认】`，不把历史计划当成当前计划。
- 不把 Linear Backlog 复制到 `execution-plan.md`，不把临时 issue 状态固化为长期项目规则。

## 8. 其他长期规则

- 规则冲突优先级：`AGENTS.md` → Linear 生命周期事实 → `project-rules.md` → `docs/rules/` → 任务相关资料。
- 套包升级必须同时提交安装态、脱敏 manifest 和版本锁，并通过内容哈希校验。
- 临时经验先进入 issue、复盘或候选记录，稳定且可执行后再升级为长期规则。
