# 项目全局规则

本文件只维护长期权威入口和稳定边界，不复制 `AGENTS.md`、Linear issue、套包协议或专项规则正文。

## 1. 规则入口与引用约定

- 规则权威文件：`AGENTS.md` `【系统推断】`
- 需求、优先级、负责人、验收与 issue 状态权威：Linear `【用户确认】`
- 计划权威文件：当前执行摘要为 `docs/plans/execution-plan.md`；正式 S3 计划形成前，开发范围仍以当前 Linear issue 为准 `【系统推断】`
- 状态回写权威文件：issue 状态与验收记录写回 Linear；项目阶段快照写入 `project-profile.md` `【系统推断】`
- 宿主专项规则入口：`docs/rules/` `【系统推断】`
- 既有材料角色与新旧权威关系：`docs/governance/authority-map.md` `【系统推断】`
- 套包协议只通过 `.agent/project-manager-suite/` 读取；不引用外部绝对路径。

## 2. 项目结构约定

- `.agent/project-manager-suite/`：公司治理套包的仓库内安装态，不承载 dy-data 业务事实。
- `project-profile.md`：项目身份、阶段、执行主体与待确认项。
- `docs/plans/execution-plan.md`：当前执行驾驶舱，只链接当前 issue 与正式计划入口。
- `docs/rules/`：dy-data 专项开发规则唯一落点；由 DYDATA-7 完成技术栈适配。
- `docs/governance/authority-map.md`：旧文档到套包角色的映射，不替代原文档。
- `docs/baseline/`：S0.5 的 dry-run 审核记录与正式 baseline。
- `/logs/` 继续是本地运行日志目录；开发过程日志的受控落点由 DYDATA-7 决定，当前不得混用。

## 3. 工作方式约定

- 默认使用中文沟通和文档，代码标识符遵循宿主技术栈惯例。
- 每轮先通过 `myskills-router`，再校验套包锁并进入 `ai-project-manager`。
- 新需求保持 Linear-first；未经 issue 与开发确认，不进入实现。
- DYDATA-6、DYDATA-7 完成前，普通新功能暂停进入开发；生产紧急修复必须有独立 Linear issue、风险说明和验证记录。
- 每轮形成可复用交付物；阶段、验收或阻塞变化必须写回相应权威入口。

## 4. 技术与实现边界

- 当前宿主技术事实以代码、`requirements.txt`、`apps/web/package.json`、迁移和部署配置为准。
- `docs/技术架构与部署规划.md`、`docs/data-model.md`、`docs/api-contract.md` 是重要证据，但其过期部分不能覆盖较新的代码事实。
- 视觉系统以 `docs/design-system/tokens.json` 和 `docs/design-system/README.md` 为权威入口。
- 套包默认 Java、Vue、MySQL 等规则不得直接成为 dy-data 的宿主规则；技术栈适配归 DYDATA-7。

## 5. 协作边界

- AI 负责代码与资料核对、风险识别、执行、验证和证据整理。
- 用户负责业务目标、范围取舍、关键画像字段和最终验收。
- Linear 管理需求生命周期；GitHub 管理代码、commit、PR 和 CI 证据。

## 6. 交付件要求

- 每轮都要求沉淀交付物，但不得为了满足模板复制第二份权威文档。
- baseline 必须先 dry-run、人工审核，再允许正式写入。
- 交付前至少执行套包锁校验、套包测试、协议一致性、全局文件校验、阶段路由、宿主 pytest、前端构建和 `git diff --check`。

## 7. AI 协作规则

- 项目任务必须先读取 `AGENTS.md`，并按安装态 `ai-project-manager` 路由。
- 套包缺失或内容锁失配时，只允许执行恢复动作。
- 不直接修改已安装套包；先修改标准源并验证，再重新安装和更新锁。
- 不把扫描器推断写成 `【用户确认】`，不把历史计划当成当前计划。
- 不把 Linear Backlog 复制到 `execution-plan.md`。

## 8. 其他长期规则

- 规则冲突优先级：`AGENTS.md` → Linear 生命周期事实 → `project-rules.md` → `docs/rules/` →任务相关资料。
- 套包升级必须同时提交安装态、脱敏 manifest 和版本锁，并通过内容哈希校验。
- 临时经验先进入 issue、复盘或候选记录，稳定且可执行后再升级为长期规则。
