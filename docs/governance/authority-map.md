# dy-data 既有材料权威映射

本表用于把中途接入前的材料映射到 project-manager-suite 角色。它只声明权威关系和维护状态，不复制原文，也不把历史文档升级成新的事实。

## 状态定义

- `authority`：当前职责的唯一权威入口。
- `evidence`：可用于核对，但不能单独覆盖代码或上位权威。
- `legacy`：历史方案或已结束计划，只保留追溯价值。
- `stale`：职责仍相关，但内容落后于当前代码，需要后续定向刷新。
- `missing`：套包角色尚无正式产物，不得用相似旧文档冒充。

## 权威映射

| 现有文件或目录 | 套包/项目角色 | 当前状态 | 权威处理 |
|---|---|---|---|
| `AGENTS.md` | 平台与仓库硬规则 | `authority` | 保持唯一硬门禁入口；套包规则通过链接引用。 |
| Linear `DYDATA-*` | 需求、优先级、负责人、验收、状态 | `authority` | 不复制 Backlog；驾驶舱只链接当前 issue。 |
| `README.md` | 仓库结构与运行入口 | `evidence` | 产品定义继续指向产品介绍书；代码事实优先。 |
| `docs/项目产品介绍书.md` | 产品定位与既有分账业务边界 | `authority` | 作为现有产品定义入口；新增线索、后台等范围未来通过 BRD/PRD 补齐，不直接改写成完整 BRD。 |
| `docs/architecture.md` | 早期目录与架构整理说明 | `legacy` | 文件仍声称部分现有目录尚未创建，不作为当前架构权威。 |
| `docs/技术架构与部署规划.md` | 技术栈、服务拆分与部署证据 | `evidence` | 与当前代码、Docker、CI 对照使用；过期结构描述不覆盖代码。 |
| `docs/data-model.md` | 数据模型说明 | `stale` | 作为术语和初始表设计证据；当前迁移与 SQLAlchemy 模型优先，未来映射到 foundation schema。 |
| `docs/api-contract.md` | API 契约说明 | `stale` | 只覆盖早期生产 MVP 接口；当前 FastAPI routes 优先，未来映射到 foundation API。 |
| `docs/design-system/README.md`、`docs/design-system/tokens.json` | 视觉系统及运行时契约 | `authority` | V0.2 当前生效；候选文件只保留历史评审用途。 |
| `docs/superpowers/specs/` | 已确认功能/视觉设计证据 | `evidence` | 按对应 issue 与日期读取，不合并成一份总 PRD。 |
| `docs/superpowers/plans/`、`docs/plans/` 既有日期计划 | 历史实施计划与控制规格 | `legacy` | 已完成或阶段性计划不作为当前驾驶舱；当前任务看 Linear 与 `execution-plan.md`。 |
| `docs/brd/BRD-dy-data-*.md` | S1 正式 BRD | `missing` | 本需求不补写；正式 baseline 按缺口推荐后续 skill。 |
| `src/frontend/page-preview/explainer-*-dy-data.md` | S2 页面交互语义 | `missing` | 现有 React 页面和设计规格只作为证据，不冒充 page-explainer 产物。 |
| `docs/prd/foundation/foundation-*-dy-data.md` | S2 术语、Schema、API foundation | `missing` | 现有数据/API 文档先标记 stale，后续由 foundation-builder 定向补齐。 |
| `docs/prd/mainprd-dy-data.md` 与 `docs/prd/subprd/` | S2 正式 PRD | `missing` | 现有 specs 与 plans 不复制为 PRD。 |

## 维护规则

- 代码、迁移和运行配置是客观事实证据，但需求与业务决策仍以 Linear 和已确认产品材料为准。
- 同一职责只能有一个 `authority`；`evidence`、`legacy`、`stale` 不得自动晋升。
- baseline 或后续补档改变状态时，原地更新本表，不另建第二份映射。
