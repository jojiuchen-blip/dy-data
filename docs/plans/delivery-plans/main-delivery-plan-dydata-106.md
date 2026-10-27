# DYDATA-106 线索明细核销事实与手机号精准筛选

> **版本**：v1
> **发布日期**：2026-10-27
> **适用范围**：DYDATA-106
> **开发模式**：团队协作，主 Codex 统一集成
> **上游发现**：pipeline；canProceed=true；超大文件按章节读取，foundation 拆分索引按需定位。

## 0. 本计划使用指南

用户已明确授权两项修复、合入 main 并部署；沿用会话确认范围，当前任务进行中。Linear 为需求与验收权威，AI 执行、人类 Owner 审核决策。

### 0.1 PRD 加载约束

读取 `docs/prd/mainprd-dy-data.md` 权限和导出一致性、`docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md`、`docs/prd/foundation/foundation-schema-clue-center.md`；DYDATA-106 用户确认覆盖旧查询筛选假设。不改变考核指标定义。

### 0.2 读前门禁 / AI 自检清单

套件锁、全局文件、S4 route 通过；基于最新 origin/main 独立分支；保留其他工作区。三方计划一致及任务上下文检查通过方可实装。

### 0.3 完成前验证门禁

核销取消、重核销、分配时点、POI匹配、指标不变，完整号码精准、无URL/日志泄露、权限与组合筛选、列表分页与导出同口径回归。完整pytest、Web build、CI和生产 smoke 分别留证；未运行不得称通过。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >=3.12 | `python --version` |
| Node | >=22 | `node --version` |

## 1. 差距基线

明细核销状态误用 `is_self_store_verified` 考核标记；号码筛选缺少完整11位精准入口。生产 mixed-owner 发布失败待只读对照既有恢复路径，未执行部署。

## 2. 分工与边界

主 Codex 集成和发布；治理协作者仅计划与发布调查。只改线索明细/导出筛选事实，不重算考核、改写原始/分配/财务事实，不扩权、不触发外部电话查询。

## 3. 执行阶段

### Phase 1：明细筛选修复并验证发布

Entry Criteria：DYDATA-106 已 In Progress，用户明确开发、合入及部署授权；Exit Criteria：专项/全仓/构建、最终CI和生产验收留证，剩余风险明确。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [T1.1](sub-delivery-plan-dydata-106-T1.1-clue-filters.md) | 进行中 |

## 4. 任务看板

[任务看板](task-kanban-dydata-106.md)

## 5. 发布闸门

最终合入SHA必须通过CI。部署遵守 `docs/rules/storage-management.md`，保留容量、备份校验轮换、静态发布和回滚保护。先核对已部署SHA与mixed-owner恢复工作流；无数据库变更时不额外修复生产数据。上线后验证列表、筛选、导出、权限及日志脱敏；仅成功部署并不等于用户业务接受。

## 6. 风险与应对

核销状态与考核定义分离；原始有效核销必须成功且未撤销、晚于分配并匹配该轮门店POI。号码仅POST正文传输，不记录号码、密文、令牌或数据库连接。权限服务端重验，校验错误不得回显号码。来源缺失按明确未命中处理，不伪造事实。

## 7. AI 执行示例

为超期后真实本店核销、取消后重核销、异店核销及相同尾号不同完整号码建立回归；检查组合筛选总数、页内结果和导出一致，验证受限账号无法越权。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| DYDATA-106；mainprd 权限/导出规则；线索 API 查询与联系契约 | T1.1 | [T1.1](sub-delivery-plan-dydata-106-T1.1-clue-filters.md) |
