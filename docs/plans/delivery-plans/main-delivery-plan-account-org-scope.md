# 账号组织权限与门店选择 Main Delivery Plan

> **版本**：v1
> **发布日期**：2026-09-15
> **适用范围**：account-org-scope
> **开发模式**：solo-local
> **上游发现结论**：canProceed=true, slug=account-org-scope

## 0. 本计划使用指南

1. 先读取本主开发计划，确认阶段顺序、任务索引、发布闸门与风险。
2. 再打开任务看板，定位当前 Task 对应的子开发计划。
3. 执行前只加载当前 Task 的子开发计划和 `PRD 双链·读` 指向的真实文件。

### 0.1 PRD 加载约束

- 先读 `mainprd-dy-data.md` 建立全局地图。
- 每个 Task 只读取子开发计划中列出的 PRD 和相关章节。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 必须能从任务看板定位到一个子开发计划。
- 子开发计划必须声明 `PRD 双链·读`、`核心逻辑`、`核心文件` 和 `完成标准`。

### 0.3 完成前验证门禁

- 完成前必须执行子开发计划里的 `Verification Method`。
- 证据必须写入子开发计划的 `Evidence` 指定位置。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node -v` |

> 表格必须符合环境自检脚本的可解析格式（第 3 列为反引号包裹的完整检测命令；工程依赖目录用两列表声明，写法见 `delivery-planner/references/plan-anatomy.md` 的「环境依赖声明」）。写成其他格式会被脚本当作 0 条声明，只提醒不拦截。

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 组织账号缺少动态数据范围，门店选择及批量开通不便 | 管理人员无法按组织安全使用线索与结算数据 | T0.1 | 已实现，发布验证中 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 执行代码理解、实装、验证与计划状态回写 |
| 人类 Owner | 审核业务判断、验收关键结果 |

## 3. 执行阶段

### Phase 0：账号组织权限与门店选择 闭环

**Entry Criteria**：主 PRD、子开发计划和任务看板均存在。

**Exit Criteria**：T0.1 完成并留下验证证据。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-account-org-scope-T0.1-account-scope.md](sub-delivery-plan-account-org-scope-T0.1-account-scope.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-account-org-scope.md](task-kanban-account-org-scope.md)

## 5. 发布闸门

- [ ] T0.1 的 `Verification Method` 已执行
- [ ] T0.1 的 `Evidence` 已落盘
- [ ] 任务看板和子开发计划状态一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 同名组织或空范围被误判全局 | 跨组织数据泄露 | 完整路径解析；空范围拒绝；API及CLI共用授权 | AI | 专项通过 |
| 批量导入标识冲突或部分创建 | 账号归属混乱 | 归一化预览；提交时重校验；整批事务 | AI | 专项通过 |
| 生产数据库迁移不一致 | 上线失败 | PostgreSQL发布闸门及0059降级保护 | AI | CI验证中 |

## 7. AI 执行示例

1. 从任务看板选择 T0.1。
2. 打开 T0.1 对应子开发计划。
3. 按子开发计划中的 PRD、核心文件和验证方法执行。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| mainprd-dy-data.md §1 | T0.1 | [sub-delivery-plan-account-org-scope-T0.1-account-scope.md](sub-delivery-plan-account-org-scope-T0.1-account-scope.md) |

## 当前需求边界

本任务覆盖集团、服务中心、大区、区域及门店账号数据范围，线索与结算统一授权，三个打榜指标全量开放，门店搜索多选及名单导入，以及标准账号开通模板、批量预览和创建。用户已授权主分支合并及服务器部署，完成条件包括CI通过、生产迁移及上线检查。模板仅提供填写规范，不预先创建真实账号。
