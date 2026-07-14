# 当前执行计划（驾驶舱）

本文件只记录当前执行入口和下一步，不复制 Linear Backlog 或完整开发计划。当前需求权威为 [DYDATA-6](https://linear.app/keith-lim/issue/DYDATA-6/p0-接入-project-manager-suite建立项目治理底座与状态入口)。

## 1. 当前阶段

- S0.5 既有项目基线诊断已完成；普通后续工作按正式 baseline 路由 `【主入口回写】`

## 2. 当前目标

- 保持 project-manager-suite 2.0 的可追溯接入、项目治理入口、可信 baseline 和 CI 门禁有效，不改业务逻辑 `【用户确认】`

## 3. 进行中任务

- 无开发中任务；DYDATA-6 已实现并通过本地完整门禁，待提交和 Linear 完成回写 `【主入口回写】`

## 4. 下一步任务

- 提交 DYDATA-6 并完成 Linear 验收回写；随后 DYDATA-7 可按独立 issue 启动 `【主入口回写】`
- 正式 baseline 的首个维护文档缺口为 BRD，需按新需求交由 `brd-writer`，不在 DYDATA-6 内扩写 `【主入口回写】`

## 5. 完成标准

- [x] 安装态和版本锁可复算，Git 中没有本机绝对路径。
- [x] `AGENTS.md`、`project-rules.md`、项目画像、执行驾驶舱和材料映射职责不重叠。
- [x] dry-run 审核记录与正式 baseline 均存在，路由不再是 `UNKNOWN`。
- [x] CI 等价本地完整门禁通过，业务逻辑没有被修改。

## 6. 前置依赖

- 标准套包源 `2.0.0` 已通过 114 项测试并安装到 `.agent/project-manager-suite/` `【系统推断】`
- DYDATA-6 完成回写后解除 DYDATA-7 的依赖阻塞；DYDATA-7 负责后续 FastAPI、React、PostgreSQL、Linear 和日志规则适配 `【系统推断】`

## 7. 待确认项

- 无 DYDATA-6 阻塞项 `【主入口回写】`
- `docs/rules/` 的六类宿主专项规则属于 DYDATA-7，不从套包 Java / Vue / MySQL 默认规则直接复制 `【主入口回写】`
- `/logs/` 仍是被忽略的本地运行目录；`project-devlog` 的可提交落点与状态映射由 DYDATA-7 解决，当前全局校验对应 warning 不阻断 S0.5 `【主入口回写】`

## 8. 当前正式计划文件组

- 主开发计划：待生成 `【主入口回写】`
- 任务看板：待生成 `【主入口回写】`
- 当前子开发计划：待生成 `【主入口回写】`
