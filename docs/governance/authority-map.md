# dy-data 既有材料权威映射

本表将中途接入套包前后的材料映射到明确职责。它只声明权威关系和维护状态，不复制原文，也不把历史文档升级为新的事实。

## 状态定义

- `authority`：当前职责的唯一权威入口。
- `evidence`：用于核对或指导，但不能单独覆盖代码、运行配置或上位权威。
- `legacy`：历史方案或已结束计划，只保留追溯价值。
- `stale`：职责仍相关，但内容尚未完整覆盖当前实现，需要后续定向刷新。
- `missing`：套包角色尚无正式产物，不得用相似旧文档冒充。

## 权威映射

| 文件或目录 | 职责 | 状态 | 权威处理 |
|---|---|---|---|
| `AGENTS.md` | 平台与仓库硬规则 | `authority` | 保持唯一 turn gate、套包门禁和 Linear-first 入口。 |
| Linear `DYDATA-*` | 需求、范围、优先级、负责人、验收和 issue 状态 | `authority` | 不复制 Backlog；执行驾驶舱只保留当前 issue。 |
| `project-rules.md` | 长期项目边界与权威索引 | `authority` | 不写临时 issue 状态，不复制专项规则正文。 |
| `project-profile.md` | 项目身份、业务范围、阶段和 baseline 缺口快照 | `authority` | 用户确认与系统推断保持来源标记。 |
| `docs/plans/execution-plan.md` | 当前执行驾驶舱 | `authority` | 只维护当前 issue、完成标准和紧邻下一步。 |
| `docs/rules/` | FastAPI、React、PostgreSQL、调试、文档和日志宿主规则 | `authority` | 宿主实现规则优先于套包中的异栈示例。 |
| `docs/项目产品介绍书.md` | 当前产品总览、四个业务域与产品导航 | `authority` | 保留面向项目理解的总览职责；业务目标、角色、范围、成功标准和风险以正式 BRD 为准。 |
| `docs/design-system/README.md`、`docs/design-system/tokens.json` | 视觉系统与运行时设计契约 | `authority` | 当前强视觉规范入口；候选与评审文件仅作 evidence。 |
| `docs/architecture.md` | 当前服务组成、边界、数据链路和认证架构 | `authority` | 与当前代码、迁移、`deploy/` 同步维护。 |
| `docs/runbook.md` | 生产部署、迁移、数据任务、备份和恢复操作 | `authority` | 运行命令与生产安全边界的文档入口。 |
| `.github/workflows/*.yml`、`deploy/` | 实际 CI/CD 和生产编排行为 | `authority` | 实际启用目标由仓库变量与 secrets 决定，文档不得固化生产标识。 |
| `README.md` | 仓库总览、开发入口和权威文档导航 | `evidence` | 不复制完整产品、架构或运行手册。 |
| `apps/web/README.md` | Web 开发与当前路由范围指南 | `evidence` | 准确路由和数据行为仍以 `src/App.tsx`、client 与后端 schema 为准。 |
| `docs/技术架构与部署规划.md` | 部署选择与演进指南 | `evidence` | 当前事实链接架构、运行手册、workflow 和 `deploy/`。 |
| `docs/api-contract.md` | 当前认证、响应包络和 API 分组索引 | `evidence` | 运行契约以 routes、schema、依赖、OpenAPI 和测试为准；后续映射到 FOUNDATION API。 |
| `docs/github-cicd.md`、`docs/tencent-lighthouse-cicd.md` | CI/CD 配置操作指南 | `evidence` | 只记录变量名和通用步骤，不保存真实项目、主机或 URL。 |
| `docs/tencent-edgeone-migration.md` | Railway 到 CVM/EdgeOne 的历史迁移方案 | `legacy` | 不代表当前部署状态；执行前需重新验证云产品要求并以当前 workflow、`deploy/` 和运行手册为准。 |
| `docs/data-model.md` | 当前 37 个表模型的业务分组索引 | `evidence` | 运行结构以迁移、SQLAlchemy 模型和实际 schema 为准；未来由 FOUNDATION schema 定向补齐字段契约。 |
| `docs/superpowers/specs/` | 已确认功能和视觉设计证据 | `evidence` | 按对应 issue 与日期读取，不合并成总 PRD。 |
| `docs/superpowers/plans/`、`docs/plans/` 中既有日期计划 | 历史实施计划与控制规格 | `legacy` | 保留当时事实，不覆盖 Linear、项目画像或当前执行驾驶舱。 |
| `docs/devlog/` | 按天追加的开发执行记录 | `evidence` | 提供执行与验证证据，不替代 Linear 和当前计划。 |
| `docs/brd/BRD-dy-data-20260716-1255.md` | S1 业务目标、角色、痛点、价值、范围、成功标准、风险与下游边界 | `authority` | 当前唯一权威 BRD；修改业务口径时须重开 BRD 台账并重新完成质量门与终稿确认。 |
| `docs/brd/ledger-state-dy-data.json`、`docs/brd/brd-ledger-dy-data.md` | BRD 决策状态与追溯记录 | `evidence` | JSON 是决策状态源，Markdown 是脚本渲染的只读展示层；二者不替代 BRD 正文。 |
| `src/frontend/page-preview/explainer-*-dy-data.md` | S2 页面交互语义 | `missing` | 现有页面和设计规格只作 evidence，不冒充页面说明产物。 |
| `docs/prd/foundation/foundation-*-dy-data.md` | S2 术语、Schema、API FOUNDATION | `missing` | 现有数据与 API 索引不冒充正式 foundation。 |
| `docs/prd/mainprd-dy-data.md`、`docs/prd/subprd/` | S2 正式 PRD | `missing` | 现有 specs 与计划不复制为 PRD。 |

## 维护规则

- 产品决策以 Linear 与已确认产品材料为准；代码、迁移和运行配置提供当前实现事实。
- 同一职责只能有一个 `authority`；`evidence`、`legacy`、`stale` 不得自动晋升。
- 历史材料保留原时间点，不因当前纠偏而重写其历史状态。
- baseline 或后续补档改变角色时原地更新本表，不另建第二份映射。
